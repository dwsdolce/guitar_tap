"""
Dialog for listing, loading, comparing, and managing saved measurements.
Matches MeasurementsListView.swift — macOS layout.

Button layout (matches SwiftUI .cancellationAction / .primaryAction on macOS):
  Bottom-left : [Compare…/Compare(N)] [Import] [Delete All]
  Bottom-right : [Done]  (becomes [Cancel] while in compare mode)

Row content (matches MeasurementRowView.swift):
  Line 1 : location/"Measurement" (bold)  •  waveform icon (if snapshot)  •  HH:MM time
  Line 2 : N peaks  •  Ratio: X.XX (if available)  •  Decay: X.XXs (if available)
  Line 3 : notes, max 2 lines (if any)

Click a row    → opens MeasurementDetailDialog
Right-click    → context menu: Load into View | View Details | Export Measurement |
                 Export Spectrum | Export PDF Report | Delete
"""

import os
from datetime import datetime

from PyQt6 import QtCore, QtGui, QtWidgets

import measurement as M
import measurement_detail_dialog as MDD
import guitar_modes as GM
import guitar_type as GT


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resolve_guitar_type(s: str | None) -> GT.GuitarType:
    if s:
        try:
            return GT.GuitarType(s)
        except ValueError:
            pass
    return GT.GuitarType.CLASSICAL


def _tap_tone_ratio(m: M.TapToneMeasurement) -> float | None:
    if not m.peaks:
        return None
    try:
        gt = _resolve_guitar_type(m.guitar_type)
        pairs = [(p.frequency, p.magnitude) for p in m.peaks]
        idx_map = GM.GuitarMode.classify_all(pairs, gt)
        air = next(
            (m.peaks[i].frequency for i, mode in idx_map.items()
             if mode.normalized == GM.GuitarMode.AIR),
            None,
        )
        top = next(
            (m.peaks[i].frequency for i, mode in idx_map.items()
             if mode.normalized == GM.GuitarMode.TOP),
            None,
        )
        if air and top and air > 0:
            return top / air
    except Exception:
        pass
    return None


# ── Row widget — matches MeasurementRowView.swift ─────────────────────────────

class _MeasurementRow(QtWidgets.QWidget):
    """
    Full-row clickable widget (matches .contentShape(Rectangle()) in Swift).
      Line 1 : [bold location/"Measurement"] ··· [waveform?] [HH:MM] [›]
      Line 2 : [N peaks] [• Ratio: X.XX] [• Decay: X.XXs]
      Line 3 : [notes, word-wrapped]   (optional)

    Shows PointingHandCursor on hover (matches .onHover { NSCursor.pointingHand }).
    Emits clicked() when the left mouse button is released inside the widget.
    """

    clicked: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(
        self,
        m: M.TapToneMeasurement,
        compare_mode: bool = False,
        compare_selected: bool = False,
        compare_eligible: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._pressed = False

        if not compare_mode:
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Compare-mode circle icon + content in an HBox
        top_hbox = QtWidgets.QHBoxLayout()
        top_hbox.setSpacing(8)

        if compare_mode:
            circle = QtWidgets.QLabel("●" if compare_selected else "○")
            color = "#3478f6" if compare_selected else (
                "#888888" if compare_eligible else "#cccccc"
            )
            circle.setStyleSheet(f"color: {color}; font-size: 18px;")
            circle.setFixedWidth(22)
            top_hbox.addWidget(circle)

        content = QtWidgets.QVBoxLayout()
        content.setSpacing(3)

        # Line 1: location + waveform + time + chevron
        line1 = QtWidgets.QHBoxLayout()
        line1.setSpacing(6)

        loc = QtWidgets.QLabel(m.tap_location or "Measurement")
        loc.setStyleSheet("font-weight: bold; font-size: 13px;")
        loc.setWordWrap(True)
        line1.addWidget(loc)
        line1.addStretch()

        if m.spectrum_snapshot is not None:
            wave = QtWidgets.QLabel("〜")
            wave.setStyleSheet("color: #28a028; font-size: 11px;")
            wave.setToolTip("Has spectrum snapshot")
            line1.addWidget(wave)

        try:
            dt = datetime.fromisoformat(m.timestamp).astimezone()
            time_str = dt.strftime("%H:%M")
        except Exception:
            time_str = m.timestamp[11:16] if len(m.timestamp) >= 16 else ""
        time_lbl = QtWidgets.QLabel(time_str)
        time_lbl.setStyleSheet("color: #888888; font-size: 10px;")
        line1.addWidget(time_lbl)

        # Disclosure chevron — matches Image(systemName: "chevron.right") in Swift
        if not compare_mode:
            chevron = QtWidgets.QLabel("›")
            chevron.setStyleSheet("color: #888888; font-size: 13px;")
            line1.addWidget(chevron)

            # Ellipsis hint — transparent when idle, visible on hover to signal RMB menu
            # Matches Image(systemName: "ellipsis.circle").opacity(isHovered ? 1 : 0) in Swift
            # Always occupies space (no layout shift) — only color alpha changes.
            self._ellipsis_lbl = QtWidgets.QLabel("⋯")
            self._ellipsis_lbl.setStyleSheet("color: rgba(136,136,136,0); font-size: 11px;")
            line1.addWidget(self._ellipsis_lbl)
        else:
            self._ellipsis_lbl = None

        content.addLayout(line1)

        # Line 2: peaks • ratio • decay
        parts: list[str] = [f"{len(m.peaks)} peaks"]
        ratio = _tap_tone_ratio(m)
        if ratio is not None:
            parts.append(f"Ratio: {ratio:.2f}")
        if m.decay_time is not None:
            parts.append(f"Decay: {m.decay_time:.2f}s")
        meta = QtWidgets.QLabel("  •  ".join(parts))
        meta.setStyleSheet("color: #888888; font-size: 10px;")
        content.addWidget(meta)

        # Line 3: notes (word-wrapped, expands to fit)
        if m.notes:
            notes_lbl = QtWidgets.QLabel(m.notes)
            notes_lbl.setStyleSheet("color: #888888; font-size: 10px;")
            notes_lbl.setWordWrap(True)
            content.addWidget(notes_lbl)

        top_hbox.addLayout(content)
        layout.addLayout(top_hbox)

        if compare_mode and not compare_eligible:
            eff = QtWidgets.QGraphicsOpacityEffect(self)
            eff.setOpacity(0.4)
            self.setGraphicsEffect(eff)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._pressed and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed = False
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        else:
            self._pressed = False
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), QtGui.QColor(0, 0, 0, 10))
        self.setPalette(p)
        if self._ellipsis_lbl is not None:
            self._ellipsis_lbl.setStyleSheet("color: rgba(136,136,136,255); font-size: 11px;")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._pressed = False
        self.setAutoFillBackground(False)
        if self._ellipsis_lbl is not None:
            self._ellipsis_lbl.setStyleSheet("color: rgba(136,136,136,0); font-size: 11px;")
        super().leaveEvent(event)


# ── Main dialog ───────────────────────────────────────────────────────────────

class MeasurementsDialog(QtWidgets.QDialog):
    """
    Saved measurements list dialog matching MeasurementsListView.swift (macOS).

    Emits measurementSelected(TapToneMeasurement) when a measurement is loaded.
    """

    measurementSelected: QtCore.pyqtSignal = QtCore.pyqtSignal(object)
    comparisonRequested: QtCore.pyqtSignal = QtCore.pyqtSignal(object)  # list[TapToneMeasurement]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Saved Measurements")
        self.resize(640, 480)
        self.setMinimumSize(520, 340)

        self._measurements: list[M.TapToneMeasurement] = []
        self._compare_mode: bool = False
        self._compare_ids: set[str] = set()

        self._build_ui()
        self._refresh()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(6)

        # ── Count label ───────────────────────────────────────────────────────
        self._count_lbl = QtWidgets.QLabel()
        self._count_lbl.setStyleSheet("color: #888888; font-size: 10px;")
        root.addWidget(self._count_lbl)

        # ── List ──────────────────────────────────────────────────────────────
        self._list = QtWidgets.QListWidget()
        self._list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        self._list.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._list)

        # ── Empty state ───────────────────────────────────────────────────────
        self._empty_lbl = QtWidgets.QLabel(
            "No Saved Measurements\n\n"
            "Tap the guitar and click Save to store measurements for comparison."
        )
        self._empty_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #888888;")
        root.addWidget(self._empty_lbl)

        # ── Bottom button bar ─────────────────────────────────────────────────
        # Layout: [Compare…] [Import] [Delete All]  ···  [Done / Cancel]
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(6)

        self._compare_btn = QtWidgets.QPushButton("Compare…")
        self._compare_btn.setCheckable(False)
        self._compare_btn.setToolTip(
            "Select two or more measurements with spectrum snapshots to compare"
        )
        self._compare_btn.clicked.connect(self._on_compare_clicked)
        btn_row.addWidget(self._compare_btn)

        self._import_btn = QtWidgets.QPushButton("Import…")
        self._import_btn.setToolTip("Import a .json or .guitartap measurement file")
        self._import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(self._import_btn)

        self._delete_all_btn = QtWidgets.QPushButton("Delete All")
        self._delete_all_btn.setToolTip("Delete all saved measurements")
        self._delete_all_btn.clicked.connect(self._on_delete_all)
        btn_row.addWidget(self._delete_all_btn)

        btn_row.addStretch()

        self._done_btn = QtWidgets.QPushButton("Done")
        self._done_btn.setDefault(True)
        self._done_btn.clicked.connect(self._on_done)
        btn_row.addWidget(self._done_btn)

        root.addLayout(btn_row)

    # ── Data ─────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._measurements = M.load_all_measurements()
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        try:
            self._list.itemChanged.disconnect(self._on_item_check_changed)
        except (RuntimeError, TypeError):
            pass

        self._list.clear()

        has = bool(self._measurements)
        self._list.setVisible(has)
        self._empty_lbl.setVisible(not has)

        n = len(self._measurements)
        self._count_lbl.setText(
            f"Total: {n} measurement{'s' if n != 1 else ''}"
        )

        comparable = sum(1 for m in self._measurements if m.spectrum_snapshot is not None)
        self._compare_btn.setEnabled(
            comparable >= 2 if not self._compare_mode else True
        )
        self._import_btn.setEnabled(not self._compare_mode)
        self._delete_all_btn.setEnabled(has and not self._compare_mode)

        # Done ↔ Cancel
        self._done_btn.setText("Cancel" if self._compare_mode else "Done")

        for m in self._measurements:
            eligible = m.spectrum_snapshot is not None
            selected = m.id in self._compare_ids

            item = QtWidgets.QListWidgetItem()
            row = _MeasurementRow(
                m,
                compare_mode=self._compare_mode,
                compare_selected=selected,
                compare_eligible=eligible,
            )
            item.setSizeHint(row.sizeHint())

            if self._compare_mode:
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    QtCore.Qt.CheckState.Checked
                    if selected
                    else QtCore.Qt.CheckState.Unchecked
                )
                if not eligible:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)

            self._list.addItem(item)
            self._list.setItemWidget(item, row)

            # Full-row click opens details (matches .contentShape(Rectangle()) in Swift)
            if not self._compare_mode:
                m_captured = m
                row.clicked.connect(
                    lambda checked=False, m=m_captured: self._open_detail(m)
                )

        if self._compare_mode:
            self._list.itemChanged.connect(self._on_item_check_changed)

        self._update_compare_btn()

    def _selected_measurement(self) -> M.TapToneMeasurement | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._measurements):
            return self._measurements[row]
        return None

    def _update_compare_btn(self) -> None:
        if self._compare_mode:
            count = len(self._compare_ids)
            self._compare_btn.setText(f"Compare ({count})")
            self._compare_btn.setEnabled(count >= 2)
        else:
            comparable = sum(
                1 for m in self._measurements if m.spectrum_snapshot is not None
            )
            self._compare_btn.setText("Compare…")
            self._compare_btn.setEnabled(comparable >= 2)

    # ── Compare mode ─────────────────────────────────────────────────────────

    def _on_compare_clicked(self) -> None:
        if self._compare_mode:
            # Open comparison
            self._open_comparison()
        else:
            # Enter compare mode
            self._compare_mode = True
            self._compare_ids.clear()
            self._rebuild_list()

    def _on_item_check_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._measurements):
            m = self._measurements[row]
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                self._compare_ids.add(m.id)
            else:
                self._compare_ids.discard(m.id)
            self._update_compare_btn()
            self._rebuild_list()

    def _open_comparison(self) -> None:
        """Emit comparisonRequested and close — mirrors the loadComparison() call path in Swift.

        Only measurements with a spectrum_snapshot are included (mirrors the
        `filter { $0.spectrumSnapshot != nil }` guard in loadComparison()).
        """
        selected = [m for m in self._measurements if m.id in self._compare_ids]
        with_snapshots = [m for m in selected if m.spectrum_snapshot is not None]
        if len(with_snapshots) < 2:
            return
        self.comparisonRequested.emit(with_snapshots)
        self.accept()

    def _on_done(self) -> None:
        if self._compare_mode:
            # Cancel compare mode
            self._compare_mode = False
            self._compare_ids.clear()
            self._rebuild_list()
        else:
            self.accept()

    def _open_detail(self, m: M.TapToneMeasurement) -> None:
        dlg = MDD.MeasurementDetailDialog(m, self)
        dlg.measurementSelected.connect(self._load_from_detail)
        dlg.exec()

    def _load_from_detail(self, m: M.TapToneMeasurement) -> None:
        self.measurementSelected.emit(m)
        self.accept()

    # ── Context menu ─────────────────────────────────────────────────────────

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        row = self._list.row(item)
        if row < 0 or row >= len(self._measurements):
            return
        m = self._measurements[row]

        menu = QtWidgets.QMenu(self)

        load_act        = menu.addAction("Load into View")
        menu.addSeparator()
        details_act     = menu.addAction("View Details")
        export_act      = menu.addAction("Export Measurement…")
        export_spec_act = menu.addAction("Export Spectrum…")
        export_pdf_act  = menu.addAction("Export PDF Report…")
        menu.addSeparator()
        delete_act      = menu.addAction("Delete")

        action = menu.exec(self._list.mapToGlobal(pos))

        if action == load_act:
            self.measurementSelected.emit(m)
            self.accept()
        elif action == details_act:
            self._open_detail(m)
        elif action == export_act:
            self._export_json(m)
        elif action == export_spec_act:
            QtWidgets.QMessageBox.information(
                self,
                "Export Spectrum",
                "Spectrum image export is not yet implemented.",
            )
        elif action == export_pdf_act:
            self._export_pdf(m)
        elif action == delete_act:
            self._delete_measurement(m)

    # ── Export / delete ───────────────────────────────────────────────────────

    def _export_json(self, m: M.TapToneMeasurement) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Measurement",
            os.path.join(os.path.expanduser("~"), "Documents", m.base_filename + ".json"),
            "JSON files (*.json *.guitartap);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(M.export_measurement_json(m))
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _export_pdf(self, m: M.TapToneMeasurement) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            os.path.join(os.path.expanduser("~"), "Documents", m.base_filename + ".pdf"),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        try:
            M.export_pdf(m, None, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _delete_measurement(self, m: M.TapToneMeasurement) -> None:
        name = m.tap_location or "Measurement"
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete Measurement?")
        box.setText(f'Are you sure you want to delete "{name}"? This cannot be undone.')
        delete_btn = box.addButton("Delete", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() != delete_btn:
            return
        # Remove only the first occurrence matching this id. Using index rather than a
        # list comprehension ensures that if the same file was imported twice (producing
        # two entries with identical ids) only the intended entry is deleted.
        idx = next((i for i, x in enumerate(self._measurements) if x.id == m.id), None)
        if idx is not None:
            self._measurements.pop(idx)
        M.save_all_measurements(self._measurements)
        self._compare_ids.discard(m.id)
        self._rebuild_list()

    def _on_delete_all(self) -> None:
        if not self._measurements:
            return
        n = len(self._measurements)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete All Measurements?")
        box.setText(
            f"This will permanently delete all {n} saved measurement{'s' if n != 1 else ''}. "
            "This cannot be undone."
        )
        delete_btn = box.addButton("Delete All", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() != delete_btn:
            return
        self._measurements = []
        M.save_all_measurements([])
        self._compare_ids.clear()
        self._rebuild_list()

    def _on_import(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import Measurement",
            os.path.expanduser("~"),
            "Measurement files (*.json *.guitartap);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            imported = M.import_measurements_from_json(raw)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Import Error", str(exc))
            return

        existing_ids = {m.id for m in self._measurements}
        new_items = [m for m in imported if m.id not in existing_ids]
        self._measurements.extend(new_items)
        M.save_all_measurements(self._measurements)
        self._rebuild_list()

        skipped = len(imported) - len(new_items)

        if len(new_items) == 1:
            # Auto-load single imported measurement (matches Swift importFromFile behaviour)
            self.measurementSelected.emit(new_items[0])
            msg = "Successfully imported and loaded 1 measurement."
            if skipped:
                msg += f"\n{skipped} duplicate(s) skipped."
            QtWidgets.QMessageBox.information(self, "Import Successful", msg)
            self.accept()
        else:
            msg = f"Successfully imported {len(new_items)} measurements."
            if skipped:
                msg += f"\n{skipped} duplicate(s) skipped."
            QtWidgets.QMessageBox.information(self, "Import Successful", msg)
