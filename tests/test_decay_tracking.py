# @parity test/decay-tracking
"""
Decay (ring-out) tracking: measure_decay_time on given histories (DK1–DK5, DK8–DK10) and the tracker
driven through production (DK6, DK7, DK11–DK13) — a fresh analyzer, start_decay_tracking,
start_tap_sequence and the per-chunk entry _on_chunk_level.

The same list, ids and values as Swift DecayTrackingTests and web test/decay-tracking.test.ts. Times are
audio-clock seconds; no audio hardware or real timing is involved.
"""

from __future__ import annotations

import json
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


with open(os.path.join(os.path.dirname(__file__), "decay-tracking.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def test_default_threshold():
    assert _make_sut().decay_threshold == DATA["defaultThreshold"]


@pytest.mark.parametrize("row", DATA["measureDecayTime"], ids=lambda r: r["id"])
def test_measure_decay_time(row):
    """measure_decay_time on given histories — the shared cases in ``decay-tracking.json`` (DK1–DK5, DK8–DK10)."""
    t = _measure(_history(row["magnitudes"], row["interval"], row["start"]), row["tapTime"], row.get("threshold"))
    if row["expect"] is None:
        assert t is None
    else:
        assert t == pytest.approx(row["expect"], abs=DATA["tolerance"])


class TestDecayTracking:
    """Mirrors Swift DecayTrackingTests."""

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

