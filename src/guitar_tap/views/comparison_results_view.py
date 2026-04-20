"""
ComparisonResultsView — Air / Top / Back peak frequency grid for comparison mode.

Mirrors Swift ComparisonResultsView.swift.

Displays a table with one row per compared spectrum (up to 5) and three
frequency columns (Air, Top, Back).  Each row shows a coloured dot matching
the spectrum's chart colour, the spectrum label, and the resolved peak
frequencies for each mode.  A '—' is shown when no peak was found for a mode.

Used in TapAnalysisResultsView when display_mode == COMPARISON.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    pass


class ComparisonResultsView(QtWidgets.QWidget):
    """Grid showing Air, Top, Back resonance frequencies for each comparison spectrum.

    Displayed in the Analysis Results panel when in comparison mode.

    Mirrors Swift ComparisonResultsView (ComparisonResultsView.swift).
    """

    # Columns shown in the table — mirrors Swift columns: [.air, .top, .back]
    _COLUMN_MODES = ["Air", "Top", "Back"]
    _COLUMN_WIDTH = 80   # pixels for each frequency column
    _LABEL_WIDTH  = 130  # pixels for the spectrum label column

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_comparison_data(self, comparison_data: list[dict]) -> None:
        """Update the grid from analyzer._comparison_data entries.

        Each entry must have keys: ``label`` (str), ``color`` (RGB tuple),
        ``peaks`` (list[ResonantPeak]), ``guitar_type`` (str|None).

        Mirrors the analogous binding in Swift ComparisonResultsView where
        spectra is read from TapToneAnalyzer.comparisonSpectra.
        """
        self._rebuild(comparison_data)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QtWidgets.QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            ["Spectrum"] + self._COLUMN_MODES
        )
        self._table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        for col in range(1, 4):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.Fixed
            )
            self._table.setColumnWidth(col, self._COLUMN_WIDTH)

        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        # Match surrounding panel's background.
        self._table.setStyleSheet("QTableWidget { border: none; }")

        layout.addWidget(self._table)

    def _rebuild(self, comparison_data: list[dict]) -> None:
        from models.tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
        from models.guitar_mode import GuitarMode

        # Map column index → GuitarMode for the three columns
        mode_for_col = {
            1: GuitarMode.AIR,
            2: GuitarMode.TOP,
            3: GuitarMode.BACK,
        }

        self._table.setRowCount(len(comparison_data))
        for row, entry in enumerate(comparison_data):
            label = entry.get("label", "")
            color_rgb = entry.get("color", (0, 122, 255))  # (r, g, b) 0–255
            peaks = entry.get("peaks", [])
            guitar_type = entry.get("guitar_type")

            mode_freqs = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
                peaks, guitar_type
            )

            # Column 0: coloured dot + label
            label_widget = self._make_label_cell(label, color_rgb)
            self._table.setCellWidget(row, 0, label_widget)

            # Columns 1–3: Air / Top / Back frequencies
            for col, mode in mode_for_col.items():
                freq = mode_freqs.get(mode)
                text = self._freq_text(freq)
                item = QtWidgets.QTableWidgetItem(text)
                item.setTextAlignment(
                    int(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                )
                if freq is None:
                    item.setForeground(QtGui.QColor(150, 150, 150))
                self._table.setItem(row, col, item)

        self._table.resizeRowsToContents()

    @staticmethod
    def _make_label_cell(label: str, color_rgb: tuple) -> QtWidgets.QWidget:
        """Build a widget with a small coloured circle dot and the spectrum label."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(6, 2, 4, 2)
        layout.setSpacing(6)

        # Coloured dot — a fixed-size QLabel with circular background.
        dot = QtWidgets.QLabel()
        dot.setFixedSize(10, 10)
        r, g, b = color_rgb
        dot.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border-radius: 5px;"
        )

        # Label text
        text_label = QtWidgets.QLabel(label)
        text_label.setMaximumWidth(200)

        layout.addWidget(dot)
        layout.addWidget(text_label, 1)
        return widget

    @staticmethod
    def _freq_text(freq: float | None) -> str:
        """Format a frequency value as '123.4 Hz', or '—' when absent.

        Mirrors Swift ComparisonResultsView.frequencyText(_:).
        """
        if freq is None:
            return "\u2014"   # em dash
        return f"{freq:.1f} Hz"
