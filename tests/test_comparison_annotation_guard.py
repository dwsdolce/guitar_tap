# @parity test/comparison
"""No peak labels while a comparison is shown: the peaks model obeys the analyzer.

The analyzer decides — `chart_annotation_peaks` is None while comparing (CM26, the shared case, in
all three) — and Swift's view hands the chart `tap.chartAnnotationPeaks`; Python's peaks model,
which decides which peaks are labelled, reads it, so no path that labels peaks can label one during
a comparison.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtWidgets  # noqa: E402

from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode  # noqa: E402
from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode  # noqa: E402
from guitar_tap.models.guitar_mode import GuitarMode  # noqa: E402
from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402
from guitar_tap.views.shared.peaks_model import PeaksModel  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class _StubAnalyzer:
    def __init__(self, mode: AnalysisDisplayMode) -> None:
        self.display_mode = mode

    @property
    def chart_annotation_peaks(self):
        """As the analyzer's: none while comparing (the decision itself is CM26)."""
        return None if self.display_mode == AnalysisDisplayMode.COMPARISON else []

    def has_manual_override(self, _peak_id) -> bool:
        return False

    def effective_mode_label(self, _peak) -> str:
        return "Air"


def _labelled(mode: AnalysisDisplayMode) -> list:
    """The peaks the model labels, with every peak's label shown."""
    model = PeaksModel(np.zeros((0, 3)))
    model._analyzer = _StubAnalyzer(mode)
    model.annotation_mode = AnnotationVisibilityMode.ALL
    labelled: list = []
    model.annotationUpdate.connect(lambda peak_id, *_: labelled.append(peak_id))
    peak = ResonantPeak(frequency=100.0, magnitude=-40.0, quality=10.0)
    model.update_data_with_modes([(peak, GuitarMode.AIR)])
    model.refresh_annotations()
    return labelled


def test_peaks_are_labelled_outside_a_comparison():
    assert len(_labelled(AnalysisDisplayMode.LIVE)) == 2  # the update and the refresh


def test_no_peak_is_labelled_while_comparing():
    assert _labelled(AnalysisDisplayMode.COMPARISON) == []
