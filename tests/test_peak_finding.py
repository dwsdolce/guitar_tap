# @parity test/peaks
"""
Port of PeakFindingTests.swift — peak finding, deduplication, spectrum averaging.

Mirrors Swift test plan coverage F10–F16 and A1–A5, plus the duplicate-peak
regression D1/D2/D4 (Development/PEAK-FINDING-DUPLICATE-PEAKS.md in GuitarTapWeb).

REWRITTEN 2026-07-19 — this file previously did not test the code it claimed to.
F10–F14 exercised ``peak_detection`` from the FFT layer rather than
``TapToneAnalyzer.find_peaks``; F15–F16 and A1–A5 called *reimplementations of the
production logic written inside this test file* (``_deduplicate_2hz``,
``_power_average_db``), so they could not fail however the app behaved. Swift's
equivalents call ``sut.findPeaks``, ``sut.removeDuplicatePeaks`` and
``sut.averageSpectra``; these now do the same:

  findPeaks (Swift)            → TapToneAnalyzer.find_peaks
  removeDuplicatePeaks (Swift) → TapToneAnalyzer.remove_duplicate_peaks
  averageSpectra (Swift)       → TapToneAnalyzer.average_spectra

The FFT-layer tests that used to live here are preserved in
test_fft_peak_detection.py, outside this parity group.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from guitar_tap.models.guitar_mode import GuitarMode  # noqa: E402
from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

SAMPLE_RATE = 48000


# ---------------------------------------------------------------------------
# Helpers — mirror the Swift makeSUT / makeSpectrum / combineSpectra helpers
# ---------------------------------------------------------------------------


def make_sut() -> TapToneAnalyzer:
    """Mirrors Swift makeSUT()."""
    return TapToneAnalyzer.for_testing()


def make_spectrum(
    peak_hz: float,
    bin_count: int = 2048,
    sample_rate: int = SAMPLE_RATE,
    peak_db: float = -20.0,
    half_width_hz: float = 5.0,
    noise_floor: float = -100.0,
) -> tuple[list[float], list[float]]:
    """Gaussian peak on a noise floor. Mirrors Swift makeSpectrum(...)."""
    bin_width = (sample_rate / 2) / (bin_count - 1)
    sigma = half_width_hz / 2.355
    freqs = [i * bin_width for i in range(bin_count)]
    mags = [
        max(noise_floor, peak_db + (-((f - peak_hz) ** 2) / (2 * sigma * sigma)))
        for f in freqs
    ]
    return mags, freqs


def combine_spectra(a: tuple[list, list], b: tuple[list, list]) -> tuple[list, list]:
    """Element-wise maximum of two spectra. Mirrors Swift combineSpectra(_:_:)."""
    return [max(x, y) for x, y in zip(a[0], b[0])], a[1]


def _flat(value: float, bin_count: int = 2048) -> tuple[list[float], list[float]]:
    bin_width = (SAMPLE_RATE / 2) / (bin_count - 1)
    return [value] * bin_count, [i * bin_width for i in range(bin_count)]


# ---------------------------------------------------------------------------
# FindPeaks Tests  (F10–F14)
# ---------------------------------------------------------------------------


class TestFindPeaks:
    """Mirrors Swift FindPeaksTests (F10–F14)."""

    def test_F10_single_tone_above_threshold_detected(self):
        sut = make_sut()
        sut.peak_min_threshold = -60
        sut.min_frequency = 50
        sut.max_frequency = 2000

        mags, freqs = make_spectrum(peak_hz=1000, peak_db=-20, half_width_hz=15)
        peaks = sut.find_peaks(mags, freqs)

        assert len(peaks) >= 1, "Should detect at least 1 peak above threshold"
        assert any(abs(p.frequency - 1000) < 25 for p in peaks), (
            f"Expected a peak near 1000 Hz; got {[round(p.frequency, 1) for p in peaks]}"
        )

    def test_F11_silence_produces_no_peaks(self):
        sut = make_sut()
        sut.peak_min_threshold = -60
        mags, freqs = _flat(-100.0)
        assert sut.find_peaks(mags, freqs) == []

    def test_F12_clipped_flat_spectrum_produces_no_peaks(self):
        """A perfectly flat spectrum has no strict local maximum."""
        sut = make_sut()
        sut.peak_min_threshold = -60
        mags, freqs = _flat(-20.0)
        assert sut.find_peaks(mags, freqs) == []

    def test_F13_multiple_tones_all_detected(self):
        sut = make_sut()
        sut.peak_min_threshold = -60
        sut.min_frequency = 50
        sut.max_frequency = 2000

        p1 = make_spectrum(peak_hz=400, peak_db=-20, half_width_hz=15)
        p2 = make_spectrum(peak_hz=700, peak_db=-22, half_width_hz=15)
        p3 = make_spectrum(peak_hz=1000, peak_db=-25, half_width_hz=15)
        mags, freqs = combine_spectra(combine_spectra(p1, p2), p3)

        peaks = sut.find_peaks(mags, freqs)
        assert len(peaks) >= 3, f"Expected >= 3 peaks, got {len(peaks)}"

        bin_width = (SAMPLE_RATE / 2) / 2047
        for target in (400, 700, 1000):
            assert any(abs(p.frequency - target) < bin_width * 2 for p in peaks), (
                f"No peak near {target} Hz in {[round(p.frequency, 1) for p in peaks]}"
            )

    def test_F14_all_below_threshold_returns_empty(self):
        sut = make_sut()
        sut.peak_min_threshold = -10  # above the tone
        mags, freqs = make_spectrum(peak_hz=1000, peak_db=-30)
        assert sut.find_peaks(mags, freqs) == []


# ---------------------------------------------------------------------------
# RemoveDuplicatePeaks Tests  (F15–F16)
# ---------------------------------------------------------------------------


class TestRemoveDuplicatePeaks:
    """Mirrors Swift RemoveDuplicatePeaksTests (F15–F16) — calls the real method."""

    def test_F15_close_peaks_keep_higher_magnitude(self):
        sut = make_sut()
        lower = ResonantPeak(frequency=440.0, magnitude=-30.0)
        higher = ResonantPeak(frequency=441.0, magnitude=-20.0)  # 1 Hz apart

        result = sut.remove_duplicate_peaks([lower, higher])
        assert len(result) == 1, f"Duplicate within 2 Hz should collapse; got {result}"
        assert result[0].magnitude == -20.0, "The louder peak should survive"

    def test_F16_well_separated_peaks_keep_both(self):
        sut = make_sut()
        p1 = ResonantPeak(frequency=440.0, magnitude=-30.0)
        p2 = ResonantPeak(frequency=445.0, magnitude=-20.0)  # 5 Hz apart

        result = sut.remove_duplicate_peaks([p1, p2])
        assert len(result) == 2, f"Both peaks should survive; got {result}"


# ---------------------------------------------------------------------------
# Spectrum Averaging Tests  (A1–A5)
# ---------------------------------------------------------------------------


class TestSpectrumAveraging:
    """Mirrors Swift SpectrumAveragingTests (A1–A5) — calls the real method."""

    @staticmethod
    def _tap(mags: list[float]) -> tuple:
        return (mags, [float(i) for i in range(len(mags))], 0.0)

    def test_A1_average_of_identical_spectra_is_unchanged(self):
        sut = make_sut()
        spec = [-30.0, -40.0, -50.0, -35.0]
        mags, _ = sut.average_spectra([self._tap(list(spec)) for _ in range(3)])
        np.testing.assert_allclose(mags, spec, atol=0.01)

    def test_A2_power_domain_averaging_correct_result(self):
        """avg(-10 dB, -20 dB) = 10*log10((0.1 + 0.01)/2)."""
        sut = make_sut()
        mags, _ = sut.average_spectra([self._tap([-10.0]), self._tap([-20.0])])
        expected = 10.0 * np.log10((10 ** (-1.0) + 10 ** (-2.0)) / 2.0)
        np.testing.assert_allclose(mags, [expected], atol=0.001)

    def test_A3_single_tap_average_equals_itself(self):
        sut = make_sut()
        spec = [-25.0, -30.0, -45.0, -60.0]
        mags, _ = sut.average_spectra([self._tap(list(spec))])
        np.testing.assert_allclose(mags, spec, atol=0.001)

    def test_A4_empty_input_returns_empty(self):
        sut = make_sut()
        mags, freqs = sut.average_spectra([])
        assert mags == [] and freqs == []

    def test_A5_louder_spectrum_dominates_power_average(self):
        sut = make_sut()
        mags, _ = sut.average_spectra([self._tap([-10.0] * 8), self._tap([-40.0] * 8)])
        assert all(m > -15.0 for m in mags), (
            "Power average should sit closer to the louder spectrum"
        )


# ---------------------------------------------------------------------------
# Duplicate-peak regression  (D1, D2, D4)
#
# find_peaks must never return two peaks for one spectral feature. It did: the
# per-mode scan visited a bin once per overlapping mode range, minting a fresh id
# each time, and the final assembly reconciled two independently deduplicated
# lists **by id** — so the twin survived.
#
# Authored against the UNFIXED code; expected to fail until detection stops being
# interleaved with classification.
# ---------------------------------------------------------------------------

PEAK_PROXIMITY_HZ = 2.0


def expect_no_duplicate_peaks(peaks: list, label: str) -> None:
    """D1 — the uniqueness invariant."""
    offenders = []
    for i in range(len(peaks)):
        for j in range(i + 1, len(peaks)):
            delta = abs(peaks[i].frequency - peaks[j].frequency)
            if delta < PEAK_PROXIMITY_HZ:
                offenders.append(
                    f"{peaks[i].frequency:.5f} Hz @ {peaks[i].magnitude:.2f} dB and "
                    f"{peaks[j].frequency:.5f} Hz @ {peaks[j].magnitude:.2f} dB "
                    f"({delta:.5f} apart)"
                )
    assert not offenders, (
        f"{label}: duplicate peaks — {'; '.join(offenders)}. "
        "find_peaks must return one peak per spectral feature."
    )


class TestFindPeaksDuplicates:
    """Mirrors Swift FindPeaksDuplicateTests (D1, D2, D4)."""

    # Generic ranges: Top 140–260 Hz, Back 180–300 Hz — overlapping at 180–260.
    # Every duplicate observed in the field sits in that band.
    #
    # Resolution matters. The suite's default 2048-bin spectrum has a ~11.7 Hz bin
    # width, so the +/-5-bin local-max window spans +/-58 Hz and two peaks 7 Hz apart
    # can never both be detected. Real captures use 32768 bins (+/-3.7 Hz), which is
    # why the field data shows adjacent overlap peaks the synthetic suite could not
    # produce. Do not "simplify" bin_count back to the default — it disarms the test.
    #
    # The weak peak must be far enough from the Back winner to survive as its own local
    # maximum. An earlier version placed it at 232 Hz with half_width_hz 8, where the
    # 240 Hz peak's tail reaches -52.8 dB and buries a -56 dB peak entirely — so the
    # spectrum only ever held TWO features, and `len == 3` passed only because the
    # duplicate made up the number. That assertion would have masked the fix.
    def _overlap_spectrum(self):
        bins = 32768
        top = make_spectrum(peak_hz=195, bin_count=bins, peak_db=-40, half_width_hz=4)
        weak = make_spectrum(peak_hz=210, bin_count=bins, peak_db=-56, half_width_hz=4)
        back = make_spectrum(peak_hz=240, bin_count=bins, peak_db=-50, half_width_hz=4)
        return combine_spectra(combine_spectra(top, weak), back)

    def _overlap_sut(self) -> TapToneAnalyzer:
        TDS.set_guitar_type("Generic")
        sut = make_sut()
        sut.peak_min_threshold = -60
        sut.min_frequency = 30
        sut.max_frequency = 2000
        return sut

    def test_D2_overlap_zone_returns_one_peak_per_feature(self):
        sut = self._overlap_sut()
        mags, freqs = self._overlap_spectrum()

        peaks = sut.find_peaks(mags, freqs)

        expect_no_duplicate_peaks(peaks, "Top/Back overlap")
        assert len(peaks) == 3, (
            f"Expected 3 peaks for 3 spectral features, got {len(peaks)}: "
            f"{[round(p.frequency, 2) for p in peaks]}"
        )

    def test_D2b_overlap_zone_classifies_top_and_back(self):
        sut = self._overlap_sut()
        mags, freqs = self._overlap_spectrum()

        peaks = sut.find_peaks(mags, freqs)
        mode_map = GuitarMode.classify_all(peaks, TDS.guitar_type())

        top = next((p for p in peaks if mode_map.get(p.id) == GuitarMode.TOP), None)
        back = next((p for p in peaks if mode_map.get(p.id) == GuitarMode.BACK), None)

        assert top is not None, "no Top peak identified"
        assert back is not None, "no Back peak identified"
        assert abs(top.frequency - 195) < 5, f"Top at {top.frequency}, expected ~195"
        assert abs(back.frequency - 240) < 5, f"Back at {back.frequency}, expected ~240"

    def test_D1_multiple_tones_contain_no_duplicates(self):
        sut = make_sut()
        sut.peak_min_threshold = -60
        sut.min_frequency = 50
        sut.max_frequency = 2000

        p1 = make_spectrum(peak_hz=400, peak_db=-20, half_width_hz=15)
        p2 = make_spectrum(peak_hz=700, peak_db=-22, half_width_hz=15)
        p3 = make_spectrum(peak_hz=1000, peak_db=-25, half_width_hz=15)
        mags, freqs = combine_spectra(combine_spectra(p1, p2), p3)

        expect_no_duplicate_peaks(sut.find_peaks(mags, freqs), "three distinct tones")

    def test_D4_winner_invariants_hold_on_overlap_spectrum(self):
        sut = self._overlap_sut()
        mags, freqs = self._overlap_spectrum()

        peaks = sut.find_peaks(mags, freqs)
        mode_map = GuitarMode.classify_all(peaks, TDS.guitar_type())
        selected = sut.guitar_mode_selected_peak_ids(peaks)

        # At most one peak per named mode is SELECTED.
        #
        # Note this counts *selected* peaks, not *labelled* ones. classify_all deliberately
        # labels additional peaks: an unclaimed peak above the claimed Top and inside the Back
        # range resolves to BACK too, so several peaks can carry the same label while only one
        # is claimed as that mode's winner. An earlier version asserted at most one *labelled*
        # peak per mode, which is not an invariant of the algorithm — it only appeared to hold
        # because the overlap spectrum had a swamped third peak that was never detected.
        per_mode: dict = {}
        for p in peaks:
            if p.id not in selected:
                continue
            m = mode_map.get(p.id)
            if m is None or m == GuitarMode.UNKNOWN:
                continue
            per_mode[m] = per_mode.get(m, 0) + 1
        for mode, count in per_mode.items():
            assert count <= 1, f"{mode} selected {count} peaks; at most 1 expected"

        top = next((p for p in peaks if mode_map.get(p.id) == GuitarMode.TOP), None)
        back = next((p for p in peaks if mode_map.get(p.id) == GuitarMode.BACK), None)
        if top and back:
            assert back.frequency > top.frequency, (
                f"Back ({back.frequency} Hz) must be above Top ({top.frequency} Hz)"
            )

        ids = {p.id for p in peaks}
        assert selected <= ids, "selected peak ids contain ids absent from the peak list"