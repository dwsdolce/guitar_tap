# @parity view/save-sheet
"""
Modal dialog for entering Measurement Name and notes before saving a measurement.
Matches SaveMeasurementSheet.swift.
"""

from PySide6 import QtGui, QtWidgets

from guitar_tap.views.utilities import palette


def section_label(text: str) -> QtWidgets.QLabel:
    """A field's title above it — Swift's .headline: bold, at body size."""
    label = QtWidgets.QLabel(text)
    font = QtGui.QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


def caption_label(text: str) -> QtWidgets.QLabel:
    """A hint under a field — Swift's .caption in the secondary colour."""
    label = QtWidgets.QLabel(text)
    font = QtGui.QFont(label.font())
    font.setPointSize(max(8, font.pointSize() - 3))
    label.setFont(font)
    label.setWordWrap(True)
    palette.tag(label, color=palette.Role.TEXT_SECONDARY)
    return label


def set_commit_enabled(button: QtWidgets.QPushButton, enabled: bool) -> None:
    """A button that commits (Save, Play) — Swift's .confirmationAction: the accent with white
    text while it can act, a plain grey button while it cannot."""
    button.setEnabled(enabled)
    palette.tag(button, prominent=palette.Role.ACCENT if enabled else None)


class SaveMeasurementDialog(QtWidgets.QDialog):
    """Gather the measurement name and notes before saving — Swift's SaveMeasurementSheet: a bold
    title above each field, the notes hint under its box, Cancel and Save at the bottom right."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Measurement")
        self.setMinimumSize(450, 250)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(6)

        layout.addWidget(section_label("Measurement Name"))
        self._location_edit = QtWidgets.QLineEdit()
        self._location_edit.setPlaceholderText("e.g. Martin 000-28, Spruce Top")
        layout.addWidget(self._location_edit)
        layout.addSpacing(10)

        layout.addWidget(section_label("Notes (Optional)"))
        self._notes_edit = QtWidgets.QTextEdit()
        self._notes_edit.setMinimumHeight(100)
        layout.addWidget(self._notes_edit, 1)
        layout.addWidget(caption_label("Add any observations about this measurement"))
        layout.addSpacing(10)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._save_btn = QtWidgets.QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self.accept)
        buttons.addWidget(self._save_btn)
        layout.addLayout(buttons)

        self._location_edit.textChanged.connect(self._update_save_enabled)
        self._update_save_enabled()

        self._location_edit.setFocus()

    def _update_save_enabled(self) -> None:
        from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
        set_commit_enabled(
            self._save_btn, TapToneMeasurement.is_valid_name(self._location_edit.text()))

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
