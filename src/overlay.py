"""Desktop caption overlay: always on top, a fixed number of lines, newest text at the bottom."""
from __future__ import annotations
from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
                           QTextCharFormat, QTextLayout, QTextOption)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

PAD_X, PAD_Y, GAP, EDGE = 22, 14, 6, 8


def layout_lines(text: str, live_from: list[tuple[int, int]], font: QFont, width: float, live_color: QColor,
                 spacing: float) -> tuple[QTextLayout, list[float]]:
    """Lay out `text` at `width`; returns the layout and each line's top position."""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    ranges = []
    for start, length in live_from:
        r = QTextLayout.FormatRange()
        r.start, r.length = start, length
        fmt = QTextCharFormat()
        fmt.setForeground(live_color)
        r.format = fmt
        ranges.append(r)
    layout.setFormats(ranges)
    tops, y = [], 0.0
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(10.0, width))
        line.setPosition(QPointF(0, y))
        tops.append(y)
        y += spacing
    layout.endLayout()
    return layout, tops


def flatten(runs: list[tuple[str, bool]]) -> tuple[str, list[tuple[int, int]]]:
    text, live, pos = '', [], 0
    for chunk, is_live in runs:
        if is_live:
            live.append((pos, len(chunk)))
        text += chunk
        pos += len(chunk)
    return text, live


class CaptionOverlay(QWidget):
    closed = Signal()
    changed = Signal()          # appearance or geometry changed; persist settings

    def __init__(self, settings):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.settings = settings
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('听课稿 · 悬浮字幕')
        self.setMouseTracking(True)
        self.setMinimumWidth(360)
        self.src_runs: list[tuple[str, bool]] = []
        self.tgt_runs: list[tuple[str, bool]] = []
        self.hint = '等待讲话…'
        self.hovered = False
        self._drag = None
        self._resize = None
        self._lines_seen = 0
        self._shift = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(170)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on_shift)
        self.apply_settings()
        geometry = settings.overlay_geometry
        # A position saved on a monitor that is no longer connected falls back to the default.
        if len(geometry) == 3 and QApplication.screenAt(QPoint(geometry[0] + 20, geometry[1] + 20)) is not None:
            self.resize(geometry[2], self.height())
            self.move(geometry[0], geometry[1])
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            width = min(1100, int(screen.width() * 0.62))
            self.resize(width, self.height())
            self.move(screen.center().x() - width // 2, screen.bottom() - self.height() - 70)

    # ---- appearance ----------------------------------------------------------------------------
    def apply_settings(self) -> None:
        s = self.settings
        self.tgt_font = QFont('Microsoft YaHei UI')
        self.tgt_font.setPixelSize(s.overlay_font_size)
        self.tgt_font.setWeight(QFont.Weight.DemiBold)
        self.src_font = QFont('Segoe UI')
        self.src_font.setPixelSize(max(13, round(s.overlay_font_size * 0.56)))
        self.tgt_step = QFontMetricsF(self.tgt_font).height() * 1.22
        self.src_step = QFontMetricsF(self.src_font).height() * 1.18
        height = PAD_Y * 2 + self.tgt_step * s.overlay_lines
        if s.overlay_show_source:
            height += self.src_step + GAP
        self.setFixedHeight(round(height))
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, s.overlay_locked)
        self.update()

    def set_locked(self, locked: bool) -> None:
        self.settings.overlay_locked = locked
        visible = self.isVisible()
        self.apply_settings()
        if visible:
            self.show()
        self.changed.emit()

    def set_content(self, src_runs, tgt_runs, hint: str = '') -> None:
        self.src_runs, self.tgt_runs = src_runs, tgt_runs
        self.hint = hint
        self.update()

    def _on_shift(self, value) -> None:
        self._shift = float(value)
        self.update()

    # ---- painting ------------------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        s = self.settings
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.fillPath(panel, QColor(16, 22, 19, round(255 * s.overlay_opacity)))
        if self.hovered and not s.overlay_locked:
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawPath(panel)
            self._draw_close(p)
        width = self.width() - PAD_X * 2
        y = PAD_Y
        if s.overlay_show_source:
            self._draw_block(p, self.src_runs, self.src_font, QColor(255, 255, 255, 150), QColor(255, 255, 255, 105),
                             QRectF(PAD_X, y, width, self.src_step), self.src_step, 1, 0.0)
            y += self.src_step + GAP
        slot = QRectF(PAD_X, y, width, self.tgt_step * s.overlay_lines)
        if not self.tgt_runs and self.hint:
            p.setFont(self.tgt_font)
            p.setPen(QColor(255, 255, 255, 110))
            p.drawText(slot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self.hint)
        else:
            count = self._draw_block(p, self.tgt_runs, self.tgt_font, QColor(255, 255, 255), QColor(255, 255, 255, 150),
                                     slot, self.tgt_step, s.overlay_lines, self._shift)
            if count > self._lines_seen and self._lines_seen and self.anim.state() != QVariantAnimation.State.Running:
                self.anim.setStartValue(self.tgt_step)
                self.anim.setEndValue(0.0)
                self.anim.start()
            self._lines_seen = count
        p.end()

    def _draw_block(self, p, runs, font, color, live_color, slot: QRectF, step: float, max_lines: int, shift: float) -> int:
        text, live = flatten(runs)
        if not text:
            return 0
        layout, tops = layout_lines(text, live, font, slot.width(), live_color, step)
        shown = tops[-max_lines:]
        # Bottom-align: the newest line sits on the slot's last row.
        offset = slot.bottom() - (shown[-1] + step) + shift
        p.save()
        p.setClipRect(QRectF(slot.left() - 2, slot.top(), slot.width() + 4, slot.height() + 2))
        p.setPen(color)
        layout.draw(p, QPointF(slot.left(), offset + (step - QFontMetricsF(font).height()) / 2))
        p.restore()
        return len(tops)

    def _close_rect(self) -> QRectF:
        return QRectF(self.width() - 30, 8, 20, 20)

    def _draw_close(self, p) -> None:
        r = self._close_rect()
        p.setBrush(QColor(255, 255, 255, 40))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(r)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1.6))
        c = r.center()
        p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))

    # ---- interaction ---------------------------------------------------------------------------
    def enterEvent(self, event) -> None:
        self.hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def _edge(self, x: float) -> str | None:
        if x <= EDGE:
            return 'left'
        if x >= self.width() - EDGE:
            return 'right'
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self._close_rect().contains(pos):
            self.hide()
            self.closed.emit()
            return
        edge = self._edge(pos.x())
        if edge:
            self._resize = (edge, event.globalPosition().toPoint(), self.geometry())
        else:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._resize:
            edge, origin, geometry = self._resize
            dx = event.globalPosition().toPoint().x() - origin.x()
            if edge == 'right':
                self.resize(max(self.minimumWidth(), geometry.width() + dx), self.height())
            else:
                width = max(self.minimumWidth(), geometry.width() - dx)
                self.setGeometry(geometry.right() - width + 1, geometry.top(), width, self.height())
        elif self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)
        else:
            cursor = Qt.CursorShape.SizeHorCursor if self._edge(pos.x()) else Qt.CursorShape.SizeAllCursor
            self.setCursor(Qt.CursorShape.PointingHandCursor if self._close_rect().contains(pos) else cursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None or self._resize:
            self._drag = self._resize = None
            self.remember_geometry()

    def mouseDoubleClickEvent(self, event) -> None:
        self.settings.overlay_show_source = not self.settings.overlay_show_source
        self.apply_settings()
        self.changed.emit()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.change_font(2 if event.angleDelta().y() > 0 else -2)

    def change_font(self, delta: int) -> None:
        bottom = self.geometry().bottom()
        self.settings.overlay_font_size = max(16, min(56, self.settings.overlay_font_size + delta))
        self.apply_settings()
        self.move(self.x(), bottom - self.height() + 1)
        self.remember_geometry()

    def contextMenuEvent(self, event) -> None:
        s = self.settings
        menu = QMenu(self)
        show_source = QAction('显示原文', menu, checkable=True, checked=s.overlay_show_source)
        show_source.toggled.connect(lambda v: (setattr(s, 'overlay_show_source', v), self.apply_settings(), self.changed.emit()))
        menu.addAction(show_source)
        lines = menu.addMenu('译文行数')
        for n in (1, 2, 3):
            act = QAction(f'{n} 行', lines, checkable=True, checked=s.overlay_lines == n)
            act.triggered.connect(lambda _=False, n=n: (setattr(s, 'overlay_lines', n), self.apply_settings(), self.changed.emit()))
            lines.addAction(act)
        menu.addAction('放大字号', lambda: self.change_font(2))
        menu.addAction('缩小字号', lambda: self.change_font(-2))
        background = menu.addMenu('背景')
        for label, value in (('更深', 0.92), ('适中', 0.78), ('更透明', 0.55), ('很淡', 0.35)):
            act = QAction(label, background, checkable=True, checked=abs(s.overlay_opacity - value) < 0.01)
            act.triggered.connect(lambda _=False, v=value: (setattr(s, 'overlay_opacity', v), self.update(), self.changed.emit()))
            background.addAction(act)
        menu.addSeparator()
        menu.addAction('锁定（鼠标穿透，在主窗口解锁）', lambda: self.set_locked(True))
        menu.addAction('关闭悬浮字幕', lambda: (self.hide(), self.closed.emit()))
        menu.exec(QCursor.pos())

    def remember_geometry(self) -> None:
        self.settings.overlay_geometry = [self.x(), self.y(), self.width()]
        self.changed.emit()
