"""
Port of TapDetectionTests.swift — hysteresis, warmup, cooldown, EMA.

Mirrors Swift test plan coverage T1–T8.

The Python TapDetector uses PyQt6.QtCore.QObject and pyqtSignal, so a
QCoreApplication is required.  The fixture below ensures one exists for
the duration of the test session.

NOTE: TapDetector.reset() calls traceback.print_stack() (debug logging).
      This produces harmless output during tests — it does not affect behaviour.
"""

from __future__ import annotations

import sys, os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Must create QCoreApplication before importing TapDetector
from PyQt6 import QtCore, QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.tap_tone_analyzer_tap_detection import TapDetector


# ---------------------------------------------------------------------------
# Helper: build TapDetector and collect tap events
# ---------------------------------------------------------------------------

def _make_detector(
    threshold: int = 60,
    hysteresis: float = 3.0,
    warmup_s: float = 0.0,   # 0 for most tests — skips warmup
    cooldown_s: float = 0.0,
    mode: str = TapDetector.MODE_GUITAR,
) -> tuple["TapDetector", list]:
    _get_app()
    det = TapDetector(
        tap_threshold=threshold,
        hysteresis_margin=hysteresis,
        warmup_s=warmup_s,
        cooldown_s=cooldown_s,
        mode=mode,
    )
    taps: list[int] = []
    det.tapDetected.connect(lambda: taps.append(1))
    # Jump straight to IDLE (warmup already 0, but we need to process one frame
    # at below-threshold to confirm the WARMUP→IDLE transition happens)
    det.update(0)   # below threshold, causes warmup exit → IDLE (warmup_s=0)
    taps.clear()    # discard any phantom events from initial update
    return det, taps


# ---------------------------------------------------------------------------
# T1: Rising edge fires tap
# ---------------------------------------------------------------------------

class TestRisingEdge:
    """Mirrors Swift TapDetectionTests T1/T1b."""

    def test_T1_rising_edge_fires_tap(self):
        """T1: A level above the threshold triggers exactly one tap."""
        det, taps = _make_detector(threshold=60)
        # Level 65 = -35 dBFS; threshold=60 → -40 dBFS → above threshold
        det.update(65)
        assert len(taps) == 1, f"Expected 1 tap; got {len(taps)}"

    def test_T1b_only_fires_once_per_rising_edge(self):
        """T1b: Multiple updates while above threshold only fire one tap."""
        det, taps = _make_detector(threshold=60)
        for _ in range(5):
            det.update(70)
        assert len(taps) == 1, f"Should fire exactly once per rising edge; got {len(taps)}"


# ---------------------------------------------------------------------------
# T2: Below threshold
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    """Mirrors Swift TapDetectionTests T2."""

    def test_T2_below_threshold_never_fires(self):
        """T2: A level below threshold never triggers a tap."""
        det, taps = _make_detector(threshold=60)
        for _ in range(10):
            det.update(50)   # 50 < 60 threshold
        assert len(taps) == 0, f"Below threshold should never fire; got {len(taps)}"


# ---------------------------------------------------------------------------
# T3: Warmup suppression
# ---------------------------------------------------------------------------

class TestWarmup:
    """Mirrors Swift TapDetectionTests T3."""

    def test_T3_warmup_suppresses_tap(self):
        """T3: A tap during warmup period should be suppressed."""
        _get_app()
        det = TapDetector(
            tap_threshold=60,
            warmup_s=5.0,   # long warmup
            cooldown_s=0.0,
        )
        taps: list[int] = []
        det.tapDetected.connect(lambda: taps.append(1))

        # Fire multiple high-level updates during warmup
        for _ in range(5):
            det.update(80)

        assert len(taps) == 0, (
            f"No tap should fire during warmup; got {len(taps)}"
        )


# ---------------------------------------------------------------------------
# T4: Cooldown suppression
# ---------------------------------------------------------------------------

class TestCooldown:
    """Mirrors Swift TapDetectionTests T4."""

    def test_T4_second_tap_suppressed_during_cooldown(self):
        """T4: A second tap fired immediately after the first is in cooldown → suppressed."""
        _get_app()
        det = TapDetector(
            tap_threshold=60,
            hysteresis_margin=3.0,
            warmup_s=0.0,
            cooldown_s=5.0,   # long cooldown
        )
        taps: list[int] = []
        det.tapDetected.connect(lambda: taps.append(1))

        # Initial warmup frame
        det.update(0)
        taps.clear()

        # First rising edge — should fire
        det.update(70)
        assert len(taps) == 1, "First tap should fire"

        # Drop below falling threshold to re-arm
        for _ in range(3):
            det.update(40)

        # Second rising edge — still in cooldown window → should NOT fire
        det.update(70)
        assert len(taps) == 1, (
            f"Second tap during cooldown should be suppressed; got {len(taps)}"
        )


# ---------------------------------------------------------------------------
# T5: Hysteresis prevents bouncing
# ---------------------------------------------------------------------------

class TestHysteresis:
    """Mirrors Swift TapDetectionTests T5/T5b."""

    def test_T5_does_not_re_arm_until_below_falling_threshold(self):
        """T5: After a tap, level must drop below the falling threshold before re-arming."""
        det, taps = _make_detector(threshold=60, hysteresis=10.0)

        # First tap
        det.update(70)
        assert len(taps) == 1

        # Drop to level still above falling threshold (falling = 60-10 = 50 → amplitude 50)
        # Level 55 > 50 → still TRIGGERED
        det.update(55)
        det.update(70)   # try another rising edge — should NOT fire (still triggered)
        assert len(taps) == 1, (
            f"Should not re-arm above falling threshold; got {len(taps)}"
        )

    def test_T5b_re_arms_after_falling_below_threshold(self):
        """T5b: Once the level drops below the falling threshold, the detector re-arms."""
        det, taps = _make_detector(threshold=60, hysteresis=10.0)

        # First tap
        det.update(70)
        assert len(taps) == 1

        # Drop well below falling threshold (40 < 50) — now IDLE
        det.update(40)

        # Second rising edge should fire
        det.update(70)
        assert len(taps) == 2, (
            f"Should re-arm after dropping below falling threshold; got {len(taps)}"
        )


# ---------------------------------------------------------------------------
# T8: Post-warmup sync frame
# ---------------------------------------------------------------------------

class TestPostWarmupSync:
    """Mirrors Swift TapDetectionTests T8."""

    def test_T8_signal_already_above_threshold_on_warmup_exit_goes_to_triggered(self):
        """T8: If signal is high when warmup ends, state goes to TRIGGERED (no false tap)."""
        _get_app()
        det = TapDetector(
            tap_threshold=60,
            warmup_s=0.001,   # tiny but nonzero warmup
            cooldown_s=0.0,
        )
        taps: list[int] = []
        det.tapDetected.connect(lambda: taps.append(1))

        # Feed a high-level sample during the tiny warmup
        det.update(80)

        # Wait for warmup to expire
        time.sleep(0.02)

        # Feed one more high sample — this should trigger WARMUP→TRIGGERED (no emission)
        det.update(80)

        # No tap should have been emitted (signal was already above when warmup exited)
        assert len(taps) == 0, (
            f"Signal already above threshold on warmup exit should not fire; got {len(taps)}"
        )


# ---------------------------------------------------------------------------
# T6: Plate mode (relative threshold)
# ---------------------------------------------------------------------------

class TestPlateMode:
    """Mirrors Swift TapDetectionTests T6."""

    def test_T6_plate_mode_adapts_to_noise_floor(self):
        """T6: In plate/brace mode, a loud spike above the noise floor fires a tap."""
        _get_app()
        det = TapDetector(
            tap_threshold=60,
            hysteresis_margin=3.0,
            warmup_s=0.0,
            cooldown_s=0.0,
            mode=TapDetector.MODE_PLATE_BRACE,
        )
        taps: list[int] = []
        det.tapDetected.connect(lambda: taps.append(1))

        # Feed many quiet frames to let the EMA settle well below the threshold
        for _ in range(50):
            det.update(20)   # very quiet
        taps.clear()

        # Now send a loud tap well above the adaptive threshold
        det.update(80)

        assert len(taps) == 1, (
            f"Plate mode should detect a large spike above the noise floor; got {len(taps)}"
        )


# ---------------------------------------------------------------------------
# T7: EMA noise-floor convergence
# ---------------------------------------------------------------------------

class TestEMAConvergence:
    """Mirrors Swift TapDetectionTests T7."""

    def test_T7_ema_converges_toward_input_level(self):
        """T7: After many frames at a constant level, the EMA noise floor converges."""
        _get_app()
        det = TapDetector(
            tap_threshold=80,
            warmup_s=0.0,
            cooldown_s=0.0,
            mode=TapDetector.MODE_PLATE_BRACE,
        )
        # Initial warmup frame
        det.update(0)

        constant_level = 30   # 30 → -70 dBFS
        constant_level_db = constant_level - 100.0

        # Feed 200 frames at the constant level
        for _ in range(200):
            det._compute_thresholds(float(constant_level_db))

        # After 200 frames with α=0.05, EMA should be within 1 dB of the constant level
        # (convergence: after n frames, error = (1-α)^n × initial_offset)
        assert abs(det._noise_floor_db - constant_level_db) < 2.0, (
            f"EMA noise floor should converge to {constant_level_db:.1f} dB; "
            f"got {det._noise_floor_db:.1f} dB"
        )
