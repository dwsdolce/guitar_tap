"""
WI-6 — TapDisplaySettings round-trip and helper tests (D18, D19).

D18: Verifies the tap_detection_threshold getter/setter are mutual inverses.
     The setter must convert dBFS → 0-100 scale before persisting, matching
     what the getter expects when it reads back (0-100 → dBFS).

D19: Verifies validate_frequency_range and validate_magnitude_range behave
     identically to Swift's equivalents. reset_to_defaults() smoke test.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch, call

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


# ---------------------------------------------------------------------------
# D19 — validate_frequency_range
# ---------------------------------------------------------------------------

class TestD19ValidateFrequencyRange:
    """D19: validate_frequency_range mirrors Swift validateFrequencyRange."""

    def _cls(self):
        _get_app()
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        return TapDisplaySettings

    def test_valid_range_returned_unchanged(self):
        tds = self._cls()
        result = tds.validate_frequency_range(200.0, 5000.0)
        assert result == pytest.approx((200.0, 5000.0))

    def test_clamps_below_20hz(self):
        tds = self._cls()
        lo, hi = tds.validate_frequency_range(5.0, 5000.0)
        assert lo == pytest.approx(20.0)
        assert hi == pytest.approx(5000.0)

    def test_clamps_above_20khz(self):
        tds = self._cls()
        lo, hi = tds.validate_frequency_range(200.0, 25000.0)
        assert lo == pytest.approx(200.0)
        assert hi == pytest.approx(20000.0)

    def test_inverted_range_returns_persisted_fallback(self):
        """min >= max after clamping → falls back to persisted range."""
        tds = self._cls()
        # Store a known range first
        tds.set_min_frequency(100.0)
        tds.set_max_frequency(8000.0)
        lo, hi = tds.validate_frequency_range(5000.0, 200.0)
        assert lo == pytest.approx(tds.min_frequency())
        assert hi == pytest.approx(tds.max_frequency())

    def test_range_too_narrow_returns_persisted_fallback(self):
        """Separation < 10 Hz → falls back to persisted range."""
        tds = self._cls()
        tds.set_min_frequency(100.0)
        tds.set_max_frequency(8000.0)
        lo, hi = tds.validate_frequency_range(1000.0, 1005.0)
        assert lo == pytest.approx(tds.min_frequency())
        assert hi == pytest.approx(tds.max_frequency())

    def test_exactly_10hz_separation_accepted(self):
        """Exactly 10 Hz separation is accepted."""
        tds = self._cls()
        lo, hi = tds.validate_frequency_range(100.0, 110.0)
        assert lo == pytest.approx(100.0)
        assert hi == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# D19 — validate_magnitude_range
# ---------------------------------------------------------------------------

class TestD19ValidateMagnitudeRange:
    """D19: validate_magnitude_range mirrors Swift validateMagnitudeRange."""

    def _cls(self):
        _get_app()
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        return TapDisplaySettings

    def test_valid_range_returned_unchanged(self):
        tds = self._cls()
        result = tds.validate_magnitude_range(-80.0, -20.0)
        assert result == pytest.approx((-80.0, -20.0))

    def test_clamps_below_minus_120(self):
        tds = self._cls()
        lo, hi = tds.validate_magnitude_range(-150.0, -20.0)
        assert lo == pytest.approx(-120.0)
        assert hi == pytest.approx(-20.0)

    def test_clamps_above_20(self):
        tds = self._cls()
        lo, hi = tds.validate_magnitude_range(-80.0, 50.0)
        assert lo == pytest.approx(-80.0)
        assert hi == pytest.approx(20.0)

    def test_inverted_range_returns_persisted_fallback(self):
        tds = self._cls()
        tds.set_min_magnitude(-100.0)
        tds.set_max_magnitude(-10.0)
        lo, hi = tds.validate_magnitude_range(-20.0, -80.0)
        assert lo == pytest.approx(tds.min_magnitude())
        assert hi == pytest.approx(tds.max_magnitude())

    def test_range_too_narrow_returns_persisted_fallback(self):
        tds = self._cls()
        tds.set_min_magnitude(-100.0)
        tds.set_max_magnitude(-10.0)
        lo, hi = tds.validate_magnitude_range(-50.0, -45.0)
        assert lo == pytest.approx(tds.min_magnitude())
        assert hi == pytest.approx(tds.max_magnitude())

    def test_exactly_10db_separation_accepted(self):
        tds = self._cls()
        lo, hi = tds.validate_magnitude_range(-60.0, -50.0)
        assert lo == pytest.approx(-60.0)
        assert hi == pytest.approx(-50.0)


# ---------------------------------------------------------------------------
# D19 — reset_to_defaults smoke test
# ---------------------------------------------------------------------------

class TestD19ResetToDefaults:
    """D19: reset_to_defaults() restores key settings to Swift-matching defaults."""

    def _cls(self):
        _get_app()
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        return TapDisplaySettings

    def test_tap_detection_threshold_reset(self):
        """tapDetectionThreshold resets to -40.0 dBFS (matches Swift default)."""
        tds = self._cls()
        tds.set_tap_detection_threshold(-20.0)   # dirty the value
        tds.reset_to_defaults()
        assert tds.tap_detection_threshold() == pytest.approx(-40.0)

    def test_hysteresis_margin_reset(self):
        """hysteresisMargin resets to 3.0 dB (matches Swift default)."""
        tds = self._cls()
        tds.set_hysteresis_margin(10.0)
        tds.reset_to_defaults()
        assert tds.hysteresis_margin() == pytest.approx(3.0)

    def test_measure_flc_reset(self):
        """measureFlc resets to False (matches Swift default)."""
        tds = self._cls()
        tds.set_measure_flc(True)
        tds.reset_to_defaults()
        assert tds.measure_flc() is False
