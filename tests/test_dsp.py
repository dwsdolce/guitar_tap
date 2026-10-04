# @parity test/dsp
"""The DSP under peak finding and the live spectrum, against the shared case file, ``dsp.json`` — the same
cases the Swift and web suites run: parabolic interpolation and the Q factor (TapToneAnalyzer), and signals
through RealtimeFFTAnalyzer's gated FFT, live FFT, live peak and per-chunk levels.

Silence is -inf in every bin and on the readout, not a finite floor: -100 dB is a REAL reading (a quiet
UMIK-1 reaches it, and it is the dead-input watchdog's threshold), so "no microphone at all" must not look
like "a very quiet microphone". Detection keeps -100 on silence."""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "dsp.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _close(actual: float, expected) -> bool:
    """|actual - expected| <= relative * |expected| + absolute; equal infinities match."""
    e = float(expected)  # float() reads "NaN", "Infinity" and "-Infinity"
    if math.isinf(e) or math.isinf(actual):
        return actual == e
    tol = DATA["tolerance"]
    return abs(actual - e) <= tol["relative"] * abs(e) + tol["absolute"]


def _spectrum(row: dict) -> tuple[list[float], list[float]]:
    """A case's spectrum: inline, or named in ``spectra``."""
    s = DATA["spectra"][row["spectrum"]] if "spectrum" in row else row
    return [float(x) for x in s["magnitudes"]], [float(x) for x in s["frequencies"]]


def _signal(row: dict, fft_size: int) -> np.ndarray:
    """A case's signal: silence, a constant (DC), an alternating ±amplitude (Nyquist), a constant plus an
    alternating, or a tone; a count of "fftSize" is the analyzer's FFT size."""
    s = row["signal"]
    n = fft_size if s["count"] == "fftSize" else s["count"]
    if s["kind"] == "silence":
        return np.zeros(n, dtype=np.float32)
    if s["kind"] == "constant":
        alternating = s.get("alternating", 0.0)
        return (s.get("value", 0.0) + np.where(np.arange(n) % 2 == 0, alternating, -alternating)).astype(np.float32)
    t = np.arange(n, dtype=np.float64)
    return (s["amplitude"] * np.sin(2 * np.pi * s["frequency"] * t / s["sampleRate"])).astype(np.float32)


@pytest.mark.parametrize("row", DATA["parabolicInterpolate"], ids=lambda r: r["id"])
def test_parabolic_interpolate(row):
    m, f = _spectrum(row)
    freq, mag = TapToneAnalyzer()._parabolic_interpolate(m, f, row["peakIndex"])
    assert _close(freq, row["expect"]["frequency"]), f"frequency {freq}"
    assert _close(mag, row["expect"]["magnitude"]), f"magnitude {mag}"


@pytest.mark.parametrize("row", DATA["calculateQFactor"], ids=lambda r: r["id"])
def test_calculate_q_factor(row):
    m, f = _spectrum(row)
    q, bw = TapToneAnalyzer()._calculate_q_factor(m, f, row["peakIndex"], float(row["peakMagnitude"]))
    assert _close(q, row["expect"]["quality"]), f"quality {q}"
    assert _close(bw, row["expect"]["bandwidth"]), f"bandwidth {bw}"


@pytest.mark.parametrize("row", DATA["signals"], ids=lambda r: r["id"])
def test_signal(row):
    e = row["expect"]
    a = RealtimeFFTAnalyzer.for_testing()
    samples = _signal(row, a.fft_size)

    def check_spectrum(m, f):
        if "binCount" in e:
            assert len(m) == e["binCount"], f"bin count {len(m)}"
        if "bin0" in e:
            assert _close(float(m[0]), e["bin0"]), f"bin 0 {m[0]}"
            assert _close(float(m[-1]), e["lastBin"]), f"last bin {m[-1]}"
            return
        if "allNegativeInfinity" in e:
            assert len(m) > 0 and bool(np.all(np.isneginf(m))) == e["allNegativeInfinity"]
        else:
            i = int(np.argmax(m))
            assert _close(float(f[i]), e["peakFrequency"]), f"peak frequency {f[i]}"
            assert _close(float(m[i]), e["peakMagnitude"]), f"peak magnitude {m[i]}"

    path = row["path"]
    if path == "gatedFFT":
        m, f = a.compute_gated_fft(samples, float(row["signal"].get("sampleRate", 48000)))
        check_spectrum(np.asarray(m), np.asarray(f))
    elif path == "computeFFT":
        m = a.compute_fft(samples)
        check_spectrum(m, np.arange(len(m)) * 48000.0 / a.fft_size)
    elif path == "performFFT":
        a.rate = 48000
        a.perform_fft(samples)
        assert _close(a.peak_frequency, e["peakFrequency"]), f"peak_frequency {a.peak_frequency}"
        assert _close(a.peak_magnitude, e["peakMagnitude"]), f"peak_magnitude {a.peak_magnitude}"
    elif path == "processRawSamples":
        a.process_raw_samples(samples)
        assert _close(a.input_level_db, e["inputLevelDB"]), f"input_level_db {a.input_level_db}"
        assert _close(a.readout_level_db, e["readoutLevelDB"]), f"readout_level_db {a.readout_level_db}"
    else:
        pytest.fail(f"unknown path {path!r}")
