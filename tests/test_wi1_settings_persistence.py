"""
WI-1 — Settings persistence tests (D2, D3, D4, D5).

Verifies that each setter on TapToneAnalyzer / TapToneAnalyzerControlMixin
calls the corresponding TapDisplaySettings classmethod so that the new value
is persisted to QSettings.

These tests mock TapDisplaySettings at the call site so that no real QSettings
file is written during the test run.

Mirrors the WI-1 fix in:
  - models/tap_tone_analyzer.py          cycle_annotation_visibility (D2)
  - models/tap_tone_analyzer_control.py  set_tap_threshold  (D3)
                                         set_hysteresis_margin (D4)
                                         set_threshold      (D5)
"""

from __future__ import annotations

import sys
import os
from unittest.mock import patch, call

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode


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


# ---------------------------------------------------------------------------
# D2 — cycle_annotation_visibility persists mode
# ---------------------------------------------------------------------------

class TestD2CycleAnnotationVisibilityPersists:
    """D2: cycle_annotation_visibility() must call TapDisplaySettings.set_annotation_visibility_mode
    with the new mode so the value survives a restart."""

    def test_persists_after_first_cycle(self):
        """Cycling once (ALL → SELECTED) persists SELECTED."""
        sut = _make_sut()
        sut.annotation_visibility_mode = AnnotationVisibilityMode.ALL

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_annotation_visibility_mode"
        ) as mock_set:
            sut.cycle_annotation_visibility()
            mock_set.assert_called_once_with(AnnotationVisibilityMode.SELECTED)

    def test_persists_after_second_cycle(self):
        """Cycling twice (ALL → SELECTED → NONE) persists NONE."""
        sut = _make_sut()
        sut.annotation_visibility_mode = AnnotationVisibilityMode.ALL

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_annotation_visibility_mode"
        ) as mock_set:
            sut.cycle_annotation_visibility()
            sut.cycle_annotation_visibility()
            assert mock_set.call_count == 2
            assert mock_set.call_args_list[-1] == call(AnnotationVisibilityMode.NONE)

    def test_persists_wrap_around(self):
        """Cycling from NONE wraps to ALL and persists ALL."""
        sut = _make_sut()
        sut.annotation_visibility_mode = AnnotationVisibilityMode.NONE

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_annotation_visibility_mode"
        ) as mock_set:
            sut.cycle_annotation_visibility()
            mock_set.assert_called_once_with(AnnotationVisibilityMode.ALL)


# ---------------------------------------------------------------------------
# D3 — set_tap_threshold persists tap_detection_threshold
# ---------------------------------------------------------------------------

class TestD3SetTapThresholdPersists:
    """D3: set_tap_threshold() must call TapDisplaySettings.set_tap_detection_threshold
    with the converted dBFS value."""

    def test_persists_converted_value(self):
        """Slider value 80 → dBFS −20; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_tap_detection_threshold"
        ) as mock_set:
            sut.set_tap_threshold(80)
            mock_set.assert_called_once_with(-20.0)

    def test_persists_minimum_value(self):
        """Slider value 0 → dBFS −100; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_tap_detection_threshold"
        ) as mock_set:
            sut.set_tap_threshold(0)
            mock_set.assert_called_once_with(-100.0)


# ---------------------------------------------------------------------------
# D4 — set_hysteresis_margin persists hysteresis_margin
# ---------------------------------------------------------------------------

class TestD4SetHysteresisMarginPersists:
    """D4: set_hysteresis_margin() must call TapDisplaySettings.set_hysteresis_margin
    with the new value."""

    def test_persists_value(self):
        sut = _make_sut()

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_hysteresis_margin"
        ) as mock_set:
            sut.set_hysteresis_margin(8.0)
            mock_set.assert_called_once_with(8.0)

    def test_persists_float_coercion(self):
        """Integer argument is coerced to float before persisting."""
        sut = _make_sut()

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_hysteresis_margin"
        ) as mock_set:
            sut.set_hysteresis_margin(6)
            mock_set.assert_called_once_with(6.0)


# ---------------------------------------------------------------------------
# D5 — set_threshold persists peak_threshold
# ---------------------------------------------------------------------------

class TestD5SetThresholdPersists:
    """D5: set_threshold() must call TapDisplaySettings.set_peak_threshold
    with the converted dBFS value."""

    def test_persists_converted_value(self):
        """Slider value 60 → dBFS −40; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_peak_threshold"
        ) as mock_set:
            sut.set_threshold(60)
            mock_set.assert_called_once_with(-40.0)

    def test_persists_maximum_slider(self):
        """Slider value 100 → dBFS 0; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "models.tap_display_settings.TapDisplaySettings.set_peak_threshold"
        ) as mock_set:
            sut.set_threshold(100)
            mock_set.assert_called_once_with(0.0)
