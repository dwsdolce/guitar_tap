"""
MultiTapComparisonResultsView — Air / Top / Back peak frequency grid for multi-tap comparison.

Mirrors Swift MultiTapComparisonResultsView.swift.

Displays a table with one row per individual tap in a completed multi-tap guitar
sequence, plus a final bold "Averaged" row drawn from the analyzer's current peaks.
Each row shows a coloured circle (or square for the Averaged row) matching the
comparison palette, the tap label ("Tap 1", "Tap 2", …), and the resolved Air,
Top, and Back peak frequencies.  A '—' is shown when no peak was found for a mode.

Shown in TapAnalysisResultsView when analyzer.showing_multi_tap_comparison is True.

Mirrors Swift MultiTapComparisonResultsView (MultiTapComparisonResultsView.swift).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from models.tap_tone_measurement import TapEntry
    from models.resonant_peak import ResonantPeak


# Comparison palette — mirrors TapToneAnalyzer.comparisonPalette (Swift: [.blue, .orange, .green, .purple, .teal]).
# RGB tuples in 0–255 range.
_PALETTE: list[tuple[int, int, int]] = [
    (0,   122, 255),   # .blue
    (255, 149,   0),   # .orange
    (52,  199,  89),   # .green
    (175,  82, 222),   # .purple
    (90,  200, 250),   # .teal
]

# Averaged row color — mirrors Swift Color(red: 1.0, green: 0.85, blue: 0.0) (bold yellow).
_AVERAGED_COLOR: tuple[int, int, int] = (255, 217, 0)


class MultiTapComparisonResultsView(QtWidgets.QWidget):
    """Grid showing Air, Top, Back resonance frequencies for each tap + Averaged row.

    Displayed in the Analysis Results panel when showing_multi_tap_comparison is True.

    Mirrors Swift MultiTapComparisonResultsView (MultiTapComparisonResultsView.swift).
    """

    _COLUMN_MODES = ["Air", "Top", "Back"]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_tap_data(
        self,
        tap_entries: list[TapEntry],
        averaged_peaks: list[ResonantPeak],
        guitar_type: str | None,
    ) -> None:
        """Rebuild the grid from per-tap entries and the averaged peaks.

        Parameters
        ----------
        tap_entries:
            Ordered list of TapEntry objects from the most recent (or loaded)
            multi-tap guitar sequence.
        averaged_peaks:
            The analyzer's current peaks, which represent the averaged spectrum.
            Used to populate the final "Averaged" row.
        guitar_type:
            Active guitar type string (e.g. "steel_string") used for mode
            classification when a tap entry does not carry its own guitar type.

        Mirrors the SwiftUI view's ``tapEntries``, ``averagedPeaks``, and
        ``guitarType`` inputs.
        """
        self._rebuild(tap_entries, averaged_peaks, guitar_type)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Four columns: Tap label | Air | Top | Back
        self._table = QtWidgets.QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["Tap"] + self._COLUMN_MODES)
        # Stretch all columns to fill the available width.
        # Column 0 (label) gets a larger stretch factor so it takes more space
        # than each of the three equal-width frequency columns.
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setStretchLastSection(False)
        for col in range(1, 4):
            hdr.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Stretch)

        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        # Use caption-equivalent font size — mirrors Swift .font(.caption).
        caption_font = self._table.font()
        caption_font.setPointSize(10)
        self._table.setFont(caption_font)
        self._table.horizontalHeader().setFont(caption_font)
        self._table.setStyleSheet("QTableWidget { border: none; }")

        layout.addWidget(self._table)

    def _rebuild(
        self,
        tap_entries: list[TapEntry],
        averaged_peaks: list[ResonantPeak],
        guitar_type: str | None,
    ) -> None:
        from models.tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
        from models.guitar_mode import GuitarMode

        mode_for_col = {
            1: GuitarMode.AIR,
            2: GuitarMode.TOP,
            3: GuitarMode.BACK,
        }

        # Rows = one per tap + one Averaged row
        row_count = len(tap_entries) + 1
        self._table.setRowCount(row_count)

        # Per-tap rows
        for row, entry in enumerate(tap_entries):
            color_rgb = _PALETTE[row % len(_PALETTE)]
            label = f"Tap {entry.tap_index}"

            # Resolve peaks: filter entry.peaks to those in entry.selected_peak_ids.
            # Mirrors Swift: entry.peaks.filter { selectedIDs.contains($0.id) }
            selected_ids = set(entry.selected_peak_ids)
            selected_peaks = [p for p in entry.peaks if p.id in selected_ids]

            # Guitar type: entry's snapshot type takes priority, then fall back to analyzer type.
            # Mirrors Swift: entry.snapshot.guitarType ?? guitarType
            tap_guitar_type = (
                entry.snapshot.guitar_type if entry.snapshot.guitar_type else guitar_type
            )

            mode_freqs = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
                selected_peaks, tap_guitar_type
            )

            label_widget = self._make_label_cell(label, color_rgb, bold=False)
            self._table.setCellWidget(row, 0, label_widget)

            for col, mode in mode_for_col.items():
                freq = mode_freqs.get(mode)
                item = QtWidgets.QTableWidgetItem(self._freq_text(freq))
                item.setTextAlignment(int(QtCore.Qt.AlignmentFlag.AlignCenter))
                if freq is None:
                    item.setForeground(QtGui.QColor(150, 150, 150))
                self._table.setItem(row, col, item)

        # Averaged row — bold yellow indicator + semibold text.
        # Mirrors Swift: bold yellow Rectangle() + "Averaged" + semibold font weight.
        avg_row = len(tap_entries)
        avg_mode_freqs = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
            averaged_peaks, guitar_type
        )
        avg_label_widget = self._make_label_cell("Averaged", _AVERAGED_COLOR, bold=True)
        self._table.setCellWidget(avg_row, 0, avg_label_widget)

        for col, mode in mode_for_col.items():
            freq = avg_mode_freqs.get(mode)
            item = QtWidgets.QTableWidgetItem(self._freq_text(freq))
            item.setTextAlignment(int(QtCore.Qt.AlignmentFlag.AlignCenter))
            if freq is None:
                item.setForeground(QtGui.QColor(150, 150, 150))
            _f = item.font()
            _f.setBold(True)
            item.setFont(_f)
            self._table.setItem(avg_row, col, item)

        self._table.resizeRowsToContents()

    @staticmethod
    def _make_label_cell(
        label: str, color_rgb: tuple[int, int, int], bold: bool = False
    ) -> QtWidgets.QWidget:
        """Build a widget with a small coloured indicator and the tap label.

        Regular tap rows use a circle; the Averaged row uses a filled rectangle —
        mirrors Swift's Circle() vs Rectangle() shape for the averaged row.
        """
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.setSpacing(6)

        # Coloured indicator — circle for tap rows, rectangle for Averaged row.
        # Mirrors Swift: Circle().fill(color) vs Rectangle().fill(color).
        dot = QtWidgets.QLabel()
        dot.setFixedSize(10, 10)
        r, g, b = color_rgb
        border_radius = "0px" if bold else "5px"
        dot.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border-radius: {border_radius};"
        )

        text_label = QtWidgets.QLabel(label)
        text_label.setMinimumWidth(0)
        text_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        caption_font = text_label.font()
        caption_font.setPointSize(10)
        if bold:
            caption_font.setBold(True)
        text_label.setFont(caption_font)

        layout.addWidget(dot)
        layout.addWidget(text_label, 1)
        return widget

    @staticmethod
    def _freq_text(freq: float | None) -> str:
        """Format a frequency value as '123.4 Hz', or '—' when absent.

        Mirrors Swift MultiTapComparisonResultsView.frequencyText(_:).
        """
        if freq is None:
            return "\u2014"   # em dash
        return f"{freq:.1f} Hz"
