import argparse
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    from app import MainWindow
    args = argparse.Namespace(mode='local', audio_file='x.wav', auto_start=False, stop_after=None, quit_after=None,
                              overlay=False, open=None, report=None, screenshot=None, shot_at=None,
                              session_dir=str(tmp_path / 'sessions'), settings_file=str(tmp_path / 'settings.json'))
    w = MainWindow(args)
    yield w
    w.overlay.close()
    w.close()


def feed(window, updates):
    for u in updates:
        window.transcript.apply(u)
    window.render()


def test_panes_render_paragraphs_and_live_text(window):
    feed(window, [{'id': 'a', 'src': 'One.', 'tgt': '一。', 'start': 0, 'end': 1},
                  {'id': 'b', 'src': 'Two', 'src_live': ' three', 'tgt_live': '二', 'start': 1.2, 'end': 2},
                  {'id': 'c', 'src': 'New paragraph.', 'start': 6, 'end': 7}])
    src = window.src_pane.view.document()
    assert src.blockCount() == 2
    assert src.firstBlock().text() == 'One. Two three'
    assert window.tgt_pane.view.document().firstBlock().text() == '一。二'
    # Live text is rewritten in place when it becomes final.
    feed(window, [{'id': 'b', 'src': 'Two three.', 'src_live': ''}])
    assert src.firstBlock().text() == 'One. Two three.'
    assert src.blockCount() == 2
    assert '2 段' in window.count_label.text()


def test_view_modes_hide_panes(window):
    window.set_view('target')
    assert window.src_pane.isHidden() and not window.tgt_pane.isHidden()
    window.set_view('both')
    assert not window.src_pane.isHidden()


def test_overlay_shows_recent_text(window):
    window.set_overlay(True)
    feed(window, [{'id': 'a', 'src': 'Hello.', 'tgt': '你好。', 'start': 0, 'end': 1}])
    assert window.overlay.tgt_runs == [('你好。', False)]
    assert not window.overlay.grab().isNull()
    height = window.overlay.height()
    window.overlay.change_font(4)
    assert window.overlay.height() > height
    window.set_overlay(False)
    assert not window.overlay.isVisible()


def test_settings_persist(window, tmp_path):
    from settings import load_settings
    window.change_font(2)
    assert load_settings(tmp_path / 'settings.json').font_size == window.settings.font_size


def test_open_saved_transcript(window, tmp_path):
    from transcript import Transcript
    t = Transcript()
    t.apply({'id': 'a', 'src': 'Saved.', 'tgt': '已保存。', 'start': 0, 'end': 1})
    t.save(tmp_path / 'transcript.json')
    window.open_transcript(str(tmp_path / 'transcript.json'))
    assert window.tgt_pane.view.document().firstBlock().text() == '已保存。'
