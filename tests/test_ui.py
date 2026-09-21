import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QScrollArea
from PySide6.QtGui import QTextCursor
from app import MainWindow,STYLE
from core import Settings

def test_modes_continuous_manuscript_and_selection(monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    args=argparse.Namespace(key_file=None,topic=None,open_session=None,auto_start=False,stop_after=None,quit_after=None,screenshot=None,session_dir=None,report=None)
    window=MainWindow(args)
    window.resize(960,700);window.show();app.processEvents()
    sidebar=window.findChild(QScrollArea)
    assert sidebar.widget().width()<=sidebar.viewport().width()
    window.on_entries([{'source':f'The coefficient is {i}.','zh':f'系数是 {i}。'} for i in range(40)])
    window.set_mode(True)
    assert 'The coefficient is 0.' in window.document.toPlainText() and '系数是 39。' in window.document.toPlainText()
    window.set_mode(False)
    assert 'The coefficient' not in window.document.toPlainText() and '系数是 0。' in window.document.toPlainText()
    cursor=window.document.textCursor();cursor.movePosition(QTextCursor.MoveOperation.Start)
    cursor.movePosition(QTextCursor.MoveOperation.NextCharacter,QTextCursor.MoveMode.KeepAnchor,5);window.document.setTextCursor(cursor)
    selected=window.document.textCursor().selectedText()
    window.on_entries(window.entries+[{'source':'One more.','zh':'再来一句。'}])
    assert window.document.textCursor().selectedText()==selected and window.deferred
    # Avoid modifying live user settings from this isolated UI test.
    monkeypatch.setattr('app.save_settings',lambda *args:None)
    window.close()


def test_source_switch_remembers_each_device_and_controls_fit_small_window(monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    monkeypatch.setattr('app.load_settings',lambda:Settings())
    monkeypatch.setattr('app.save_settings',lambda *args:None)
    def devices(kind):
        suffix=' [Loopback]' if kind=='system' else ''
        return [{'index':i,'name':kind+str(i)+suffix,'kind':kind,'rate':48000,'channels':2} for i in (0,1)]
    monkeypatch.setattr('app.list_devices',devices)
    args=argparse.Namespace(key_file=None,topic=None,open_session=None,auto_start=False,stop_after=None,
                            quit_after=None,screenshot=None,session_dir=None,report=None)
    window=MainWindow(args);window.resize(960,700);window.show();app.processEvents()
    window.devices.setCurrentIndex(1)
    window.source_kind.setCurrentIndex(1)
    assert window.devices.currentData()['kind']=='microphone' and '麦克风' in window.device_note.text()
    window.devices.setCurrentIndex(1)
    window.source_kind.setCurrentIndex(0)
    assert window.devices.currentData()['name']=='system1 [Loopback]'
    assert '[Loopback]' not in window.devices.currentText()
    window.source_kind.setCurrentIndex(1)
    assert window.devices.currentData()['name']=='microphone1'
    assert window.collect_settings().microphone_name=='microphone1'
    window.refresh_devices()
    assert window.devices.currentData()['name']=='microphone1'
    window.set_running(True)
    assert not window.source_kind.isEnabled() and not window.devices.isEnabled()
    window.set_running(False)
    for button in (window.refresh_button,window.smaller,window.larger):
        assert button.width()>=button.sizeHint().width(),button.text()
        assert button.fontMetrics().horizontalAdvance(button.text())+18<=button.width()
    sidebar=window.findChild(QScrollArea)
    assert sidebar.widget().width()<=sidebar.viewport().width()
    for button in (window.start_button,window.stop_button):
        assert button.visibleRegion().boundingRect()==button.rect()
    assert '字号' in window.smaller.text() and '字号' in window.larger.text()
    previous=window.settings.font_size;window.larger.click()
    assert window.settings.font_size==previous+1 and window.font_label.text()==str(previous+1)
    window.change_font(100);assert not window.larger.isEnabled()
    window.change_font(-100);assert not window.smaller.isEnabled()
    window.on_entries([{'source':'Saved sentence.','zh':'已保存的句子。'}])
    saved=window.document.toPlainText()
    window.set_running(True);app.processEvents();height=window.document.height()
    window.on_preview([{'source':'Draft sentence.','zh':'尚待校对的预览。'}]);app.processEvents()
    assert window.document.toPlainText()==saved and '预览' in window.preview_document.toPlainText()
    assert window.document.height()==height
    window.on_preview([]);app.processEvents()
    assert window.document.height()==height and window.document.toPlainText()==saved
    window.set_running(False)
    window.close()
