"""
Dialog for listing, loading, comparing, and managing saved measurements.
Matches MeasurementsListView.swift — macOS layout.

Button layout (matches SwiftUI .cancellationAction / .primaryAction on macOS):
  Bottom-left : [Compare…/Compare(N)] [Import] [Delete All]
  Bottom-right : [Done]  (becomes [Cancel] while in compare mode)

Row content (matches MeasurementRowView.swift):
  Line 1 : measurementName/"Measurement" (bold)  •  waveform icon (if snapshot)  •  locale-aware short date+time
  Line 2 : N peaks  •  Ratio: X.XX (if available)  •  Decay: X.XXs (if available)
  Line 3 : notes, max 2 lines (if any)

Click a row    → opens MeasurementDetailDialog
Right-click    → context menu: Load into View | View Details | Edit Name & Notes |
                 Export Measurement | Export Spectrum | Export PDF Report | Delete
"""

# @parity view/measurements-list

import os

import qtawesome as qta
from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.models import TapToneMeasurement
from guitar_tap.views import tap_analysis_results_view as M
from guitar_tap.views.measurements import edit_measurement_view as EMV
from guitar_tap.views.measurements import measurement_detail_view as MDD
from guitar_tap.views.measurements.measurement_row_view import MeasurementRowView
from guitar_tap.views.utilities import palette

# ── Main dialog ───────────────────────────────────────────────────────────────

class MeasurementsDialog(QtWidgets.QDialog):
    """
    Saved measurements list dialog matching MeasurementsListView.swift (macOS).

    Emits measurementSelected(TapToneMeasurement) when a measurement is loaded.

    The ``analyzer`` is the single source of truth for the measurement list,
    mirroring the Swift sheet's access to the shared TapToneAnalyzer
    @EnvironmentObject.  All mutations go through analyzer methods so that
    ``savedMeasurementsChanged`` is emitted and any other observers are notified.
    """

    measurementSelected: QtCore.Signal = QtCore.Signal(object)
    comparisonRequested: QtCore.Signal = QtCore.Signal(object)  # list[TapToneMeasurement]

    def __init__(self, analyzer, parent=None) -> None:
        super().__init__(parent)
        self._analyzer = analyzer
        self.setWindowTitle("Saved Measurements")
        self.resize(640, 480)
        self.setMinimumSize(520, 340)

        self._compare_mode: bool = False
        self._compare_indices: set[int] = set()  # mirrors Swift selectedCompareIndices: Set<Int>

        self._build_ui()
        self._rebuild_list()

        # Stay in sync if another part of the UI mutates the list while open.
        self._analyzer.savedMeasurementsChanged.connect(self._rebuild_list)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(6)

        # ── Count label ───────────────────────────────────────────────────────
        self._count_lbl = QtWidgets.QLabel()
        self._count_lbl.setStyleSheet("font-size: 10px;")
        palette.tag(self._count_lbl, color=palette.Role.TEXT_SECONDARY)
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
        palette.tag(self._empty_lbl, color=palette.Role.TEXT_SECONDARY)
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
        self._import_btn.setToolTip("Import measurements from a .json or .guitartap file (one or many)")
        self._import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(self._import_btn)

        self._export_all_btn = QtWidgets.QPushButton("Export All")
        self._export_all_btn.setToolTip(
            "Export the whole library as one .guitartap file (backup / move to another machine)"
        )
        self._export_all_btn.clicked.connect(self._export_all)
        btn_row.addWidget(self._export_all_btn)

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

    @property
    def _measurements(self) -> "list[TapToneMeasurement]":
        """Live view of the analyzer's measurement list — the single source of truth."""
        return self._analyzer.saved_measurements

    def _rebuild_list(self) -> None:
        self._list.clear()

        has = bool(self._measurements)
        self._list.setVisible(has)
        self._empty_lbl.setVisible(not has)

        n = len(self._measurements)
        self._count_lbl.setText(
            f"Total: {n} measurement{'s' if n != 1 else ''}"
        )

        comparable = sum(
            1 for m in self._measurements
            if m.spectrum_snapshot is not None and not m.is_comparison
        )
        self._compare_btn.setEnabled(
            comparable >= 2 if not self._compare_mode else True
        )
        self._import_btn.setEnabled(not self._compare_mode)
        self._export_all_btn.setEnabled(has and not self._compare_mode)
        self._delete_all_btn.setEnabled(has and not self._compare_mode)

        # Done ↔ Cancel
        self._done_btn.setText("Cancel" if self._compare_mode else "Done")

        for idx, m in enumerate(self._measurements):
            # Comparison records are never eligible for compare-mode selection.
            eligible = m.spectrum_snapshot is not None and not m.is_comparison
            selected = idx in self._compare_indices  # index-based, mirrors Swift selectedCompareIndices

            item = QtWidgets.QListWidgetItem()
            row = MeasurementRowView(
                m,
                compare_mode=self._compare_mode,
                compare_selected=selected,
                compare_eligible=eligible,
            )
            item.setSizeHint(row.sizeHint())

            if self._compare_mode and not eligible:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)

            self._list.addItem(item)
            self._list.setItemWidget(item, row)

            if self._compare_mode:
                # Row click toggles selection by index, then rebuilds.
                # Using index (not m.id) so duplicate-imported measurements each
                # have an independent selection state — mirrors Swift toggleCompareSelection(at:for:).
                row.clicked.connect(
                    lambda checked=False, i=idx, meas=m: self._toggle_compare(i, meas)
                )
            else:
                # Single click does nothing in normal mode.
                # Double-click loads the measurement and closes the dialog —
                # mirrors Swift .onTapGesture(count: 2) { loadMeasurement; dismiss() }
                m_captured = m
                row.doubleClicked.connect(
                    lambda checked=False, m=m_captured: self._load_and_close(m)
                )
                # The "⋯" button opens the same per-row menu as right-click — the
                # web/touch affordance; right-click still works via the list menu.
                row.menuRequested.connect(
                    lambda gp, m=m_captured, r=idx: self._show_row_menu(m, r, gp)
                )

        self._update_compare_btn()

    def _update_compare_btn(self) -> None:
        if self._compare_mode:
            count = len(self._compare_indices)
            self._compare_btn.setText(f"Compare ({count})")
            self._compare_btn.setEnabled(count >= 2)
        else:
            comparable = sum(
                1 for m in self._measurements
                if m.spectrum_snapshot is not None and not m.is_comparison
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
            self._compare_indices.clear()
            self._rebuild_list()

    def _toggle_compare(self, index: int, m: "TapToneMeasurement") -> None:
        """Toggle the measurement at *index* in/out of the comparison set.

        Uses the list index (not m.id) so that duplicate-imported measurements
        — which share the same UUID — each have an independent selection state.
        Mirrors Swift toggleCompareSelection(at:for:).
        """
        if m.spectrum_snapshot is None or m.is_comparison:
            return
        if index in self._compare_indices:
            self._compare_indices.discard(index)
            now_selected = False
        else:
            self._compare_indices.add(index)
            now_selected = True

        # In-place update: just refresh the affected row's circle and the
        # Compare-button label/state. Avoids _rebuild_list(), which would
        # clear the QListWidget and reset the scroll position.
        item = self._list.item(index)
        if item is not None:
            row = self._list.itemWidget(item)
            if isinstance(row, MeasurementRowView):
                row.setCompareSelected(now_selected)
        self._update_compare_btn()

    def _open_comparison(self) -> None:
        """Emit comparisonRequested and close — mirrors the loadComparison() call path in Swift.

        Resolves selected indices to measurements in list order, then filters to
        those with a spectrum_snapshot — mirrors selectedCompareMeasurements + the
        `filter { $0.spectrumSnapshot != nil }` guard in loadComparison().
        """
        selected = [
            m for idx, m in enumerate(self._measurements)
            if idx in self._compare_indices and m.spectrum_snapshot is not None
        ]
        if len(selected) < 2:
            return
        self.comparisonRequested.emit(selected)
        self.accept()

    def _on_done(self) -> None:
        if self._compare_mode:
            # Cancel compare mode
            self._compare_mode = False
            self._compare_indices.clear()
            self._rebuild_list()
        else:
            self.accept()

    def _open_detail(self, m: TapToneMeasurement) -> None:
        dlg = MDD.MeasurementDetailDialog(m, self)
        dlg.exec()

    def _open_edit(self, index: int, m: TapToneMeasurement) -> None:
        """Open EditMeasurementView for the measurement at the given index.

        Mirrors Swift .sheet { EditMeasurementView(index:measurement:analyzer:) }.
        Delegates persistence to analyzer.update_measurement() so that
        savedMeasurementsChanged is emitted and all observers are notified.
        """
        dlg = EMV.EditMeasurementView(index, m, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            measurement_name, notes = dlg.edited_values()
            self._analyzer.update_measurement(index, measurement_name, notes)

    def _load_and_close(self, m: TapToneMeasurement) -> None:
        """Close the dialog, then emit measurementSelected.

        Mirrors Swift: dismiss first so the sheet is gone before
        loadMeasurement() sets @Published properties (including
        microphoneWarning).  The mic warning dialog then appears
        on the main view, not on the closing measurements dialog.
        """
        self.accept()
        self.measurementSelected.emit(m)

    # ── Context menu ─────────────────────────────────────────────────────────

    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        row = self._list.row(item)
        if row < 0 or row >= len(self._measurements):
            return
        self._show_row_menu(self._measurements[row], row, self._list.mapToGlobal(pos))

    def _show_row_menu(self, m: TapToneMeasurement, row: int, global_pos: QtCore.QPoint) -> None:
        """Build and exec the per-row action menu at ``global_pos``. Shared by the
        right-click handler and the row's ``⋯`` button (see MeasurementRowView)."""
        menu = QtWidgets.QMenu(self)

        # The qtawesome glyphs in text.primary so they read in either scheme. Icons mirror the
        # Swift SF Symbols on the same actions.
        c = palette.color(palette.Role.TEXT_PRIMARY)

        def _ico(name: str) -> QtGui.QIcon:
            return qta.icon(name, color=c)

        load_act        = menu.addAction(_ico("mdi.file-download-outline"), "Load into View")
        menu.addSeparator()
        details_act     = menu.addAction(_ico("mdi.eye-outline"), "View Details")
        # "&&" so Qt renders a literal ampersand instead of consuming it as a mnemonic.
        edit_act        = menu.addAction(_ico("mdi.pencil-outline"), "Edit Name && Notes")
        export_act      = menu.addAction(_ico("mdi.file-export-outline"), "Export Measurement")
        export_spec_act = menu.addAction(_ico("mdi.chart-line"), "Export Spectrum")
        export_pdf_act  = menu.addAction(_ico("mdi.file-pdf-box"), "Export PDF Report")
        menu.addSeparator()
        delete_act      = menu.addAction(_ico("mdi.trash-can-outline"), "Delete")

        action = menu.exec(global_pos)

        if action == load_act:
            self._load_and_close(m)
        elif action == details_act:
            self._open_detail(m)
        elif action == edit_act:
            self._open_edit(row, m)
        elif action == export_act:
            self._export_json(m)
        elif action == export_spec_act:
            self._export_spectrum(m)
        elif action == export_pdf_act:
            self._export_pdf(m)
        elif action == delete_act:
            self._delete_measurement(row, m)

    # ── Export / delete ───────────────────────────────────────────────────────

    def _export_json(self, m: TapToneMeasurement) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Measurement",
            os.path.join(M.last_export_dir(), m.base_filename + ".guitartap"),
            "GuitarTap files (*.guitartap);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        M.update_export_dir(path)
        try:
            text = M.export_measurement_json(m)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _export_all(self) -> None:
        """Export the whole library to a chosen `.guitartap` file — the same content as the
        internal saved_measurements.json, just written to an arbitrary location."""
        if not self._measurements:
            return
        import time
        default = os.path.join(
            M.last_export_dir(), f"guitartap-library-{int(time.time())}.guitartap"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export All Measurements",
            default,
            "GuitarTap files (*.guitartap);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        M.update_export_dir(path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(M.measurements_to_json(self._measurements))
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _export_spectrum(self, m: TapToneMeasurement) -> None:
        """Export the spectrum PNG for *m* — mirrors Swift exportSpectrumMeasurement(_:).

        Routes to render_spectrum_image_for_comparison for comparison records and to
        render_spectrum_image_for_measurement for regular measurements.
        """
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Spectrum",
            os.path.join(M.last_export_dir(), m.export_stem_for("spectrum") + ".png"),
            "PNG images (*.png)",
        )
        if not path:
            return
        if not path.endswith(".png"):
            path += ".png"
        M.update_export_dir(path)
        if m.is_comparison:
            png_data = M.render_spectrum_image_for_comparison(m)
        else:
            png_data = M.render_spectrum_image_for_measurement(m)
        if png_data is None:
            QtWidgets.QMessageBox.warning(self, "Export Error", "This measurement has no spectrum snapshot.")
            return
        try:
            with open(path, "wb") as f:
                f.write(png_data)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _export_pdf(self, m: TapToneMeasurement) -> None:
        """Export the measurement's PDF report (``export_report_for_measurement`` picks the report for
        its kind). Mirrors Swift MeasurementsListView.exportPDFReport(for:)."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            os.path.join(M.last_export_dir(), M.report_basename(m) + ".pdf"),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        M.update_export_dir(path)
        try:
            M.export_report_for_measurement(m, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _delete_measurement(self, index: int, m: TapToneMeasurement) -> None:
        name = m.measurement_name or "Measurement"
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete Measurement?")
        box.setText(f'Are you sure you want to delete "{name}"? This cannot be undone.')
        delete_btn = box.addButton("Delete", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() != delete_btn:
            return
        # Use the positional index captured at render time rather than searching by id.
        # This mirrors Swift's deleteMeasurement(at:) approach: duplicate imports share
        # the same id, so only the specific entry at `index` should be removed.
        self._analyzer.delete_measurement(index)
        # Remove the deleted index and shift down any higher indices so the set
        # stays consistent with the new array positions after deletion.
        self._compare_indices = {
            i - 1 if i > index else i
            for i in self._compare_indices
            if i != index
        }

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
        self._compare_indices.clear()
        self._analyzer.delete_all_measurements()

    def _on_import(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import Measurement",
            M.last_export_dir(),
            "Measurement files (*.json *.guitartap);;All files (*)",
        )
        if not path:
            return
        M.update_export_dir(path)
        try:
            with open(path, "rb") as f:
                data = f.read()
            # The model imports, loads a single measurement, and words the message — mirrors
            # Swift importAndLoadMeasurements(from:). The main view follows the load by signal.
            msg = self._analyzer.import_and_load_measurements(data)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Import Error", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Import Successful", msg)
