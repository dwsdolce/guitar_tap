# @parity test/effective-peak-id
"""WI-2 — effective_xxx_peak_id: the identified material peak for a phase.

    effective_xxx_peak_id == selected_xxx_peak.id, or None before the phase finalises.

This was a THREE-layer resolution until 2026-09-20, and both extra layers are gone:

  - a user-override tier, set by L / C / FLC buttons on each peak row. The buttons were removed on
    2026-04-17 and replaced by redoing the phase; the model outlived them by five months. Its three
    ``test_user_override_wins`` tests went with it.
  - ``auto_selected_xxx_peak_id``, which was UNREACHABLE: it and the selected peak are assigned on
    adjacent lines in the phase handlers, and the selected one is never None when the auto id is
    set. Its three ``test_auto_fallback`` tests went with it.

The auto attributes THEMSELVES stay — they are the change channel the view rides to widen the chart
axis onto a newly identified peak (see test_display_range_expansion.py).

Twin of Swift GuitarTapTests/EffectivePeakIDTests.swift. This was an untagged, Python-only file
until 2026-09-20 (project issue #8), while Swift used effectiveLongitudinalPeakID in five
production files with no test at all. All three directions tested: longitudinal, cross, flc.
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
    """Three-layer resolution for effective_longitudinal_peak_id."""

    def test_selected_peak_middle_layer(self):
        """Layer 2: selected_longitudinal_peak.id used when set."""
        sut = _make_sut()
        sut.selected_longitudinal_peak = _make_peak("phase-id")
        sut.auto_selected_longitudinal_peak_id = "auto-id"

        assert sut.effective_longitudinal_peak_id == "phase-id"

    def test_all_none(self):
        """Returns None when all three layers are unset."""
        sut = _make_sut()
        sut.selected_longitudinal_peak = None
        sut.auto_selected_longitudinal_peak_id = None

        assert sut.effective_longitudinal_peak_id is None


# ---------------------------------------------------------------------------
# Cross-grain
# ---------------------------------------------------------------------------

class TestEffectiveCrossPeakID:
    """Three-layer resolution for effective_cross_peak_id."""

    def test_selected_peak_middle_layer(self):
        sut = _make_sut()
        sut.selected_cross_peak = _make_peak("phase-id")
        sut.auto_selected_cross_peak_id = "auto-id"

        assert sut.effective_cross_peak_id == "phase-id"

    def test_all_none(self):
        sut = _make_sut()
        sut.selected_cross_peak = None
        sut.auto_selected_cross_peak_id = None

        assert sut.effective_cross_peak_id is None


# ---------------------------------------------------------------------------
# FLC
# ---------------------------------------------------------------------------

class TestEffectiveFlcPeakID:
    """Three-layer resolution for effective_flc_peak_id."""

    def test_selected_peak_middle_layer(self):
        sut = _make_sut()
        sut.selected_flc_peak = _make_peak("phase-id")
        sut.auto_selected_flc_peak_id = "auto-id"

        assert sut.effective_flc_peak_id == "phase-id"

    def test_all_none(self):
        sut = _make_sut()
        sut.selected_flc_peak = None
        sut.auto_selected_flc_peak_id = None

        assert sut.effective_flc_peak_id is None
