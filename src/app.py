from __future__ import annotations
import argparse
import dataclasses
import html
import json
import os
from pathlib import Path
import sys
import threading
import time
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF
from PySide6.QtGui import QAction, QFont, QIcon, QPainter, QColor, QPixmap, QPen, QTextOption
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QLabel,QPushButton,
    QComboBox,QTextEdit,QTextBrowser,QLineEdit,QCheckBox,QDialog,QDialogButtonBox,QFormLayout,
    QFileDialog,QMessageBox,QFrame,QProgressBar,QSpinBox,QSizePolicy,QScrollArea)
from core import Settings,MODEL,app_data,load_settings,save_settings,protect_secret,transcript_text,atomic_json,AudioClient
from audio_engine import list_devices,TranslationSession

STYLE='''
QWidget {font-family:"Microsoft YaHei UI", "Segoe UI";font-size:13px;color:#243a36;}
QMainWindow, QDialog {background:#f2f4f0;}
QLabel#brand {font-size:23px;font-weight:700;color:#123e36;}
QLabel#eyebrow {font-size:11px;font-weight:600;color:#648076;letter-spacing:2px;}
QLabel#muted {color:#718078;font-size:12px;}
QLabel#label {font-size:12px;font-weight:600;color:#405e54;}
QLabel#title {font-size:25px;font-weight:600;color:#213e34;}
QFrame#sidebar {background:#e8eee7;border:1px solid #dce5dc;border-radius:14px;}
QWidget#configuration {background:#e8eee7;}
QFrame#paper {background:#fffef9;border:1px solid #e1e5db;border-radius:14px;}
QFrame#preview {background:#f0f5ec;border:1px solid #d7e3d3;border-radius:8px;}
QTextEdit,QLineEdit,QComboBox,QSpinBox {background:#fafcf8;border:1px solid #cfdacf;border-radius:7px;padding:9px;selection-background-color:#b6d9c8;}
QTextEdit:focus,QLineEdit:focus,QComboBox:focus {border:1px solid #488772;}
QComboBox {min-height:20px;padding-right:23px;}
QComboBox::drop-down {width:28px;border:0;background:transparent;}
QComboBox::down-arrow {image:none;width:0;height:0;}
QComboBox QAbstractItemView {background:#fffef9;selection-background-color:#d8e9df;color:#203e33;}
QPushButton {background:#fafcf8;border:1px solid #ccd9ce;border-radius:7px;padding:9px 14px;color:#2b5144;}
QPushButton:hover {background:#e0ebe2;border-color:#97bba4;}
QPushButton:disabled {color:#9aa99e;border-color:#d7e0d6;background:#edf1eb;}
QPushButton#primary {background:#1e6450;border:0;color:white;font-size:14px;font-weight:600;min-height:27px;}
QPushButton#primary:hover {background:#17503f;}
QPushButton#primary:disabled {background:#b6c8ba;color:#eef4ed;}
QPushButton#mode {border:0;background:transparent;color:#78877d;padding:8px 16px;}
QPushButton#mode:checked {background:#e0ece1;color:#245641;font-weight:600;}
QPushButton#stop {border-color:#cda98c;color:#865738;background:#f8f1e9;}
QPushButton#stop:disabled {border-color:#d7e0d6;color:#9aa99e;background:#edf1eb;}
QPushButton#compact {padding:6px 10px;}
QPushButton#refresh {padding:4px 8px;font-size:12px;}
QTextBrowser {background:transparent;border:0;selection-background-color:#c6e5d1;selection-color:#183c2b;}
QProgressBar {border:0;background:#cfdccd;border-radius:3px;max-height:5px;}
QProgressBar::chunk {background:#4d9877;border-radius:3px;}
QCheckBox {spacing:6px;color:#536b5e;font-size:12px;}
QCheckBox::indicator {width:16px;height:16px;border:1px solid #98b3a4;border-radius:4px;background:#fafcf8;}
QCheckBox::indicator:checked {background:#1e6450;border-color:#1e6450;}
QScrollBar:vertical {background:transparent;width:9px;margin:1px;}
QScrollBar::handle:vertical {background:#cad6c9;border-radius:4px;min-height:35px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QLabel#error {background:#fff1de;border:1px solid #e6c795;border-radius:8px;padding:12px;color:#79551d;}
'''

def label(text,name=None):
    w=QLabel(text)
    if name:w.setObjectName(name)
    return w


class ChoiceBox(QComboBox):
    """Draw a scale-independent chevron; give long device names room in the popup."""
    def paintEvent(self,event):
        super().paintEvent(event)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#527365' if self.isEnabled() else '#a9b7ad'),1.6))
        x=self.width()-15;y=self.height()/2
        p.drawLine(QPointF(x-4,y-2),QPointF(x,y+2));p.drawLine(QPointF(x,y+2),QPointF(x+4,y-2));p.end()

    def showPopup(self):
        widest=max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())),default=0)
        self.view().setMinimumWidth(max(self.width(),min(620,widest+48)))
        super().showPopup()


class FollowCheckBox(QCheckBox):
    def paintEvent(self,event):
        super().paintEvent(event)
        if self.isChecked():
            p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor('white'),1.8));y=self.height()/2
            p.drawLine(QPointF(4,y),QPointF(7,y+3));p.drawLine(QPointF(7,y+3),QPointF(13,y-3));p.end()

def icon():
    pix=QPixmap(64,64);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor('#1e6450'));p.setPen(Qt.PenStyle.NoPen);p.drawRoundedRect(1,1,62,62,15,15)
    p.setPen(QColor('#f1f2d8'))
    for i,h in enumerate([12,23,35,24,15]):p.drawRoundedRect(16+i*7,32-h//2,3,h,1,1)
    p.end();return QIcon(pix)

class KeyDialog(QDialog):
    def __init__(self,key,remember,parent=None):
        super().__init__(parent);self.setWindowTitle('连接硅基流动');self.setMinimumWidth(460)
        layout=QVBoxLayout(self);layout.setContentsMargins(26,24,26,24);layout.setSpacing(15)
        layout.addWidget(label('连接你的音频模型','title'))
        note=label('音频直接发送至硅基流动，由 Qwen3-Omni 理解与翻译。','muted');note.setWordWrap(True);layout.addWidget(note)
        layout.addWidget(label('API Key','label'))
        self.key=QLineEdit(key);self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('sk-…');self.key.setAccessibleName('API Key');layout.addWidget(self.key)
        self.remember=FollowCheckBox('在本机加密记住密钥');self.remember.setChecked(remember);layout.addWidget(self.remember)
        more=label('密钥不会写入文稿或分享包。接收程序的人可填写自己的密钥。','muted');more.setWordWrap(True);layout.addWidget(more)
        layout.addWidget(label('模型：'+MODEL,'muted'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

class BackgroundSignals(QObject):
    checked=Signal(str)

class MainWindow(QMainWindow):
    def __init__(self,args):
        super().__init__();self.args=args;self.settings=load_settings();self.entries=[];self.session=None
        self.key='';self.busy=False;self.deferred=False;self.last_request=0.;self.signals=BackgroundSignals()
        self.signals.checked.connect(self.on_checked)
        if self.settings.protected_key:
            try:self.key=protect_secret(self.settings.protected_key,True)
            except Exception:pass
        self.key=os.environ.get('SILICONFLOW_API_KEY',self.key)
        candidates=[]
        if args.key_file:candidates.append(Path(args.key_file))
        candidates.append((Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])/'apikey.txt')
        for path in candidates:
            if path.is_file():
                self.key=path.read_text(encoding='utf-8-sig').strip();break
        if args.topic:self.settings.topic=args.topic
        if getattr(args,'source_kind',None):self.settings.source_kind=args.source_kind
        if getattr(args,'segment_seconds',None):self.settings.segment_seconds=args.segment_seconds
        self.preview_entries=[]
        self._listed_kind=None
        self.setWindowTitle('听课稿 · LectureInk');self.setWindowIcon(icon());self.resize(1180,820);self.setMinimumSize(960,700)
        self.build_ui();self.refresh_devices();self.render();self.update_key_status()
        if args.open_session:self.open_session(args.open_session)
        if args.auto_start:QTimer.singleShot(500,self.start)
        if args.stop_after:QTimer.singleShot(int(args.stop_after*1000),self.stop)
        if args.quit_after:QTimer.singleShot(int(args.quit_after*1000),self.close)
        self.status_timer=QTimer(self);self.status_timer.timeout.connect(self.tick);self.status_timer.start(1000)
        if args.screenshot:QTimer.singleShot(1200,lambda:self.grab().save(args.screenshot))

    def build_ui(self):
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(24,20,24,15);outer.setSpacing(18)
        head=QHBoxLayout();brand=QVBoxLayout();brand.setSpacing(3)
        brand.addWidget(label('听课稿','brand'));brand.addWidget(label('LECTUREINK  /  把课堂听成文稿','eyebrow'));head.addLayout(brand);head.addStretch()
        self.key_status=label('','muted');head.addWidget(self.key_status)
        self.key_button=QPushButton('连接设置');self.key_button.clicked.connect(self.key_dialog);head.addWidget(self.key_button)
        self.open_button=QPushButton('打开文稿');self.open_button.clicked.connect(lambda:self.open_session());head.addWidget(self.open_button)
        self.export_button=QPushButton('导出文稿');self.export_button.clicked.connect(self.export);head.addWidget(self.export_button);outer.addLayout(head)
        self.error_label=label('','error');self.error_label.setWordWrap(True);self.error_label.hide();outer.addWidget(self.error_label)
        body=QHBoxLayout();body.setSpacing(18);outer.addLayout(body,1)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(310)
        side_layout=QVBoxLayout(side);side_layout.setContentsMargins(18,16,18,18);side_layout.setSpacing(12)
        config=QWidget();config.setObjectName('configuration');config.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);config.setMinimumWidth(0)
        s=QVBoxLayout(config);s.setContentsMargins(0,0,6,0);s.setSpacing(7)
        s.addWidget(label('本次课程','eyebrow'))
        s.addWidget(label('主要在讲什么？','label'))
        self.topic=QTextEdit();self.topic.setAccessibleName('课程主题');self.topic.setPlaceholderText('例如：机器学习，线性回归、矩阵求逆和正则化');self.topic.setPlainText(self.settings.topic);self.topic.setFixedHeight(62);s.addWidget(self.topic)
        s.addWidget(label('术语与背景（可选）','label'))
        self.glossary=QTextEdit();self.glossary.setAccessibleName('术语与背景');self.glossary.setPlaceholderText('例如：ridge regression = 岭回归\npseudoinverse = 伪逆\n可粘贴本节课的术语或简短提纲');self.glossary.setPlainText(self.settings.glossary);self.glossary.setFixedHeight(70);s.addWidget(self.glossary)
        row=QHBoxLayout();row.addWidget(label('原音语言','label'));row.addStretch();self.language=ChoiceBox();self.language.setAccessibleName('原音语言');self.language.addItems(['自动识别','英语','日语','韩语','法语','德语','西班牙语','中文']);self.language.setCurrentText(self.settings.language);self.language.setMaximumWidth(130);row.addWidget(self.language);s.addLayout(row)
        devrow=QHBoxLayout();devrow.addWidget(label('声音来源','label'));devrow.addStretch()
        self.refresh_button=QPushButton('刷新设备');self.refresh_button.setObjectName('refresh');self.refresh_button.setToolTip('重新查找新接入的耳机、扬声器和麦克风');self.refresh_button.clicked.connect(self.refresh_devices);devrow.addWidget(self.refresh_button);s.addLayout(devrow)
        self.source_kind=ChoiceBox();self.source_kind.setAccessibleName('声音来源类型')
        self.source_kind.addItem('系统声音 · 网课播放','system');self.source_kind.addItem('麦克风 · 现场收音','microphone')
        self.source_kind.setCurrentIndex(max(0,self.source_kind.findData(self.settings.source_kind)));s.addWidget(self.source_kind)
        self.devices=ChoiceBox();self.devices.setAccessibleName('音频设备');self.devices.setMinimumWidth(0);self.devices.setMinimumContentsLength(8);self.devices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon);self.devices.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);s.addWidget(self.devices)
        self.devices.currentIndexChanged.connect(self.update_device_tooltip)
        self.source_kind.currentIndexChanged.connect(self.refresh_devices)
        self.meter=QProgressBar();self.meter.setRange(0,100);self.meter.setTextVisible(False);self.meter.setValue(0);s.addWidget(self.meter)
        self.device_note=label('','muted');self.device_note.setWordWrap(True);s.addWidget(self.device_note)
        s.addWidget(label('音频语境长度','label'))
        self.pace=ChoiceBox();self.pace.setAccessibleName('音频语境长度');self.pace.addItem('快速预览 · 8 秒',8);self.pace.addItem('均衡 · 12 秒',12);self.pace.addItem('更多语境 · 18 秒',18);self.pace.addItem('长语境 · 26 秒',26)
        idx=self.pace.findData(self.settings.segment_seconds);self.pace.setCurrentIndex(max(0,idx));s.addWidget(self.pace)
        context_note=label('只在人声出现时翻译。\n保留前后文，未完句随后文补全。','muted');context_note.setWordWrap(True);s.addWidget(context_note)
        s.addStretch()
        sidebar_scroll=QScrollArea();sidebar_scroll.setWidgetResizable(True);sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setWidget(config);sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setStyleSheet('QScrollArea {background:transparent;}');side_layout.addWidget(sidebar_scroll,1)
        self.start_button=QPushButton('开始听课');self.start_button.setObjectName('primary');self.start_button.clicked.connect(self.start);side_layout.addWidget(self.start_button)
        self.stop_button=QPushButton('结束并处理剩余音频');self.stop_button.setObjectName('stop');self.stop_button.setToolTip('停止收音，并继续翻译已经采集的剩余音频');self.stop_button.clicked.connect(self.stop);self.stop_button.setEnabled(False);side_layout.addWidget(self.stop_button)
        self.retry_button=QPushButton('重试未完成的音频');self.retry_button.clicked.connect(self.retry);self.retry_button.hide();side_layout.addWidget(self.retry_button)
        body.addWidget(side)
        paper=QFrame();paper.setObjectName('paper');p=QVBoxLayout(paper);p.setContentsMargins(30,23,25,17);p.setSpacing(9)
        dochead=QHBoxLayout();dochead.addWidget(label('课堂文稿','title'));dochead.addStretch()
        self.chinese=QPushButton('中文');self.chinese.setObjectName('mode');self.chinese.setCheckable(True);self.chinese.setAccessibleName('仅中文')
        self.bilingual=QPushButton('双语');self.bilingual.setObjectName('mode');self.bilingual.setCheckable(True);self.bilingual.setAccessibleName('双语显示')
        self.chinese.clicked.connect(lambda:self.set_mode(False));self.bilingual.clicked.connect(lambda:self.set_mode(True));dochead.addWidget(self.chinese);dochead.addWidget(self.bilingual);p.addLayout(dochead)
        self.doc_meta=label('按句整理 · 自动折行 · 可选择、复制与导出','muted');p.addWidget(self.doc_meta)
        line=QFrame();line.setFrameShape(QFrame.Shape.HLine);line.setStyleSheet('color:#e5e8dd;');p.addWidget(line)
        self.document=QTextBrowser();self.document.setAccessibleName('连续课堂文稿');self.document.setOpenExternalLinks(False);self.document.setOpenLinks(False);self.document.setUndoRedoEnabled(False);self.document.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);self.document.selectionChanged.connect(self.selection_changed);p.addWidget(self.document,1)
        self.preview_panel=QFrame();self.preview_panel.setObjectName('preview');preview_layout=QVBoxLayout(self.preview_panel);preview_layout.setContentsMargins(12,8,12,8);preview_layout.setSpacing(4)
        self.preview_title=label('即时预览 · 待校对，后文可能修订','muted');preview_layout.addWidget(self.preview_title)
        self.preview_document=QTextBrowser();self.preview_document.setAccessibleName('即时翻译预览');self.preview_document.setFixedHeight(88);self.preview_document.setOpenLinks(False);self.preview_document.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.preview_document.selectionChanged.connect(self.preview_selection_changed);preview_layout.addWidget(self.preview_document)
        p.addWidget(self.preview_panel);self.preview_panel.hide()
        foot=QHBoxLayout();self.count=label('0 句','muted');foot.addWidget(self.count);foot.addStretch()
        self.follow=FollowCheckBox('跟随最新内容');self.follow.setChecked(True);self.follow.toggled.connect(self.follow_changed);foot.addWidget(self.follow)
        self.smaller=QPushButton('缩小字号');self.smaller.setObjectName('compact');self.smaller.setToolTip('缩小原文与译文的字号');self.smaller.clicked.connect(lambda:self.change_font(-1));foot.addWidget(self.smaller)
        self.font_label=label(str(self.settings.font_size),'muted');self.font_label.setAlignment(Qt.AlignmentFlag.AlignCenter);self.font_label.setMinimumWidth(20);foot.addWidget(self.font_label)
        self.larger=QPushButton('放大字号');self.larger.setObjectName('compact');self.larger.setToolTip('放大原文与译文的字号');self.larger.clicked.connect(lambda:self.change_font(1));foot.addWidget(self.larger);p.addLayout(foot);body.addWidget(paper,1)
        status=QHBoxLayout();self.status_label=label('准备就绪 · 填写课程主题，开始听课','muted');status.addWidget(self.status_label);status.addStretch();self.stats_label=label('Qwen3-Omni · 音频直译','muted');status.addWidget(self.stats_label);outer.addLayout(status)
        self.chinese.setChecked(not self.settings.bilingual);self.bilingual.setChecked(self.settings.bilingual)
        for title,shortcut,callback in [('导出文稿','Ctrl+S',self.export),('打开文稿','Ctrl+O',lambda:self.open_session())]:
            action=QAction(title,self);action.setShortcut(shortcut);action.triggered.connect(callback);self.addAction(action)

    def collect_settings(self):
        self.settings.topic=self.topic.toPlainText().strip()[:6000]
        self.settings.glossary=self.glossary.toPlainText().strip()[:10000]
        self.settings.language=self.language.currentText()
        self.settings.segment_seconds=self.pace.currentData()
        self.settings.source_kind=self.source_kind.currentData()
        self.remember_device()
        return self.settings

    def key_dialog(self):
        dialog=KeyDialog(self.key,self.settings.remember_key,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.key=dialog.key.text().strip();self.settings.remember_key=dialog.remember.isChecked()
            try:save_settings(self.collect_settings(),self.key)
            except Exception as ex:self.show_error(str(ex))
            self.update_key_status()

    def update_key_status(self):
        self.key_status.setText('已填写密钥' if self.key else '尚未连接')

    def remember_device(self):
        device=self.devices.currentData()
        if device:
            field='microphone_name' if self._listed_kind=='microphone' else 'device_name'
            setattr(self.settings,field,device['name'])

    def update_device_tooltip(self):
        device=self.devices.currentData()
        self.devices.setToolTip(device['name'] if device else '没有可用设备，请连接后刷新')

    def refresh_devices(self):
        self.remember_device()
        kind=self.source_kind.currentData()
        self._listed_kind=kind
        self.device_note.setText('采集麦克风周围的人声。\n开始后说话，声音条会随音量变化。' if kind=='microphone'
                                 else '采集所选耳机／扬声器的声音。\n开始后播放课程，保持视频有声。')
        try:
            selected=self.settings.microphone_name if kind=='microphone' else self.settings.device_name
            self.devices.clear()
            for d in list_devices(kind):
                display=d['name'].removesuffix(' [Loopback]')
                self.devices.addItem(display,d)
                self.devices.setItemData(self.devices.count()-1,d['name'],Qt.ItemDataRole.ToolTipRole)
                if d['name']==selected:self.devices.setCurrentIndex(self.devices.count()-1)
            self.update_device_tooltip()
            if not self.devices.count():
                self.show_error('未找到麦克风，请连接麦克风后点击“刷新设备”。' if kind=='microphone'
                                else '未找到可采集的输出设备，请连接扬声器或耳机后刷新。')
            elif self.error_label.text().startswith(('未找到麦克风','未找到可采集的输出设备','无法枚举音频设备')):
                self.error_label.hide()
        except Exception as ex:self.show_error('无法枚举音频设备：'+str(ex))

    def start(self):
        if self.busy:return
        if not self.key:self.key_dialog()
        if not self.key:return
        if not self.devices.currentData():self.show_error('请先选择可用的音频设备。');return
        self.error_label.hide();self.collect_settings();self.busy=True;self.set_running(True)
        self.status_label.setText('正在检查连接…')
        def check():
            try:AudioClient(self.key).check();self.signals.checked.emit('')
            except Exception as ex:self.signals.checked.emit(str(ex))
        threading.Thread(target=check,daemon=True).start()

    def on_checked(self,error):
        if error:self.show_error(error);self.busy=False;self.set_running(False);return
        self.key_status.setText('● 已连接硅基流动')
        self.entries=[];self.render()
        self.session=TranslationSession(self.key,dataclasses.replace(self.settings),self.devices.currentData(),Path(self.args.session_dir) if self.args.session_dir else None)
        self.connect_session();self.session.start()
        try:save_settings(self.settings,self.key)
        except Exception as ex:self.show_error(str(ex))

    def connect_session(self):
        e=self.session.events;e.changed.connect(self.on_entries);e.status.connect(self.status_label.setText);e.error.connect(self.show_error)
        e.preview.connect(self.on_preview)
        e.level.connect(lambda x:self.meter.setValue(min(100,int(x*800))))
        e.stats.connect(self.on_stats);e.stopped.connect(self.on_stopped)
        self.retry_button.hide()

    def set_running(self,active):
        self.start_button.setEnabled(not active);self.stop_button.setEnabled(active)
        self.devices.setEnabled(not active);self.refresh_button.setEnabled(not active);self.open_button.setEnabled(not active)
        self.source_kind.setEnabled(not active)
        self.key_button.setEnabled(not active);self.pace.setEnabled(not active)
        self.preview_panel.setVisible(active)
        if not active:self.preview_entries=[]
        self.render_preview()

    def stop(self):
        if self.session and self.busy:
            self.session.finish();self.stop_button.setEnabled(False)

    def retry(self):
        if not self.session or self.busy:return
        self.error_label.hide();self.retry_button.hide();self.busy=True;self.set_running(True);self.stop_button.setEnabled(False)
        self.session.retry(self.key)

    def on_stopped(self):
        self.busy=False;self.set_running(False);self.meter.setValue(0)
        if not self.document.textCursor().hasSelection():self.render()
        self.start_button.setText('开始新的听课')
        if self.session and self.session.failed:self.retry_button.show()
        if self.args.report and self.session:
            atomic_json(Path(self.args.report),{'session_path':str(self.session.path),'entries':self.entries,
                'metrics':self.session.metrics,'captured_seconds':self.session.available,'processed_seconds':self.session.cursor,
                'failed':self.session.failed,'bilingual':self.settings.bilingual})
        if self.args.screenshot:self.grab().save(self.args.screenshot)

    def show_error(self,message):
        # Provider exceptions never contain request bodies; redact defensively as well.
        if self.key:message=message.replace(self.key,'[密钥已隐藏]')
        self.error_label.setText(message);self.error_label.show()

    def on_entries(self,entries):
        self.entries=entries
        if self.document.textCursor().hasSelection():self.deferred=True
        else:self.render()

    def on_preview(self,entries):
        self.preview_entries=entries
        if not self.preview_document.textCursor().hasSelection():self.render_preview()

    def preview_selection_changed(self):
        if not self.preview_document.textCursor().hasSelection():QTimer.singleShot(0,self.render_preview)

    def render_preview(self):
        # A fixed preview area prevents the saved document from jumping on every token.
        if self.preview_document.textCursor().hasSelection():return
        parts=[];items=[]
        if self.busy and self.entries and (self.entries[-1].get('pending') or self.entries[-1].get('provisional')):
            items=[self.entries[-1]]
        for entry in self.preview_entries:
            # Replace an overlapping draft visually; final merge still waits for full validation.
            if items and entry['source'].casefold().startswith(items[-1]['source'].rstrip('.…').casefold()):items[-1]=entry
            else:items.append(entry)
        for entry in items:
            if self.settings.bilingual:parts.append('<p style="color:#758574;margin:0;">'+html.escape(entry['source'])+'</p>')
            parts.append('<p style="color:#3a5c46;margin:3px 0 8px 0;">'+html.escape(entry['zh'])+'</p>')
        if not parts:parts=['<p style="color:#83947f;">等待下一段讲话… 完整内容会整理到上方文稿。</p>']
        self.preview_document.blockSignals(True)
        self.preview_document.setHtml('<html><body style="font-family:Microsoft YaHei UI;font-size:14px;">'+''.join(parts)+'</body></html>')
        self.preview_document.blockSignals(False)
        bar=self.preview_document.verticalScrollBar();bar.setValue(bar.maximum())

    def selection_changed(self):
        if self.deferred and not self.document.textCursor().hasSelection():
            self.deferred=False;QTimer.singleShot(0,self.render)

    def on_stats(self,stats):
        if stats.get('request_seconds'):self.last_request=stats['request_seconds']
        seconds=int(stats.get('captured',0));queued=int(max(0,stats.get('queued',0)))
        self.stats_label.setText(f'已收听 {seconds//60:02d}:{seconds%60:02d}  ·  待处理 {queued} 秒'+(f'  ·  上次请求 {self.last_request:.1f} 秒' if self.last_request else ''))

    def tick(self):
        if self.busy and self.session:
            self.collect_settings()
            self.session.settings=dataclasses.replace(self.settings)
            self.on_stats({'captured':self.session.available,'queued':self.session.available-self.session.cursor})

    def set_mode(self,bilingual):
        self.settings.bilingual=bilingual;self.chinese.setChecked(not bilingual);self.bilingual.setChecked(bilingual);self.render();self.render_preview()

    def change_font(self,delta):
        self.settings.font_size=max(12,min(26,self.settings.font_size+delta));self.render()

    def follow_changed(self,enabled):
        if enabled:self.document.verticalScrollBar().setValue(self.document.verticalScrollBar().maximum())

    def render(self):
        self.font_label.setText(str(self.settings.font_size))
        self.smaller.setEnabled(self.settings.font_size>12);self.larger.setEnabled(self.settings.font_size<26)
        scrollbar=self.document.verticalScrollBar();position=scrollbar.value();near_bottom=position>=scrollbar.maximum()-45
        display=self.entries
        draft=bool(self.busy and display and (display[-1].get('pending') or display[-1].get('provisional')))
        if draft:display=display[:-1]
        if not display:
            content='''<div style="margin-top:70px;"><p style="font-size:34px;color:#b2c5b4;">“</p><p style="font-size:23px;color:#47644f;">让理解，跟上课堂。</p><p style="color:#81907d;line-height:190%;">播放课程后，原文与译文会逐段出现在这里。<br>前面的内容始终保留，你可以随时回看、选择和复制。</p><p style="color:#94a08c;font-size:12px;">建议先填写主题和术语，让专业表达更贴近这门课。<br>首段需要积累音频语境，再由模型处理。</p></div>'''
        else:
            parts=[]
            for e in display:
                if self.settings.bilingual:parts.append(f'<p style="color:#7c887c;font-size:{max(12,self.settings.font_size-2)}px;margin-top:12px;margin-bottom:3px;">'+html.escape(e['source'])+'</p>')
                flags=(' <span style="font-size:11px;color:#a48351;">待续</span>' if e.get('pending') else '')+(' <span style="font-size:11px;color:#b07a3a;">需核对</span>' if e.get('uncertain') else '')
                if e.get('provisional') and not e.get('pending'):flags+=' <span style="font-size:11px;color:#8b9b89;">末句待确认</span>'
                parts.append(f'<p style="font-size:{self.settings.font_size}px;color:#253e30;line-height:155%;margin-top:3px;margin-bottom:12px;">'+html.escape(e['zh'])+flags+'</p>')
            content=''.join(parts)
        self.document.setHtml('<html><body style="font-family:Microsoft YaHei UI;">'+content+'</body></html>')
        if self.follow.isChecked() and near_bottom:scrollbar.setValue(scrollbar.maximum())
        else:scrollbar.setValue(position)
        self.count.setText(f'{len(display)} 句'+(' · 1 句待定' if draft else ''))
        self.export_button.setEnabled(bool(self.entries))
        self.render_preview()

    def export(self):
        if not self.entries:return
        path,_=QFileDialog.getSaveFileName(self,'导出课堂文稿','课堂文稿-'+time.strftime('%Y%m%d-%H%M')+'.txt','纯文本 (*.txt);;Markdown (*.md);;双语网页文稿 (*.html)')
        if not path:return
        try:
            if Path(path).suffix.lower()=='.html':
                body=''.join(('<p class="en">'+html.escape(e['source'])+'</p>' if self.settings.bilingual else '')+'<p>'+html.escape(e['zh'])+(' 〔需核对〕' if e.get('uncertain') else '')+(' 〔待续〕' if e.get('pending') else ' 〔待校对〕' if e.get('provisional') else '')+'</p>' for e in self.entries)
                data='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>课堂文稿</title><style>body{max-width:850px;margin:60px auto;padding:0 28px;font:18px/1.8 system-ui;background:#fffef9;color:#253e30}.en{color:#7c887c;font-size:15px;margin-bottom:0}p{margin-top:5px}</style><h1>课堂文稿</h1><p>'+html.escape(self.topic.toPlainText())+'</p>'+body+'</html>'
            else:data=transcript_text(self.entries,self.settings.bilingual,self.topic.toPlainText())
            Path(path).write_text(data,encoding='utf-8-sig');self.status_label.setText('已导出：'+Path(path).name)
        except OSError as ex:self.show_error('无法保存文稿：'+str(ex))

    def open_session(self,path=None):
        if self.busy:return
        if not path:
            path,_=QFileDialog.getOpenFileName(self,'打开自动保存的文稿',str(app_data()/'sessions'),'课堂会话 (session.json)')
        if not path:return
        try:
            info=json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(info.get('entries'),list):raise ValueError('不是有效的课堂文稿')
            self.entries=info['entries'];self.topic.setPlainText(info.get('topic',''));self.glossary.setPlainText(info.get('glossary',''))
            self.collect_settings();self.render();self.session=None;self.retry_button.hide()
            if (Path(path).parent/'audio.pcm').exists():
                self.session=TranslationSession.recover(Path(path).parent,self.key);self.connect_session()
                if self.session.available-self.session.cursor>.2:self.retry_button.show()
            self.status_label.setText('已打开自动保存的课堂文稿')
        except Exception as ex:self.show_error('无法打开：'+str(ex))

    def closeEvent(self,event):
        if self.busy and self.session:
            # Closing always preserves the manifest and raw captured audio for reopening/retry.
            self.session.stop_capture.set();self.session.cancel.set()
            if self.session.capture_thread:self.session.capture_thread.join(timeout=2)
            self.session._persist()
        try:save_settings(self.collect_settings(),self.key)
        except Exception:pass
        event.accept()

def main():
    parser=argparse.ArgumentParser(description='听课稿：原生 Windows 音频直译应用')
    parser.add_argument('--key-file');parser.add_argument('--topic');parser.add_argument('--auto-start',action='store_true')
    parser.add_argument('--stop-after',type=float);parser.add_argument('--quit-after',type=float);parser.add_argument('--session-dir')
    parser.add_argument('--report');parser.add_argument('--screenshot');parser.add_argument('--open-session')
    parser.add_argument('--source-kind',choices=['system','microphone'])
    parser.add_argument('--segment-seconds',type=int,choices=[8,12,18,26])
    args=parser.parse_args()
    app=QApplication(sys.argv[:1]);app.setApplicationName('LectureInk');app.setOrganizationName('LectureInk')
    app.setFont(QFont('Microsoft YaHei UI',10));app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=MainWindow(args);window.show();sys.exit(app.exec())

if __name__=='__main__':main()
