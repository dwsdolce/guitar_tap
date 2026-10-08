"""A menu picker drawn as Swift's on macOS: a filled rounded box with no border, the value at its
left and a ⌃⌄ at its right — the same on every OS. The menu that opens is Qt's own.

Mirrors Swift's ``Picker`` with ``.pickerStyle(.menu)``."""

from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.views.utilities import palette

HEIGHT = 24
RADIUS = 6
TEXT_INSET = 10
CHEVRON_SIZE = 14
CHEVRON_INSET = 7
# The room the chevron takes at the right: its inset, its size and a gap before the text.
TRAILING = CHEVRON_INSET + CHEVRON_SIZE + 7


class MenuPicker(QtWidgets.QComboBox):
    """A ``QComboBox`` that draws itself as Swift's menu picker."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        # The width follows the longest item, so the layout is told whenever the items change.
        model = self.model()
        model.rowsInserted.connect(self.updateGeometry)
        model.rowsRemoved.connect(self.updateGeometry)
        model.modelReset.connect(self.updateGeometry)

    def _text_width(self) -> int:
        # The exact width, rounded up: a box sized to a rounded-down width would elide its text.
        metrics = QtGui.QFontMetricsF(self.font())
        texts = [self.itemText(i) for i in range(self.count())] or [self.currentText()]
        return math.ceil(max((metrics.horizontalAdvance(t) for t in texts), default=0.0))

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(TEXT_INSET + self._text_width() + TRAILING, HEIGHT)

    def minimumSizeHint(self) -> QtCore.QSize:
        ellipsis = self.fontMetrics().horizontalAdvance("…")
        return QtCore.QSize(TEXT_INSET + ellipsis + TRAILING, HEIGHT)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        import qtawesome as qta

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.5)
        rect = QtCore.QRectF(self.rect())
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(palette.color(palette.Role.BACKGROUND_PICKER))
        p.drawRoundedRect(rect, RADIUS, RADIUS)

        text_color = palette.color(palette.Role.TEXT_PRIMARY)
        text_rect = self.rect().adjusted(TEXT_INSET, 0, -TRAILING, 0)
        text = self.fontMetrics().elidedText(
            self.currentText(), QtCore.Qt.TextElideMode.ElideRight, text_rect.width())
        p.setPen(text_color)
        align = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        p.drawText(text_rect, int(align), text)

        chevron = qta.icon("mdi.unfold-more-horizontal", color=text_color)
        x = self.width() - CHEVRON_INSET - CHEVRON_SIZE
        y = (self.height() - CHEVRON_SIZE) // 2
        chevron.paint(p, QtCore.QRect(x, y, CHEVRON_SIZE, CHEVRON_SIZE))
        p.end()
