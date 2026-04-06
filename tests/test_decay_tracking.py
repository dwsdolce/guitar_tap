"""
Port of DecayTrackingTests.swift — measureDecayTime edge cases and
trackDecayFast guard behaviour.

Mirrors Swift DecayTrackingTests test suite (DK1–DK7).

All tests operate directly on TapToneAnalyzer's state; no audio hardware
or real timing is involved.  TapToneAnalyzer() is constructible without
audio hardware (Part 5).

NOTE: Python uses monotonic float timestamps (time.monotonic()) instead of
      Swift's Date objects.  History tuples are (float, float) → (time, magnitude).
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sut() -> TapToneAnalyzer:
    _get_app()
    return TapToneAnalyzer()


def _make_history(
    starting_at: float,
    magnitudes: list[float],
    interval_seconds: float = 0.1,
) -> list[tuple[float, float]]:
    """Build a history list of (monotonic_time, magnitude) tuples.

    Mirrors Swift makeHistory(startingAt:intervalSeconds:magnitudes:).
    Samples are spaced interval_seconds apart starting at starting_at.
    """
    return [
        (starting_at + i * interval_seconds, mag)
        for i, mag in enumerate(magnitudes)
    ]


# ---------------------------------------------------------------------------
# DK1–DK5: measureDecayTime edge cases
# ---------------------------------------------------------------------------

class TestDecayTracking:
    """Mirrors Swift DecayTrackingTests."""

    def test_DK1_empty_history_returns_none(self):
        """DK1: Empty history → None (no samples to analyse)."""
        sut = _make_sut()
        sut.peak_magnitude_history = []
        tap_time = time.monotonic()
        result = sut.measure_decay_time(tap_time)
        assert result is None, "Expected None for empty history"

    def test_DK2_all_samples_before_tap_returns_none(self):
        """DK2: All samples are before tap_time → post_tap_history is empty → None."""
        sut = _make_sut()
        tap_time = time.monotonic()
        # Place all samples 1 s before the tap
        sut.peak_magnitude_history = _make_history(
            starting_at=tap_time - 1.0,
            magnitudes=[-20, -25, -30, -35, -40, -50],
        )
        result = sut.measure_decay_time(tap_time)
        assert result is None, "Expected None when all samples precede tap_time"

    def test_DK3_signal_never_decays_returns_none(self):
        """DK3: Signal never decays by decay_threshold → None (threshold not crossed)."""
        sut = _make_sut()
        sut.decay_threshold = 30.0  # require 30 dB drop
        tap_time = time.monotonic()
        # Peak at -20 dB; subsequent samples only drop to -25 dB (5 dB, not 30)
        sut.peak_magnitude_history = _make_history(
            starting_at=tap_time,
            magnitudes=[-20, -22, -24, -25, -25, -25, -25],
        )
        result = sut.measure_decay_time(tap_time)
        assert result is None, "Expected None when signal never decays enough"

    def test_DK4_normal_decay_returns_positive_time(self):
        """DK4: Signal decays past threshold → returns positive elapsed time."""
        sut = _make_sut()
        sut.decay_threshold = 20.0  # require 20 dB drop
        tap_time = time.monotonic()
        # Peak at index 0 = -10 dB; target = -30 dB; crossing at index 5 = -31 dB
        # Time between index 0 and index 5 = 5 × 0.1 s = 0.5 s
        sut.peak_magnitude_history = _make_history(
            starting_at=tap_time,
            magnitudes=[-10, -15, -20, -24, -28, -31, -35],
        )
        result = sut.measure_decay_time(tap_time)
        assert result is not None, "Expected a decay time value"
        assert result > 0, f"Decay time must be positive, got {result}"
        # 5 intervals × 0.1 s = 0.5 s; allow ±0.05 s for floating-point
        assert abs(result - 0.5) < 0.05, f"Expected ≈0.5 s, got {result}"

    def test_DK5_immediate_decay_returns_short_positive_time(self):
        """DK5: Decay crossing immediately after the peak → very short but positive time."""
        sut = _make_sut()
        sut.decay_threshold = 10.0
        tap_time = time.monotonic()
        # Peak at -10 dB; second sample at -21 dB already crosses (target = -20 dB)
        sut.peak_magnitude_history = _make_history(
            starting_at=tap_time,
            magnitudes=[-10, -21, -30, -40],
            interval_seconds=0.1,
        )
        result = sut.measure_decay_time(tap_time)
        assert result is not None, "Expected a decay time for immediate drop"
        assert result > 0, f"Decay time must be positive, got {result}"

    # -----------------------------------------------------------------------
    # DK6–DK7: trackDecayFast guard behaviour
    # -----------------------------------------------------------------------

    def test_DK6_not_tracking_is_noop(self):
        """DK6: When is_tracking_decay is False, track_decay_fast is a no-op."""
        sut = _make_sut()
        sut.is_tracking_decay = False
        initial_count = len(sut.peak_magnitude_history)
        sut.track_decay_fast(-20.0)
        assert len(sut.peak_magnitude_history) == initial_count, \
            "History must not grow when is_tracking_decay is False"

    def test_DK7_tracking_no_tap_time_accumulates(self):
        """DK7: When is_tracking_decay is True but last_tap_time is None,
        samples accumulate but current_decay_time stays None.
        """
        sut = _make_sut()
        sut.is_tracking_decay = True
        sut.last_tap_time = None
        sut.current_decay_time = None
        before = len(sut.peak_magnitude_history)
        sut.track_decay_fast(-30.0)
        assert len(sut.peak_magnitude_history) == before + 1, \
            "Sample should be appended when tracking is active"
        assert sut.current_decay_time is None, \
            "current_decay_time stays None when last_tap_time is not set"
