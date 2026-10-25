# @parity model/detected-peaks tests=test/detected-peaks
"""
DetectedPeaks — the detected peaks: all of them, their Peak Min projection, their modes and which are selected.

Owned by ``TapToneAnalyzer`` as ``peaks``, which reads and writes them through its own ``all_peaks``,
``peaks_above_peak_min``, ``identified_modes`` and ``selected_peak_ids``. While a sequence waits for a tap they
are found again on every live frame, several times a second; once a measurement completes they are its peaks.
They are an object of their own so that only what shows peaks hears of them — the chart's markers and labels,
the Results list and the controls that need peaks. Announced by the analyzer, every frame would reach every
view that listens to the analyzer.

Mirrors Swift ``DetectedPeaks`` (Models/DetectedPeaks.swift) and web ``DetectedPeaks``.
"""

from __future__ import annotations

from PySide6 import QtCore


class DetectedPeaks(QtCore.QObject):
    """The detected peaks. Mirrors Swift ``DetectedPeaks``."""

    # The peaks to show (list[ResonantPeak]), announced whenever they change. Swift's objectWillChange.
    peaksChanged: QtCore.Signal = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        # Every peak found, down to the detection floor, regardless of Peak Min. Swift ``allPeaks``.
        self.all_peaks: list = []
        # ``all_peaks`` with Peak Min applied — set by the analyzer, which owns Peak Min.
        # Swift ``peaksAbovePeakMin``.
        self.peaks_above_peak_min: list = []
        # Each peak paired with the mode it is classified as. Swift ``identifiedModes``.
        self.identified_modes: list = []
        # The peaks the user has marked as significant. Swift ``selectedPeakIDs``.
        self.selected_peak_ids: set = set()
