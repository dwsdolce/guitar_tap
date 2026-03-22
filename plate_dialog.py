"""
    Non-modal dialog for plate / brace material analysis.

    Sections
    --------
    1. Dimensions input  (length, width, thickness, mass)
    2. Status / instructions (which tap to take next)
    3. Material property results (shown after analysis completes)
"""

from __future__ import annotations

from PyQt6 import QtWidgets, QtCore, QtGui

import plate_analysis as pa


class _DimSpinBox(QtWidgets.QDoubleSpinBox):
    """Double spin-box pre-configured for plate dimensions."""

    def __init__(self, suffix: str, max_val: float = 1000.0) -> None:
        super().__init__()
        self.setDecimals(1)
        self.setMinimum(0.1)
        self.setMaximum(max_val)
        self.setSuffix(f" {suffix}")
        self.setValue(300.0)


class PlateDialog(QtWidgets.QDialog):
    """Non-modal dialog that drives the plate/brace two-tap analysis.

    Emits
    -----
    startAnalysis()   — user clicked "Start Analysis"; caller should arm PlateCapture.
    resetAnalysis()   — user clicked "Reset"; caller should call PlateCapture.reset().
    """

    startAnalysis: QtCore.pyqtSignal = QtCore.pyqtSignal()
    resetAnalysis: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, QtCore.Qt.WindowType.Tool)
        self.setWindowTitle("Plate / Brace Analysis")
        self.setMinimumWidth(420)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, False)

        self._dims: pa.PlateDimensions | None = None
        self._props: pa.MaterialProperties | None = None

        main_layout = QtWidgets.QVBoxLayout(self)

        # ---- Dimensions group ----------------------------------------
        dim_group = QtWidgets.QGroupBox("Specimen Dimensions")
        form = QtWidgets.QFormLayout(dim_group)

        self._length_spin = _DimSpinBox("mm", 2000.0)
        self._length_spin.setValue(400.0)
        self._length_spin.setToolTip("Long-grain (L) dimension")
        form.addRow("Length (L):", self._length_spin)

        self._width_spin = _DimSpinBox("mm", 1000.0)
        self._width_spin.setValue(100.0)
        self._width_spin.setToolTip("Cross-grain (W) dimension")
        form.addRow("Width (W):", self._width_spin)

        self._thick_spin = _DimSpinBox("mm", 50.0)
        self._thick_spin.setValue(3.0)
        self._thick_spin.setToolTip("Thickness (T)")
        form.addRow("Thickness (T):", self._thick_spin)

        self._mass_spin = QtWidgets.QDoubleSpinBox()
        self._mass_spin.setDecimals(1)
        self._mass_spin.setMinimum(0.1)
        self._mass_spin.setMaximum(5000.0)
        self._mass_spin.setSuffix(" g")
        self._mass_spin.setValue(50.0)
        self._mass_spin.setToolTip("Mass of specimen")
        form.addRow("Mass (m):", self._mass_spin)

        main_layout.addWidget(dim_group)

        # ---- Control buttons ----------------------------------------
        ctrl_layout = QtWidgets.QHBoxLayout()
        self._start_btn = QtWidgets.QPushButton("Start Analysis")
        self._start_btn.setDefault(True)
        self._start_btn.clicked.connect(self._on_start)
        self._reset_btn = QtWidgets.QPushButton("Reset")
        self._reset_btn.setEnabled(False)
        self._reset_btn.clicked.connect(self._on_reset)
        ctrl_layout.addWidget(self._start_btn)
        ctrl_layout.addWidget(self._reset_btn)
        ctrl_layout.addStretch()
        main_layout.addLayout(ctrl_layout)

        # ---- Status label -------------------------------------------
        self._status_label = QtWidgets.QLabel("Enter dimensions and click Start Analysis.")
        self._status_label.setWordWrap(True)
        font = QtGui.QFont()
        font.setBold(True)
        self._status_label.setFont(font)
        main_layout.addWidget(self._status_label)

        # ---- Results group (hidden until complete) ------------------
        self._results_group = QtWidgets.QGroupBox("Material Properties")
        results_form = QtWidgets.QFormLayout(self._results_group)

        def _result_label() -> QtWidgets.QLabel:
            lbl = QtWidgets.QLabel("—")
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            return lbl

        self._r_density = _result_label()
        results_form.addRow("Density:", self._r_density)
        self._r_f_long = _result_label()
        results_form.addRow("f_L (long-grain):", self._r_f_long)
        self._r_f_cross = _result_label()
        results_form.addRow("f_C (cross-grain):", self._r_f_cross)
        self._r_E_long = _result_label()
        results_form.addRow("E_L (long-grain):", self._r_E_long)
        self._r_E_cross = _result_label()
        results_form.addRow("E_C (cross-grain):", self._r_E_cross)
        self._r_c_long = _result_label()
        results_form.addRow("Speed of sound (L):", self._r_c_long)
        self._r_c_cross = _result_label()
        results_form.addRow("Speed of sound (C):", self._r_c_cross)
        self._r_spec_mod = _result_label()
        results_form.addRow("Specific modulus:", self._r_spec_mod)
        self._r_rad = _result_label()
        results_form.addRow("Radiation ratio:", self._r_rad)
        self._r_aniso = _result_label()
        results_form.addRow("Anisotropy (EL/EC):", self._r_aniso)
        self._r_target_t = _result_label()
        results_form.addRow("Target thickness:", self._r_target_t)
        self._r_quality = _result_label()
        self._r_quality.setFont(font)
        results_form.addRow("Quality rating:", self._r_quality)

        self._results_group.setVisible(False)
        main_layout.addWidget(self._results_group)

        # ---- Close button ------------------------------------------
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        main_layout.addWidget(close_btn)

        self.adjustSize()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        dims = self._current_dims()
        if not dims.is_valid():
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Dimensions",
                "All dimensions and mass must be greater than zero.",
            )
            return
        self._dims = dims
        self._results_group.setVisible(False)
        self._start_btn.setEnabled(False)
        self._reset_btn.setEnabled(True)
        self.startAnalysis.emit()

    def _on_reset(self) -> None:
        self._start_btn.setEnabled(True)
        self._reset_btn.setEnabled(False)
        self._results_group.setVisible(False)
        self._status_label.setText("Enter dimensions and click Start Analysis.")
        self.resetAnalysis.emit()

    # ------------------------------------------------------------------
    # Public update methods
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        """Update the status / instruction label."""
        self._status_label.setText(text)

    def show_results(
        self,
        f_long: float,
        f_cross: float,
        props: pa.MaterialProperties,
    ) -> None:
        """Populate and reveal the results section."""
        self._props = props
        self._r_f_long.setText(f"{f_long:.1f} Hz")
        self._r_f_cross.setText(f"{f_cross:.1f} Hz")
        self._r_density.setText(f"{props.density_kg_m3:.0f} kg/m³")
        self._r_E_long.setText(f"{props.E_long_GPa:.2f} GPa")
        self._r_E_cross.setText(f"{props.E_cross_GPa:.2f} GPa")
        self._r_c_long.setText(f"{props.c_long_m_s:.0f} m/s")
        self._r_c_cross.setText(f"{props.c_cross_m_s:.0f} m/s")
        self._r_spec_mod.setText(f"{props.specific_modulus_m2s2:.2f} ×10⁶ m²/s²")
        self._r_rad.setText(f"{props.radiation_ratio:.2f} ×10³")
        self._r_aniso.setText(f"{props.anisotropy_ratio:.1f}")
        self._r_target_t.setText(f"{props.target_thickness_mm:.2f} mm")
        self._r_quality.setText(props.quality_rating)
        self._results_group.setVisible(True)
        self.adjustSize()
        self._reset_btn.setEnabled(True)
        self._start_btn.setEnabled(True)

    def dimensions(self) -> pa.PlateDimensions | None:
        """Return the currently entered dimensions, or None if invalid."""
        d = self._current_dims()
        return d if d.is_valid() else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_dims(self) -> pa.PlateDimensions:
        return pa.PlateDimensions(
            length_mm=self._length_spin.value(),
            width_mm=self._width_spin.value(),
            thickness_mm=self._thick_spin.value(),
            mass_g=self._mass_spin.value(),
        )
