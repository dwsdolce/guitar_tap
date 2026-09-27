# @parity test/effective-peak-id
"""effective_xxx_peak_id: the identified material peak for a phase.

    effective_xxx_peak_id == selected_xxx_peak.id, or None before the phase finalises.

A single layer: there is no user-override tier (a wrong identification is fixed by redoing the
phase) and no separate auto-selected id. The view widens the chart axis from the identified peak's
own change channel (see test_display_range_expansion.py).

Twin of Swift GuitarTapTests/EffectivePeakIDTests.swift. All three directions tested: longitudinal,
cross, flc.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Shared fixture — one QApplication for the whole module
# ---------------------------------------------------------------------------

_APP: "QtWidgets.QApplication | None" = None


def _get_app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


def _make_sut():
    _get_app()
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer()


def _make_peak(peak_id: str):
    """Return a mock ResonantPeak with the given id."""
    peak = MagicMock()
    peak.id = peak_id
    return peak


# ---------------------------------------------------------------------------
# Longitudinal
# ---------------------------------------------------------------------------

class TestEffectiveLongitudinalPeakID:
    """effective_longitudinal_peak_id is the identified peak's id."""

    def test_selected_peak_middle_layer(self):
        """selected_longitudinal_peak.id is used when set."""
        sut = _make_sut()
        sut.selected_longitudinal_peak = _make_peak("phase-id")

        assert sut.effective_longitudinal_peak_id == "phase-id"

    def test_all_none(self):
        """Returns None before the phase finalises."""
        sut = _make_sut()
        sut.selected_longitudinal_peak = None

        assert sut.effective_longitudinal_peak_id is None


# ---------------------------------------------------------------------------
# Cross-grain
# ---------------------------------------------------------------------------

class TestEffectiveCrossPeakID:
    """effective_cross_peak_id is the identified peak's id."""

    def test_selected_peak_middle_layer(self):
        sut = _make_sut()
        sut.selected_cross_peak = _make_peak("phase-id")

        assert sut.effective_cross_peak_id == "phase-id"

    def test_all_none(self):
        sut = _make_sut()
        sut.selected_cross_peak = None

        assert sut.effective_cross_peak_id is None


# ---------------------------------------------------------------------------
# FLC
# ---------------------------------------------------------------------------

class TestEffectiveFlcPeakID:
    """effective_flc_peak_id is the identified peak's id."""

    def test_selected_peak_middle_layer(self):
        sut = _make_sut()
        sut.selected_flc_peak = _make_peak("phase-id")

        assert sut.effective_flc_peak_id == "phase-id"

    def test_all_none(self):
        sut = _make_sut()
        sut.selected_flc_peak = None

        assert sut.effective_flc_peak_id is None
