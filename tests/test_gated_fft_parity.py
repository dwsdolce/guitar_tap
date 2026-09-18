# @parity test/gated-fft
"""
Parity tests for compute_gated_fft: feed identical synthetic signals and verify
the output magnitudes match the expected values.  The companion Swift test
(GatedFFTParityTests.swift) uses the same signal and expected values, so any
systematic difference between the two implementations will show up as a
failing test on one side only.

Test plan coverage: GFFT1–GFFT5
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

sys.path.insert(0, os.path.dirname(__file__))

from parity_oracle import TOLERANCES, gated  # noqa: E402  (follows the src path insert)

# Expected magnitudes and the tones that produce them come from the shared oracle
# (tests/parity-oracle.json), not from literals repeated in each edition. TOL is the
# one tolerance all editions apply to gated-FFT dB.
TOL: float = TOLERANCES["gatedFftDb"]


def _expected(case_name: str, hz: float) -> float:
    """The oracle dB for one tone of a GFFT case, matched on its target frequency."""
    for e in gated(case_name)["expected"]:
        if abs(float(e["hz"]) - hz) < 1e-6:
            return float(e["db"])
    raise KeyError(f"{case_name}: no expected entry near {hz} Hz")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_two_tone_signal(
    sample_rate: float = 48000,
    duration: float = 0.4,
    freq1: float = 0,
    amp1: float = 0,
    freq2: float = 0,
    amp2: float = 0,
) -> np.ndarray:
    """Generate a synthetic PCM signal consisting of two sine waves."""
    count = int(sample_rate * duration)
    t = np.arange(count) / sample_rate
    s = amp1 * np.sin(2 * np.pi * freq1 * t) + amp2 * np.sin(2 * np.pi * freq2 * t)
    return s.astype(np.float32)


def _magnitude_at_frequency(
    target_hz: float,
    magnitudes: list[float],
    frequencies: list[float],
) -> float | None:
    """Find the magnitude (dB) at the bin closest to target_hz."""
    if not frequencies:
        return None
    best_idx = 0
    best_dist = float("inf")
    for i, f in enumerate(frequencies):
        d = abs(f - target_hz)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return magnitudes[best_idx]


def _make_proc_thread():
    """Create a minimal RealtimeFFTAnalyzer for calling compute_gated_fft.

    compute_gated_fft now lives on RealtimeFFTAnalyzer (not _FftProcessingThread).
    It only uses self._settings_lock and self._calibration_profile.
    """
    mic = RealtimeFFTAnalyzer.for_testing(sample_rate=48000)
    return mic


# ---------------------------------------------------------------------------
# Gated FFT Parity Tests
# ---------------------------------------------------------------------------

class TestGatedFFTParity:
    """Mirrors Swift GatedFFTParityTests (GFFT1–GFFT5).

    Expected magnitudes are pinned to the exact same values asserted by the Swift
    suite (within 1 dB), so any systematic divergence between the two FFT
    implementations surfaces as a one-sided failure rather than passing loosely.
    """

    def test_GFFT1_single_tone_100Hz_magnitude_is_reasonable(self):
        """GFFT1: A single 100 Hz sine at amplitude 0.5, pinned by the oracle."""
        sample_rate = 48000.0
        (tone_hz, tone_amp), = gated("GFFT1")["tones"]
        expected = _expected("GFFT1", tone_hz)
        signal = _make_two_tone_signal(
            sample_rate=sample_rate, duration=0.4,
            freq1=tone_hz, amp1=tone_amp,
            freq2=0, amp2=0,
        )
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        mag100 = _magnitude_at_frequency(tone_hz, mags, freqs)
        assert mag100 is not None, f"Should find bin near {tone_hz} Hz"
        print(f"GFFT1 Python: {tone_hz} Hz magnitude = {mag100:.2f} dB")
        assert abs(mag100 - expected) < TOL, \
            f"{tone_hz} Hz: Python={mag100:.2f} dB, oracle={expected} dB — difference > {TOL} dB"

    def test_GFFT2_two_tone_67Hz_and_117Hz_magnitudes_match(self):
        """GFFT2: Two tones at 67 Hz and 117 Hz with known amplitudes.
        This mirrors the exact frequencies from the plate C capture discrepancy."""
        sample_rate = 48000.0
        (f1, a1), (f2, a2) = gated("GFFT2")["tones"]
        exp1, exp2 = _expected("GFFT2", f1), _expected("GFFT2", f2)
        exp_delta = float(gated("GFFT2")["deltaDb"])
        signal = _make_two_tone_signal(
            sample_rate=sample_rate, duration=0.4,
            freq1=f1, amp1=a1,
            freq2=f2, amp2=a2,
        )
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        mag67 = _magnitude_at_frequency(f1, mags, freqs)
        mag117 = _magnitude_at_frequency(f2, mags, freqs)
        assert mag67 is not None and mag117 is not None, \
            "Should find bins near 67 and 117 Hz"

        print(f"GFFT2 Python: 67 Hz = {mag67:.2f} dB, 117 Hz = {mag117:.2f} dB")
        delta = mag117 - mag67
        print(f"GFFT2 Python: delta (117 - 67) = {delta:.2f} dB")
        assert abs(mag67 - exp1) < TOL, \
            f"{f1} Hz: Python={mag67:.2f} dB, oracle={exp1} dB — difference > {TOL} dB"
        assert abs(mag117 - exp2) < TOL, \
            f"{f2} Hz: Python={mag117:.2f} dB, oracle={exp2} dB — difference > {TOL} dB"
        assert abs(delta - exp_delta) < TOL, \
            f"Delta: Python={delta:.2f} dB, oracle={exp_delta} dB — difference > {TOL} dB"

    def test_GFFT3_bin_centred_tones_exact_magnitudes(self):
        """GFFT3: Exact bin-centred tones to eliminate spectral leakage.
        With paddedSize=32768 and sampleRate=48000, binWidth=1.46484375 Hz.
        Bin 46 = 67.3828125 Hz, Bin 80 = 117.1875 Hz"""
        sample_rate = 48000.0
        # Bin-centred by construction: with paddedSize=32768 the oracle tone frequencies
        # are exact multiples of the 1.46484375 Hz bin width (bins 46 and 80).
        (freq1, amp1), (freq2, amp2) = gated("GFFT3")["tones"]
        exp1, exp2 = _expected("GFFT3", freq1), _expected("GFFT3", freq2)
        exp_delta = float(gated("GFFT3")["deltaDb"])

        signal = _make_two_tone_signal(
            sample_rate=sample_rate, duration=0.4,
            freq1=freq1, amp1=amp1,
            freq2=freq2, amp2=amp2,
        )
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        mag1 = _magnitude_at_frequency(freq1, mags, freqs)
        mag2 = _magnitude_at_frequency(freq2, mags, freqs)

        print(f"GFFT3 Python: {freq1:.4f} Hz = {mag1:.2f} dB, "
              f"{freq2:.4f} Hz = {mag2:.2f} dB")
        delta = mag2 - mag1
        print(f"GFFT3 Python: delta = {delta:.2f} dB")

        assert abs(mag1 - exp1) < TOL, \
            f"{freq1:.4f} Hz: Python={mag1:.2f} dB, oracle={exp1} dB — difference > {TOL} dB"
        assert abs(mag2 - exp2) < TOL, \
            f"{freq2:.4f} Hz: Python={mag2:.2f} dB, oracle={exp2} dB — difference > {TOL} dB"
        assert abs(delta - exp_delta) < TOL, \
            f"Delta: Python={delta:.2f} dB, oracle={exp_delta} dB — difference > {TOL} dB"

    def test_GFFT4_silence_all_bins_below_noise_floor(self):
        """GFFT4: Silence should produce all bins near noise floor (< -100 dB)."""
        sample_rate = 48000.0
        count = int(sample_rate * 0.4)
        signal = np.zeros(count, dtype=np.float32)
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        ceiling = float(gated("GFFT4")["maxDbBelow"])
        max_mag = max(mags)
        print(f"GFFT4 Python: max magnitude for silence = {max_mag:.2f} dB")
        assert max_mag < ceiling, \
            f"All bins should be below {ceiling} dB for silence, max = {max_mag:.2f}"

    def test_GFFT5_after_fix_bin_centred_matches_swift(self):
        """GFFT5: Hann-window normalization (DENORM, unit-peak) parity.

        A bin-centred tone (bin 46, amplitude 0.01) must read -49.70 dB.  This
        pins the window-normalization convention: the wrong (NORM) window would
        inflate the value by ~4.26 dB.  Mirrors Swift
        GatedFFTParityTests.afterFix_binCentred_matchesPython."""
        sample_rate = 48000.0
        (freq, amplitude), = gated("GFFT5")["tones"]
        expected = _expected("GFFT5", freq)
        target_bin = round(freq * 32768 / sample_rate)  # 46, for the printout
        sample_count = int(sample_rate * 0.4)

        t = np.arange(sample_count) / sample_rate
        signal = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)

        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)
        py_db = _magnitude_at_frequency(freq, mags, freqs)

        print(f"GFFT5 Python: bin {target_bin} ({freq:.4f} Hz) = {py_db:.2f} dB")
        assert abs(py_db - expected) < TOL, \
            f"bin {target_bin}: Python={py_db:.2f} dB, oracle={expected} dB — difference > {TOL} dB"
