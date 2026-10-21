"""
Value stepper — a whole number shown as text, then a stepper of two stacked arrows, in a rounded outline, that
raise and lower it.

Mirrors Swift's tap count: a ``Text`` of the value (caption, medium, text.primary) before a label-less
``Stepper``. The value is not editable; the arrows change it, each one unable to act at its end of the range.

Usage::

    taps = ValueStepper(1, 10, font)
    taps.valueChanged.connect(on_taps_changed)
    taps.setValue(3)
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.views.utilities import palette


class ValueStepper(QtWidgets.QWidget):
    """A value label, then stacked up/down arrows. ``value``, ``setValue`` and ``valueChanged`` as QSpinBox's."""

    valueChanged = QtCore.Signal(int)

    def __init__(
        self, minimum: int, maximum: int, font: QtGui.QFont, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._value = minimum

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._label = QtWidgets.QLabel(str(minimum))
        value_font = QtGui.QFont(font)
        value_font.setWeight(QtGui.QFont.Weight.Medium)
        self._label.setFont(value_font)
        self._label.setMinimumWidth(16)
        self._label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        palette.tag(self._label, color=palette.Role.TEXT_PRIMARY)
        layout.addWidget(self._label)

        # The arrows in a rounded outline 22 tall, as Swift's macOS stepper. The objectName selector keeps the
        # outline to this frame, not the buttons inside it.
        frame = QtWidgets.QFrame()
        frame.setObjectName("stepper_arrows")
        frame.setStyleSheet("#stepper_arrows { border-width: 1px; border-style: solid; border-radius: 5px; }")
        palette.tag(frame, border=palette.Role.SEPARATOR)
        arrows = QtWidgets.QVBoxLayout(frame)
        arrows.setContentsMargins(1, 0, 1, 0)
        arrows.setSpacing(0)
        self._up = self._arrow("mdi.chevron-up", "Increase", 1)
        self._down = self._arrow("mdi.chevron-down", "Decrease", -1)
        arrows.addWidget(self._up)
        arrows.addWidget(self._down)
        frame.setFixedHeight(22)
        layout.addWidget(frame)

        self._refresh()

    def _arrow(self, icon: str, name: str, step: int) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setAccessibleName(name)
        button.setAutoRaise(True)
        button.setStyleSheet("border: none; padding: 0")
        button.setIconSize(QtCore.QSize(10, 10))
        button.setFixedSize(12, 10)
        palette.set_icon(button, icon, palette.Role.TEXT_PRIMARY)
        button.clicked.connect(lambda: self.setValue(self._value + step))
        return button

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        """Set the value, kept within the range; announces a change unless signals are blocked."""
        value = max(self._minimum, min(self._maximum, int(value)))
        if value == self._value:
            return
        self._value = value
        self._refresh()
        self.valueChanged.emit(value)

    def _refresh(self) -> None:
        self._label.setText(str(self._value))
        self._up.setEnabled(self._value < self._maximum)
        self._down.setEnabled(self._value > self._minimum)
