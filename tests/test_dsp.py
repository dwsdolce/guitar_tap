# @parity test/dsp
"""
Port of DSPTests.swift — parabolic interpolation and Q-factor calculation (F1–F9).

REWRITTEN 2026-09-20 (#17) — this file previously did not test the code the app runs.

It exercised ``peak_interp`` and ``peak_q_factor`` from
``realtime_fft_analyzer_fft_processing``: NumPy ports of the peak-finding section of Swift's
findPeaks that **nothing in the application ever called**. The app uses the scalar pair on
TapToneAnalyzer — ``_parabolic_interpolate`` and ``_calculate_q_factor`` — which are the direct
counterparts of Swift's ``parabolicInterpolate`` / ``calculateQFactor`` and are what the capture
and peak-analysis paths run. Those had no test at all.

So test/dsp paired Swift's tests of the live code with this edition's tests of a second,
unused implementation. Swift and the web each have exactly one; the duplicate was Python-only.
The dead trio (peak_detection, peak_interp, peak_q_factor) has been removed, and these tests now
call what the app calls.

This is the same defect test_peak_finding.py records finding on 2026-07-19 in test/peaks. It was
fixed there by relocating the FFT-layer tests rather than repointing them, which left this copy
alive and the sibling slug untouched. See SLUG-SWEEP.md F14.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402


def _sut() -> TapToneAnalyzer:
    """The analyzer, which owns both functions under test. Mirrors Swift's makeSUT()."""
    return TapToneAnalyzer()


def _spectrum(
    peak_hz: float,
    peak_db: float,
    half_width: float,
    bin_count: int = 2048,
    sample_rate: int = 48000,
    noise_floor: float = -100.0,
) -> tuple[list[float], list[float]]:
    """A Gaussian peak on a noise floor — the same synthetic spectrum Swift's makeSpectrum
    builds, with the same defaults, so the Q cases compare like with like."""
    bin_width = (sample_rate / 2) / (bin_count - 1)
    sigma = half_width / 2.355
    mags: list[float] = []
    freqs: list[float] = []
    for i in range(bin_count):
        f = i * bin_width
        freqs.append(f)
        dist = f - peak_hz
        gauss = peak_db + (-dist * dist / (2 * sigma * sigma))
        mags.append(max(gauss, noise_floor))
    return mags, freqs


def _index_of_max(values: list[float]) -> int:
    return max(range(len(values)), key=lambda i: values[i])


# ---------------------------------------------------------------------------
# Parabolic interpolation (F1–F6). Mirrors Swift ParabolicInterpolationTests.
# ---------------------------------------------------------------------------

class TestParabolicInterpolation:
    """Mirrors Swift ParabolicInterpolationTests."""

    def test_F1_equal_neighbours_give_the_exact_centre_bin(self):
        """Both neighbours equal → the numerator (lval - rval) is 0, so δ = 0."""
        sut = _sut()
        mags = [-80.0, -80.0, -30.0, -30.0, -30.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, _ = sut._parabolic_interpolate(mags, freqs, 3)
        assert abs(freq - 30) < 0.01, f"expected ≈30 Hz, got {freq}"

    def test_F2_higher_left_neighbour_shifts_the_peak_left(self):
        sut = _sut()
        mags = [-80.0, -80.0, -25.0, -20.0, -35.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, _ = sut._parabolic_interpolate(mags, freqs, 3)
        assert freq < 30, f"expected a left shift, got {freq}"

    def test_F3_higher_right_neighbour_shifts_the_peak_right(self):
        sut = _sut()
        mags = [-80.0, -80.0, -35.0, -20.0, -25.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, _ = sut._parabolic_interpolate(mags, freqs, 3)
        assert freq > 30, f"expected a right shift, got {freq}"

    def test_F4_bin_zero_falls_back_to_the_raw_bin(self):
        """Rather than reading index -1."""
        sut = _sut()
        mags = [-20.0, -30.0, -40.0, -50.0]
        freqs = [0.0, 10.0, 20.0, 30.0]
        freq, mag = sut._parabolic_interpolate(mags, freqs, 0)
        assert freq == 0.0
        assert mag == -20.0

    def test_F4b_last_bin_falls_back_to_the_raw_bin(self):
        """Rather than reading past the end."""
        sut = _sut()
        mags = [-50.0, -40.0, -30.0, -20.0]
        freqs = [0.0, 10.0, 20.0, 30.0]
        freq, mag = sut._parabolic_interpolate(mags, freqs, len(mags) - 1)
        assert freq == 30.0
        assert mag == -20.0

    def test_F5_flat_top_gives_neither_nan_nor_inf(self):
        """lval = val = rval, so the denominator is exactly 0.

        Without the guard this is 0/0 → NaN, and a NaN frequency travels into the saved
        measurement.
        """
        sut = _sut()
        mags = [-80.0, -80.0, -20.0, -20.0, -20.0, -80.0, -80.0]
        freqs = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        freq, mag = sut._parabolic_interpolate(mags, freqs, 3)
        assert not math.isnan(freq) and math.isfinite(freq)
        assert not math.isnan(mag) and math.isfinite(mag)
        # And it returns the raw bin, not something invented.
        assert freq == 30.0
        assert mag == -20.0

    def test_F6_interpolated_magnitude_is_at_least_the_bin_magnitude(self):
        """The parabola's apex sits at or above the sampled bins when the centre is a local max."""
        sut = _sut()
        mags, freqs = _spectrum(peak_hz=200, peak_db=-15, half_width=8)
        i = _index_of_max(mags)
        _, interp_mag = sut._parabolic_interpolate(mags, freqs, i)
        assert interp_mag >= mags[i] - 0.5, f"{interp_mag} should be ≥ {mags[i]}"


# ---------------------------------------------------------------------------
# Q factor and −3 dB bandwidth (F7–F9). Mirrors Swift QFactorTests.
# ---------------------------------------------------------------------------

class TestQFactor:
    """Mirrors Swift QFactorTests."""

    def test_F7_sharp_peak_has_a_higher_q_than_a_broad_one(self):
        sut = _sut()
        sharp_mags, sharp_freqs = _spectrum(peak_hz=200, peak_db=-20, half_width=20)
        broad_mags, broad_freqs = _spectrum(peak_hz=200, peak_db=-20, half_width=80)
        si = _index_of_max(sharp_mags)
        bi = _index_of_max(broad_mags)
        sharp_q, sharp_bw = sut._calculate_q_factor(sharp_mags, sharp_freqs, si, sharp_mags[si])
        broad_q, _ = sut._calculate_q_factor(broad_mags, broad_freqs, bi, broad_mags[bi])
        assert sharp_q > broad_q, f"sharp {sharp_q} should exceed broad {broad_q}"
        assert sharp_bw > 0
        assert sharp_q > 0

    def test_F8_broad_peak_gives_a_plausible_low_q(self):
        """80 Hz half-width at 200 Hz → Q ≈ 200/160 ≈ 1.25."""
        sut = _sut()
        mags, freqs = _spectrum(peak_hz=200, peak_db=-20, half_width=80)
        i = _index_of_max(mags)
        q, _ = sut._calculate_q_factor(mags, freqs, i, mags[i])
        assert 0 < q < 15, f"expected 0 < Q < 15 for a broad peak, got {q}"

    def test_F9_no_bin_below_threshold_means_bandwidth_spans_the_spectrum(self):
        """When nothing drops 3 dB below the peak, the walk runs to both edges.

        This was called ``test_F9_peak_with_all_bins_above_threshold_returns_zero`` and asserted
        only ``q >= 0``. Q is centre/span here, not 0 — the name promised a behaviour the body
        never checked and that does not hold. A test name is a comment. See SLUG-SWEEP.md F14.
        """
        sut = _sut()
        n = 100
        mags = [-20.0] * n
        freqs = [i * 10.0 for i in range(n)]
        q, bw = sut._calculate_q_factor(mags, freqs, 50, -20.0)
        # The walk reaches bin 0 and bin 99, so the bandwidth is the full span: 990 - 0.
        assert abs(bw - 990.0) < 1e-3, f"bandwidth should span the spectrum, got {bw}"
        # Q = centre / span = 500 / 990.
        assert abs(q - 0.50505) < 1e-4, f"Q should be centre/span ≈ 0.505, got {q}"
        assert math.isfinite(q) and not math.isnan(q)


# ---------------------------------------------------------------------------
# A silent buffer yields -inf, not a finite floor
# ---------------------------------------------------------------------------

class TestSilentBufferIsNegativeInfinity:
    """A bin with no energy must read -inf, not a clamped number.

    All three editions convert magnitude with 20*log10, so an empty bin is -inf, and that is what
    Swift's vDSP_vdbcon returns.  Python and web had each clamped the magnitude up to float64
    epsilon first -- the SAME literal, 2.220446049250313e-16, Python's since 2026-05-09 and web's
    transcribed from it -- which put "-313.0 dB" on screen for the absence of a signal.

    It matters because -100 dB is a REAL reading: a live UMIK-1 in a quiet room sits near there, and
    it is the dead-input watchdog's own threshold.  A finite floor makes "no microphone at all" look
    like "a very quiet microphone", which is the one distinction the Peak readout has to keep.
    Owner's call during the #17 run-review, having seen -inf on Swift and -313 here.

    Python carried the clamp TWICE -- the live per-frame path (dft_anal) and the gated capture path
    (compute_gated_fft).  Only the live one reaches the Peak readout, which is why removing the
    other first would have looked like a fix and changed nothing on screen.

    Paired with Swift DSPTests and web test/dsp.test.ts.
    """

    def test_every_bin_of_a_silent_buffer_is_negative_infinity(self):
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer_fft_processing import dft_anal

        mag, _abs_fft = dft_anal(np.zeros(1024, dtype=np.float32), np.ones(1024), 1024)
        assert np.all(np.isneginf(mag)), "an all-zero buffer must be -inf in every bin"

    def test_the_floor_is_not_a_finite_epsilon(self):
        """The -313 dB regression: a clamp at float64 eps reads as a precise measurement."""
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer_fft_processing import dft_anal

        mag, _ = dft_anal(np.zeros(1024, dtype=np.float32), np.ones(1024), 1024)
        peak = float(np.max(mag))
        assert not math.isfinite(peak), f"silence must not report a finite level, got {peak}"

    def test_the_gated_path_is_also_unclamped(self):
        """The GATED capture path carried the identical clamp and is fixed with the live one.

        Removing only one of the two would have looked like a fix and changed nothing on screen:
        the Peak readout reads the live path, so the gated clamp was invisible there — and the live
        clamp was invisible in any test that only drove the gated path.  Swift pins this path too
        (its live path cannot be called without starting the engine); web pins both.
        """
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

        # A real instance: the method reads self._calibration_profile under a lock. Constructing
        # the analyzer opens no audio device — the existing _sut() helper relies on the same thing.
        mags, _freqs = RealtimeFFTAnalyzer(None).compute_gated_fft(
            np.zeros(4096, dtype=np.float32), 48000.0
        )
        assert len(mags) > 0, "precondition: the gated FFT produced a spectrum"
        assert all(math.isinf(m) and m < 0 for m in mags), (
            "an all-zero buffer must be -inf in every bin of the gated path too"
        )

    def test_the_live_peak_of_silence_is_negative_infinity_at_zero_hz(self):
        """The model's live peak — what the status bar and the Metrics panel both show.

        Swift's RealtimeFFTAnalyzer owns peakFrequency / peakMagnitude and takes the first maximum
        on ties (max(by:)), so an all -inf spectrum reports bin 0: "-∞ dB @ 0.0 Hz". perform_fft
        now owns the same pair. Before it did, Python's Metrics panel read the detected-peaks list
        instead, which is empty on silence (and after any live capture) and showed "—".
        """
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        from guitar_tap.models.realtime_fft_analyzer_fft_processing import perform_fft

        a = RealtimeFFTAnalyzer(None)
        assert (a.peak_frequency, a.peak_magnitude) == (0.0, -100.0), "starts at Swift's silent state"

        perform_fft(a, np.zeros(a.fft_size, dtype=np.float32), a.fft_size)
        assert a.peak_frequency == 0.0
        assert math.isinf(a.peak_magnitude) and a.peak_magnitude < 0

    def test_a_tones_live_peak_lands_within_one_bin(self):
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        from guitar_tap.models.realtime_fft_analyzer_fft_processing import perform_fft

        a = RealtimeFFTAnalyzer(None)
        n = a.fft_size
        t = np.arange(n)
        perform_fft(a, (0.5 * np.sin(2 * np.pi * 1000.0 * t / a.rate)).astype(np.float32), n)
        assert abs(a.peak_frequency - 1000.0) < a.rate / n, "a tone's peak lands within one bin"
        assert math.isfinite(a.peak_magnitude)

    def test_a_silent_chunk_reads_negative_infinity_on_the_readout_detection_sees_minus_100(self):
        """True digital silence: the READOUT is -inf; detection's level is -100, as Swift's.

        -100 dB is a real level (a quiet UMIK-1 reaches it), so the material level readout must not
        show it for no signal at all. Detection keeps -100 — Swift's rule. Python used
        max(rms, 1e-10), i.e. -200, written independently of Swift, so on true silence its
        detection saw a different level than Swift's. Paired with Swift SilentBufferTests.
        """
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

        a = RealtimeFFTAnalyzer(None)
        seen: list[float] = []
        a.rms_level_handler = lambda level_db, _t: seen.append(level_db)
        a.process_raw_samples(np.zeros(1024, dtype=np.float32))
        assert seen == [-100.0], f"detection's level on silence must be Swift's -100, got {seen}"
        assert math.isinf(a.readout_level_db) and a.readout_level_db < 0

    def test_a_real_chunk_reads_the_same_level_on_the_readout_and_for_detection(self):
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

        a = RealtimeFFTAnalyzer(None)
        seen: list[float] = []
        a.rms_level_handler = lambda level_db, _t: seen.append(level_db)
        t = np.arange(1024)
        a.process_raw_samples((0.01 * np.sin(2 * np.pi * 1000 * t / 48000)).astype(np.float32))
        assert len(seen) == 1 and math.isfinite(seen[0]) and seen[0] > -100
        assert a.readout_level_db == seen[0]

    def test_a_real_signal_is_unaffected(self):
        """The clamp never applied to real audio -- removing it must not move any real value."""
        import numpy as np
        from guitar_tap.models.realtime_fft_analyzer_fft_processing import dft_anal

        n = 1024
        t = np.arange(n, dtype=np.float64)
        sig = (0.5 * np.sin(2 * np.pi * 1000 * t / 48000)).astype(np.float32)
        mag, _ = dft_anal(sig, np.ones(n), n)   # rectangular window, as the live path uses
        peak = float(np.max(mag))
        assert math.isfinite(peak)
        assert peak > -60, f"a half-scale tone should be well above -60 dB, got {peak}"
