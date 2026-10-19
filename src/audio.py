"""Audio sources. Every source delivers 16 kHz mono float32 chunks into a queue; `None` marks the end."""
from __future__ import annotations
import queue
import threading
import time
import wave
import numpy as np

RATE = 16000
CHUNK = 1600  # 100 ms
# PortAudio set-up and tear-down are not thread-safe: two devices opening at once can crash the process.
_PA_LOCK = threading.RLock()


def list_devices(kind: str = 'system') -> list[dict]:
    """WASAPI render loopbacks ('system') or physical inputs ('microphone')."""
    import pyaudiowpatch as pa
    if kind not in ('system', 'microphone'):
        raise ValueError('未知的声音来源')
    with _PA_LOCK, pa.PyAudio() as p:
        if kind == 'system':
            # A missing default output must not hide other connected devices.
            try:
                default_index = p.get_default_wasapi_loopback()['index']
            except (OSError, LookupError):
                default_index = -1
            devices = list(p.get_loopback_device_info_generator())
        else:
            host = p.get_host_api_info_by_type(pa.paWASAPI)
            default_index = host.get('defaultInputDevice', -1)
            devices = [p.get_device_info_by_index(i) for i in range(p.get_device_count())]
            devices = [d for d in devices if d['hostApi'] == host['index']
                       and d['maxInputChannels'] > 0 and not d.get('isLoopbackDevice', False)]
        devices = [d for d in devices if d['maxInputChannels'] > 0]
        devices.sort(key=lambda d: d['index'] != default_index)
        return [{'index': d['index'], 'name': d['name'], 'rate': int(d['defaultSampleRate']),
                 'channels': d['maxInputChannels'], 'default': d['index'] == default_index, 'kind': kind}
                for d in devices]


class Resampler:
    """Streaming resampler: windowed-sinc low-pass, then linear interpolation with carried phase."""

    def __init__(self, src_rate: int, dst_rate: int = RATE):
        self.src_rate, self.dst_rate = src_rate, dst_rate
        self.ratio = src_rate / dst_rate
        self.kernel = None
        if src_rate > dst_rate:
            k = np.arange(-32, 33, dtype=np.float64)
            cutoff = 0.45 * dst_rate / src_rate
            kernel = 2 * cutoff * np.sinc(2 * cutoff * k) * np.hamming(len(k))
            self.kernel = (kernel / kernel.sum()).astype(np.float32)
            self.history = np.zeros(len(k) - 1, dtype=np.float32)
        self.buffer = np.zeros(0, dtype=np.float32)
        self.pos = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if self.src_rate == self.dst_rate:
            return x
        if self.kernel is not None:
            joined = np.concatenate((self.history, x))
            x = np.convolve(joined, self.kernel, mode='valid').astype(np.float32)
            self.history = joined[-(len(self.kernel) - 1):]
        buf = np.concatenate((self.buffer, x))
        if len(buf) < 2 or self.pos > len(buf) - 1:
            self.buffer = buf
            return np.zeros(0, dtype=np.float32)
        n = int((len(buf) - 1 - self.pos) // self.ratio) + 1
        points = self.pos + np.arange(n) * self.ratio
        out = np.interp(points, np.arange(len(buf)), buf).astype(np.float32)
        nxt = self.pos + n * self.ratio
        drop = min(int(nxt), len(buf) - 1)
        self.buffer = buf[drop:]
        self.pos = nxt - drop
        return out


class _Chunker:
    """Collects resampled audio into fixed 100 ms chunks."""

    def __init__(self, out: queue.Queue):
        self.out = out
        self.pending = np.zeros(0, dtype=np.float32)
        self.produced = 0

    def push(self, samples: np.ndarray) -> None:
        self.pending = np.concatenate((self.pending, samples))
        while len(self.pending) >= CHUNK:
            self.out.put(self.pending[:CHUNK].copy())
            self.pending = self.pending[CHUNK:]
            self.produced += CHUNK

    def flush(self) -> None:
        if len(self.pending):
            self.out.put(self.pending.copy())
            self.produced += len(self.pending)
            self.pending = np.zeros(0, dtype=np.float32)


class DeviceCapture:
    """WASAPI capture. Fills gaps with silence: loopback devices deliver nothing while no sound plays,
    but recognisers need the pause on their timeline to finish sentences and start paragraphs."""

    def __init__(self, device: dict, out: queue.Queue, on_level=None, on_error=None):
        self.device, self.out = device, out
        self.on_level, self.on_error = on_level or (lambda v: None), on_error or (lambda m: None)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name='audio-capture')
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        import pyaudiowpatch as pa
        channels = int(self.device['channels'])
        resampler = Resampler(int(self.device['rate']))
        chunker = _Chunker(self.out)
        last_level = [0.0]
        p = stream = None

        def callback(data, frame_count, time_info, status):
            try:
                pcm = np.frombuffer(data, dtype=np.float32).reshape(-1, channels)
                mono = np.nan_to_num(pcm.mean(axis=1), nan=0.0, posinf=1.0, neginf=-1.0)
                with self.lock:
                    chunker.push(resampler.process(mono))
                now = time.monotonic()
                if now - last_level[0] > 0.12 and mono.size:
                    self.on_level(float(np.sqrt(np.mean(mono * mono))))
                    last_level[0] = now
                return (None, pa.paComplete if self.stop_event.is_set() else pa.paContinue)
            except Exception as ex:  # never let an exception escape into PortAudio
                self.on_error('音频采集异常：' + str(ex))
                self.stop_event.set()
                return (None, pa.paAbort)

        try:
            with _PA_LOCK:
                p = pa.PyAudio()
                stream = p.open(format=pa.paFloat32, channels=channels, rate=int(self.device['rate']), input=True,
                                input_device_index=self.device['index'], frames_per_buffer=1024, stream_callback=callback)
            started = time.monotonic()
            while not self.stop_event.wait(0.1):
                if not stream.is_active():
                    self.on_error('音频设备意外停止，请检查所选设备。')
                    break
                expected = int((time.monotonic() - started) * RATE)
                with self.lock:
                    behind = expected - chunker.produced - len(chunker.pending)
                    if behind > RATE // 4:
                        chunker.push(np.zeros(behind - RATE // 20, dtype=np.float32))
                        self.on_level(0.0)
            stream.stop_stream()
        except Exception as ex:
            hint = ' 请确认麦克风已连接，且 Windows 允许桌面应用使用麦克风。' if self.device.get('kind') == 'microphone' else ''
            self.on_error('收音失败：' + str(ex) + hint)
        finally:
            with _PA_LOCK:
                if stream:
                    stream.close()
                if p:
                    p.terminate()
            with self.lock:
                chunker.flush()
            self.out.put(None)


class FileSource:
    """Plays a WAV file into the queue at real-time pace (testing, demos, replaying recordings)."""

    def __init__(self, path: str, out: queue.Queue, on_level=None, speed: float = 1.0, tail_silence: float = 1.5):
        self.path, self.out, self.speed, self.tail = path, out, speed, tail_silence
        self.on_level = on_level or (lambda v: None)
        self.stop_event = threading.Event()
        self.thread = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name='file-source')
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        try:
            audio = read_wav(self.path)
            audio = np.concatenate((audio, np.zeros(int(self.tail * RATE), dtype=np.float32)))
            started = time.monotonic()
            for i in range(0, len(audio), CHUNK):
                if self.stop_event.is_set():
                    break
                chunk = audio[i:i + CHUNK]
                self.out.put(chunk)
                self.on_level(float(np.sqrt(np.mean(chunk * chunk))) if chunk.size else 0.0)
                wait = (i + CHUNK) / RATE / self.speed - (time.monotonic() - started)
                if wait > 0:
                    self.stop_event.wait(wait)
        finally:
            self.out.put(None)


def read_wav(path: str) -> np.ndarray:
    """Read a PCM WAV file as 16 kHz mono float32."""
    with wave.open(str(path), 'rb') as w:
        width, channels, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        audio = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768
    elif width == 4:
        audio = np.frombuffer(raw, dtype='<i4').astype(np.float32) / 2147483648
    elif width == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    else:
        raise ValueError('不支持的 WAV 位深')
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return Resampler(rate).process(audio)


class RecordingQueue(queue.Queue):
    """A chunk queue that also writes everything put into it to a 16 kHz mono WAV file."""

    def __init__(self, path):
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.wav = wave.open(str(path), 'wb')
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)

    def put(self, item, block=True, timeout=None):
        if self.wav is not None:
            if item is None:
                self.wav.close()
                self.wav = None
            else:
                self.wav.writeframes(to_pcm16(item))
        super().put(item, block, timeout)


def to_pcm16(chunk: np.ndarray) -> bytes:
    return (np.clip(chunk, -1, 1) * 32767).astype('<i2').tobytes()
