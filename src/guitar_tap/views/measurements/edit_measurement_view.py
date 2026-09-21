"""
EditMeasurementView — modal dialog for editing measurementName and notes of a
saved TapToneMeasurement.

Mirrors Swift EditMeasurementView.swift.

Pre-populates the fields from the measurement passed in. Returns the edited
values via ``edited_values()`` after the dialog is accepted. The caller
(MeasurementsDialog._open_edit) is responsible for updating the in-memory
list and persisting to disk, matching how the dialog manages its own
measurement list.

Save is disabled until the name or notes actually differ from the stored values. A saved
edit mints a new measurement ``id`` — an amended measurement is a different dataset — so a
Save that changes nothing must not be reachable, or unchanged content would get a new
identity. With the button disabled, saving an untouched form and cancelling it are the same
action. Mirrors Swift ``EditMeasurementView.hasChanges``.

- SeeAlso: ``MeasurementsDialog``, ``MeasurementDetailDialog``
"""

# @parity view/edit-sheet
from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement


class EditMeasurementView(QtWidgets.QDialog):
    """Modal dialog for editing the measurementName and notes of a saved measurement.

    Mirrors Swift ``EditMeasurementView``.

    Pre-populates fields from ``measurement``. Call ``edited_values()`` after
    ``exec()`` returns ``Accepted`` to retrieve the new measurement_name and notes.
    """

    def __init__(
        self,
        index: int,
        measurement: "TapToneMeasurement",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._measurement = measurement

        self.setWindowTitle("Edit Measurement")
        self.setMinimumWidth(450)
        self.setMinimumHeight(250)
        self.resize(500, 350)

        self._build_ui()

    # MARK: - UI Construction

    def _build_ui(self) -> None:
        """Construct the dialog layout, mirroring Swift formContent (macOS branch)."""
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(16)

        # ── Title ──────────────────────────────────────────────────────────────
        # Mirrors Swift Text("Edit Measurement").font(.title2).fontWeight(.semibold)
        title = QtWidgets.QLabel("Edit Measurement")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)

        # ── Measurement Name ───────────────────────────────────────────────────
        # Mirrors Swift VStack { Text("Measurement Name") TextField(...) }
        loc_group = QtWidgets.QVBoxLayout()
        loc_group.setSpacing(6)

        loc_heading = QtWidgets.QLabel("Measurement Name")
        loc_heading_font = loc_heading.font()
        loc_heading_font.setBold(True)
        loc_heading.setFont(loc_heading_font)
        loc_group.addWidget(loc_heading)

        self._measurement_name_edit = QtWidgets.QLineEdit()
        self._measurement_name_edit.setPlaceholderText("e.g. Martin 000-28, Spruce Top")
        self._measurement_name_edit.setText(self._measurement.measurement_name or "")
        loc_group.addWidget(self._measurement_name_edit)

        outer.addLayout(loc_group)

        # ── Notes ──────────────────────────────────────────────────────────────
        # Mirrors Swift VStack { Text("Notes (Optional)") TextEditor(...) caption }
        notes_group = QtWidgets.QVBoxLayout()
        notes_group.setSpacing(6)

        notes_heading = QtWidgets.QLabel("Notes (Optional)")
        notes_heading_font = notes_heading.font()
        notes_heading_font.setBold(True)
        notes_heading.setFont(notes_heading_font)
        notes_group.addWidget(notes_heading)

        self._notes_edit = QtWidgets.QPlainTextEdit()
        self._notes_edit.setPlainText(self._measurement.notes or "")
        self._notes_edit.setMinimumHeight(80)
        notes_group.addWidget(self._notes_edit)

        caption = QtWidgets.QLabel("Add any observations about this measurement")
        caption_font = caption.font()
        caption_font.setPointSize(max(8, caption_font.pointSize() - 2))
        caption.setFont(caption_font)
        caption.setStyleSheet("color: gray")
        notes_group.addWidget(caption)

        outer.addLayout(notes_group)

        outer.addStretch()

        # ── Button row ─────────────────────────────────────────────────────────
        # Mirrors Swift toolbar: Cancel (.cancellationAction) + Save (.confirmationAction)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self._save_btn = QtWidgets.QPushButton("Save")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._save_btn)

        outer.addLayout(btn_row)

        # Gate Save on an actual change — see the module docstring.
        self._measurement_name_edit.textChanged.connect(self._sync_save_enabled)
        self._notes_edit.textChanged.connect(self._sync_save_enabled)
        self._sync_save_enabled()

    # MARK: - Change detection

    def has_changes(self) -> bool:
        """Whether Save would write anything different from the stored measurement.

        The rule itself lives on the model (``TapToneMeasurement.is_amended``) so all three
        platforms and their tests share one definition; this dialog only supplies the normalised
        values. Mirrors Swift ``EditMeasurementView.hasChanges``.
        """
        measurement_name, notes = self.edited_values()
        return self._measurement.is_amended(measurement_name, notes)

    def _sync_save_enabled(self, *_args: object) -> None:
        """Enable Save only while ``has_changes()`` holds."""
        self._save_btn.setEnabled(self.has_changes())

    # MARK: - Result

    def edited_values(self) -> tuple[str | None, str | None]:
        """Return (measurement_name, notes) as entered by the user.

        Mirrors Swift save() reading self.measurementName / self.notes before
        calling analyzer.updateMeasurement(at:measurementName:notes:). Both fields are normalised
        by the model's own rules — the same ones the save path uses — so the change test compares
        against what would actually be stored.
        """
        measurement_name = TapToneMeasurement.normalized_name(self._measurement_name_edit.text())
        notes = TapToneMeasurement.normalized_notes(self._notes_edit.toPlainText())
        return measurement_name, notes
