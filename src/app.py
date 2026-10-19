"""听课稿 · LectureInk — live lecture transcription and translation for Windows."""
from __future__ import annotations
import argparse
import dataclasses
import os
import queue
import sys
import math
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QProgressBar, QPushButton, QSizePolicy, QSplitter, QTextEdit,
                               QVBoxLayout, QWidget)

import audio
from engine_local import MODEL_NOTE, LocalEngine
from engine_soniox import SonioxEngine
from overlay import CaptionOverlay
from settings import (APP_NAME, SOURCE_LANGUAGES, VERSION, app_data, load_settings, load_soniox_key, looks_like_api_key,
                      save_settings, store_soniox_key)
from transcript import Transcript
from views import TranscriptPane

STYLE = '''
QWidget {font-family:"Microsoft YaHei UI","Segoe UI";font-size:13px;color:#2a3d33;}
QMainWindow, QDialog {background:#f1f3ee;}
QLabel#brand {font-size:20px;font-weight:700;color:#14402f;}
QLabel#brandSub {font-size:11px;color:#6d8176;letter-spacing:1px;}
QLabel#muted {color:#728077;font-size:12px;}
QLabel#status {color:#3c5a4b;}
QLabel#paneTitle {font-size:16px;font-weight:700;color:#1d3b2e;}
QLabel#paneTag {font-size:11px;color:#7a8a80;background:#eef2ec;border-radius:9px;padding:2px 8px;}
QLabel#error {background:#fff2df;border:1px solid #ebcd9c;border-radius:8px;padding:10px 12px;color:#7a531b;}
QLabel#fieldLabel {font-weight:600;color:#3c5a4b;}
QFrame#pane {background:#fffffb;border:1px solid #e0e5dc;border-radius:12px;}
QFrame#controls {background:#e7ede5;border:1px solid #dbe3d9;border-radius:12px;}
QTextEdit {background:transparent;border:0;selection-background-color:#cfe6d6;selection-color:#14321f;}
QDialog QTextEdit, QLineEdit {background:#fbfcf9;border:1px solid #cfd9cf;border-radius:7px;padding:7px;}
QComboBox {background:#fbfcf9;border:1px solid #cdd8cd;border-radius:7px;padding:6px 26px 6px 10px;min-height:20px;}
QComboBox:disabled {color:#9aa79e;background:#eef1ec;}
QComboBox QAbstractItemView {background:#fffffb;selection-background-color:#d8e9de;color:#203e33;}
QPushButton {background:#fbfcf9;border:1px solid #cdd8cd;border-radius:7px;padding:6px 12px;color:#2b5144;}
QPushButton:hover {background:#e3ece4;border-color:#9dbba8;}
QPushButton:disabled {color:#9eaba2;border-color:#d8e0d7;background:#edf1eb;}
QFrame#segment {background:#e2e9e0;border:1px solid #d3ddd1;border-radius:9px;}
QFrame#segment QPushButton {background:transparent;border:1px solid transparent;border-radius:6px;padding:3px 14px;color:#4e6659;}
QFrame#segment QPushButton:hover {background:#ecf1ea;}
QFrame#segment QPushButton:checked {background:#fffffb;border-color:#cbd9ce;color:#173f2f;font-weight:600;}
QFrame#segment QPushButton:disabled {color:#a5b2a9;}
QFrame#segment QPushButton:checked:disabled {color:#7d9285;}
QFrame#segment QPushButton#toggle:checked {background:#1d6a50;border-color:#1d6a50;color:white;}
QFrame#segment QPushButton#arrow {padding:1px 9px 3px 9px;font-size:15px;}
QFrame#segment QLabel {color:#4e6659;padding:0 4px;}
QMenu {background:#fffffb;border:1px solid #d3ddd1;border-radius:8px;padding:5px;}
QMenu::item {padding:7px 22px 7px 30px;border-radius:5px;color:#2a3d33;background:transparent;}
QMenu::item:selected {background:#e3ede5;color:#163a2a;}
QMenu::item:disabled {color:#a5b2a9;}
QMenu::separator {height:1px;background:#e3e8e0;margin:5px 8px;}
QMenu::indicator {width:13px;height:13px;left:9px;border:1px solid #98b3a4;border-radius:3px;background:#fbfcf9;}
QMenu::indicator:checked {background:#1d6a50;border-color:#1d6a50;}
QMenu::right-arrow {width:8px;height:8px;}
QToolTip {background:#fffffb;color:#2a3d33;border:1px solid #d3ddd1;padding:5px 8px;}
QPushButton#primary {background:#1d6a50;border:0;color:white;font-size:14px;font-weight:700;padding:8px 22px;}
QPushButton#primary:hover {background:#175641;}
QPushButton#primary[running="true"] {background:#b4573a;}
QPushButton#primary[running="true"]:hover {background:#97462d;}
QPushButton#primary:disabled {background:#b9c9bd;color:#f1f5f0;}
QPushButton#flat {border:0;background:transparent;color:#6c7f74;padding:4px 8px;}
QPushButton#flat:hover {color:#1f4c39;}
QProgressBar {border:0;background:#cfdbcf;border-radius:2px;max-height:4px;}
QProgressBar::chunk {background:#3f8f6c;border-radius:2px;}
QCheckBox {color:#4f675a;spacing:6px;}
QCheckBox::indicator {width:14px;height:14px;border:1px solid #98b3a4;border-radius:4px;background:#fbfcf9;}
QCheckBox::indicator:checked {background:#1d6a50;border-color:#1d6a50;}
QComboBox::drop-down {border:0;width:24px;background:transparent;}
QComboBox::down-arrow {image:none;width:0;height:0;}
QSplitter::handle {background:transparent;width:12px;}
QScrollBar:vertical {background:transparent;width:9px;margin:2px;}
QScrollBar::handle:vertical {background:#cbd7ca;border-radius:4px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
'''


def light_palette() -> QPalette:
    """Fixed light palette: with Windows dark mode, Fusion would otherwise draw unstyled popups dark."""
    palette = QPalette()
    roles = {QPalette.ColorRole.Window: '#f1f3ee', QPalette.ColorRole.WindowText: '#2a3d33',
             QPalette.ColorRole.Base: '#fffffb', QPalette.ColorRole.AlternateBase: '#f3f6f1',
             QPalette.ColorRole.Text: '#2a3d33', QPalette.ColorRole.Button: '#fbfcf9',
             QPalette.ColorRole.ButtonText: '#2b5144', QPalette.ColorRole.Highlight: '#cfe6d6',
             QPalette.ColorRole.HighlightedText: '#14321f', QPalette.ColorRole.ToolTipBase: '#fffffb',
             QPalette.ColorRole.ToolTipText: '#2a3d33', QPalette.ColorRole.PlaceholderText: '#9aa79e',
             QPalette.ColorRole.Link: '#1d6a50'}
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor('#9eaba2'))
    return palette


def make_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor('#1d6a50'))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(1, 1, 62, 62, 15, 15)
    p.setBrush(QColor('#f1f2d8'))
    for i, h in enumerate([12, 23, 35, 24, 15]):
        p.drawRoundedRect(16 + i * 7, 32 - h // 2, 3, h, 1, 1)
    p.end()
    return QIcon(pix)


def segmented(*widgets) -> QFrame:
    """A rounded track holding buttons side by side; the checked one is raised."""
    frame = QFrame()
    frame.setObjectName('segment')
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(2, 2, 2, 2)
    layout.setSpacing(2)
    for w in widgets:
        layout.addWidget(w)
    return frame


def label(text: str, name: str | None = None) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w


class ChoiceBox(QComboBox):
    """Combo box with a drawn chevron, so it scales with the display and matches the theme."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#527365' if self.isEnabled() else '#a9b7ad'), 1.6))
        x, y = self.width() - 14, self.height() / 2
        p.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        p.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))
        p.end()

    def showPopup(self) -> None:
        widest = max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        self.view().setMinimumWidth(max(self.width(), min(620, widest + 48)))
        super().showPopup()


class Bridge(QObject):
    """Thread-safe hop from audio callbacks to the GUI thread."""
    level = Signal(float)
    error = Signal(str)


class CourseDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('课程与术语')
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(8)
        layout.addWidget(label('本节课在讲什么？', 'fieldLabel'))
        self.topic = QTextEdit(settings.topic)
        self.topic.setPlaceholderText('例如：机器学习导论 · 线性回归、正则化与泛化')
        self.topic.setFixedHeight(70)
        layout.addWidget(self.topic)
        layout.addWidget(label('术语表（每行一个，可写译法）', 'fieldLabel'))
        self.glossary = QTextEdit(settings.glossary)
        self.glossary.setPlaceholderText('overfitting = 过拟合\nridge regression = 岭回归\nKullback–Leibler')
        self.glossary.setFixedHeight(150)
        layout.addWidget(self.glossary)
        note = label('术语用于提高识别准确度；写了译法的术语会按指定译法翻译。\n'
                     '基础模式填写了术语时只用术语偏置识别，没填术语才参考课程主题；API 模式会把主题和术语都提供给 Soniox。', 'muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SettingsDialog(QDialog):
    def __init__(self, settings, key: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('设置')
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(8)
        layout.addWidget(label('API 模式 · Soniox', 'paneTitle'))
        layout.addWidget(label('API Key', 'fieldLabel'))
        self.key = QLineEdit(key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('在 soniox.com 控制台创建')
        layout.addWidget(self.key)
        self.remember = QCheckBox('在本机加密记住密钥（Windows DPAPI）')
        self.remember.setChecked(settings.remember_key)
        layout.addWidget(self.remember)
        row = QHBoxLayout()
        row.addWidget(label('讲课语言', 'fieldLabel'))
        row.addStretch()
        self.language = ChoiceBox()
        for code, name in SOURCE_LANGUAGES:
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.source_language)))
        row.addWidget(self.language)
        layout.addLayout(row)
        note = label('音频实时上传至 Soniox，转写与中文翻译在同一连接中逐词返回。按用量计费。', 'muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(10)
        layout.addWidget(label('基础模式 · 本地识别', 'paneTitle'))
        local = label(MODEL_NOTE + '。识别在本机完成；识别出的英文句子会发送到谷歌翻译的免费网页接口，'
                      '该接口无需密钥，但可能限流，中国大陆网络通常无法直接访问。', 'muted')
        local.setWordWrap(True)
        layout.addWidget(local)
        layout.addSpacing(10)
        layout.addWidget(label('录音', 'paneTitle'))
        self.save_audio = QCheckBox('保存每次听课的录音（16 kHz WAV，约 115 MB/小时）')
        self.save_audio.setChecked(settings.save_audio)
        layout.addWidget(self.save_audio)
        audio_note = label('录音与文稿存在同一个文件夹，只保存在本机。识别有问题时可以用它重放复查。', 'muted')
        audio_note.setWordWrap(True)
        layout.addWidget(audio_note)
        folder = QPushButton('打开数据文件夹')
        folder.clicked.connect(lambda: os.startfile(app_data()))
        layout.addWidget(folder, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.settings_path = Path(args.settings_file) if args.settings_file else None
        self.settings = load_settings(self.settings_path)
        if args.mode:
            self.settings.mode = args.mode
        self.soniox_key = load_soniox_key(self.settings)
        self.transcript = Transcript()
        self.engine = None
        self.source = None
        self.running = False
        self.started_at = 0.0
        self.session_dir: Path | None = None
        self.saved_revision = -1
        self.latency = None
        self.source_kind_running = ''
        self.last_loud = 0.0
        self.quiet_warned = False
        self.bridge = Bridge()
        self.bridge.level.connect(self.on_level)
        self.bridge.error.connect(self.on_capture_error)
        self.overlay = CaptionOverlay(self.settings)
        self.overlay.closed.connect(self.on_overlay_closed)
        self.overlay.changed.connect(self.persist)
        self.setWindowTitle(f'{APP_NAME} · LectureInk')
        self.setWindowIcon(make_icon())
        self.resize(1260, 800)
        self.setMinimumSize(900, 560)
        self.build_ui()
        self.refresh_devices()
        self.apply_view()
        self.update_mode_ui()
        self.render_timer = QTimer(self, interval=50, timeout=self.render)
        self.render_timer.start()
        self.clock = QTimer(self, interval=1000, timeout=self.tick)
        self.clock.start()
        if self.settings.overlay_enabled or args.overlay:
            self.set_overlay(True)
        if args.open:
            self.open_transcript(args.open)
        if args.auto_start:
            QTimer.singleShot(400, self.start)
        if args.stop_after:
            QTimer.singleShot(int(args.stop_after * 1000), self.stop)
        if args.shot_at:
            QTimer.singleShot(int(args.shot_at * 1000), self.take_screenshot)
        if args.quit_after:
            QTimer.singleShot(int(args.quit_after * 1000), self.close)

    # ---- layout --------------------------------------------------------------------------------
    def build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(12)

        head = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label(APP_NAME, 'brand'))
        brand.addWidget(label('LECTUREINK · 实时听课翻译', 'brandSub'))
        head.addLayout(brand)
        head.addSpacing(22)
        self.mode_group = QButtonGroup(self)
        mode_buttons = []
        for mode, text, tip in (('local', '基础模式', '本地 Moonshine 识别 + 谷歌免费翻译'),
                                ('soniox', 'API 模式', 'Soniox 实时转写与翻译')):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setProperty('mode', mode)
            self.mode_group.addButton(button)
            mode_buttons.append(button)
            button.setChecked(self.settings.mode == mode)
        head.addWidget(segmented(*mode_buttons))
        self.mode_group.buttonClicked.connect(self.on_mode)
        head.addSpacing(10)
        self.mode_note = label('', 'muted')
        head.addWidget(self.mode_note)
        head.addStretch()
        self.overlay_button = QPushButton('悬浮字幕')
        self.overlay_button.setObjectName('toggle')
        self.overlay_button.setCheckable(True)
        self.overlay_button.setToolTip('在桌面显示置顶字幕条')
        self.overlay_button.clicked.connect(self.set_overlay)
        self.overlay_menu = QMenu(self)
        self.overlay_menu.aboutToShow.connect(self.fill_overlay_menu)
        overlay_more = QPushButton('▾')
        overlay_more.setObjectName('arrow')
        overlay_more.setToolTip('悬浮字幕选项')
        overlay_more.clicked.connect(lambda: self.overlay_menu.exec(
            overlay_more.mapToGlobal(overlay_more.rect().bottomLeft()) + QPoint(-4, 6)))
        head.addWidget(segmented(self.overlay_button, overlay_more))
        head.addSpacing(6)
        for text, slot in (('课程与术语', self.course_dialog), ('设置', self.settings_dialog),
                           ('打开', lambda: self.open_transcript()), ('导出', self.export)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            head.addWidget(button)
            setattr(self, {'课程与术语': 'course_button', '设置': 'settings_button', '打开': 'open_button',
                           '导出': 'export_button'}[text], button)
        outer.addLayout(head)

        controls = QFrame()
        controls.setObjectName('controls')
        bar = QHBoxLayout(controls)
        bar.setContentsMargins(14, 10, 14, 10)
        bar.setSpacing(10)
        self.source_kind = ChoiceBox()
        self.source_kind.addItem('系统声音 · 网课', 'system')
        self.source_kind.addItem('麦克风 · 现场', 'microphone')
        self.source_kind.setCurrentIndex(max(0, self.source_kind.findData(self.settings.source_kind)))
        self.source_kind.currentIndexChanged.connect(self.refresh_devices)
        bar.addWidget(self.source_kind)
        self.devices = ChoiceBox()
        self.devices.setMinimumContentsLength(20)
        self.devices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.devices.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bar.addWidget(self.devices)
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.setObjectName('flat')
        self.refresh_button.setToolTip('重新查找耳机、扬声器和麦克风')
        self.refresh_button.clicked.connect(self.refresh_devices)
        bar.addWidget(self.refresh_button)
        meter_box = QVBoxLayout()
        meter_box.setSpacing(3)
        self.status_label = label('准备就绪', 'status')
        meter_box.addWidget(self.status_label)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedWidth(220)
        meter_box.addWidget(self.meter)
        bar.addSpacing(8)
        bar.addLayout(meter_box)
        bar.addStretch()
        self.stats_label = label('', 'muted')
        bar.addWidget(self.stats_label)
        self.start_button = QPushButton('开始听课')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.toggle)
        bar.addWidget(self.start_button)
        outer.addWidget(controls)

        self.error_label = label('', 'error')
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.error_label.mousePressEvent = lambda e: self.error_label.hide()
        self.error_label.setToolTip('点击关闭')
        outer.addWidget(self.error_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.src_pane = TranscriptPane('原稿', 'English', 'src', self.transcript,
                                       '开始听课后，识别出的原文会在这里逐词出现，并按停顿自动分段。')
        self.tgt_pane = TranscriptPane('译稿', '简体中文', 'tgt', self.transcript,
                                       '译文会跟随原文实时出现。浅色文字是还在变化的草稿，定稿后变为深色。')
        self.splitter.addWidget(self.src_pane)
        self.splitter.addWidget(self.tgt_pane)
        self.splitter.setChildrenCollapsible(False)
        outer.addWidget(self.splitter, 1)

        foot = QHBoxLayout()
        self.view_group = QButtonGroup(self)
        view_buttons = []
        for view, text in (('both', '原稿 + 译稿'), ('target', '仅译稿'), ('source', '仅原稿')):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty('view', view)
            button.setChecked(self.settings.view == view)
            self.view_group.addButton(button)
            view_buttons.append(button)
        foot.addWidget(segmented(*view_buttons))
        self.view_group.buttonClicked.connect(lambda b: self.set_view(b.property('view')))
        foot.addSpacing(16)
        smaller = QPushButton('A−')
        smaller.setToolTip('缩小字号')
        smaller.clicked.connect(lambda: self.change_font(-1))
        larger = QPushButton('A+')
        larger.setToolTip('放大字号')
        larger.clicked.connect(lambda: self.change_font(1))
        self.font_label = label('')
        self.font_label.setToolTip('正文字号')
        foot.addWidget(segmented(smaller, self.font_label, larger))
        foot.addSpacing(12)
        self.follow = QCheckBox('跟随最新内容')
        self.follow.setChecked(self.settings.follow_latest)
        self.follow.toggled.connect(self.set_follow)
        foot.addWidget(self.follow)
        foot.addStretch()
        self.count_label = label('', 'muted')
        foot.addWidget(self.count_label)
        outer.addLayout(foot)

        for text, keys, slot in (('导出', QKeySequence.StandardKey.Save, self.export),
                                 ('打开', QKeySequence.StandardKey.Open, lambda: self.open_transcript())):
            action = QAction(text, self)
            action.setShortcut(keys)
            action.triggered.connect(slot)
            self.addAction(action)
        self.src_pane.set_font_size(self.settings.font_size)
        self.tgt_pane.set_font_size(self.settings.font_size + 1)
        self.set_follow(self.settings.follow_latest)

    # ---- settings helpers ----------------------------------------------------------------------
    def persist(self) -> None:
        try:
            save_settings(self.settings, self.settings_path)
        except OSError as ex:
            self.show_error('无法保存设置：' + str(ex))

    def on_mode(self, button) -> None:
        self.settings.mode = button.property('mode')
        self.update_mode_ui()
        self.persist()

    def update_mode_ui(self) -> None:
        if self.settings.mode == 'soniox':
            lang = dict(SOURCE_LANGUAGES).get(self.settings.source_language, '自动识别')
            self.mode_note.setText('Soniox 云端 · ' + ('已填写密钥' if self.soniox_key else '未填写密钥'))
            self.src_pane.findChild(QLabel, 'paneTag').setText(lang)
        else:
            self.mode_note.setText('本机识别（英语）· 谷歌翻译')
            self.src_pane.findChild(QLabel, 'paneTag').setText('English')

    def course_dialog(self) -> None:
        dialog = CourseDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings.topic = dialog.topic.toPlainText().strip()[:4000]
            self.settings.glossary = dialog.glossary.toPlainText().strip()[:12000]
            self.persist()
            if self.running:
                self.show_notice('课程与术语已保存，下次开始听课时生效。')

    def settings_dialog(self) -> None:
        dialog = SettingsDialog(self.settings, self.soniox_key, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            key = dialog.key.text().strip()
            if key and not looks_like_api_key(key):
                self.show_error('填写的内容不像 API Key（含空格、换行或中文），没有保存。请在 Soniox 控制台复制密钥后重新填写。')
                key = self.soniox_key
            self.soniox_key = key
            self.settings.remember_key = dialog.remember.isChecked()
            self.settings.source_language = dialog.language.currentData()
            self.settings.save_audio = dialog.save_audio.isChecked()
            try:
                store_soniox_key(self.settings, self.soniox_key)
            except OSError as ex:
                self.show_error(str(ex))
            self.persist()
            self.update_mode_ui()

    def remember_device(self) -> None:
        device = self.devices.currentData()
        if device:
            field = 'microphone_name' if device['kind'] == 'microphone' else 'device_name'
            setattr(self.settings, field, device['name'])

    def refresh_devices(self) -> None:
        self.remember_device()
        kind = self.source_kind.currentData()
        self.settings.source_kind = kind
        selected = self.settings.microphone_name if kind == 'microphone' else self.settings.device_name
        self.devices.clear()
        try:
            for d in audio.list_devices(kind):
                self.devices.addItem(d['name'].removesuffix(' [Loopback]'), d)
                self.devices.setItemData(self.devices.count() - 1, d['name'], Qt.ItemDataRole.ToolTipRole)
                if d['name'] == selected:
                    self.devices.setCurrentIndex(self.devices.count() - 1)
        except Exception as ex:
            self.show_error('无法列出音频设备：' + str(ex))
            return
        if not self.devices.count() and not self.args.audio_file:
            self.show_error('未找到麦克风，请连接后点“刷新”。' if kind == 'microphone'
                            else '未找到可采集的输出设备，请连接扬声器或耳机后点“刷新”。')

    # ---- view ----------------------------------------------------------------------------------
    def set_view(self, view: str) -> None:
        self.settings.view = view
        self.apply_view()
        self.persist()

    def apply_view(self) -> None:
        view = self.settings.view
        self.src_pane.setVisible(view in ('both', 'source'))
        self.tgt_pane.setVisible(view in ('both', 'target'))
        self.font_label.setText(str(self.settings.font_size))

    def change_font(self, delta: int) -> None:
        self.settings.font_size = max(12, min(30, self.settings.font_size + delta))
        self.src_pane.set_font_size(self.settings.font_size)
        self.tgt_pane.set_font_size(self.settings.font_size + 1)
        self.font_label.setText(str(self.settings.font_size))
        self.persist()

    def set_follow(self, enabled: bool) -> None:
        self.settings.follow_latest = enabled
        for pane in (self.src_pane, self.tgt_pane):
            pane.follow = enabled
            if enabled:
                bar = pane.view.verticalScrollBar()
                bar.setValue(bar.maximum())

    # ---- overlay -------------------------------------------------------------------------------
    def set_overlay(self, enabled: bool) -> None:
        self.settings.overlay_enabled = bool(enabled)
        self.overlay_button.setChecked(bool(enabled))
        if enabled:
            self.overlay.apply_settings()
            self.overlay.show()
            self.push_overlay()
        else:
            self.overlay.hide()
        self.persist()

    def on_overlay_closed(self) -> None:
        self.overlay_button.setChecked(False)
        self.settings.overlay_enabled = False
        self.persist()

    def fill_overlay_menu(self) -> None:
        menu, s = self.overlay_menu, self.settings
        menu.clear()
        act = menu.addAction('显示悬浮字幕')
        act.setCheckable(True)
        act.setChecked(self.overlay.isVisible())
        act.toggled.connect(self.set_overlay)
        act = menu.addAction('锁定位置（鼠标穿透）')
        act.setCheckable(True)
        act.setChecked(s.overlay_locked)
        act.toggled.connect(self.overlay.set_locked)
        act = menu.addAction('显示原文')
        act.setCheckable(True)
        act.setChecked(s.overlay_show_source)
        act.toggled.connect(lambda v: (setattr(s, 'overlay_show_source', v), self.overlay.apply_settings(), self.persist()))
        menu.addAction('放大字幕', lambda: self.overlay.change_font(2))
        menu.addAction('缩小字幕', lambda: self.overlay.change_font(-2))
        menu.addAction('移回屏幕下方', self.reset_overlay)

    def reset_overlay(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(1100, int(screen.width() * 0.62))
        self.overlay.resize(width, self.overlay.height())
        self.overlay.move(screen.center().x() - width // 2, screen.bottom() - self.overlay.height() - 70)
        self.overlay.remember_geometry()

    def push_overlay(self) -> None:
        if not self.overlay.isVisible():
            return
        hint = '等待讲话…' if self.running else '点“开始听课”后，字幕显示在这里'
        self.overlay.set_content(self.transcript.recent_runs('src'), self.transcript.recent_runs('tgt'), hint)

    # ---- session -------------------------------------------------------------------------------
    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def start(self) -> None:
        if self.running:
            return
        mode = self.settings.mode
        if mode == 'soniox' and not self.soniox_key:
            self.settings_dialog()
            if not self.soniox_key:
                return
        device = self.devices.currentData()
        if not self.args.audio_file and not device:
            self.show_error('请先选择可用的音频设备。')
            return
        self.error_label.hide()
        self.remember_device()
        self.persist()
        settings = dataclasses.replace(self.settings)
        source_language = 'en' if mode == 'local' else (settings.source_language if settings.source_language != 'auto' else 'en')
        self.transcript = Transcript(source_language, 'zh')
        self.src_pane.transcript = self.tgt_pane.transcript = self.transcript
        self.src_pane.clear()
        self.tgt_pane.clear()
        self.latency = None
        self.engine = LocalEngine(settings) if mode == 'local' else SonioxEngine(settings, self.soniox_key)
        self.engine.update.connect(self.on_update)
        self.engine.status.connect(self.status_label.setText)
        self.engine.error.connect(self.on_engine_error)
        self.engine.notice.connect(self.show_notice)
        self.engine.latency.connect(self.on_latency)
        self.engine.finished.connect(self.on_finished)
        root = Path(self.args.session_dir) if self.args.session_dir else app_data() / 'sessions'
        self.session_dir = root / time.strftime('%Y%m%d-%H%M%S')
        self.saved_revision = -1
        chunks = audio.RecordingQueue(self.session_dir / 'audio.wav') if settings.save_audio else queue.Queue()
        if self.args.audio_file:
            self.source = audio.FileSource(self.args.audio_file, chunks, self.bridge.level.emit)
        else:
            self.source = audio.DeviceCapture(device, chunks, self.bridge.level.emit, self.bridge.error.emit)
        self.source_kind_running = 'file' if self.args.audio_file else device['kind']
        self.engine.start(chunks)
        self.source.start()
        self.started_at = self.last_loud = time.monotonic()
        self.quiet_warned = False
        self.set_running(True)
        self.push_overlay()

    def stop(self) -> None:
        if self.running and self.source:
            self.source.stop()
            self.start_button.setEnabled(False)
            self.start_button.setText('正在收尾…')

    def set_running(self, running: bool) -> None:
        self.running = running
        for w in (self.source_kind, self.devices, self.refresh_button, self.open_button, self.settings_button):
            w.setEnabled(not running)
        for b in self.mode_group.buttons():
            b.setEnabled(not running)
        self.start_button.setEnabled(True)
        self.start_button.setText('结束听课' if running else '开始听课')
        self.start_button.setProperty('running', running)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)
        if not running:
            self.meter.setValue(0)

    def on_finished(self) -> None:
        if self.source:
            self.source.stop()
        self.render()
        self.autosave(force=True)
        self.set_running(False)
        if not self.error_label.isVisible() or self.error_label.property('notice'):
            self.status_label.setText('本次听课已结束 · 文稿已自动保存' if not self.transcript.is_empty() else '已停止')
        self.push_overlay()
        if self.args.report:
            from settings import atomic_json
            atomic_json(Path(self.args.report), {'mode': self.settings.mode, 'pairs': self.transcript.pairs(),
                                                 'segments': len(self.transcript.segments),
                                                 'paragraphs': len(self.transcript.paragraphs),
                                                 'error': self.error_label.text() if self.error_label.isVisible() else '',
                                                 'session_dir': str(self.session_dir)})
        if self.args.screenshot and not self.args.shot_at:
            QTimer.singleShot(300, self.take_screenshot)

    def take_screenshot(self) -> None:
        self.grab().save(self.args.screenshot)
        if self.overlay.isVisible():
            self.overlay.grab().save(str(Path(self.args.screenshot).with_name(Path(self.args.screenshot).stem + '-overlay.png')))

    def on_engine_error(self, message: str) -> None:
        self.show_error(message)
        self.status_label.setText('已停止')
        if self.source:
            self.source.stop()

    def on_capture_error(self, message: str) -> None:
        self.show_error(message)

    def on_update(self, update: dict) -> None:
        if self.sender() is self.engine:
            self.transcript.apply(update)

    QUIET_DB = -50.0     # below this the recogniser mostly hears noise
    QUIET_SECONDS = 10

    def on_level(self, value: float) -> None:
        if not self.running:
            self.meter.setValue(0)
            return
        db = 20 * math.log10(max(value, 1e-6))
        self.meter.setValue(max(0, min(100, int((db + 60) * 2))))      # -60 dB empty, -10 dB full
        now = time.monotonic()
        if db > self.QUIET_DB:
            self.last_loud = now
            self.quiet_warned = False
        elif now - self.last_loud > self.QUIET_SECONDS and not self.quiet_warned:
            self.quiet_warned = True
            if self.source_kind_running == 'system':
                self.show_notice('10 秒内没有检测到系统声音：请确认课程正在播放，且选择的是正在出声的扬声器或耳机。')
            elif self.source_kind_running == 'microphone':
                self.show_notice(f'麦克风输入很弱（约 {db:.0f} dB），识别结果可能不可靠。网课或回放请改用“系统声音”；'
                                 '现场请靠近讲者，或在 Windows 声音设置里调高麦克风音量。')

    def on_latency(self, seconds: float) -> None:
        self.latency = seconds if self.latency is None else self.latency * 0.7 + seconds * 0.3

    def show_error(self, message: str) -> None:
        if self.soniox_key:
            message = message.replace(self.soniox_key, '[密钥已隐藏]')
        self.error_label.setProperty('notice', False)
        self.error_label.setText(message)
        self.error_label.show()

    def show_notice(self, message: str) -> None:
        self.error_label.setProperty('notice', True)
        self.error_label.setText(message)
        self.error_label.show()
        QTimer.singleShot(8000, lambda: self.error_label.text() == message and self.error_label.hide())

    # ---- refresh -------------------------------------------------------------------------------
    def render(self) -> None:
        dirty = self.transcript.take_dirty()
        if dirty is None:
            return
        self.src_pane.refresh(dirty)
        self.tgt_pane.refresh(dirty)
        self.push_overlay()
        words = sum(len(self.transcript.text(p, 'src', False).split()) for p in range(len(self.transcript.paragraphs)))
        self.count_label.setText(f'{len(self.transcript.paragraphs)} 段 · {words} 词')

    def tick(self) -> None:
        if not self.running:
            return
        elapsed = int(time.monotonic() - self.started_at)
        text = f'{elapsed // 3600:d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}'
        if self.latency is not None:
            text += f'  ·  {"识别延迟" if self.settings.mode == "local" else "处理滞后"} {self.latency:.1f} 秒'
        self.stats_label.setText(text)
        self.autosave()

    def autosave(self, force: bool = False) -> None:
        if not self.session_dir or self.transcript.is_empty():
            return
        if not force and (self.transcript.revision == self.saved_revision or int(time.monotonic()) % 10):
            return
        try:
            self.transcript.save(self.session_dir / 'transcript.json')
            self.saved_revision = self.transcript.revision
        except OSError as ex:
            self.show_error('自动保存失败：' + str(ex))

    # ---- files ---------------------------------------------------------------------------------
    def export(self) -> None:
        if self.transcript.is_empty():
            self.show_notice('还没有可导出的内容。')
            return
        name = '课堂文稿-' + time.strftime('%Y%m%d-%H%M')
        path, chosen = QFileDialog.getSaveFileName(self, '导出文稿', name + '.html',
                                                   '双语对照网页 (*.html);;Markdown (*.md);;纯文本 (*.txt)')
        if not path:
            return
        suffix = Path(path).suffix.lower()
        fmt = {'.html': 'html', '.md': 'md'}.get(suffix, 'txt')
        try:
            data = self.transcript.export(fmt, '课堂文稿', self.settings.topic, self.settings.view)
            Path(path).write_text(data, encoding='utf-8-sig' if fmt == 'txt' else 'utf-8')
            self.status_label.setText('已导出：' + Path(path).name)
        except OSError as ex:
            self.show_error('无法保存：' + str(ex))

    def open_transcript(self, path: str | None = None) -> None:
        if self.running:
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, '打开自动保存的文稿', str(app_data() / 'sessions'),
                                                  '课堂文稿 (transcript.json)')
        if not path:
            return
        try:
            self.transcript = Transcript.load(Path(path))
        except Exception as ex:
            self.show_error('无法打开：' + str(ex))
            return
        self.src_pane.transcript = self.tgt_pane.transcript = self.transcript
        self.src_pane.clear()
        self.tgt_pane.clear()
        self.session_dir = None
        self.render()
        self.status_label.setText('已打开：' + Path(path).parent.name)

    def closeEvent(self, event) -> None:
        if self.running:
            if self.engine:
                self.engine.abort()
            if self.source:
                self.source.stop()
            self.autosave(force=True)
        self.persist()
        self.overlay.close()
        event.accept()


def main() -> None:
    parser = argparse.ArgumentParser(description='听课稿：实时听课转写与翻译')
    parser.add_argument('--mode', choices=['local', 'soniox'])
    parser.add_argument('--audio-file', help='用 WAV 文件代替声音设备（测试与演示）')
    parser.add_argument('--auto-start', action='store_true')
    parser.add_argument('--stop-after', type=float)
    parser.add_argument('--quit-after', type=float)
    parser.add_argument('--overlay', action='store_true')
    parser.add_argument('--open')
    parser.add_argument('--report')
    parser.add_argument('--screenshot')
    parser.add_argument('--shot-at', type=float, help='在指定秒数截图（默认在结束时）')
    parser.add_argument('--session-dir')
    parser.add_argument('--settings-file')
    args = parser.parse_args()
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LectureInk.' + VERSION)
    app = QApplication(sys.argv[:1])
    app.setApplicationName('LectureInk')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyle('Fusion')
    app.setPalette(light_palette())
    app.setStyleSheet(STYLE)
    window = MainWindow(args)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
