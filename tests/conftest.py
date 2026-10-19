import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ASSETS = Path(__file__).resolve().parent / 'assets'


def drain_events():
    """Deliver signals that worker threads queued for the main thread."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    for _ in range(5):
        app.processEvents()
