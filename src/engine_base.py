"""Common engine plumbing: a worker thread that reads audio chunks and emits segment updates."""
from __future__ import annotations
import queue
import threading
from PySide6.QtCore import QObject, Signal


class Engine(QObject):
    update = Signal(object)      # dict: id plus any of src/src_live/tgt/tgt_live/start/end/closed
    status = Signal(str)
    error = Signal(str)
    notice = Signal(str)         # recoverable problems, shown without stopping
    latency = Signal(float)      # seconds from speech to text, when the engine can tell
    finished = Signal()

    label = ''

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.aborted = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self, audio: queue.Queue) -> None:
        self.thread = threading.Thread(target=self._main, args=(audio,), daemon=True, name=type(self).__name__)
        self.thread.start()

    def abort(self) -> None:
        """Stop without flushing (window closing)."""
        self.aborted.set()

    def _main(self, audio: queue.Queue) -> None:
        try:
            self.run(audio)
        except Exception as ex:
            if not self.aborted.is_set():
                self.error.emit(str(ex) or type(ex).__name__)
        finally:
            self.finished.emit()

    def run(self, audio: queue.Queue) -> None:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def next_chunk(self, audio: queue.Queue):
        """Next chunk, `None` at the end of audio. Returns `False` while waiting."""
        try:
            return audio.get(timeout=0.2)
        except queue.Empty:
            return False
