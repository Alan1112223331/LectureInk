import queue
import numpy as np
from audio import CHUNK, RATE, FileSource, RecordingQueue, Resampler, read_wav, to_pcm16
from conftest import ASSETS


def tone(rate, seconds, freq=440.0):
    t = np.arange(int(rate * seconds)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def dominant_frequency(x, rate):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / rate)[np.argmax(spectrum)]


def test_resampler_streaming_matches_length_and_pitch():
    x = tone(48000, 2.0)
    r = Resampler(48000)
    out = np.concatenate([r.process(x[i:i + 1024]) for i in range(0, len(x), 1024)])
    assert abs(len(out) - len(x) / 3) <= 2
    assert abs(dominant_frequency(out[1000:], RATE) - 440) < 5


def test_resampler_removes_content_above_new_nyquist():
    out = Resampler(48000).process(tone(48000, 1.0, freq=12000))
    assert np.sqrt(np.mean(out[200:] ** 2)) < 0.02


def test_resampler_handles_odd_rates_and_passthrough():
    out = Resampler(44100).process(tone(44100, 1.0))
    assert abs(len(out) - RATE) <= 2
    same = tone(RATE, 0.1)
    assert np.array_equal(Resampler(RATE).process(same), same)


def test_read_wav_resamples_to_16k_mono():
    audio = read_wav(ASSETS / 'speech.wav')
    assert audio.dtype == np.float32
    assert 7.9 < len(audio) / RATE < 8.3


def test_file_source_delivers_chunks_then_end_marker():
    q = queue.Queue()
    src = FileSource(str(ASSETS / 'speech.wav'), q, speed=200.0, tail_silence=0)
    src.start()
    src.thread.join(10)
    chunks = []
    while True:
        item = q.get_nowait()
        if item is None:
            break
        chunks.append(item)
    assert all(len(c) == CHUNK for c in chunks[:-1])
    assert 7.9 < sum(len(c) for c in chunks) / RATE < 8.3


def test_recording_queue_writes_wav_and_passes_chunks(tmp_path):
    q = RecordingQueue(tmp_path / 'rec' / 'audio.wav')
    q.put(np.full(CHUNK, 0.5, dtype=np.float32))
    q.put(None)
    assert len(q.get()) == CHUNK and q.get() is None
    assert abs(read_wav(tmp_path / 'rec' / 'audio.wav')[100] - 0.5) < 0.01


def test_pcm16_clips():
    assert to_pcm16(np.array([2.0, -2.0], dtype=np.float32)) == np.array([32767, -32767], '<i2').tobytes()
