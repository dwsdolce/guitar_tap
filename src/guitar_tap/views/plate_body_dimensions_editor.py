# @parity view/plate-body-dimensions-editor
"""
Editable display of a completed plate measurement's own Gore body settings — the finished-guitar body
dimensions (a, b) and the panel vibrational stiffness (f_vs) — stored per-measurement in
``MaterialMeasurementInputs`` (Store B), shown in the Results panel's Body Dimensions box.

Mirrors Swift PlateBodyDimensionsEditor.swift.

These feed only the Gore target thickness; editing a field updates the measurement's ``material_inputs``
live so the target recomputes, and never touches the Settings defaults (Store A). Shown only when the
plate measurement is complete. See GuitarTapWeb/Development/MEASUREMENT-DIMENSIONS-SPEC.md.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from models import field_precision as fp
from models.plate_stiffness_preset import PlateStiffnessPreset


class PlateBodyDimensionsEditor(QtWidgets.QWidget):
    """Editable Body Length (a) / Lower Bout Width (b) + a Panel Stiffness (f_vs) preset/custom row.

    Args:
        get_inputs: returns the live ``MaterialMeasurementInputs`` (Store B), or ``None``.
        on_changed: called after a field edit mutates the inputs, so the view recomputes the Gore target.
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

        self._body_len_field = self._dim_field(fp.BODY_DIMENSION_MM)
        self._body_wid_field = self._dim_field(fp.BODY_DIMENSION_MM)
        vbox.addLayout(self._dim_row("Body Length (a):", self._body_len_field, "mm"))
        vbox.addLayout(self._dim_row("Lower Bout Width (b):", self._body_wid_field, "mm"))

        # Panel Stiffness (f_vs): preset combo (all presets by short name) + optional custom value.
        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.setFont(small_font)
        for preset in PlateStiffnessPreset:
            self._preset_combo.addItem(preset.short_name, preset)
        _prow = QtWidgets.QHBoxLayout()
        _plbl = QtWidgets.QLabel("Panel Stiffness (f_vs):")
        _plbl.setFont(small_font)
        _prow.addWidget(_plbl)
        _prow.addStretch()
        _prow.addWidget(self._preset_combo)
        vbox.addLayout(_prow)

        self._custom_field = self._dim_field(fp.STIFFNESS)
        self._custom_row_w = QtWidgets.QWidget()
        _crow = QtWidgets.QHBoxLayout(self._custom_row_w)
        _crow.setContentsMargins(0, 0, 0, 0)
        _clbl = QtWidgets.QLabel("Custom f_vs:")
        _clbl.setFont(small_font)
        _crow.addWidget(_clbl)
        _crow.addStretch()
        _crow.addWidget(self._custom_field)
        vbox.addWidget(self._custom_row_w)

        self._body_len_field.textEdited.connect(
            lambda t: self._commit("body_length_mm", t, fp.BODY_DIMENSION_MM))
        self._body_wid_field.textEdited.connect(
            lambda t: self._commit("body_width_mm", t, fp.BODY_DIMENSION_MM))
        self._custom_field.textEdited.connect(
            lambda t: self._commit("custom_stiffness", t, fp.STIFFNESS))
        self._preset_combo.activated.connect(self._on_preset_changed)

        self.seed()

    # ── Field factories ───────────────────────────────────────────────────────────────────

    def _dim_field(self, decimals: int) -> QtWidgets.QLineEdit:
        tf = QtWidgets.QLineEdit()
        tf.setFixedWidth(80)
        tf.setFont(self._small_font)
        tf.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        tf.setValidator(QtGui.QRegularExpressionValidator(
            QtCore.QRegularExpression(fp.input_regex(decimals))))
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
            return
        setattr(mi, attr, fp.rounded(value, decimals))
        self._on_changed()

    def _on_preset_changed(self, index: int) -> None:
        mi = self._get_inputs()
        if mi is None:
            return
        preset = self._preset_combo.itemData(index)
        mi.stiffness_preset = preset
        self._custom_row_w.setVisible(preset == PlateStiffnessPreset.CUSTOM)
        self._on_changed()

    def seed(self) -> None:
        """Refresh the fields + combo from the current inputs (external change: load / capture)."""
        mi = self._get_inputs()
        if mi is None:
            return
        self._seed_field(self._body_len_field, mi.body_length_mm, fp.BODY_DIMENSION_MM)
        self._seed_field(self._body_wid_field, mi.body_width_mm, fp.BODY_DIMENSION_MM)
        self._seed_field(self._custom_field, mi.custom_stiffness, fp.STIFFNESS)
        idx = self._preset_combo.findData(mi.stiffness_preset)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._custom_row_w.setVisible(mi.stiffness_preset == PlateStiffnessPreset.CUSTOM)

    @staticmethod
    def _seed_field(field: QtWidgets.QLineEdit, value: float, decimals: int) -> None:
        try:
            if float(field.text()) == value:
                return
        except ValueError:
            pass
        field.setText(fp.string(value, decimals))
