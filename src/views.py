"""Transcript panes. Only the paragraphs that changed are rewritten, so a two-hour lecture stays smooth
and selections in earlier paragraphs survive live updates."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout

INK = '#1f3329'
LIVE = '#8a9a8f'


class TranscriptPane(QFrame):
    def __init__(self, title: str, tag: str, side: str, transcript, placeholder: str):
        super().__init__()
        self.setObjectName('pane')
        self.side, self.transcript = side, transcript
        self.follow = True
        self.font_px = 17
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 18, 18, 14)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName('paneTitle')
        tag_label = QLabel(tag)
        tag_label.setObjectName('paneTag')
        head.addWidget(title_label)
        head.addWidget(tag_label)
        head.addStretch()
        layout.addLayout(head)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setUndoRedoEnabled(False)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setPlaceholderText(placeholder)
        self.view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.view.setAccessibleName(title)
        self.view.document().setDocumentMargin(2)
        layout.addWidget(self.view, 1)
        self._formats()

    def _formats(self) -> None:
        family = 'Segoe UI' if self.side == 'src' else 'Microsoft YaHei UI'
        font = QFont(family)
        font.setPixelSize(self.font_px)
        self.view.document().setDefaultFont(font)
        self.final_fmt = QTextCharFormat()
        self.final_fmt.setForeground(QColor(INK))
        self.live_fmt = QTextCharFormat()
        self.live_fmt.setForeground(QColor(LIVE))
        self.block_fmt = QTextBlockFormat()
        self.block_fmt.setLineHeight(168 if self.side == 'tgt' else 158, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        self.block_fmt.setBottomMargin(self.font_px * 0.95)

    def set_font_size(self, px: int) -> None:
        self.font_px = px
        self._formats()
        self.refresh(0)

    def clear(self) -> None:
        self.view.clear()

    def refresh(self, from_paragraph: int | None) -> None:
        if from_paragraph is None:
            return
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 40
        position = bar.value()
        doc = self.view.document()
        paragraphs = len(self.transcript.paragraphs)
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        reuse = from_paragraph < doc.blockCount()
        if reuse:
            cursor.setPosition(doc.findBlockByNumber(from_paragraph).position())
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        for n, p in enumerate(range(from_paragraph, paragraphs)):
            if n or not reuse:
                cursor.insertBlock(self.block_fmt, self.final_fmt)
            else:
                cursor.setBlockFormat(self.block_fmt)
            for text, live in self.transcript.runs(p, self.side):
                cursor.insertText(text, self.live_fmt if live else self.final_fmt)
        # A paragraph whose translation has not arrived keeps an empty block, so both panes share
        # the same paragraph numbering.
        cursor.endEditBlock()
        if self.follow and at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(position)
