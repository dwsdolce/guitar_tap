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

from PySide6 import QtCore, QtGui, QtWidgets

from views import tap_analysis_results_view as M
from models import TapToneMeasurement
from views.measurements import measurement_detail_view as MDD
from views.measurements import edit_measurement_view as EMV
from views.measurements.measurement_row_view import MeasurementRowView


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

    @property
    def _measurements(self) -> "list[TapToneMeasurement]":
        """Live view of the analyzer's measurement list — the single source of truth."""
        return self._analyzer.savedMeasurements

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
                # Full-row click opens details (matches .contentShape(Rectangle()) in Swift)
                m_captured = m
                row.clicked.connect(
                    lambda checked=False, m=m_captured: self._open_detail(m)
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
        else:
            self._compare_indices.add(index)
        self._update_compare_btn()
        self._rebuild_list()

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
        dlg.measurementSelected.connect(self._load_from_detail)
        dlg.exec()

    def _open_edit(self, index: int, m: TapToneMeasurement) -> None:
        """Open EditMeasurementView for the measurement at the given index.

        Mirrors Swift .sheet { EditMeasurementView(index:measurement:analyzer:) }.
        Delegates persistence to analyzer.update_measurement() so that
        savedMeasurementsChanged is emitted and all observers are notified.
        """
        dlg = EMV.EditMeasurementView(index, m, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            tap_location, notes = dlg.edited_values()
            self._analyzer.update_measurement(index, tap_location, notes)

    def _load_from_detail(self, m: TapToneMeasurement) -> None:
        self.measurementSelected.emit(m)

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
        edit_act        = menu.addAction("Edit…")
        export_act      = menu.addAction("Export Measurement…")
        export_spec_act = menu.addAction("Export Spectrum…")
        export_pdf_act  = menu.addAction("Export PDF Report…")
        menu.addSeparator()
        delete_act      = menu.addAction("Delete")

        action = menu.exec(self._list.mapToGlobal(pos))

        if action == load_act:
            self.measurementSelected.emit(m)
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

    def _export_spectrum(self, m: TapToneMeasurement) -> None:
        """Export the spectrum PNG for *m* — mirrors Swift exportSpectrumMeasurement(_:).

        Routes to render_spectrum_image_for_comparison for comparison records and to
        render_spectrum_image_for_measurement for regular measurements.
        """
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Spectrum",
            os.path.join(M.last_export_dir(), m.base_filename + ".png"),
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
        """Route PDF export based on measurement type.

        Multi-tap guitar → two-page report (averaged + per-tap comparison).
        Saved-measurement comparison → single-page comparison report.
        All others → single-page averaged report.

        Mirrors Swift routing in MeasurementsListView.exportPDFReport(for:).
        """
        if m.tap_entries:
            self._export_multi_tap_pdf(m)
        elif m.is_comparison:
            self._export_comparison_pdf(m)
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export PDF Report",
                os.path.join(M.last_export_dir(), m.base_filename + ".pdf"),
                "PDF files (*.pdf)",
            )
            if not path:
                return
            M.update_export_dir(path)
            # Render spectrum image from the saved snapshot (mirrors Swift
            # renderSpectrumImageForMeasurement called from exportPDFReport).
            png_data = M.render_spectrum_image_for_measurement(m)
            try:
                # Mirrors Swift: PDFReportData.from(measurement:) → PDFReportGenerator.generate(data:)
                report_data = M.pdf_report_data_from_measurement(m, png_data)
                M.export_pdf(report_data, path)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _export_multi_tap_pdf(self, m: TapToneMeasurement) -> None:
        """Export a two-page multi-tap PDF report for a saved multi-tap measurement.

        Page 1 — averaged-result report.
        Page 2 — per-tap comparison report.

        Mirrors Swift exportMultiTapPDFReport(for:) in MeasurementsListView.swift.
        """
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Multi-Tap PDF Report",
            os.path.join(M.last_export_dir(), m.base_filename + ".pdf"),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        M.update_export_dir(path)

        avg_png_data = M.render_spectrum_image_for_measurement(m)
        cmp_png_data = M.render_spectrum_image_for_multi_tap(m)

        try:
            averaged_data = M.pdf_report_data_from_measurement(m, avg_png_data)

            # Build ComparisonPDFReportData from tap_entries + averaged row.
            from models.guitar_mode import GuitarMode
            from models.tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
            from models.tap_tone_measurement import ComparisonEntry
            from datetime import datetime, timezone
            import uuid as _uuid

            # Palette and avg color imported from the shared module-level constants — mirrors Swift's
            # TapToneAnalyzer.multiTapPalette / TapToneAnalyzer.multiTapAvgColor.
            _PALETTE = M.MULTI_TAP_PALETTE
            _AVERAGED_COLOR = M.MULTI_TAP_AVG_COLOR

            # Step 1 — Build cmp_entries (mirrors Swift's [ComparisonEntry] build step).
            # Colors are stored as RGBA 0.0–1.0 inside ComparisonEntry, mirroring Swift's
            # colorComponents: [Double].
            cmp_entries: list[ComparisonEntry] = []
            for idx, entry in enumerate(m.tap_entries):
                r, g, b = _PALETTE[idx % len(_PALETTE)]
                color_components = [r / 255.0, g / 255.0, b / 255.0, 1.0]
                sel_ids = set(entry.selected_peak_ids)
                sel_peaks = [p for p in entry.peaks if p.id in sel_ids]
                cmp_entries.append(ComparisonEntry(
                    id=str(_uuid.uuid4()),
                    label=f"Tap {entry.tap_index}",
                    color_components=color_components,
                    snapshot=entry.snapshot,
                    peaks=sel_peaks,
                    guitar_type=entry.snapshot.guitar_type if entry.snapshot else None,
                    source_measurement_id=None,
                ))
            # Averaged entry — mirrors Swift's avgSnap from measurement.spectrumSnapshot + peaks.
            avg_snap = m.spectrum_snapshot
            avg_guitar_type_str = avg_snap.guitar_type if avg_snap else None
            avg_all_peaks = m.peaks or []
            avg_sel_ids = set(m.selected_peak_ids or [p.id for p in avg_all_peaks])
            avg_sel_peaks = [p for p in avg_all_peaks if p.id in avg_sel_ids]
            if avg_snap is not None:
                avg_r, avg_g, avg_b = _AVERAGED_COLOR
                avg_color_components = [avg_r / 255.0, avg_g / 255.0, avg_b / 255.0, 1.0]
                cmp_entries.append(ComparisonEntry(
                    id=str(_uuid.uuid4()),
                    label="Averaged",
                    color_components=avg_color_components,
                    snapshot=avg_snap,
                    peaks=avg_sel_peaks,
                    guitar_type=avg_guitar_type_str,
                    source_measurement_id=None,
                ))

            # Step 2 — Map cmp_entries → mode_frequencies tuples (mirrors Swift's map step).
            # Colors are converted back to (r, g, b) 0–255 integers for the PDF renderer.
            mode_frequencies = []
            for cmp_entry in cmp_entries:
                c = cmp_entry.color_components
                color = (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))
                mode_freqs = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
                    cmp_entry.peaks, cmp_entry.guitar_type
                )
                mode_frequencies.append((
                    cmp_entry.label,
                    color,
                    mode_freqs.get(GuitarMode.AIR),
                    mode_freqs.get(GuitarMode.TOP),
                    mode_freqs.get(GuitarMode.BACK),
                ))

            comparison_data = M.ComparisonPDFReportData(
                timestamp=datetime.now(timezone.utc).isoformat(),
                comparison_label=m.tap_location or None,
                notes=m.notes or None,
                spectrum_image_data=cmp_png_data,
                # Pass cmp_entries so _build_comparison_story can derive the frequency range
                # metadata row from their snapshots.
                # Mirrors Swift cmpReportData(entries: cmpEntries) in exportMultiTapPDFReport(for:).
                entries=cmp_entries,
                mode_frequencies=mode_frequencies,
            )

            M.export_multi_tap_pdf(averaged_data, comparison_data, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _export_comparison_pdf(self, m: TapToneMeasurement) -> None:
        """Export a comparison PDF report — mirrors Swift's comparison PDF export path."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Comparison PDF Report",
            os.path.join(M.last_export_dir(), m.base_filename + ".pdf"),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        M.update_export_dir(path)
        png_data = M.render_spectrum_image_for_comparison(m)
        try:
            report_data = M.comparison_pdf_report_data_from_measurement(m, png_data)
            M.export_comparison_pdf(report_data, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Error", str(exc))

    def _delete_measurement(self, index: int, m: TapToneMeasurement) -> None:
        name = m.tap_location or "Measurement"
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
            # mirrors Swift importMeasurements(from: Data) — model owns decode+append
            imported = self._analyzer.import_measurements_from_data(data)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Import Error", str(exc))
            return

        if len(imported) == 1:
            # Auto-load single imported measurement (matches Swift importFromFile behaviour).
            # Suppress the standalone microphone warning so we can fold it into the success
            # message below — mirrors Swift's "Fold any microphone warning into the success
            # message so only one alert fires" comment in importFromFile(url:).
            main_view = self.parent()
            if main_view is not None:
                main_view._suppress_mic_warning = True
                main_view._pending_mic_warning = None
            self.measurementSelected.emit(imported[0])
            if main_view is not None:
                main_view._suppress_mic_warning = False
            msg = "Successfully imported and loaded 1 measurement."
            # Fold microphone warning into the success message (mirrors Swift).
            if main_view is not None and main_view._pending_mic_warning:
                msg += f"\n\n⚠️ {main_view._pending_mic_warning}"
                main_view._pending_mic_warning = None
            QtWidgets.QMessageBox.information(self, "Import Successful", msg)
        else:
            msg = f"Successfully imported {len(imported)} measurements."
            QtWidgets.QMessageBox.information(self, "Import Successful", msg)
