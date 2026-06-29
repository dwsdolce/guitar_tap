"""Regression: peak annotations must be suppressed while a comparison overlay is shown.

Mirrors Swift, where the annotation layer is fed `annotationPeaks: isComparing ? nil`
(TapToneAnalysisView+SpectrumViews.swift) so no peak labels render during comparison.
Python gates this reactively at the source: FftAnnotations.update_annotation is a no-op
when the analyzer's display_mode is COMPARISON, so a stray annotationUpdate signal (e.g.
from cycling the annotation mode) cannot re-add labels that hide_annotations() removed.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pyqtgraph as pg
from PySide6 import QtWidgets

# Use the SAME AnalysisDisplayMode object that peak_annotations compares against. This
# codebase has two import styles (`models...` in app code vs `guitar_tap.models...` in
# tests); importing the enum off the SUT module avoids an enum-identity mismatch that
# would only exist under the test's import path, never in the running app.
from guitar_tap.views import peak_annotations as pa

AnalysisDisplayMode = pa.AnalysisDisplayMode
FftAnnotations = pa.FftAnnotations


@pytest.fixture(scope="module", autouse=True)
def _app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


class _StubAnalyzer:
    def __init__(self, mode: AnalysisDisplayMode) -> None:
        self.display_mode = mode
        self.peak_annotation_offsets: dict = {}


def _make_annotations(mode: AnalysisDisplayMode) -> FftAnnotations:
    return FftAnnotations(pg.PlotWidget(), analyzer=_StubAnalyzer(mode))


def test_update_annotation_draws_outside_comparison():
    ann = _make_annotations(AnalysisDisplayMode.LIVE)
    ann.update_annotation("p1", 100.0, -40.0, "<b>Air</b>", "Air")
    assert len(ann.annotations) == 1


def test_update_annotation_noop_in_comparison_mode():
    ann = _make_annotations(AnalysisDisplayMode.COMPARISON)
    ann.update_annotation("p1", 100.0, -40.0, "<b>Air</b>", "Air")
    assert ann.annotations == []