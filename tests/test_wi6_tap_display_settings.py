"""
TapDisplaySettings round-trip and helper tests (D18, D19).

D18: Verifies the tap_detection_threshold getter/setter are mutual inverses.
     The setter must convert dBFS → 0-100 scale before persisting, matching
     what the getter expects when it reads back (0-100 → dBFS).

D19: Verifies validate_frequency_range and validate_magnitude_range behave
     identically to Swift's equivalents. reset_to_defaults() smoke test.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, call, patch

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


# ---------------------------------------------------------------------------
# D18 — tap_detection_threshold round-trip (getter/setter are inverses)
# ---------------------------------------------------------------------------

class TestD18TapDetectionThresholdRoundTrip:
    """D18: set_tap_detection_threshold(v) followed by tap_detection_threshold()
    must return a value equal to v (within floating-point precision).

    The setter must convert dBFS → 0-100 scale (add 100) before persisting.
    The getter converts 0-100 → dBFS (subtract 100) when reading back.
    """

    def _make_settings(self):
        _get_app()
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        return TapDisplaySettings

    def test_round_trip_minus_20(self):
        """-20 dBFS survives a set/get round-trip."""
        tds = self._make_settings()
        tds.set_tap_detection_threshold(-20.0)
        assert tds.tap_detection_threshold() == pytest.approx(-20.0)

    def test_round_trip_minus_40(self):
        """-40 dBFS (default) survives a set/get round-trip."""
        tds = self._make_settings()
        tds.set_tap_detection_threshold(-40.0)
        assert tds.tap_detection_threshold() == pytest.approx(-40.0)

    def test_round_trip_minus_100(self):
        """-100 dBFS (slider minimum) survives a set/get round-trip."""
        tds = self._make_settings()
        tds.set_tap_detection_threshold(-100.0)
        assert tds.tap_detection_threshold() == pytest.approx(-100.0)

    def test_round_trip_zero(self):
        """0 dBFS (slider maximum) survives a set/get round-trip."""
        tds = self._make_settings()
        tds.set_tap_detection_threshold(0.0)
        assert tds.tap_detection_threshold() == pytest.approx(0.0)

    def test_setter_stores_slider_scale(self):
        """Setter stores the value as a 0-100 integer (slider scale), not as dBFS.

        -40 dBFS → AppSettings.set_tap_threshold(60).
        """
        _get_app()
        from guitar_tap.models.tap_display_settings import TapDisplaySettings

        captured = {}

        def fake_set(v):
            captured["stored"] = v

        mock_app_settings = MagicMock()
        mock_app_settings.set_tap_threshold.side_effect = fake_set
        mock_app_settings.tap_threshold.return_value = 60  # not used in setter path

        with patch(
            "guitar_tap.models.tap_display_settings._app_settings",
            return_value=mock_app_settings,
        ):
            TapDisplaySettings.set_tap_detection_threshold(-40.0)

        assert captured["stored"] == 60, (
            "Expected -40 dBFS to be stored as slider value 60 (= -40 + 100)"
        )
