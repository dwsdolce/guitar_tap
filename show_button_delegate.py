"""
    Delegate for the peak selection column — renders a filled/empty star.
"""

from PyQt6 import QtWidgets, QtCore, QtGui


class ShowComboDelegate(QtWidgets.QStyledItemDelegate):
    """Renders a ★ (selected) or ☆ (unselected) star in the Show column."""

    enable: bool = True

    _STAR_ON  = "★"
    _STAR_OFF = "☆"

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        value = index.model().data_value(index) if index.isValid() else "off"
        glyph = self._STAR_ON if value == "on" else self._STAR_OFF
        painter.save()
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        color = QtGui.QColor(30, 120, 255) if value == "on" else QtGui.QColor(160, 160, 160)
        painter.setPen(color)
        font = painter.font()
        font.setPointSize(13)
        painter.setFont(font)
        painter.drawText(option.rect, QtCore.Qt.AlignmentFlag.AlignCenter, glyph)
        painter.restore()

    def createEditor(
        self,
        parent: QtWidgets.QWidget,
        _option: QtWidgets.QStyleOptionViewItem,
        _index: QtCore.QModelIndex,
    ) -> QtWidgets.QWidget | None:
        if not self.enable:
            return None
        # Transparent button — click commits toggle immediately via editorEvent
        return None

    def editorEvent(
        self,
        event: QtCore.QEvent,
        model: QtCore.QAbstractItemModel,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> bool:
        if not self.enable:
            return False
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            current = model.data_value(index) if index.isValid() else "off"
            model.setData(index, "off" if current == "on" else "on")
            return True
        return False

    def sizeHint(
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ) -> QtCore.QSize:
        return QtCore.QSize(28, 22)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if hasattr(obj, "setEnabled"):
            obj.setEnabled(self.enable)  # type: ignore[union-attr]
        return super().eventFilter(obj, event)
