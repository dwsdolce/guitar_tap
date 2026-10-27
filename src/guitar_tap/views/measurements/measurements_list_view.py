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

from PySide6 import QtCore, QtWidgets

from guitar_tap.models import TapToneMeasurement
from guitar_tap.models.tap_tone_analyzer_measurement_management import ImportFile
from guitar_tap.models import saved_measurements_order as SMO
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS
from guitar_tap.views import tap_analysis_results_view as M
from guitar_tap.views.exportable_spectrum_chart import ExportRenderError
from guitar_tap.views.measurements import edit_measurement_view as EMV
from guitar_tap.views.measurements import measurement_detail_view as MDD
from guitar_tap.views.measurements.measurement_row_view import MeasurementRowView
from guitar_tap.views.measurements import export_menus, saved_measurement_menu
from guitar_tap.views.shared.empty_state_view import EmptyStateView
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
        # The width's minimum is the layout's — the action row's full width — so no button is ever squeezed; the
        # dialog opens at that width (set once the row is built), as Swift's sheet sizes itself to its toolbar.
        self.setMinimumHeight(340)
        palette.surface(self, palette.Role.BACKGROUND_PANEL)

        self._compare_mode: bool = False
        # What a select mode is ticking rows for — "delete" (Delete › Selected…) or "export" (the Export menu's
        # Export Selected…) — as compare mode ticks rows to compare; None when no select mode is on. Mirrors Swift
        # selectingFor.
        self._selecting_for: "str | None" = None
        self._selected_indices: set[int] = set()
        self._compare_indices: set[int] = set()  # mirrors Swift selectedCompareIndices: Set<Int>

        self._build_ui()
        self._rebuild_list()
        self.resize(self.minimumSizeHint().width(), 480)

        # Stay in sync if another part of the UI mutates the list while open.
        self._analyzer.savedMeasurementsChanged.connect(self._rebuild_list)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(6)

        # ── Count line: the total, or — while a filter is on — how many of how many, with an × ──
        # Sort & Filter: what the list shows and in what order; the library keeps its own order.
        self._sort = TDS.saved_measurements_sort()
        self._ascending = TDS.saved_measurements_ascending()
        self._filter = TDS.saved_measurements_filter()
        self._shown: list[int] = []
        count_row = QtWidgets.QHBoxLayout()
        count_row.setContentsMargins(0, 0, 0, 0)
        self._count_lbl = QtWidgets.QLabel()
        self._count_lbl.setStyleSheet("font-size: 10px;")
        palette.tag(self._count_lbl, color=palette.Role.TEXT_SECONDARY)
        count_row.addWidget(self._count_lbl)
        self._clear_filter_btn = QtWidgets.QToolButton()
        palette.set_icon(self._clear_filter_btn, "mdi.close-circle-outline", palette.Role.TEXT_SECONDARY)
        palette.tag(self._clear_filter_btn, icon=True)
        self._clear_filter_btn.setToolTip("Show all measurements")
        self._clear_filter_btn.clicked.connect(lambda: self._set_filter(None))
        count_row.addWidget(self._clear_filter_btn)
        count_row.addStretch()
        root.addLayout(count_row)

        # ── List ──────────────────────────────────────────────────────────────
        self._list = QtWidgets.QListWidget()
        # Plain rows on the panel, as Swift's List: no frame; each row draws its own line.
        self._list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        # No keyboard focus, so no row becomes the list's current item (some styles paint it).
        self._list.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._list.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._list)

        # ── Empty state ───────────────────────────────────────────────────────
        # Swift's EmptyStateView: the tray icon (the nearest Material Design icon), the title and the message.
        self._empty_lbl = EmptyStateView(
            icon="mdi.inbox-outline",
            title="No Saved Measurements",
            message="Tap the guitar and click Save to store measurements for comparison.",
        )
        root.addWidget(self._empty_lbl, 1)

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
        # The buttons carry Swift's toolbar icons (waveform.path, square.and.arrow.down / up,
        # trash).
        palette.set_icon(self._compare_btn, "mdi.waveform", palette.Role.TEXT_PRIMARY)
        btn_row.addWidget(self._compare_btn)

        # Sort & Filter — the sort (choosing the ticked one again reverses it, the arrow showing which way)
        # and the one type shown. Mirrors Swift SavedMeasurementsSortMenu.
        self._sort_btn = QtWidgets.QPushButton("Sort && Filter \u25BE")  # "&&": a single "&" marks a shortcut letter; ▾: a menu
        palette.set_icon(self._sort_btn, "mdi.filter-variant", palette.Role.TEXT_PRIMARY)
        self._sort_btn.setToolTip("Sort the list, or show one type of measurement")
        self._sort_btn.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0px; }")
        self._sort_menu = QtWidgets.QMenu(self._sort_btn)
        self._sort_menu.aboutToShow.connect(self._fill_sort_menu)
        self._sort_btn.setMenu(self._sort_menu)
        btn_row.addWidget(self._sort_btn)

        self._import_btn = QtWidgets.QPushButton("Import\u2026")
        palette.set_icon(self._import_btn, "mdi.download-outline", palette.Role.TEXT_PRIMARY)
        self._import_btn.setToolTip("Import measurements from one or more .guitartap or .json files")
        self._import_btn.clicked.connect(self._on_import)
        btn_row.addWidget(self._import_btn)

        # Export — a menu (export_menus.PANEL): Export All… and Export Selected… (tick the rows to export, as
        # Delete's Selected… does), each as one .guitartap file. Mirrors Swift's library menu.
        panel = export_menus.PANEL
        self._export_all_btn = QtWidgets.QPushButton(f"{panel.button} \u25BE")  # ▾: a menu
        palette.set_icon(self._export_all_btn, f"mdi.{panel.mdi}", palette.Role.TEXT_PRIMARY)
        self._export_all_btn.setToolTip("Export all the measurements, or the ones you select, as one .guitartap file")
        self._export_all_btn.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0px; }")
        export_menu = QtWidgets.QMenu(self._export_all_btn)
        panel_handlers = {"exportAll": self._export_all, "exportSelected": lambda: self._enter_select_mode("export")}
        for i, group in enumerate(panel.groups):
            if i:
                export_menu.addSeparator()
            for entry in group:
                palette.add_menu_item(export_menu, f"mdi.{entry.mdi}", entry.title, panel_handlers[entry.action])
        self._export_all_btn.setMenu(export_menu)
        btn_row.addWidget(self._export_all_btn)

        # Delete — a menu: All…, Duplicates… (disabled when there are none) and Selected… (tick the rows to delete,
        # as compare mode does). Mirrors Swift SavedMeasurementsDeleteMenu.
        self._delete_all_btn = QtWidgets.QPushButton("Delete \u25BE")  # ▾: a menu
        palette.set_icon(self._delete_all_btn, "mdi.trash-can-outline", palette.Role.TEXT_PRIMARY)
        self._delete_all_btn.setToolTip("Delete all measurements, the duplicates, or the ones you select")
        self._delete_all_btn.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0px; }")
        delete_menu = QtWidgets.QMenu(self._delete_all_btn)
        # Each item with its icon, as Swift's (trash, square.on.square, checkmark.circle).
        palette.add_menu_item(delete_menu, "mdi.trash-can-outline", "All…", self._on_delete_all)
        self._delete_duplicates_action = palette.add_menu_item(
            delete_menu, "mdi.content-copy", "Duplicates…", self._on_delete_duplicates)
        palette.add_menu_item(delete_menu, "mdi.check-circle-outline", "Selected…",
                              lambda: self._enter_select_mode("delete"))
        delete_menu.aboutToShow.connect(
            lambda: self._delete_duplicates_action.setEnabled(bool(self._analyzer.duplicate_measurement_indices)))
        self._delete_all_btn.setMenu(delete_menu)
        btn_row.addWidget(self._delete_all_btn)

        btn_row.addStretch()

        self._done_btn = QtWidgets.QPushButton("Done")
        self._done_btn.clicked.connect(self._on_done)
        btn_row.addWidget(self._done_btn)

        # No default button, as Swift's list: Done only closes (.cancellationAction) and the
        # others act on a click. A dialog makes every button auto-default, which draws the
        # focused one — Compare… — as the default; so none is.
        for btn in (self._compare_btn, self._sort_btn, self._import_btn, self._export_all_btn,
                    self._delete_all_btn, self._done_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
            # Never narrower than its label (a squeezed button cuts its text, the ▾ first): the dialog keeps the
            # row's width instead, and a relabel (Compare (n), Delete (n)) resizes the button.
            btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

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
        self._shown = SMO.shown(SMO.keys(self._measurements), self._sort, self._ascending, self._filter)
        if self._filter is not None:
            self._count_lbl.setText(f"Showing {len(self._shown)} of {n} · {self._filter}")
        else:
            self._count_lbl.setText(f"Total: {n} measurement{'s' if n != 1 else ''}")
        self._clear_filter_btn.setVisible(self._filter is not None)

        comparable = sum(
            1 for m in self._measurements
            if m.spectrum_snapshot is not None and not m.is_comparison
        )
        self._compare_btn.setEnabled(
            comparable >= 2 if not self._compare_mode else True
        )
        selecting = self._compare_mode or self._selecting_for is not None
        self._import_btn.setEnabled(not selecting)
        self._export_all_btn.setEnabled(has and not selecting)
        self._delete_all_btn.setEnabled(has and not selecting)

        # Done ↔ Cancel
        self._done_btn.setText("Cancel" if selecting else "Done")

        for idx in self._shown:
            m = self._measurements[idx]
            # Comparison records are never eligible for compare-mode selection.
            # Any measurement can be deleted or exported; only one with a spectrum can be compared.
            ticking = self._selecting_for is not None
            eligible = ticking or (m.spectrum_snapshot is not None and not m.is_comparison)
            selected = idx in (self._selected_indices if ticking else self._compare_indices)

            item = QtWidgets.QListWidgetItem()
            row = MeasurementRowView(
                m,
                compare_mode=self._compare_mode or ticking,
                compare_selected=selected,
                compare_eligible=eligible,
            )
            item.setSizeHint(row.sizeHint())

            if (self._compare_mode or ticking) and not eligible:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)

            self._list.addItem(item)
            self._list.setItemWidget(item, row)

            if ticking:
                row.clicked.connect(lambda checked=False, i=idx: self._toggle_selected(i))
            elif self._compare_mode:
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
        if self._selecting_for is not None:
            # The Compare button's place says Delete (n) or Export (n) while selecting, as Swift's toolbar.
            count = len(self._selected_indices)
            self._compare_btn.setText(f"{self._selecting_for.capitalize()} ({count})")
            self._compare_btn.setEnabled(count > 0)
        elif self._compare_mode:
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
        if self._selecting_for == "delete":
            self._confirm_delete_selected()
        elif self._selecting_for == "export":
            self._export_selected()
        elif self._compare_mode:
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

        self._refresh_row_tick(index, now_selected)

    def _refresh_row_tick(self, index: int, selected: bool) -> None:
        """In-place update of the row showing the library's ``index``: just its circle and the Compare (or Delete)
        button. Avoids _rebuild_list(), which would clear the QListWidget and reset the scroll position. The row is
        found by where the list shows it, which a sort or filter makes different from its place in the library."""
        if index in self._shown:
            item = self._list.item(self._shown.index(index))
            if item is not None:
                row = self._list.itemWidget(item)
                if isinstance(row, MeasurementRowView):
                    row.setCompareSelected(selected)
        self._update_compare_btn()

    # ── Selected…: Delete's and Export's / Duplicates… ───────────────────────

    def _enter_select_mode(self, purpose: str) -> None:
        """Start a select mode for ``purpose`` ("delete" or "export"), nothing ticked. Mirrors Swift
        startSelection(_:)."""
        self._selecting_for = purpose
        self._selected_indices.clear()
        self._rebuild_list()

    def _exit_select_mode(self) -> None:
        self._selecting_for = None
        self._selected_indices.clear()
        self._rebuild_list()

    def _toggle_selected(self, index: int) -> None:
        if index in self._selected_indices:
            self._selected_indices.discard(index)
        else:
            self._selected_indices.add(index)
        self._refresh_row_tick(index, index in self._selected_indices)

    def _confirm(self, title: str, text: str, action: str) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        yes = box.addButton(action, QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() == yes

    def _confirm_delete_selected(self) -> None:
        n = len(self._selected_indices)
        if n == 0:
            return
        if not self._confirm("Delete Selected Measurements?",
                             f"This will permanently delete {n} measurement{'s' if n != 1 else ''}. "
                             "This cannot be undone.", "Delete"):
            return
        doomed = set(self._selected_indices)
        self._selecting_for = None
        self._selected_indices.clear()
        self._compare_indices.clear()
        self._analyzer.delete_measurements(doomed)
        self._rebuild_list()

    def _on_delete_duplicates(self) -> None:
        n = len(self._analyzer.duplicate_measurement_indices)
        if n == 0:
            return
        if not self._confirm("Delete Duplicates?",
                             f"This will delete {n} duplicate measurement{'s' if n != 1 else ''}; "
                             "the first copy of each is kept.", "Delete"):
            return
        self._compare_indices.clear()
        self._analyzer.delete_duplicate_measurements()

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
        if self._selecting_for is not None:
            self._exit_select_mode()
        elif self._compare_mode:
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
        if row < 0 or row >= len(self._shown):
            return
        index = self._shown[row]  # the row's place in the library
        self._show_row_menu(self._measurements[index], index, self._list.mapToGlobal(pos))

    # ── Sort & Filter ─────────────────────────────────────────────────────────

    def _fill_sort_menu(self) -> None:
        """The menu's items, ticked as they stand, built as it opens."""
        menu = self._sort_menu
        menu.clear()
        # Section titles as greyed items, as Swift's and the web's menus show them — Qt's addSection drops the
        # title in a native macOS menu.
        def heading(text: str) -> None:
            menu.addAction(text).setEnabled(False)

        heading("Sort by")
        for key in SMO.SavedMeasurementsSort:
            ticked = key is self._sort
            title = f"{key.title}  {'↑' if self._ascending else '↓'}" if ticked else key.title
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(ticked)
            action.triggered.connect(lambda _c=False, k=key: self._choose_sort(k))
        menu.addSeparator()
        heading("Show")
        for title, value in [("All", None)] + [(t, t) for t in SMO.FILTER_TYPES]:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(value == self._filter)
            action.triggered.connect(lambda _c=False, v=value: self._set_filter(v))

    def _choose_sort(self, key: "SMO.SavedMeasurementsSort") -> None:
        """Choose a sort; choosing the ticked one again reverses it."""
        if key is self._sort:
            self._ascending = not self._ascending
        else:
            self._sort, self._ascending = key, True
        TDS.set_saved_measurements_sort(self._sort)
        TDS.set_saved_measurements_ascending(self._ascending)
        self._rebuild_list()

    def _set_filter(self, value: "str | None") -> None:
        """Show one type, or all (None). A measurement the filter hides cannot stay ticked for a comparison."""
        self._filter = value
        TDS.set_saved_measurements_filter(value)
        self._rebuild_list()
        self._compare_indices &= set(self._shown)
        self._selected_indices &= set(self._shown)
        self._update_compare_btn()

    def _show_row_menu(self, m: TapToneMeasurement, row: int, global_pos: QtCore.QPoint) -> None:
        """Build and exec the per-row action menu at ``global_pos``. Shared by the
        right-click handler and the row's ``⋯`` button (see MeasurementRowView)."""
        menu = QtWidgets.QMenu(self)

        # From its groups (saved_measurement_menu), a separator between them; the icons mirror Swift's SF Symbols,
        # in the menu's own colours. "&&" so Qt renders a literal ampersand instead of a mnemonic.
        handlers = {
            "load": lambda: self._load_and_close(m),
            "details": lambda: self._open_detail(m),
            "edit": lambda: self._open_edit(row, m),
            "exportMeasurement": lambda: self._export_json(m),
            "exportSpectrum": lambda: self._export_spectrum(m),
            "exportPDF": lambda: self._export_pdf(m),
            "delete": lambda: self._delete_measurement(row, m),
        }
        chosen: dict = {}
        for i, group in enumerate(saved_measurement_menu.GROUPS):
            if i:
                menu.addSeparator()
            for entry in group:
                act = palette.add_menu_item(menu, f"mdi.{entry.mdi}", entry.title.replace("&", "&&"))
                chosen[act] = handlers[entry.action]

        action = menu.exec(global_pos)
        if action in chosen:
            chosen[action]()

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
            QtWidgets.QMessageBox.warning(self, "Export Failed", M.export_failure_message(exc, path))

    def _export_all(self) -> None:
        """Export the whole library to a chosen `.guitartap` file — the same content as the
        internal saved_measurements.json, just written to an arbitrary location."""
        import time
        self._export_measurements(self._measurements, f"guitartap-library-{int(time.time())}", "Export All Measurements")

    def _export_selected(self) -> None:
        """Export the ticked measurements, in the library's order, to one chosen `.guitartap` file, and leave the
        select mode. Mirrors Swift confirmSelection(.export)."""
        import time
        chosen = [self._measurements[i] for i in sorted(self._selected_indices)]
        self._exit_select_mode()
        if len(chosen) == 1:
            # One measurement is named as its own Export Measurement… names it; several, neutrally.
            self._export_json(chosen[0])
        else:
            self._export_measurements(chosen, f"guitartap-measurements-{int(time.time())}", "Export Selected Measurements")

    def _export_measurements(self, measurements: "list[TapToneMeasurement]", stem: str, title: str) -> None:
        """Write ``measurements`` as one `.guitartap` file — the form Import reads back — where the user chooses,
        starting from ``stem``. Mirrors Swift deliverMeasurements(_:filename:as: .export)."""
        if not measurements:
            return
        default = os.path.join(M.last_export_dir(), f"{stem}.guitartap")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            title,
            default,
            "GuitarTap files (*.guitartap);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        M.update_export_dir(path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(M.measurements_to_json(measurements))
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Export Failed", M.export_failure_message(exc, path))

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
        try:
            if m.is_comparison:
                png_data = M.render_spectrum_image_for_comparison(m)
            else:
                png_data = M.render_spectrum_image_for_measurement(m)
        except ExportRenderError as exc:
            QtWidgets.QMessageBox.warning(self, "Export Failed", M.export_failure_message(exc, path))
            return
        if png_data is None:
            return
        try:
            with open(path, "wb") as f:
                f.write(png_data)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Export Failed", M.export_failure_message(exc, path))

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
            QtWidgets.QMessageBox.warning(self, "Export Failed", M.export_failure_message(exc, path))

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
        """Import the files chosen — one or several — and show the one message for them. The model imports, loads
        exactly one measurement imported in all, and words the message — mirrors Swift importFiles(_:). The main view
        follows a load by signal."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Import Measurements",
            M.last_export_dir(),
            "Measurement files (*.json *.guitartap);;All files (*)",
        )
        if not paths:
            return
        M.update_export_dir(paths[0])
        files = []
        for path in paths:
            try:
                with open(path, "rb") as f:
                    files.append(ImportFile(os.path.basename(path), f.read()))
            except OSError as exc:
                files.append(ImportFile(os.path.basename(path), exc))
        report = self._analyzer.import_files(files)
        if report.imported:
            QtWidgets.QMessageBox.information(self, "Import Successful", report.message)
        else:
            QtWidgets.QMessageBox.warning(self, "Import Error", report.message)
