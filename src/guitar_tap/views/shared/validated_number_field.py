# @parity view/validated-number-field
"""
ValidatedNumberField — a ``QLineEdit`` that rejects an over-precise keystroke *before* it is displayed,
so the disallowed character never appears (a 2-dp field accepts "29.35" but not "29.356"; a 0-dp field
rejects the decimal point entirely). Validity is decided by ``FieldPrecision.input_regex`` via a
``QRegularExpressionValidator`` — Qt's pre-display input veto.

This is the Python edition's mechanism for the same restrict-on-entry behaviour Swift gets from a
UITextField/NSTextField delegate veto and the web from a synchronous ``onChange`` revert. Each edition
uses its framework's idiom over the SHARED precision policy in ``FieldPrecision`` (the
``util/field-precision`` parity group); together the three widgets form the ``view/validated-number-field``
mirror. Mirrors Swift ``ValidatedNumberField`` / web ``NumberField``.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from models import field_precision as fp


class ValidatedNumberField(QtWidgets.QLineEdit):
    """A right-aligned numeric field limited to ``decimals`` fractional digits.

    :param decimals: fractional digits allowed (0 rejects the decimal point; negatives are permitted,
        matching ``FieldPrecision.input_regex``).
    :param value: optional initial value, displayed at ``decimals`` precision.
    :param width: optional fixed field width in px (the dimension fields use 80).
    :param placeholder: optional placeholder text (e.g. a unit).
    """

    def __init__(self, decimals: int, *, value: float | None = None,
                 width: int | None = None, placeholder: str = "",
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        if value is not None:
            self.setText(fp.string(value, decimals))
        if width is not None:
            self.setFixedWidth(width)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.setValidator(QtGui.QRegularExpressionValidator(
            QtCore.QRegularExpression(fp.input_regex(decimals))))
