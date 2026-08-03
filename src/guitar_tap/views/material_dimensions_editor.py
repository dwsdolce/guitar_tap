# @parity view/material-dimensions-editor
"""
Editable display of a completed material measurement's own dimensions — Store B
(``MaterialMeasurementInputs``) — shown in the Results panel's Sample Dimensions box.

Mirrors Swift MaterialDimensionsEditor.swift.

Editing a field updates the measurement's ``material_inputs`` live (via the ``get_inputs`` accessor),
so every derived property recomputes; it never touches the Settings defaults (Store A). Shown only when
the measurement is complete (its container gates on that).
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from models import field_precision as fp
from views.shared.validated_number_field import ValidatedNumberField


class MaterialDimensionsEditor(QtWidgets.QWidget):
    """Editable Length / Width / Thickness / Mass rows + a read-only Calculated Density.

    Args:
        get_inputs: returns the live ``MaterialMeasurementInputs`` (Store B), or ``None``.
        on_changed: called after a field edit mutates the inputs, so the view recomputes properties.
        small_font: the Results-panel body font, for visual consistency.
    """

    def __init__(
        self,
        get_inputs: Callable[[], Optional[object]],
        on_changed: Callable[[], None],
        small_font: QtGui.QFont,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._get_inputs = get_inputs
        self._on_changed = on_changed
        self._small_font = small_font

        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(4)

        self._length_field = self._dim_field(fp.LINEAR_DIMENSION_MM)
        self._width_field = self._dim_field(fp.LINEAR_DIMENSION_MM)
        self._thick_field = self._dim_field(fp.LINEAR_DIMENSION_MM)
        self._mass_field = self._dim_field(fp.MASS_G)

        vbox.addLayout(self._dim_row("Length:", self._length_field, "mm"))
        vbox.addLayout(self._dim_row("Width:", self._width_field, "mm"))
        vbox.addLayout(self._dim_row("Thickness:", self._thick_field, "mm"))
        vbox.addLayout(self._dim_row("Mass:", self._mass_field, "g"))

        # Derived, read-only — recomputes as the dimensions above change.
        self._density_lbl = QtWidgets.QLabel("—")
        self._density_lbl.setFont(small_font)
        self._density_lbl.setStyleSheet("font-weight: 500;")
        self._density_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        _drow = QtWidgets.QHBoxLayout()
        _dtitle = QtWidgets.QLabel("Calculated Density:")
        _dtitle.setFont(small_font)
        _dtitle.setStyleSheet("color: palette(mid);")
        _drow.addWidget(_dtitle)
        _drow.addStretch()
        _drow.addWidget(self._density_lbl)
        vbox.addLayout(_drow)

        # Commit on each user edit (textEdited fires only on user input, not programmatic setText —
        # so seeding the fields never triggers a recompute loop). Mirrors Swift onChange(of: text).
        self._length_field.textEdited.connect(
            lambda t: self._commit("length_mm", t, fp.LINEAR_DIMENSION_MM))
        self._width_field.textEdited.connect(
            lambda t: self._commit("width_mm", t, fp.LINEAR_DIMENSION_MM))
        self._thick_field.textEdited.connect(
            lambda t: self._commit("thickness_mm", t, fp.LINEAR_DIMENSION_MM))
        self._mass_field.textEdited.connect(
            lambda t: self._commit("mass_g", t, fp.MASS_G))

        self.seed()

    # ── Field factories (mirror the Settings-dialog _dim_field/_dim_row) ──────────────────

    def _dim_field(self, decimals: int) -> QtWidgets.QLineEdit:
        tf = ValidatedNumberField(decimals, width=80)  # shared view/validated-number-field widget
        tf.setFont(self._small_font)
        return tf

    def _dim_row(self, text: str, widget: QtWidgets.QWidget, unit: str) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(text)
        lbl.setFont(self._small_font)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(widget)
        unit_lbl = QtWidgets.QLabel(unit)
        unit_lbl.setFont(self._small_font)
        unit_lbl.setStyleSheet("color: palette(shadow);")
        row.addWidget(unit_lbl)
        return row

    # ── Edit → Store B → recompute ────────────────────────────────────────────────────────

    def _commit(self, attr: str, text: str, decimals: int) -> None:
        mi = self._get_inputs()
        if mi is None:
            return
        try:
            value = float(text)
        except ValueError:
            return  # empty / partial input — leave the prior value (mirrors Swift `if let v = Float`)
        setattr(mi, attr, fp.rounded(value, decimals))
        self._update_density(mi)
        self._on_changed()

    def _update_density(self, mi) -> None:
        self._density_lbl.setText(f"{mi.dimensions.density_g_per_cm3():.3f} g/cm³")

    def seed(self) -> None:
        """Refresh the field text from the current inputs. Called when the measurement itself changes
        (a new load / capture completes), not on a live edit — a field whose text already parses to the
        value is left alone so typing isn't reset (mirrors Swift seedField)."""
        mi = self._get_inputs()
        if mi is None:
            return
        self._seed_field(self._length_field, mi.length_mm, fp.LINEAR_DIMENSION_MM)
        self._seed_field(self._width_field, mi.width_mm, fp.LINEAR_DIMENSION_MM)
        self._seed_field(self._thick_field, mi.thickness_mm, fp.LINEAR_DIMENSION_MM)
        self._seed_field(self._mass_field, mi.mass_g, fp.MASS_G)
        self._update_density(mi)

    @staticmethod
    def _seed_field(field: QtWidgets.QLineEdit, value: float, decimals: int) -> None:
        try:
            if float(field.text()) == value:
                return
        except ValueError:
            pass
        field.setText(fp.string(value, decimals))
