# @parity test/live-frame
"""
One contract, three mechanisms: a live FFT frame is announced on the live frame alone.

A frame comes several times a second. Whatever announces it is redrawn that often, so only what draws a
frame may hear it: announced by the engine or the analyzer, every frame would reach every view that listens
to them — in Swift's the whole main window, and a menu open in it, which snapped back under the user's
finger. The values were right all along; only who was told was wrong, so the value tests could not see it.

Swift checks ``objectWillChange`` on each object, Python which signals fire, the web which listeners and
callbacks are called. A private signal (a leading underscore) is the analyzer's own delivery path to itself,
not an announcement, and is left out.

Mirrors: GuitarTapTests/LiveFrameTests.swift · test/live-frame.test.ts
"""

from __future__ import annotations

import numpy as np

from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from tests.test_input_level import _app, _count_public_signals, _drain
from tests.test_measurement_complete_transitions import _captured_tap


def _quiet_frame(n: int) -> np.ndarray:
    """One FFT frame at 48 kHz of a quiet 1 kHz sine: well below any detection threshold."""
    t = np.arange(n) / 48000.0
    return (0.001 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)


def test_frame_is_announced_on_the_live_frame_alone():
    """LF1: a frame, while a completed measurement is on screen, is announced on the live frame and by
    nothing else. (While a sequence runs, a frame's live peaks are announced on the detected peaks —
    test_detected_peaks.py.)
    Mirrors Swift frame_isAnnouncedOnTheLiveFrameAlone."""
    app = _app()
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    sut = TapToneAnalyzer.for_testing(sample_rate=48000)
    sut.number_of_taps = 1
    sut.captured_taps = [_captured_tap(-30.0)]
    sut.process_multiple_taps()
    _drain(app)
    assert sut.is_measurement_complete

    frames: list[int] = []
    sut.mic.frame.frameChanged.connect(lambda: frames.append(1))
    others: list[str] = []
    _count_public_signals(sut, others, "analyzer")
    _count_public_signals(sut.mic.proc_thread, others, "engine")

    sut.mic.process_raw_samples(_quiet_frame(sut.mic.fft_size))
    _drain(app)

    assert frames, "the frame must reach the live frame, or the chart stands still"
    assert others == [], (
        f"REGRESSION: announced for one frame: {sorted(set(others))} — every view listening is "
        "redrawn on every frame")
