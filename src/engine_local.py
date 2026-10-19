"""Basic mode: Moonshine Medium Streaming on this PC, translated with Google Translate's free endpoint."""
from __future__ import annotations
import queue
import re
import time
from engine_base import Engine
from settings import parse_glossary
from translator import GoogleTranslator, TranslationWorker

MODEL_NOTE = 'Moonshine Medium Streaming（英语，约 260 MB，首次使用自动下载）'
TERMINAL = re.compile(r'[.?!…]["\'”’)\]]*$')
REPEAT = re.compile(r"\b([\w']+)((?:[\s,.;:!?-]+\1\b){3,})", re.I)
# Moonshine capitalises every line; a line that continues an unfinished sentence and starts with
# one of these words is lower-cased so the joined sentence reads naturally.
CONTINUATION_WORDS = {
    'and', 'but', 'or', 'so', 'which', 'that', 'who', 'whom', 'whose', 'because', 'when', 'where', 'while',
    'if', 'then', 'with', 'without', 'of', 'to', 'in', 'on', 'for', 'as', 'at', 'by', 'from', 'than', 'the',
    'a', 'an', 'it', 'is', 'are', 'was', 'were', 'be', 'this', 'these', 'those', 'we', 'you', 'they', 'he',
    'she', 'its', 'their', 'our', 'into', 'about', 'after', 'before', 'until', 'unless', 'although', 'though',
    'since', 'whether', 'how', 'what', 'why', 'also', 'not', 'very', 'more', 'most', 'just', 'only'}


def continue_sentence(previous: str, text: str) -> str:
    if not previous or TERMINAL.search(previous):
        return text
    first = text.split(' ', 1)[0]
    if first[:1].isupper() and not first.isupper() and first.lower().strip(',.') in CONTINUATION_WORDS:
        return text[:1].lower() + text[1:]
    return text


def clean_line(text: str) -> str:
    """Suppress typical decoder failures on noise: a word looping ("the, the, the, the…") is cut to two,
    and a line that is mostly non-Latin script cannot come from this English-only model."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isascii() for c in letters) < 0.6 * len(letters):
        return ''
    return REPEAT.sub(lambda m: f'{m.group(1)}, {m.group(1)}…', text).strip()


class Agc:
    """Slow automatic gain for the recogniser's input only: lifts quiet microphones, tames clipped
    loopback audio, and leaves near-silence alone so room noise is not amplified into "speech"."""

    TARGET, MAX_GAIN, GATE = 0.08, 16.0, 0.0012

    def __init__(self):
        self.gain = 1.0

    def __call__(self, chunk):
        import numpy as np
        rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
        if rms > self.GATE:
            want = min(self.MAX_GAIN, self.TARGET / rms)
            # Quick to turn down (avoid clipping), slow to turn up (avoid pumping between words).
            self.gain += (want - self.gain) * (0.35 if want < self.gain else 0.04)
        return np.clip(chunk * self.gain, -0.98, 0.98).astype(np.float32)


class SentenceBuilder:
    """Joins Moonshine lines (cut at short pauses) into sentences, so the translator sees whole
    sentences. A sentence ends at terminal punctuation, after a longer silence, or when too long."""

    JOIN_GAP = 1.2
    MAX_CHARS = 300

    def __init__(self, emit, translate_final, translate_live):
        self.emit, self.translate_final, self.translate_live = emit, translate_final, translate_live
        self.count = 0
        self.current: dict | None = None
        self.live_line: int | None = None
        self.completed: set[int] = set()

    def _open(self, start: float) -> None:
        self.count += 1
        self.current = {'id': f'u{self.count}', 'parts': [], 'start': start, 'end': start}

    def close(self) -> None:
        cur = self.current
        if not cur:
            return
        self.current = None
        text = self._joined(cur)
        if not text:
            return
        self.emit({'id': cur['id'], 'src': text, 'src_live': '', 'end': cur['end'], 'closed': True})
        self.translate_final(cur['id'], text)

    @staticmethod
    def _joined(cur: dict) -> str:
        return ' '.join(cur['parts'])

    def line(self, line_id: int, text: str, start: float, end: float, complete: bool) -> None:
        if line_id in self.completed:
            return
        if not text:
            # A line rejected as noise: forget its draft, keep the sentence it would have joined.
            if complete:
                self.completed.add(line_id)
            if self.live_line == line_id:
                self.live_line = None
            if self.current:
                self.emit({'id': self.current['id'], 'src': self._joined(self.current), 'src_live': ''})
            return
        if self.current and self.current['parts'] and self.live_line != line_id \
                and start - self.current['end'] >= self.JOIN_GAP:
            self.close()
        if not self.current:
            self._open(start)
        cur = self.current
        if complete:
            self.completed.add(line_id)
            self.live_line = None
            cur['parts'].append(continue_sentence(cur['parts'][-1] if cur['parts'] else '', text))
            cur['end'] = end
            joined = self._joined(cur)
            if TERMINAL.search(text) or len(joined) >= self.MAX_CHARS:
                self.emit({'id': cur['id'], 'start': cur['start'], 'end': end})
                self.close()
            else:
                self.emit({'id': cur['id'], 'src': joined, 'src_live': '', 'start': cur['start'], 'end': end})
                self.translate_live(cur['id'], joined)
        else:
            self.live_line = line_id
            done = self._joined(cur)
            draft = continue_sentence(cur['parts'][-1] if cur['parts'] else '', text)
            self.emit({'id': cur['id'], 'src': done, 'src_live': (' ' if done else '') + draft,
                       'start': cur['start'], 'end': max(cur['end'], end)})
            self.translate_live(cur['id'], (done + ' ' + draft).strip())

    def tick(self, audio_time: float) -> None:
        """Close a sentence left open without punctuation once the speaker has paused long enough."""
        cur = self.current
        if cur and cur['parts'] and self.live_line is None and audio_time - cur['end'] >= self.JOIN_GAP + 0.3:
            self.close()


class GlossaryTranslator:
    """Google has no glossary. Ask once how it translates each term on its own, then, in sentences
    containing the term, replace that rendering with the preferred one."""

    def __init__(self, translator, glossary: str):
        self.translator = translator
        self.pairs = [(s, t) for s, t in parse_glossary(glossary) if t][:60]
        self.rules: list[tuple[re.Pattern, str, str]] | None = None if self.pairs else []

    def _prepare(self) -> None:
        try:
            defaults = self.translator.translate('\n'.join(s for s, _ in self.pairs)).split('\n')
        except Exception:
            return  # tried again with the next sentence
        self.rules = []
        if len(defaults) != len(self.pairs):
            defaults = [self.translator.translate(s) for s, _ in self.pairs]
        for (source, target), default in zip(self.pairs, defaults):
            default = default.strip()
            if default and default != target:
                pattern = re.compile(r'(?<![\w-])' + re.escape(source) + r'(?![\w-])', re.I)
                self.rules.append((pattern, default, target))
        self.rules.sort(key=lambda r: -len(r[1]))

    def translate(self, text: str) -> str:
        if self.rules is None:
            self._prepare()
        result = self.translator.translate(text)
        for pattern, default, target in self.rules or []:
            if pattern.search(text):
                result = result.replace(default, target)
        return result


class LocalEngine(Engine):
    label = '基础模式 · 本地识别 + 谷歌翻译'
    UPDATE_INTERVAL = 0.3
    LIVE_MIN_WORDS = 3       # do not translate a two-word fragment
    LIVE_STEP_WORDS = 2      # re-translate a draft once it has grown this much
    LIVE_STALE = 1.6         # ...or when it changed and has waited this long

    def __init__(self, settings, translator=None):
        super().__init__(settings)
        self.translator = GlossaryTranslator(translator or GoogleTranslator('en', 'zh-CN'), settings.glossary)
        self.live_sent: dict[str, tuple[int, float, str]] = {}
        self.worker: TranslationWorker | None = None

    def load_model(self):
        from moonshine_voice import ModelArch, get_model_for_language
        from moonshine_voice.transcriber import Transcriber
        self.status.emit('正在准备本地识别模型…')
        last = [-1]

        def progress(fraction, *_):
            pct = int(fraction * 100)
            if pct != last[0]:
                last[0] = pct
                self.status.emit(f'首次使用：正在下载识别模型 {pct}%')
        path, arch = get_model_for_language('en', ModelArch.MEDIUM_STREAMING, on_progress=progress)
        self.status.emit('正在加载本地识别模型…')
        transcriber = Transcriber(path, arch, update_interval=self.UPDATE_INTERVAL)
        terms = [s for s, _ in parse_glossary(self.settings.glossary) if ',' not in s]
        try:
            if terms:
                transcriber.set_keyterms(terms[:200])
            elif self.settings.topic.strip():
                transcriber.set_context(self.settings.topic, max_terms=80)
        except Exception as ex:
            self.notice.emit('术语偏置未生效：' + str(ex))
        return transcriber

    def run(self, audio: queue.Queue) -> None:
        from moonshine_voice.transcriber import LineCompleted, LineStarted, LineTextChanged
        transcriber = self.load_model()
        self.worker = TranslationWorker(self.translator, self._on_translation, self.notice.emit)
        builder = SentenceBuilder(self.update.emit, self._final, self._maybe_live)
        agc = Agc()
        stream = transcriber.create_stream(self.UPDATE_INTERVAL)

        def on_event(event):
            if not isinstance(event, (LineStarted, LineTextChanged, LineCompleted)):
                return
            line = event.line
            done = isinstance(event, LineCompleted)
            text = clean_line(' '.join(line.text.split()))
            if not text and not done and builder.live_line != line.line_id:
                return
            builder.line(line.line_id, text, line.start_time, line.start_time + line.duration, done)
            if line.last_transcription_latency_ms:
                self.latency.emit(line.last_transcription_latency_ms / 1000)

        stream.add_listener(on_event)
        stream.start()
        self.status.emit('正在收听 · 本地识别中')
        audio_time = 0.0
        try:
            while not self.aborted.is_set():
                chunk = self.next_chunk(audio)
                if chunk is None:
                    break
                if chunk is False:
                    continue
                stream.add_audio(agc(chunk), 16000)
                audio_time += len(chunk) / 16000
                builder.tick(audio_time)
            if not self.aborted.is_set():
                self.status.emit('正在整理最后的内容…')
                stream.stop()
                builder.close()
                self.worker.close()
        finally:
            if self.aborted.is_set():
                self.worker.close(timeout=0)
            stream.close()
            transcriber.close()

    def _final(self, sid: str, text: str) -> None:
        self.live_sent.pop(sid, None)
        self.worker.submit_final(sid, text)

    def _maybe_live(self, sid: str, text: str) -> None:
        words = len(text.split())
        if words < self.LIVE_MIN_WORDS:
            return
        sent_words, sent_at, sent_text = self.live_sent.get(sid, (0, 0.0, ''))
        now = time.monotonic()
        if words - sent_words >= self.LIVE_STEP_WORDS or (text != sent_text and now - sent_at >= self.LIVE_STALE):
            self.live_sent[sid] = (words, now, text)
            self.worker.submit_live(sid, text)

    def _on_translation(self, sid: str, text: str, final: bool) -> None:
        if final:
            self.update.emit({'id': sid, 'tgt': text, 'tgt_live': ''})
        else:
            self.update.emit({'id': sid, 'tgt_live': text})
