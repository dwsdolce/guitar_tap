"""
Port of TapDetectionTests.swift — hysteresis, warmup, cooldown, EMA.

Mirrors Swift TapDetectionTests test suite (T1–T9).

Strategy: detectTap() is a method on TapToneAnalyzer.  We manipulate its
internal guard state (analyzer_start_time, is_above_threshold, last_tap_time)
directly so the method exercises pure logic without a real audio engine.
TapToneAnalyzer() is now constructible without audio hardware (Part 5).
"""

from __future__ import annotations

import sys, os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtCore, QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.measurement_type import MeasurementType


# ---------------------------------------------------------------------------
# Synthetic spectrum — sufficient for the detection path
# ---------------------------------------------------------------------------

_FAKE_MAGS: list[float] = [-80.0] * 64
_FAKE_FREQS: list[float] = [float(i) * 375 for i in range(64)]


# ---------------------------------------------------------------------------
# Helper: build a non-running TapToneAnalyzer in guitar mode
# with its warm-up period satisfied so detect_tap can fire.
# Mirrors Swift makeSUT().
# ---------------------------------------------------------------------------

def _make_sut(
    threshold: float = -40.0,
    hysteresis: float = 5.0,
    number_of_taps: int = 1,
) -> TapToneAnalyzer:
    _get_app()
    sut = TapToneAnalyzer()
    sut.tap_detection_threshold = threshold
    sut.hysteresis_margin = hysteresis
    sut.number_of_taps = number_of_taps
    # Defeat the warmup guard by setting the start time 2 s in the past.
    # Mirrors Swift: sut.analyzerStartTime = Date(timeIntervalSinceNow: -2)
    import time as _t
    sut.analyzer_start_time = _t.monotonic() - 2.0
    # Defeat the post-warmup sync frame.
    sut.just_exited_warmup = False
    # Guitar mode (absolute threshold) — ensure measurement_type is acoustic.
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    return sut


# ---------------------------------------------------------------------------
# T1: Signal crossing rising threshold fires tap
# ---------------------------------------------------------------------------

class TestRisingEdge:
    """Mirrors Swift TapDetectionTests T1/T1b."""

    def test_T1_above_threshold_sets_tap_detected(self):
        """T1: Rising edge above threshold sets tap_detected = True."""
        sut = _make_sut(threshold=-40)
        sut.is_detecting = True
        sut.is_above_threshold = False

        sut.detect_tap(peak_magnitude=-35, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.tap_detected is True, "tap_detected should be True after crossing rising threshold"

    def test_T1b_last_tap_time_set_on_detection(self):
        """T1b: last_tap_time is set when a tap is detected."""
        import time as _t
        sut = _make_sut(threshold=-40)
        sut.is_detecting = True
        sut.is_above_threshold = False

        before = _t.monotonic()
        sut.detect_tap(peak_magnitude=-35, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        after = _t.monotonic()

        assert sut.last_tap_time is not None, "last_tap_time should be set on detection"
        assert before <= sut.last_tap_time <= after


# ---------------------------------------------------------------------------
# T2: Signal below threshold leaves tap_detected = False
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    """Mirrors Swift TapDetectionTests T2."""

    def test_T2_below_threshold_does_not_detect(self):
        """T2: A level below threshold leaves tap_detected = False."""
        sut = _make_sut(threshold=-40)
        sut.is_detecting = True
        sut.is_above_threshold = False

        sut.detect_tap(peak_magnitude=-50, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.tap_detected is False, "Signal below threshold must not trigger detection"


# ---------------------------------------------------------------------------
# T3: Warm-up suppression
# ---------------------------------------------------------------------------

class TestWarmup:
    """Mirrors Swift TapDetectionTests T3."""

    def test_T3_during_warmup_suppresses_detection(self):
        """T3: Calls during warm-up period suppress detection entirely."""
        import time as _t
        sut = _make_sut()
        sut.is_detecting = True
        sut.is_above_threshold = False
        # Set start time to 'now' so warmup is still active.
        sut.analyzer_start_time = _t.monotonic()

        sut.detect_tap(peak_magnitude=-20, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.tap_detected is False, "Should not detect during warm-up"


# ---------------------------------------------------------------------------
# T4: Cooldown suppression
# ---------------------------------------------------------------------------

class TestCooldown:
    """Mirrors Swift TapDetectionTests T4."""

    def test_T4_during_cooldown_suppresses_detection(self):
        """T4: A second detect_tap call within tap_cooldown is rejected."""
        import time as _t
        sut = _make_sut(threshold=-40)
        sut.is_detecting = True
        sut.is_above_threshold = False
        # Simulate that a tap was just recorded 0.1 s ago.
        sut.last_tap_time = _t.monotonic() - 0.1

        sut.detect_tap(peak_magnitude=-30, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.tap_detected is False, "Should not fire while in cooldown window"


# ---------------------------------------------------------------------------
# T5: Hysteresis prevents bouncing
# ---------------------------------------------------------------------------

class TestHysteresis:
    """Mirrors Swift TapDetectionTests T5/T5b."""

    def test_T5_hysteresis_prevents_bouncing_on_falling_edge(self):
        """T5: Signal between falling and rising threshold keeps is_above_threshold True."""
        import time as _t
        sut = _make_sut(threshold=-40, hysteresis=5)
        sut.is_detecting = True

        # First call: rising edge fires the tap
        sut.is_above_threshold = False
        sut.detect_tap(peak_magnitude=-35, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)
        # tap_detected == True, is_above_threshold == True

        # Advance last_tap_time past cooldown so next call isn't blocked
        sut.last_tap_time = _t.monotonic() - 1.0

        # Second call: signal at -43 dB — between falling_threshold (-45) and
        # rising_threshold (-40). Should stay "above" and not fire a new tap.
        sut.tap_detected = False
        sut.detect_tap(peak_magnitude=-43, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.is_above_threshold is True, \
            "Signal above falling_threshold should keep is_above_threshold = True"
        assert sut.tap_detected is False, \
            "No new tap should fire when still above falling threshold"

    def test_T5b_signal_below_falling_threshold_resets_above_threshold(self):
        """T5b: Once signal drops below falling_threshold, is_above_threshold becomes False."""
        sut = _make_sut(threshold=-40, hysteresis=5)
        sut.is_detecting = True
        sut.is_above_threshold = True   # currently above

        # Signal drops below falling_threshold (-45)
        sut.detect_tap(peak_magnitude=-50, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        assert sut.is_above_threshold is False, \
            "Signal below falling_threshold should set is_above_threshold = False"


# ---------------------------------------------------------------------------
# T8: Post-warmup sync frame
# ---------------------------------------------------------------------------

class TestPostWarmupSync:
    """Mirrors Swift TapDetectionTests T8."""

    def test_T8_just_exited_warmup_syncs_then_skips(self):
        """T8: First frame after warmup syncs is_above_threshold but does not fire tap."""
        sut = _make_sut(threshold=-40)
        sut.is_detecting = True
        sut.just_exited_warmup = True
        # analyzer_start_time is 2 s ago → warmup check passes

        sut.detect_tap(peak_magnitude=-30, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

        # tap_detected must NOT fire on the sync frame
        assert sut.tap_detected is False, \
            "First frame after warmup should sync state but not fire a tap"
        # just_exited_warmup should be cleared
        assert sut.just_exited_warmup is False, \
            "just_exited_warmup flag should be cleared after sync frame"


# ---------------------------------------------------------------------------
# T6: Plate mode uses relative noise-floor detection
# ---------------------------------------------------------------------------

class TestPlateMode:
    """Mirrors Swift TapDetectionTests T6."""

    def test_T6_plate_mode_uses_relative_noise_floor(self):
        """T6: Plate mode uses noise_floor + headroom, not absolute tap_detection_threshold."""
        import time as _t
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        try:
            sut = TapToneAnalyzer()
            sut.tap_detection_threshold = -40.0
            sut.hysteresis_margin = 5.0
            sut.number_of_taps = 1
            sut.analyzer_start_time = _t.monotonic() - 2.0
            sut.just_exited_warmup = False
            sut.is_detecting = True
            sut.is_above_threshold = False

            # Set a controlled noise floor estimate.
            # headroom = max(-40 - (-70), 10) = 30 dB
            # effective_rising_threshold = -70 + 30 = -40 dB
            # So a signal at -35 dB should fire.
            sut.noise_floor_estimate = -70.0
            sut.detect_tap(peak_magnitude=-35, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

            assert sut.tap_detected is True, \
                "Plate mode: signal above noise floor + headroom should fire"
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)


# ---------------------------------------------------------------------------
# T7: EMA noise-floor convergence
# ---------------------------------------------------------------------------

class TestEMAConvergence:
    """Mirrors Swift TapDetectionTests T7."""

    def test_T7_noise_floor_ema_converges_with_repeated_below_threshold_frames(self):
        """T7: After many frames at a constant level, the EMA converges."""
        import time as _t
        TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
        try:
            sut = TapToneAnalyzer()
            sut.tap_detection_threshold = -40.0
            sut.hysteresis_margin = 5.0
            sut.analyzer_start_time = _t.monotonic() - 2.0
            sut.just_exited_warmup = False
            sut.is_above_threshold = False   # stays below threshold

            start_estimate = sut.noise_floor_estimate   # initial value (-60)
            target = -55.0  # ambient level to feed

            # Feed 50 frames at -55 dB (below threshold → EMA updates)
            for _ in range(50):
                sut.detect_tap(peak_magnitude=target, mag_y_db=_FAKE_MAGS, freq=_FAKE_FREQS)

            # EMA with α=0.05, 50 steps from -60 toward -55:
            # After 50 steps: estimate ≈ -57.4; should be > -58
            assert sut.noise_floor_estimate > start_estimate, \
                "Noise floor should move toward ambient level after repeated frames"
            assert sut.noise_floor_estimate > -58.0, (
                f"Noise floor after 50 frames at -55 dB should be close to -55 "
                f"(got {sut.noise_floor_estimate:.2f})"
            )
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
