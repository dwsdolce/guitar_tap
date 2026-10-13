# @parity test/guitar-capture-window
"""
A guitar tap reaches the transform as the same samples wherever the audio's chunk boundaries fall.

The tap trigger fires on a chunk boundary, so the capture begins at a different sample from one run
to the next (and from one edition to the next) for the same tap. The window is aligned to the tap's
onset, which takes that out of its start — but the capture is exactly as long as the window, so it
runs out before the window's end, by an amount that depends on the boundary. The window's audio
therefore ends at a fixed length, short of the window's end by the most that amount can be, and
zeros follow: the same tap, the same window.

Mirrors: GuitarTapTests/GuitarCaptureWindowTests.swift · test/guitar-capture-window.test.ts
"""

from __future__ import annotations

import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models import capture_probe
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
from tests.playback_support import play_file_and_wait

SAMPLE_RATE = 48000


def recording() -> np.ndarray:
    """One second of quiet noise, then a tap — two decaying tones that start at full amplitude, so
    the onset is one unmistakable sample — ringing for longer than a capture."""
    lead, tail = SAMPLE_RATE, 80_000
    state = 12345
    noise = np.empty(lead + tail, dtype=np.float32)
    for i in range(lead + tail):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        noise[i] = (np.float32(state >> 8) / np.float32(1 << 24) - np.float32(0.5)) * np.float32(0.0005)
    t = np.arange(tail) / SAMPLE_RATE
    tone = (0.25 * np.cos(2 * np.pi * 110 * t) * np.exp(-t * 4)
            + 0.1 * np.cos(2 * np.pi * 237 * t) * np.exp(-t * 6))
    noise[lead:] += tone.astype(np.float32)
    return noise


def window_fingerprint(tmp_path, samples: np.ndarray, dropped: int) -> "str | None":
    """Play the recording with its first *dropped* samples removed — the same tap, its chunk
    boundaries *dropped* samples elsewhere — and return the fingerprint of the window the capture
    handed to the transform."""
    path = str(tmp_path / f"guitar-window-{dropped}.wav")
    sf.write(path, samples[dropped:], SAMPLE_RATE, subtype="FLOAT")

    capture_probe.reset()
    capture_probe.enabled = True
    try:
        sut = TapToneAnalyzer.for_testing(sample_rate=SAMPLE_RATE)
        sut.tap_detection_threshold = -40.0
        play_file_and_wait(sut, path=path, measurement_type=MeasurementType.GENERIC, number_of_taps=1)
        return capture_probe.records[0]["windowHash"] if capture_probe.records else None
    finally:
        capture_probe.enabled = False


def test_GW1_same_tap_same_window_wherever_the_chunk_boundaries_fall(tmp_path):
    """GW1: the same tap, with its chunk boundaries at four different places, reaches the transform
    as the same window."""
    samples = recording()
    seen = {dropped: window_fingerprint(tmp_path, samples, dropped) for dropped in (0, 300, 700, 1000)}
    assert all(seen.values()), f"no capture for some chunk boundary: {seen}"
    assert len(set(seen.values())) == 1, f"REGRESSION: the window differs with the chunk boundary — {seen}"


def onset_test_signal(length: int = 40_000, tap: int = 12_000) -> np.ndarray:
    """Noise whose level rises and falls, then a tap that grows from nothing: the noise measured
    at one place gives a different threshold from the noise at another, and the tap's first sample
    above a threshold depends on the threshold."""
    import math
    x = np.empty(length, dtype=np.float32)
    state = 24680
    for i in range(length):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        u = (state >> 8) / float(1 << 24) - 0.5
        x[i] = np.float32(u * 0.0008 * (1.0 + 0.6 * math.sin(2 * math.pi * i / 3000.0)))
    for m in range(length - tap):
        x[tap + m] += np.float32(0.3 * (1 - math.exp(-m / 300.0)) * math.sin(2 * math.pi * 110 * m / 48000.0))
    return x


def test_GW2_the_aligned_window_is_the_same_wherever_the_capture_started():
    """GW2: the same tap captured from seven different starting samples — as the trigger's chunk
    boundary moves the capture's start — aligns to the same window."""
    sut = TapToneAnalyzer.for_testing(sample_rate=SAMPLE_RATE)
    x = onset_test_signal()
    windows = {start: np.asarray(sut.align_capture_to_onset(x[start:], window_size=19_200, pre_onset_samples=4_800))
               for start in (0, 300, 700, 1000, 1500, 2200, 3000)}
    first = windows[0]
    differing = [start for start, w in windows.items() if not np.array_equal(w, first)]
    assert not differing, f"REGRESSION: the window depends on where the capture started — differs at {differing}"
