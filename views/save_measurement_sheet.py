"""
Modal dialog for entering tap location and notes before saving a measurement.
Matches SaveMeasurementSheet.swift.
"""

from PyQt6 import QtWidgets


class SaveMeasurementDialog(QtWidgets.QDialog):
    """Gather optional tap location and notes before saving. 450×250 minimum."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Measurement")
        self.setMinimumSize(450, 250)

        layout = QtWidgets.QVBoxLayout(self)

        # Tap location
        loc_group = QtWidgets.QGroupBox("Tap Location (Optional)")
        loc_layout = QtWidgets.QVBoxLayout(loc_group)
        self._location_edit = QtWidgets.QLineEdit()
        self._location_edit.setPlaceholderText("Bridge, Soundhole, Upper Bout…")
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

        self._location_edit.setFocus()

    @property
    def tap_location(self) -> str:
        return self._location_edit.text().strip()

    @property
    def notes(self) -> str:
        return self._notes_edit.toPlainText().strip()

    def set_tap_location(self, value: str) -> None:
        """Pre-populate the tap location field. Mirrors Swift @Binding pre-fill."""
        self._location_edit.setText(value)

    def set_notes(self, value: str) -> None:
        """Pre-populate the notes field. Mirrors Swift @Binding pre-fill."""
        self._notes_edit.setPlainText(value)
