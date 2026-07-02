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
        """GFFT1: A single 100 Hz sine at amplitude 0.5.  Swift pins -15.72 dB."""
        sample_rate = 48000.0
        signal = _make_two_tone_signal(
            sample_rate=sample_rate, duration=0.4,
            freq1=100, amp1=0.5,
            freq2=0, amp2=0,
        )
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        mag100 = _magnitude_at_frequency(100, mags, freqs)
        assert mag100 is not None, "Should find bin near 100 Hz"
        print(f"GFFT1 Python: 100 Hz magnitude = {mag100:.2f} dB")
        assert abs(mag100 - (-15.72)) < 1.0, \
            f"100 Hz: Python={mag100:.2f} dB, Swift=-15.72 dB — difference > 1 dB"

    def test_GFFT2_two_tone_67Hz_and_117Hz_magnitudes_match(self):
        """GFFT2: Two tones at 67 Hz and 117 Hz with known amplitudes.
        This mirrors the exact frequencies from the plate C capture discrepancy."""
        sample_rate = 48000.0
        signal = _make_two_tone_signal(
            sample_rate=sample_rate, duration=0.4,
            freq1=67, amp1=0.01,
            freq2=117, amp2=0.1,
        )
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        mag67 = _magnitude_at_frequency(67, mags, freqs)
        mag117 = _magnitude_at_frequency(117, mags, freqs)
        assert mag67 is not None and mag117 is not None, \
            "Should find bins near 67 and 117 Hz"

        print(f"GFFT2 Python: 67 Hz = {mag67:.2f} dB, 117 Hz = {mag117:.2f} dB")
        delta = mag117 - mag67
        print(f"GFFT2 Python: delta (117 - 67) = {delta:.2f} dB")
        # Swift pins: 67 Hz = -49.74 dB, 117 Hz = -29.55 dB, delta = 20.19 dB.
        assert abs(mag67 - (-49.74)) < 1.0, \
            f"67 Hz: Python={mag67:.2f} dB, Swift=-49.74 dB — difference > 1 dB"
        assert abs(mag117 - (-29.55)) < 1.0, \
            f"117 Hz: Python={mag117:.2f} dB, Swift=-29.55 dB — difference > 1 dB"
        assert abs(delta - 20.19) < 1.0, \
            f"Delta: Python={delta:.2f} dB, Swift=20.19 dB — difference > 1 dB"

    def test_GFFT3_bin_centred_tones_exact_magnitudes(self):
        """GFFT3: Exact bin-centred tones to eliminate spectral leakage.
        With paddedSize=32768 and sampleRate=48000, binWidth=1.46484375 Hz.
        Bin 46 = 67.3828125 Hz, Bin 80 = 117.1875 Hz"""
        sample_rate = 48000.0
        padded_size = 32768
        bin_width = sample_rate / padded_size
        freq1 = 46 * bin_width   # 67.3828125 Hz
        freq2 = 80 * bin_width   # 117.1875 Hz
        amp1 = 0.01
        amp2 = 0.1

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

        # Swift pins: 67.3828 Hz = -49.70 dB, 117.1875 Hz = -29.51 dB, delta = 20.19 dB.
        assert abs(mag1 - (-49.70)) < 1.0, \
            f"{freq1:.4f} Hz: Python={mag1:.2f} dB, Swift=-49.70 dB — difference > 1 dB"
        assert abs(mag2 - (-29.51)) < 1.0, \
            f"{freq2:.4f} Hz: Python={mag2:.2f} dB, Swift=-29.51 dB — difference > 1 dB"
        assert abs(delta - 20.19) < 1.0, \
            f"Delta: Python={delta:.2f} dB, Swift=20.19 dB — difference > 1 dB"

    def test_GFFT4_silence_all_bins_below_noise_floor(self):
        """GFFT4: Silence should produce all bins near noise floor (< -100 dB)."""
        sample_rate = 48000.0
        count = int(sample_rate * 0.4)
        signal = np.zeros(count, dtype=np.float32)
        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)

        max_mag = max(mags)
        print(f"GFFT4 Python: max magnitude for silence = {max_mag:.2f} dB")
        assert max_mag < -100, \
            f"All bins should be below -100 dB for silence, max = {max_mag:.2f}"

    def test_GFFT5_after_fix_bin_centred_matches_swift(self):
        """GFFT5: Hann-window normalization (DENORM, unit-peak) parity.

        A bin-centred tone (bin 46, amplitude 0.01) must read -49.70 dB.  This
        pins the window-normalization convention: the wrong (NORM) window would
        inflate the value by ~4.26 dB.  Mirrors Swift
        GatedFFTParityTests.afterFix_binCentred_matchesPython."""
        sample_rate = 48000.0
        n = 32768
        target_bin = 46
        amplitude = 0.01
        sample_count = int(sample_rate * 0.4)
        freq = target_bin * sample_rate / n

        t = np.arange(sample_count) / sample_rate
        signal = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)

        pt = _make_proc_thread()
        mags, freqs = pt.compute_gated_fft(signal, sample_rate)
        py_db = _magnitude_at_frequency(freq, mags, freqs)

        print(f"GFFT5 Python: bin {target_bin} ({freq:.4f} Hz) = {py_db:.2f} dB")
        assert abs(py_db - (-49.70)) < 1.0, \
            f"bin 46: Python={py_db:.2f} dB, Swift=-49.70 dB — difference > 1 dB"
