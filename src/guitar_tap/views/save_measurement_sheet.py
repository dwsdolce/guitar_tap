# @parity view/save-sheet
"""
Modal dialog for entering Measurement Name and notes before saving a measurement.
Matches SaveMeasurementSheet.swift.
"""

from PySide6 import QtWidgets


class SaveMeasurementDialog(QtWidgets.QDialog):
    """Gather optional measurement_name and notes before saving. 450×250 minimum."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Measurement")
        self.setMinimumSize(450, 250)

        layout = QtWidgets.QVBoxLayout(self)

        # Measurement Name
        loc_group = QtWidgets.QGroupBox("Measurement Name")
        loc_layout = QtWidgets.QVBoxLayout(loc_group)
        self._location_edit = QtWidgets.QLineEdit()
        self._location_edit.setPlaceholderText("e.g. Martin 000-28, Spruce Top")
        loc_layout.addWidget(self._location_edit)
        layout.addWidget(loc_group)

        # Notes
        notes_group = QtWidgets.QGroupBox("Notes (Optional)")
        notes_layout = QtWidgets.QVBoxLayout(notes_group)
        self._notes_edit = QtWidgets.QTextEdit()
        self._notes_edit.setFixedHeight(100)
        self._notes_edit.setPlaceholderText(
            "Add any observations about this measurement"
        )
        notes_layout.addWidget(self._notes_edit)
        layout.addWidget(notes_group)

        # Buttons
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # A name must be entered before Save is allowed (§3). The rule lives on the model so all
        # three platforms agree; the view only binds the button's enabled state to it.
        self._save_btn = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
        self._location_edit.textChanged.connect(self._update_save_enabled)
        self._update_save_enabled()

        self._location_edit.setFocus()

    def _update_save_enabled(self) -> None:
        from models.tap_tone_measurement import TapToneMeasurement
        self._save_btn.setEnabled(TapToneMeasurement.is_valid_name(self._location_edit.text()))

    @property
    def measurement_name(self) -> str:
        """The entered measurement name, trimmed of surrounding whitespace."""
        return self._location_edit.text().strip()

    @property
    def notes(self) -> str:
        """The entered notes, trimmed of surrounding whitespace."""
        return self._notes_edit.toPlainText().strip()

    def set_measurement_name(self, value: str) -> None:
        """Pre-populate the measurement_name field (loaded name on re-save, else empty). Mirrors
        Swift SaveMeasurementSheet defaultName."""
        self._location_edit.setText(value)

    def set_notes(self, value: str) -> None:
        """Pre-populate the notes field. Mirrors Swift @Binding pre-fill."""
        self._notes_edit.setPlainText(value)
