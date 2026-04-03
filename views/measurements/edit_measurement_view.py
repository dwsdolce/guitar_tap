"""
EditMeasurementView — modal dialog for editing tapLocation and notes of a
saved TapToneMeasurement.

Mirrors Swift EditMeasurementView.swift.

Pre-populates the fields from the measurement passed in. Returns the edited
values via ``edited_values()`` after the dialog is accepted. The caller
(MeasurementsDialog._open_edit) is responsible for updating the in-memory
list and persisting to disk, matching how the dialog manages its own
measurement list.

- SeeAlso: ``MeasurementsDialog``, ``MeasurementDetailDialog``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from models import TapToneMeasurement


class EditMeasurementView(QtWidgets.QDialog):
    """Modal dialog for editing the tapLocation and notes of a saved measurement.

    Mirrors Swift ``EditMeasurementView``.

    Pre-populates fields from ``measurement``. Call ``edited_values()`` after
    ``exec()`` returns ``Accepted`` to retrieve the new tap_location and notes.
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

        # ── Tap Location ───────────────────────────────────────────────────────
        # Mirrors Swift VStack { Text("Tap Location (Optional)") TextField(...) }
        loc_group = QtWidgets.QVBoxLayout()
        loc_group.setSpacing(6)

        loc_heading = QtWidgets.QLabel("Tap Location (Optional)")
        loc_heading_font = loc_heading.font()
        loc_heading_font.setBold(True)
        loc_heading.setFont(loc_heading_font)
        loc_group.addWidget(loc_heading)

        self._tap_location_edit = QtWidgets.QLineEdit()
        self._tap_location_edit.setPlaceholderText("Bridge, Soundhole, Upper Bout…")
        self._tap_location_edit.setText(self._measurement.tap_location or "")
        loc_group.addWidget(self._tap_location_edit)

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

        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)

        outer.addLayout(btn_row)

    # MARK: - Result

    def edited_values(self) -> tuple[str | None, str | None]:
        """Return (tap_location, notes) as entered by the user.

        Mirrors Swift save() reading self.tapLocation / self.notes before
        calling analyzer.updateMeasurement(at:tapLocation:notes:).
        Empty strings are normalised to None (mirrors Swift's
        ``tapLocation.isEmpty ? nil : tapLocation``).
        """
        tap_location = self._tap_location_edit.text().strip() or None
        notes = self._notes_edit.toPlainText().strip() or None
        return tap_location, notes
