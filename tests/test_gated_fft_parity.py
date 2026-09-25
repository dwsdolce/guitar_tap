# @parity test/gated-fft
"""
Parity tests for compute_gated_fft, the transform every plate/brace capture runs. GFFT1–GFFT5 feed
the oracle's synthetic signals and assert the oracle's dB, as Swift (GatedFFTParityTests.swift) and
web (gated-fft.test.ts) do — any systematic difference between the implementations shows up as a
one-sided failure. The remaining cases pin rules the oracle cases cannot see: which window is used,
that calibration is applied inside the transform, and that too little input is not a spectrum
(#17 F49).

Test plan coverage: GFFT1–GFFT5
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))

from gated_signal import gated_magnitude_at, make_gated_test_signal  # noqa: E402
from parity_oracle import TOLERANCES, calibration, gated  # noqa: E402

# The cross-edition tolerance for gated-FFT dB, from the oracle.
TOL: float = TOLERANCES["gatedFftDb"]
SAMPLE_RATE = 48000.0


def _analyzer() -> RealtimeFFTAnalyzer:
    """A hardware-free analyzer: no stream, no device enumeration, no calibration loaded."""
    return RealtimeFFTAnalyzer.for_testing(sample_rate=int(SAMPLE_RATE))


def _expected(case_name: str, hz: float) -> float:
    """The oracle dB for one tone of a GFFT case, matched on its target frequency."""
    for e in gated(case_name)["expected"]:
        if abs(float(e["hz"]) - hz) < 1e-6:
            return float(e["db"])
    raise KeyError(f"{case_name}: no expected entry near {hz} Hz")


def _check(name: str) -> None:
    """Run one oracle case and check each expected tone, and the delta where the case records one."""
    spec = gated(name)
    tones = spec["tones"]
    signal = make_gated_test_signal(tones, SAMPLE_RATE)
    mags, freqs = _analyzer().compute_gated_fft(signal, SAMPLE_RATE)

    got = [gated_magnitude_at(float(hz), mags, freqs) for hz, _ in tones]
    for (hz, _), db in zip(tones, got):
        expected = _expected(name, float(hz))
        assert db is not None and abs(db - expected) < TOL, \
            f"{name} {hz} Hz: Python={db} dB, oracle={expected} dB"
    if len(got) >= 2:
        exp_delta = float(spec["deltaDb"])
        delta = got[1] - got[0]
        assert abs(delta - exp_delta) < TOL, \
            f"{name} delta: Python={delta} dB, oracle={exp_delta} dB"


class TestGatedFFTParity:
    """Mirrors Swift GatedFFTParityTests."""

    def test_GFFT1_single_tone_matches_oracle(self):
        """GFFT1: a single tone."""
        _check("GFFT1")

    def test_GFFT2_two_tones_match_oracle(self):
        """GFFT2: two tones at the plate-C capture frequencies that once exposed a discrepancy."""
        _check("GFFT2")

    def test_GFFT3_bin_centred_two_tones_match_oracle(self):
        """GFFT3: two tones whose frequencies are exact bin centres (bins 46 and 80 at 32768 points).

        Being bin centres does NOT remove leakage here: the window spans the padded 32768 samples and
        the signal only the first 19200, so no tone is periodic in the window. The 67 Hz tone reads
        differently here from GFFT5, where it is alone — that difference is leakage from the 117 Hz
        tone.
        """
        _check("GFFT3")

    def test_GFFT4_silence_is_minus_infinity_in_every_bin(self):
        """GFFT4: silence reads exactly the oracle's value — -inf in every bin.

        The oracle stores it as the string "-Infinity", which every edition's reader decodes
        (#17 F44).
        """
        signal = make_gated_test_signal([], SAMPLE_RATE)
        mags, _ = _analyzer().compute_gated_fft(signal, SAMPLE_RATE)

        expected = float(gated("GFFT4")["maxDb"])
        max_mag = float(max(mags))
        assert max_mag == expected, f"silence must read {expected} dB, got {max_mag}"

    def test_GFFT5_bin_centred_single_tone_matches_oracle(self):
        """GFFT5: one bin-centred tone. Pins the window's normalisation: Swift's HANN_NORM instead of
        HANN_DENORM would read about 4.26 dB high."""
        _check("GFFT5")

    def test_gated_window_is_the_periodic_hann(self):
        """The window is the PERIODIC Hann, 0.5·(1 − cos 2πn/N).

        A constant input fills the padded length, so the windowed signal IS the window, and a
        periodic Hann's spectrum is exactly bins 0 and 1: every bin from 2 up is empty. The
        symmetric form, np.hanning's (N−1), leaks into those bins at about −100 dB. The two are
        otherwise too close for any oracle tolerance to tell apart, which is how this edition
        drifted to np.hanning before.
        """
        n = 32768
        mags, _ = _analyzer().compute_gated_fft(np.ones(n, dtype=np.float32), SAMPLE_RATE)
        assert len(mags) == n // 2
        highest = max(mags[2:])
        assert highest < -120, f"bins ≥ 2 must be empty for a periodic Hann; highest is {highest} dB"

    def test_fewer_than_two_samples_gives_an_empty_spectrum(self):
        """Fewer than two samples is not a spectrum: the result is empty, which callers treat as a
        failed capture ("tap again")."""
        for count in (0, 1):
            mags, freqs = _analyzer().compute_gated_fft(np.full(count, 0.5, dtype=np.float32), SAMPLE_RATE)
            assert len(mags) == 0 and len(freqs) == 0, f"{count} sample(s) gave {len(mags)} bins"

    def test_calibration_is_applied_inside_the_gated_transform(self):
        """Calibration is applied INSIDE the transform, from the analyzer's active calibration at the
        moment of the call: the calibrated spectrum is the uncalibrated one plus the calibration's
        correction at every bin. Uses the UMIK-1 calibration fixture the file-playback cases use."""
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration

        cal = MicrophoneCalibration.from_path(calibration("REG-B1"))
        signal = make_gated_test_signal(gated("GFFT2")["tones"], SAMPLE_RATE)

        analyzer = _analyzer()
        plain, freqs = analyzer.compute_gated_fft(signal, SAMPLE_RATE)
        # The gated path reads only the profile; the live-bin corrections are not involved.
        analyzer.set_calibration(None, profile=cal)
        calibrated, cal_freqs = analyzer.compute_gated_fft(signal, SAMPLE_RATE)

        assert list(cal_freqs) == list(freqs)
        corrections = np.asarray(cal.interpolate_to_bins(np.asarray(freqs)))
        plain_arr, cal_arr = np.asarray(plain), np.asarray(calibrated)
        assert len(corrections) == len(plain_arr)
        assert np.any(np.abs(corrections) > 0.5), "the fixture must correct by a visible amount"
        finite = np.isfinite(plain_arr)
        worst = float(np.max(np.abs(cal_arr[finite] - (plain_arr[finite] + corrections[finite]))))
        assert worst <= 1e-4, f"calibrated ≠ uncalibrated + correction; worst bin is off by {worst} dB"
