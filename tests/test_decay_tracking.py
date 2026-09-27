# @parity test/decay-tracking
"""
Decay (ring-out) tracking: measure_decay_time on given histories (DK1–DK5, DK8–DK10) and the tracker
driven through production (DK6, DK7, DK11–DK13) — a fresh analyzer, start_decay_tracking,
start_tap_sequence and the per-chunk entry _on_chunk_level.

The same list, ids and values as Swift DecayTrackingTests and web test/decay-tracking.test.ts. Times are
audio-clock seconds; no audio hardware or real timing is involved.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtWidgets

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

EXACT = 1e-6


def _make_sut() -> TapToneAnalyzer:
    _get_app()
    return TapToneAnalyzer()


def _history(magnitudes: list[float], interval: float = 0.1, start: float = 0.0) -> list[tuple[float, float]]:
    """(audio_time, magnitude) entries `interval` seconds apart, from `start`."""
    return [(start + i * interval, m) for i, m in enumerate(magnitudes)]


def _measure(entries, tap_time: float, threshold: "float | None" = None):
    """measure_decay_time on an analyzer holding `entries`, with `threshold` if given."""
    sut = _make_sut()
    if threshold is not None:
        sut.decay_threshold = threshold
    sut.peak_magnitude_history = entries
    return sut.measure_decay_time(tap_time)


class TestDecayTracking:
    """Mirrors Swift DecayTrackingTests."""

    # ── measure_decay_time ─────────────────────────────────────────────────────────────────────

    def test_DK1_empty_history_returns_none(self):
        """DK1: An empty history measures nothing."""
        assert _measure([], 0.0) is None

    def test_DK2_all_samples_before_tap_returns_none(self):
        """DK2: Every entry before the tap — nothing to measure after it."""
        assert _measure(_history([-20, -25, -30, -35, -40, -50], start=-1.0), 0.0) is None

    def test_DK3_signal_never_decays_returns_none(self):
        """DK3: The level never drops by the threshold (30 dB here; it falls 5 dB)."""
        assert _measure(_history([-20, -22, -24, -25, -25, -25, -25]), 0.0, threshold=30.0) is None

    def test_DK4_normal_decay_is_timed_from_peak_to_crossing(self):
        """DK4: Peak -10 at 0 s; target -30 (20 dB); the first entry below it is -31 at 0.5 s."""
        t = _measure(_history([-10, -15, -20, -24, -28, -31, -35]), 0.0, threshold=20.0)
        assert t == pytest.approx(0.5, abs=EXACT)

    def test_DK5_immediate_decay_is_the_next_entry(self):
        """DK5: Peak -10 at 0 s; target -20 (10 dB); the very next entry, -21 at 0.1 s, crosses."""
        t = _measure(_history([-10, -21, -30, -40]), 0.0, threshold=10.0)
        assert t == pytest.approx(0.1, abs=EXACT)

    # ── tracking, driven through production ────────────────────────────────────────────────────

    def test_DK6_not_tracking_records_nothing(self):
        """DK6: A fresh analyzer is not tracking: a chunk is not recorded and no ring-out is measured."""
        sut = _make_sut()
        sut._on_chunk_level(-50.0, 0.1)
        assert sut.peak_magnitude_history == [], "nothing recorded before tracking starts"
        assert sut.current_decay_time is None

    def test_DK7_new_sequence_stops_the_previous_taps_ring_out(self):
        """DK7: A new sequence within 3 s of a tap stops that tap's ring-out tracking and clears its
        history, so the chunks after it measure no ring-out from the old tap. The chunks are below the
        tap threshold, so no new tap is detected."""
        sut = _make_sut()
        sut.tap_detection_threshold = -40.0
        sut.tap_peak_level = -10.0
        sut.start_decay_tracking(tap_audio_time=0.0)
        sut.start_tap_sequence()
        for k in range(1, 13):
            sut._on_chunk_level(-50.0, 0.05 * k)
        assert not sut.is_tracking_decay, "a new sequence stops the ring-out tracking"
        assert sut.current_decay_time is None, "no ring-out is measured from the previous tap"

    # ── measure_decay_time, continued ──────────────────────────────────────────────────────────

    def test_DK8_default_threshold_is_15_db(self):
        """DK8: The threshold is 15 dB unless set: peak -10 at 0 s; target -25; -26 at 0.3 s crosses."""
        assert _make_sut().decay_threshold == 15
        assert _measure(_history([-10, -12, -20, -26, -40]), 0.0) == pytest.approx(0.3, abs=EXACT)

    def test_DK9_rising_transient_is_timed_from_the_peak(self):
        """DK9: Timed from the post-tap PEAK, not the tap: the level rises to -8 at 0.1 s; target -23;
        -24 at 0.3 s crosses -> 0.2 s."""
        assert _measure(_history([-12, -8, -15, -24, -40]), 0.0) == pytest.approx(0.2, abs=EXACT)

    def test_DK10_pre_tap_entries_are_ignored(self):
        """DK10: An entry before the tap is ignored even when it is loudest: -30 at -0.1 s is skipped;
        peak -10 at 0 s; -26 at 0.2 s crosses."""
        t = _measure(_history([-30, -10, -20, -26], start=-0.1), 0.0)
        assert t == pytest.approx(0.2, abs=EXACT)

    # ── tracking, continued ────────────────────────────────────────────────────────────────────

    def test_DK11_streamed_ring_out_is_measured(self):
        """DK11: A ring-out streamed through production: the tap seeds -10 at 0 s, then twelve chunks
        falling 2 dB each, 0.05 s apart; target -25; -26 at 0.4 s crosses."""
        sut = _make_sut()
        sut.tap_peak_level = -10.0
        sut.start_decay_tracking(tap_audio_time=0.0)
        for k in range(1, 13):
            sut._on_chunk_level(-10.0 - 2.0 * k, 0.05 * k)
        assert sut.current_decay_time == pytest.approx(0.4, abs=EXACT)

    def test_DK12_tracking_stops_at_3_s_of_audio_without_recording(self):
        """DK12: Tracking stops at the first chunk 3 s of audio after the tap, without recording it."""
        sut = _make_sut()
        sut.tap_peak_level = -10.0
        sut.start_decay_tracking(tap_audio_time=0.0)
        sut._on_chunk_level(-40.0, 2.99)
        assert sut.is_tracking_decay and len(sut.peak_magnitude_history) == 2, "a chunk before 3 s is recorded"
        sut._on_chunk_level(-40.0, 3.0)
        assert not sut.is_tracking_decay, "tracking stops at 3 s"
        assert len(sut.peak_magnitude_history) == 2, "the 3 s chunk is not recorded"

    def test_DK13_no_ring_out_until_more_than_10_entries(self):
        """DK13: No ring-out is measured until the history holds more than 10 entries: the seed and nine
        chunks (10 entries) measure nothing; the tenth chunk (11 entries) measures -10 -> -50 at 0.05 s."""
        sut = _make_sut()
        sut.tap_peak_level = -10.0
        sut.start_decay_tracking(tap_audio_time=0.0)
        for k in range(1, 10):
            sut._on_chunk_level(-50.0, 0.05 * k)
        assert len(sut.peak_magnitude_history) == 10
        assert sut.current_decay_time is None, "10 entries measure nothing"
        sut._on_chunk_level(-50.0, 0.5)
        assert sut.current_decay_time == pytest.approx(0.05, abs=EXACT), "11 entries measure the ring-out"


class TestRingOutReachesTheView:
    """The measured ring-out reaches the Ring-Out box. Python-only: Swift's view observes its
    `@Published currentDecayTime` and the web's its snapshot; Python's box listens to
    currentDecayTimeChanged, which the current_decay_time property emits.
    """

    def test_a_measured_ring_out_reaches_the_view_and_a_new_tap_clears_it(self):
        sut = _make_sut()
        seen: list = []
        sut.currentDecayTimeChanged.connect(seen.append)

        sut.start_decay_tracking(tap_audio_time=0.0)
        # The ring-out: 12 chunks falling 2 dB each from -10 dB, fed through the per-chunk entry.
        for k in range(1, 13):
            sut._on_chunk_level(-10.0 - 2.0 * k, 0.05 * k)
        QtWidgets.QApplication.processEvents()
        assert sut.current_decay_time is not None, "the ring-out was measured"
        assert seen and seen[-1] == sut.current_decay_time, "the measured ring-out reached the view"

        sut.start_decay_tracking(tap_audio_time=1.0)   # the next tap
        assert sut.current_decay_time is None
        assert seen[-1] is None, "a new tap puts the box back to Waiting…"

