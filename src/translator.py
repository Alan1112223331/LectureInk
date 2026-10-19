"""Google Translate's free web endpoint, with a worker that favours finished sentences over drafts."""
from __future__ import annotations
import re
import threading
import time
from collections import OrderedDict
import requests

URL = 'https://translate.googleapis.com/translate_a/single'


class RateLimited(Exception):
    pass


class GoogleTranslator:
    """Unofficial `client=gtx` endpoint: no key, best effort, may be rate limited or unreachable."""

    def __init__(self, source: str = 'en', target: str = 'zh-CN'):
        self.source, self.target = source, target
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 LectureInk'

    def translate(self, text: str, timeout: float = 8) -> str:
        text = text.strip()
        if not text:
            return ''
        return ''.join(self._request(part, timeout) for part in _split(text, 1500))

    def _request(self, text: str, timeout: float) -> str:
        r = self.session.get(URL, params={'client': 'gtx', 'sl': self.source, 'tl': self.target, 'dt': 't', 'q': text},
                             timeout=(5, timeout))
        if r.status_code == 429:
            raise RateLimited('谷歌翻译暂时限流')
        r.raise_for_status()
        return parse_response(r.json())


def parse_response(data) -> str:
    try:
        return ''.join(part[0] for part in data[0] if part and isinstance(part[0], str))
    except (TypeError, IndexError) as ex:
        raise ValueError('谷歌翻译返回了无法识别的结果') from ex


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ''
    for sentence in re.split(r'(?<=[.!?。！？])\s+', text):
        if current and len(current) + len(sentence) + 1 > limit:
            parts.append(current)
            current = ''
        current = (current + ' ' + sentence).strip()
        while len(current) > limit:
            parts.append(current[:limit])
            current = current[limit:]
    if current:
        parts.append(current)
    return parts


class TranslationWorker:
    """One background thread. Finished segments are translated in order and retried; drafts are
    coalesced to the newest text and throttled, so a long lecture stays under the endpoint's limits."""

    LIVE_INTERVAL = 0.9
    LIVE_BACKOFF = 30.0

    def __init__(self, translator, on_result, on_error=None):
        self.translator = translator
        self.on_result = on_result          # (segment_id, text, final)
        self.on_error = on_error or (lambda message: None)
        self.cond = threading.Condition()
        self.finals: OrderedDict[str, str] = OrderedDict()
        self.live: tuple[str, str] | None = None
        self.done_ids: set[str] = set()
        self.closing = False
        self.busy = False
        self.last_live = 0.0
        self.live_paused_until = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True, name='translator')
        self.thread.start()

    def submit_final(self, sid: str, text: str) -> None:
        with self.cond:
            self.finals[sid] = text
            if self.live and self.live[0] == sid:
                self.live = None
            self.cond.notify()

    def submit_live(self, sid: str, text: str) -> None:
        with self.cond:
            if sid in self.done_ids or sid in self.finals:
                return
            self.live = (sid, text)
            self.cond.notify()

    def close(self, timeout: float = 20.0) -> None:
        """Finish queued final translations (drafts are dropped), then stop."""
        deadline = time.monotonic() + timeout
        with self.cond:
            self.closing = True
            self.live = None
            self.cond.notify()
            while (self.finals or self.busy) and time.monotonic() < deadline:
                self.cond.wait(0.1)
            self.finals.clear()
            self.cond.notify()

    def _next(self):
        with self.cond:
            while True:
                if self.finals:
                    return self.finals.popitem(last=False) + (True,)
                if self.closing:
                    return None
                now = time.monotonic()
                if self.live and now >= self.live_paused_until:
                    wait = self.last_live + self.LIVE_INTERVAL - now
                    if wait <= 0:
                        sid, text = self.live
                        self.live = None
                        self.last_live = now
                        return sid, text, False
                    self.cond.wait(wait)
                else:
                    self.cond.wait(0.5)

    def _run(self) -> None:
        while True:
            job = self._next()
            if job is None:
                return
            sid, text, final = job
            with self.cond:
                self.busy = True
            try:
                result = self._translate(text, final)
                if result is not None:
                    with self.cond:
                        stale = not final and sid in self.done_ids
                        if final:
                            self.done_ids.add(sid)
                    if not stale:
                        self.on_result(sid, result, final)
            finally:
                with self.cond:
                    self.busy = False
                    self.cond.notify_all()

    def _translate(self, text: str, final: bool) -> str | None:
        attempts = 3 if final else 1
        for attempt in range(attempts):
            try:
                return self.translator.translate(text)
            except RateLimited:
                self.live_paused_until = time.monotonic() + self.LIVE_BACKOFF
                if not final:
                    return None
                self.on_error('谷歌翻译暂时限流，正在放慢翻译频率…')
            except (requests.RequestException, ValueError) as ex:
                if not final:
                    return None
                if attempt == attempts - 1:
                    self.on_error('翻译失败：' + _describe(ex))
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
        return '〔翻译失败〕' if final else None


def _describe(ex: Exception) -> str:
    if isinstance(ex, requests.ConnectionError):
        return '无法连接谷歌翻译，请检查网络（中国大陆网络通常无法直接访问）。'
    if isinstance(ex, requests.Timeout):
        return '谷歌翻译响应超时。'
    return str(ex)
