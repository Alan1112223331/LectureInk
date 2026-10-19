"""API mode: Soniox real-time transcription with one-way translation over a single WebSocket."""
from __future__ import annotations
import json
import queue
import time
from audio import to_pcm16
from engine_base import Engine
from settings import parse_glossary

URL = 'wss://stt-rt.soniox.com/transcribe-websocket'
MODEL = 'stt-rt-v5'
SPECIAL = ('<end>', '<fin>')


def build_config(settings, key: str, target: str = 'zh') -> dict:
    config = {'api_key': key, 'model': MODEL, 'audio_format': 'pcm_s16le', 'sample_rate': 16000, 'num_channels': 1,
              'enable_endpoint_detection': True, 'max_endpoint_delay_ms': 1500,
              'translation': {'type': 'one_way', 'target_language': target}}
    if settings.source_language and settings.source_language != 'auto':
        config['language_hints'] = [settings.source_language]
    context: dict = {}
    if settings.topic.strip():
        context['general'] = [{'key': 'domain', 'value': 'university lecture'},
                              {'key': 'topic', 'value': settings.topic.strip()[:300]}]
        context['text'] = settings.topic.strip()[:4000]
    glossary = parse_glossary(settings.glossary)
    if glossary:
        context['terms'] = [s for s, _ in glossary][:300]
        pairs = [{'source': s, 'target': t} for s, t in glossary if t]
        if pairs:
            context['translation_terms'] = pairs[:300]
    if context:
        config['context'] = context
    return config


class SonioxAssembler:
    """Turns Soniox token responses into segment updates.

    Final tokens are appended once; non-final tokens are replaced by every response. A final `<end>`
    closes the current utterance. Translation lags its source and the two token streams do not map
    one to one, so translation goes to the oldest utterance that is not yet fully translated: the
    cursor moves on once that utterance is closed, has a plausible amount of translation, and no
    draft translation is pending for it.
    """

    MIN_TRANSLATION_RATIO = 0.2

    def __init__(self):
        self.segments: list[dict] = []
        self.open: int | None = None
        self.cursor = 0
        self.live_owner: dict[str, int | None] = {'src': None, 'tgt': None}
        self.pending_live_tgt = False

    def _new_segment(self, start_ms) -> int:
        self.segments.append({'id': f's{len(self.segments)}', 'src': '', 'src_live': '', 'tgt': '', 'tgt_live': '',
                              'start': None if start_ms is None else start_ms / 1000, 'end': None, 'closed': False})
        self.open = len(self.segments) - 1
        return self.open

    def _source_segment(self, start_ms) -> int:
        return self.open if self.open is not None else self._new_segment(start_ms)

    def _advance_cursor(self) -> None:
        while self.cursor < len(self.segments) - 1:
            seg = self.segments[self.cursor]
            enough = len(seg['tgt'].strip()) >= self.MIN_TRANSLATION_RATIO * len(seg['src'].strip())
            if seg['closed'] and seg['tgt'].strip() and enough and not self.pending_live_tgt:
                self.cursor += 1
            elif seg['closed'] and not seg['src'].strip():
                self.cursor += 1
            else:
                break

    def feed(self, message: dict) -> list[dict]:
        changed: set[int] = set()
        self._advance_cursor()
        live_src, live_tgt, live_start = '', '', None
        for token in message.get('tokens', []):
            text = token.get('text', '')
            status = token.get('translation_status') or 'none'
            final = bool(token.get('is_final'))
            if text in SPECIAL:
                if final and self.open is not None:
                    self.segments[self.open]['closed'] = True
                    changed.add(self.open)
                    self.open = None
                continue
            if status == 'translation':
                if final:
                    if not self.segments:
                        self._new_segment(None)
                    self.segments[self.cursor]['tgt'] += text
                    changed.add(self.cursor)
                else:
                    live_tgt += text
                continue
            # 'original' or 'none' (already in the target language: mirror it into the translation)
            if final:
                i = self._source_segment(token.get('start_ms'))
                seg = self.segments[i]
                seg['src'] += text
                if status == 'none':
                    seg['tgt'] += text
                if token.get('end_ms') is not None:
                    seg['end'] = token['end_ms'] / 1000
                changed.add(i)
            else:
                if live_start is None:
                    live_start = token.get('start_ms')
                live_src += text
                if status == 'none':
                    live_tgt += text
        if live_src.strip():
            i = self._source_segment(live_start)
        else:
            i = None
        self._set_live('src', i, live_src, changed)
        self.pending_live_tgt = bool(live_tgt.strip())
        j = min(self.cursor, len(self.segments) - 1) if self.segments and live_tgt.strip() else None
        self._set_live('tgt', j, live_tgt, changed)
        return [dict(self.segments[k]) for k in sorted(changed)]

    def _set_live(self, side: str, owner: int | None, text: str, changed: set[int]) -> None:
        key = side + '_live'
        previous = self.live_owner[side]
        if previous is not None and previous != owner and self.segments[previous][key]:
            self.segments[previous][key] = ''
            changed.add(previous)
        if owner is not None and self.segments[owner][key] != text:
            self.segments[owner][key] = text
            changed.add(owner)
        self.live_owner[side] = owner


class SonioxEngine(Engine):
    label = 'API 模式 · Soniox'

    def __init__(self, settings, key: str, url: str = URL, connect=None):
        super().__init__(settings)
        self.key, self.url = key, url
        self.connect = connect
        self.assembler = SonioxAssembler()

    POLL = 0.02          # how long to wait for replies between audio chunks
    SEND_TIMEOUT = 10.0
    FINISH_TIMEOUT = 20.0

    def run(self, audio: queue.Queue) -> None:
        if not self.key:
            raise ValueError('请先在“设置”里填写 Soniox API Key。')
        import websocket
        self.status.emit('正在连接 Soniox…')
        connect = self.connect or (lambda: websocket.create_connection(
            self.url, header=['Authorization: Bearer ' + self.key], timeout=15))
        try:
            ws = connect()
        except websocket.WebSocketBadStatusException as ex:
            raise ValueError(_status_message(ex.status_code)) from ex
        except OSError as ex:
            raise ValueError('无法连接 Soniox，请检查网络。') from ex
        # One thread both sends and reads: a read blocking on the TLS socket in another thread makes
        # concurrent writes time out ("The write operation timed out").
        self.sent = 0.0
        try:
            self._send(ws, json.dumps(build_config(self.settings, self.key)))
            self.status.emit('正在收听 · Soniox 实时转写与翻译')
            finish_by = None
            while not self.aborted.is_set():
                if finish_by is None:
                    chunk = self.next_chunk(audio)
                    if chunk is None:
                        self.status.emit('正在整理最后的内容…')
                        self._send(ws, '')
                        finish_by = time.monotonic() + self.FINISH_TIMEOUT
                    elif chunk is not False:
                        self._send(ws, to_pcm16(chunk), binary=True)
                        self.sent += len(chunk) / 16000
                elif time.monotonic() > finish_by:
                    break
                if self._drain(ws, 0.2 if finish_by else self.POLL):
                    break
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _disconnected(self) -> str:
        # Soniox drops a connection with a bad key without sending an error message.
        if self.assembler.segments:
            return '与 Soniox 的连接意外中断。'
        return 'Soniox 没有返回任何结果就断开了连接，通常是 API Key 无效。请在“设置”里重新填写。'

    def _send(self, ws, payload, binary: bool = False) -> None:
        import websocket
        try:
            ws.settimeout(self.SEND_TIMEOUT)
            ws.send_binary(payload) if binary else ws.send(payload)
        except (websocket.WebSocketException, OSError) as ex:
            raise ValueError(self._disconnected()) from ex

    def _drain(self, ws, wait: float) -> bool:
        """Handle every reply that is ready; returns True once Soniox reports the stream finished."""
        import websocket
        ws.settimeout(wait)
        while True:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                return False
            except (websocket.WebSocketException, OSError) as ex:
                raise ValueError(self._disconnected()) from ex
            if not raw:
                continue
            message = json.loads(raw)
            if message.get('error_code'):
                raise ValueError(_status_message(message['error_code'], message.get('error_message', '')))
            for update in self.assembler.feed(message):
                self.update.emit(update)
            processed = message.get('total_audio_proc_ms')
            if processed:
                self.latency.emit(max(0.0, self.sent - processed / 1000))
            if message.get('finished'):
                return True


def _status_message(code: int, detail: str = '') -> str:
    messages = {400: 'Soniox 拒绝了请求参数', 401: 'Soniox API Key 无效', 402: 'Soniox 账户余额不足',
                403: 'Soniox API Key 无权限或已过期', 408: 'Soniox 等待音频超时', 413: '已达到 Soniox 单次会话时长上限',
                429: 'Soniox 并发或频率超出限制', 503: 'Soniox 服务暂时不可用'}
    text = messages.get(int(code), f'Soniox 返回错误（{code}）')
    return text + ('：' + detail if detail and int(code) == 400 else '') + '。'
