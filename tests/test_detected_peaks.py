# @parity test/detected-peaks
"""
One contract, three mechanisms: the detected peaks are announced on the detected peaks alone.

While a sequence waits for a tap, every live frame finds the peaks again. Whatever announces them is redrawn
at the frame rate, so only what shows peaks may hear it: announced by the analyzer, every frame would reach
every view that listens to it — in Swift's the whole main window, and on iOS a menu open anywhere in it,
which lost the item under the user's finger. The peaks were right all along; only who was told was wrong, so
the value tests could not see it.

Swift checks ``objectWillChange`` on each object, Python which signals fire, the web which listeners are
called. A private signal (a leading underscore) is the analyzer's own delivery path to itself, not an
announcement, and is left out.

Mirrors: GuitarTapTests/DetectedPeaksTests.swift · test/detected-peaks.test.ts
"""

from __future__ import annotations

import numpy as np

from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from tests.test_input_level import _app, _count_public_signals, _drain


def _spectrum_with_peak() -> tuple[list[float], list[float]]:
    """One clear peak at bin 200 (about 146 Hz at 0.732 Hz a bin), falling 2 dB a bin from −30 dB."""
    bins = np.arange(4096)
    freqs = bins * 0.732
    mags = -30.0 - 2.0 * np.abs(bins - 200)
    return list(mags), list(freqs)


def _waiting_for_a_tap(app) -> TapToneAnalyzer:
    """An analyzer waiting for a tap on a running engine, the way a live frame finds it."""
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    sut = TapToneAnalyzer.for_testing(sample_rate=48000)
    sut.number_of_taps = 1
    sut.start_tap_sequence(skip_warmup=True)
    sut.mic.is_stopped = False   # a frame comes only from the running engine
    _drain(app)
    return sut


def test_live_peaks_are_announced_on_the_detected_peaks_alone():
    """DP1: while waiting for a tap, a frame's peaks are announced on the detected peaks, and the analyzer
    announces nothing. Mirrors Swift livePeaks_areAnnouncedOnTheDetectedPeaksAlone."""
    app = _app()
    sut = _waiting_for_a_tap(app)
    assert sut.is_detecting

    peaks: list[int] = []
    sut.peaks.peaksChanged.connect(lambda *_a: peaks.append(1))
    others: list[str] = []
    _count_public_signals(sut, others, "analyzer")

    mags, freqs = _spectrum_with_peak()
    for _ in range(3):
        sut.analyze_magnitudes(mags, freqs, max(mags))
    _drain(app)

    assert sut.all_peaks, "the frame must find its peak, or the test proves nothing"
    assert peaks, "the peaks must reach the detected peaks, or the chart and Results stand still"
    assert others == [], (
        f"REGRESSION: announced for a frame's peaks: {sorted(set(others))} — every view listening is "
        "redrawn on every frame")


def test_no_peaks_are_not_announced_by_the_analyzer():
    """DP2: a frame with no peaks, while waiting for a tap, is not announced by the analyzer either.
    Mirrors Swift noPeaks_areNotAnnouncedByTheAnalyzer."""
    app = _app()
    sut = _waiting_for_a_tap(app)

    others: list[str] = []
    _count_public_signals(sut, others, "analyzer")

    mags = [-100.0] * 4096
    freqs = [i * 0.732 for i in range(4096)]
    for _ in range(3):
        sut.analyze_magnitudes(mags, freqs, -100.0)
    _drain(app)

    assert others == [], (
        f"REGRESSION: announced for a frame with no peaks: {sorted(set(others))} — every view listening "
        "is redrawn on every frame")
