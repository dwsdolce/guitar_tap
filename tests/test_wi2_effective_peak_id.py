"""
WI-2 — effectiveXxxPeakID three-layer resolution tests (D1).

Verifies that each effective_xxx_peak_id property consults the middle layer
(selected_xxx_peak.id) when no user override is set, mirroring the Swift
three-layer cascade:
    userSelectedXxxPeakID ?? selectedXxxPeak?.id ?? autoSelectedXxxPeakID

Priority order (highest → lowest):
    1. user_selected_xxx_peak_id   — explicit user tap on results panel
    2. selected_xxx_peak.id        — peak stored when phase finalises
    3. auto_selected_xxx_peak_id   — HPS intermediate result

All three directions tested: longitudinal, cross, flc.
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

    def test_user_override_wins(self):
        """Layer 1: user_selected_longitudinal_peak_id takes priority over everything."""
        sut = _make_sut()
        sut.user_selected_longitudinal_peak_id = "user-id"
        sut.selected_longitudinal_peak = _make_peak("phase-id")
        sut.auto_selected_longitudinal_peak_id = "auto-id"

        assert sut.effective_longitudinal_peak_id == "user-id"

    def test_selected_peak_middle_layer(self):
        """Layer 2: selected_longitudinal_peak.id used when no user override."""
        sut = _make_sut()
        sut.user_selected_longitudinal_peak_id = None
        sut.selected_longitudinal_peak = _make_peak("phase-id")
        sut.auto_selected_longitudinal_peak_id = "auto-id"

        assert sut.effective_longitudinal_peak_id == "phase-id"

    def test_auto_fallback(self):
        """Layer 3: auto_selected_longitudinal_peak_id used when no override or phase peak."""
        sut = _make_sut()
        sut.user_selected_longitudinal_peak_id = None
        sut.selected_longitudinal_peak = None
        sut.auto_selected_longitudinal_peak_id = "auto-id"

        assert sut.effective_longitudinal_peak_id == "auto-id"

    def test_all_none(self):
        """Returns None when all three layers are unset."""
        sut = _make_sut()
        sut.user_selected_longitudinal_peak_id = None
        sut.selected_longitudinal_peak = None
        sut.auto_selected_longitudinal_peak_id = None

        assert sut.effective_longitudinal_peak_id is None


# ---------------------------------------------------------------------------
# Cross-grain
# ---------------------------------------------------------------------------

class TestEffectiveCrossPeakID:
    """Three-layer resolution for effective_cross_peak_id."""

    def test_user_override_wins(self):
        sut = _make_sut()
        sut.user_selected_cross_peak_id = "user-id"
        sut.selected_cross_peak = _make_peak("phase-id")
        sut.auto_selected_cross_peak_id = "auto-id"

        assert sut.effective_cross_peak_id == "user-id"

    def test_selected_peak_middle_layer(self):
        sut = _make_sut()
        sut.user_selected_cross_peak_id = None
        sut.selected_cross_peak = _make_peak("phase-id")
        sut.auto_selected_cross_peak_id = "auto-id"

        assert sut.effective_cross_peak_id == "phase-id"

    def test_auto_fallback(self):
        sut = _make_sut()
        sut.user_selected_cross_peak_id = None
        sut.selected_cross_peak = None
        sut.auto_selected_cross_peak_id = "auto-id"

        assert sut.effective_cross_peak_id == "auto-id"

    def test_all_none(self):
        sut = _make_sut()
        sut.user_selected_cross_peak_id = None
        sut.selected_cross_peak = None
        sut.auto_selected_cross_peak_id = None

        assert sut.effective_cross_peak_id is None


# ---------------------------------------------------------------------------
# FLC
# ---------------------------------------------------------------------------

class TestEffectiveFlcPeakID:
    """Three-layer resolution for effective_flc_peak_id."""

    def test_user_override_wins(self):
        sut = _make_sut()
        sut.user_selected_flc_peak_id = "user-id"
        sut.selected_flc_peak = _make_peak("phase-id")
        sut.auto_selected_flc_peak_id = "auto-id"

        assert sut.effective_flc_peak_id == "user-id"

    def test_selected_peak_middle_layer(self):
        sut = _make_sut()
        sut.user_selected_flc_peak_id = None
        sut.selected_flc_peak = _make_peak("phase-id")
        sut.auto_selected_flc_peak_id = "auto-id"

        assert sut.effective_flc_peak_id == "phase-id"

    def test_auto_fallback(self):
        sut = _make_sut()
        sut.user_selected_flc_peak_id = None
        sut.selected_flc_peak = None
        sut.auto_selected_flc_peak_id = "auto-id"

        assert sut.effective_flc_peak_id == "auto-id"

    def test_all_none(self):
        sut = _make_sut()
        sut.user_selected_flc_peak_id = None
        sut.selected_flc_peak = None
        sut.auto_selected_flc_peak_id = None

        assert sut.effective_flc_peak_id is None
