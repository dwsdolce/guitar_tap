# @parity test/comparison
"""The chart's peak labels are the analyzer's to decide: none while a comparison is shown, and every peak it
labels, whatever the chart's range.

The analyzer decides — `chart_annotation_peaks` is None while comparing (CM26, the shared case, in all three) —
and Swift's view hands the chart `tap.chartAnnotationPeaks`; Python's chart labels read it too, so no path that
labels peaks can label one during a comparison, and a peak off the chart keeps its label for the plot's edge to
cut, as the results list's range does not decide it.
"""

from __future__ import annotations

import os
import sys

import pyqtgraph as pg
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtWidgets  # noqa: E402

from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode  # noqa: E402
from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402
from guitar_tap.views import peak_annotations  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class _StubAnalyzer:
    def __init__(self, mode: AnalysisDisplayMode, peaks: list) -> None:
        self.display_mode = mode
        self._peaks = peaks
        self.peak_annotation_offsets: dict = {}

    @property
    def chart_annotation_peaks(self):
        """As the analyzer's: none while comparing (the decision itself is CM26)."""
        return None if self.display_mode == AnalysisDisplayMode.COMPARISON else self._peaks

    def has_manual_override(self, _peak_id) -> bool:
        return False

    def effective_mode_label(self, _peak) -> str:
        return "Air"


def _labelled(mode: AnalysisDisplayMode, peaks: list) -> list:
    """The peaks the chart labels."""
    labels = peak_annotations.FftAnnotations(pg.PlotWidget())
    labels._analyzer = _StubAnalyzer(mode, peaks)
    labels._refresh_labels()
    return [d["peak_id"] for d in labels.annotations]


def _peak(frequency: float) -> ResonantPeak:
    return ResonantPeak(frequency=frequency, magnitude=-40.0, quality=10.0)


def test_peaks_are_labelled_outside_a_comparison():
    peak = _peak(100.0)
    assert _labelled(AnalysisDisplayMode.LIVE, [peak]) == [peak.id]


def test_no_peak_is_labelled_while_comparing():
    assert _labelled(AnalysisDisplayMode.COMPARISON, [_peak(100.0)]) == []


def test_every_peak_the_analyzer_labels_is_labelled_whatever_the_range():
    """The chart labels the analyzer's peaks, not the results list's — which lists the peaks in the chart's
    range only — so a pan that takes a peak off the chart leaves its label for the plot's edge to cut."""
    peaks = [_peak(100.0), _peak(5000.0)]
    assert _labelled(AnalysisDisplayMode.LIVE, peaks) == [p.id for p in peaks]
