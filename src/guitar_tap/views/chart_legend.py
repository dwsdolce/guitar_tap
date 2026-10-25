# @parity view/spectrum-chart tests=test/chart-legend
"""
The chart's legend for its overlaid curves — a comparison's measurements, a multi-tap measurement's taps, a plate's
or brace's phases: each curve's line and its label in the curve's colour, on the readout background. It sits in the
plot's upper-right corner, over everything in the plot, and wraps onto as many lines as it needs, each line
right-aligned; the plot keeps its size. The screen and the exported image draw the same legend, each in its own sizes. Mirrors Swift
``ChartLegend`` and ``TrailingFlowLayout`` (Views/ChartLegend.swift).
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


def legend_lines(widths: list[float], width: float, spacing: float) -> list[list[int]]:
    """The views' indices in lines no wider than ``width``; a view wider than ``width`` has a line of its own.
    Mirrors Swift ``TrailingFlowLayout.lines(_:width:)``."""
    lines: list[list[int]] = []
    current: list[int] = []
    line_width = 0.0
    for index, w in enumerate(widths):
        needed = w if not current else line_width + spacing + w
        if current and needed > width:
            lines.append(current)
            current = [index]
            line_width = w
        else:
            current.append(index)
            line_width = needed
    if current:
        lines.append(current)
    return lines


class TrailingFlowLayout(QtWidgets.QLayout):
    """Lays its views out in lines as wide as it is offered, starting a new line when the next view does not fit,
    and aligns each line to the trailing edge. Mirrors Swift ``TrailingFlowLayout``."""

    def __init__(self, spacing: int, line_spacing: int, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self._spacing = spacing
        self._line_spacing = line_spacing

    def addItem(self, item: QtWidgets.QLayoutItem) -> None:  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QtWidgets.QLayoutItem | None:  # noqa: N802 (Qt API)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QtWidgets.QLayoutItem | None:  # noqa: N802 (Qt API)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def _line_size(self, line: list[int], sizes: list[QtCore.QSize]) -> QtCore.QSize:
        return QtCore.QSize(sum(sizes[i].width() for i in line) + self._spacing * max(len(line) - 1, 0),
                            max((sizes[i].height() for i in line), default=0))

    def size_that_fits(self, width: float) -> QtCore.QSize:
        """The views' size laid out in lines no wider than ``width``. Mirrors Swift ``sizeThatFits``."""
        sizes = [item.sizeHint() for item in self._items]
        line_sizes = [self._line_size(line, sizes)
                      for line in legend_lines([s.width() for s in sizes], width, self._spacing)]
        return QtCore.QSize(max((s.width() for s in line_sizes), default=0),
                            sum(s.height() for s in line_sizes) + self._line_spacing * max(len(line_sizes) - 1, 0))

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 (Qt API)
        return self.size_that_fits(float("inf"))

    def setGeometry(self, rect: QtCore.QRect) -> None:  # noqa: N802 (Qt API)
        """Places the views line by line, each line right-aligned. Mirrors Swift ``placeSubviews``."""
        super().setGeometry(rect)
        rect = rect.marginsRemoved(self.contentsMargins())
        sizes = [item.sizeHint() for item in self._items]
        y = rect.top()
        for line in legend_lines([s.width() for s in sizes], rect.width(), self._spacing):
            size = self._line_size(line, sizes)
            x = rect.right() + 1 - size.width()
            for index in line:
                self._items[index].setGeometry(QtCore.QRect(
                    QtCore.QPoint(x, y + (size.height() - sizes[index].height()) // 2), sizes[index]))
                x += sizes[index].width() + self._spacing
            y += size.height() + self._line_spacing


class ChartLegend(QtWidgets.QWidget):
    """The legend: ``series`` as (colour, label), each a ``swatch``-sized line and its label at ``font_size`` (in
    ``font``'s family), in a ``TrailingFlowLayout`` inside ``padding``, on ``background`` with ``corner_radius``.
    Sizes are in points, drawn at ``scale`` pixels per point (the exported image's 2, as Swift's
    ``ImageRenderer(scale: 2.0)``). The screen's sizes are the defaults; the exported image passes its own. Mirrors
    Swift ``ChartLegend``."""

    def __init__(self, series: list[tuple[QtGui.QColor, str]], background: QtGui.QColor,
                 font: QtGui.QFont | None = None, font_size: int = 10,
                 swatch: tuple[int, int] = (16, 2), spacing: int = 12, line_spacing: int = 4,
                 padding: tuple[int, int, int, int] = (4, 8, 4, 8), corner_radius: int = 6, scale: int = 1,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._background = background
        self._corner_radius = corner_radius * scale
        top, leading, bottom, trailing = (v * scale for v in padding)
        self._padding = QtCore.QMargins(leading, top, trailing, bottom)
        self._flow = TrailingFlowLayout(spacing * scale, line_spacing * scale, self)
        self._flow.setContentsMargins(self._padding)
        label_font = QtGui.QFont(font) if font is not None else QtGui.QFont()
        label_font.setPixelSize(font_size * scale)
        for color, label in series:
            entry = QtWidgets.QWidget(self)
            row = QtWidgets.QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4 * scale)
            line = QtWidgets.QFrame(entry)
            line.setFixedSize(swatch[0] * scale, swatch[1] * scale)
            line.setStyleSheet(f"background: {color.name()};")
            text = QtWidgets.QLabel(label, entry)
            text.setFont(label_font)
            text.setStyleSheet(f"color: {color.name()}; background: transparent;")
            row.addWidget(line, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(text, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            entry.setFixedSize(entry.sizeHint())
            self._flow.addWidget(entry)

    def size_that_fits(self, width: float) -> QtCore.QSize:
        """The legend's size when offered ``width``: its lines' size inside the padding."""
        inner = self._flow.size_that_fits(width - self._padding.left() - self._padding.right())
        return QtCore.QSize(inner.width() + self._padding.left() + self._padding.right(),
                            inner.height() + self._padding.top() + self._padding.bottom())

    def place(self, top_right: QtCore.QPoint, width: float) -> None:
        """Sizes the legend to ``width`` and puts its upper-right corner at ``top_right``."""
        size = self.size_that_fits(width)
        self.setGeometry(top_right.x() - size.width(), top_right.y(), size.width(), size.height())

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt API)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._background)
        painter.drawRoundedRect(QtCore.QRectF(self.rect()), self._corner_radius, self._corner_radius)
