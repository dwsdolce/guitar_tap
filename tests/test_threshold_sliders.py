# @parity none — Python's threshold sliders hand the analyzer 0–100; it converts to dBFS before
# saving. Swift's and the web's sliders are bound in dBFS, and saving a threshold is MS22
# (test/mic-selection).
"""
The threshold sliders: the analyzer converts a slider's 0–100 to dBFS, and saves the dBFS value.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# The tap threshold slider
# ---------------------------------------------------------------------------

class TestTapThresholdSlider:
    """set_tap_threshold() saves the slider's value converted to dBFS."""

    def test_persists_converted_value(self):
        """Slider value 80 → dBFS −20; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "guitar_tap.models.tap_display_settings.TapDisplaySettings.set_tap_detection_threshold"
        ) as mock_set:
            sut.set_tap_threshold(80)
            mock_set.assert_called_once_with(-20.0)

    def test_persists_minimum_value(self):
        """Slider value 0 → dBFS −100; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "guitar_tap.models.tap_display_settings.TapDisplaySettings.set_tap_detection_threshold"
        ) as mock_set:
            sut.set_tap_threshold(0)
            mock_set.assert_called_once_with(-100.0)


# ---------------------------------------------------------------------------
# The Peak Min slider
# ---------------------------------------------------------------------------

class TestPeakMinSlider:
    """set_threshold() saves the slider's value converted to dBFS."""

    def test_persists_converted_value(self):
        """Slider value 60 → dBFS −40; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "guitar_tap.models.tap_display_settings.TapDisplaySettings.set_peak_min_threshold"
        ) as mock_set:
            sut.set_threshold(60)
            mock_set.assert_called_once_with(-40.0)

    def test_persists_maximum_slider(self):
        """Slider value 100 → dBFS 0; that converted value is persisted."""
        sut = _make_sut()

        with patch(
            "guitar_tap.models.tap_display_settings.TapDisplaySettings.set_peak_min_threshold"
        ) as mock_set:
            sut.set_threshold(100)
            mock_set.assert_called_once_with(0.0)
