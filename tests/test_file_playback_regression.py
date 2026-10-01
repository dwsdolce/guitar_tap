# @parity test/file-playback
"""
End-to-end regression tests for the full file-playback pipeline:
  WAV read → chunk pacing → RMS → tap detection → gated capture →
  FFT (rectangular window for the guitar capture, Hann for the material one) →
  peak selection → mode identification (guitar) / L→C→FLC phases (material)

The analyzer is created via ``TapToneAnalyzer.for_testing()`` (no audio
hardware) and fed via ``playback_support.play_file_and_wait``, which runs the app's own
``play_file`` (the Play File path).

The expected values are the shared oracle's (parity-oracle.json): Swift mints them from its
pipeline and asserts them at zero; Python reads the same file.

Cases: REG-B2, REG-B1, REG-G1, the REG-G ring-out, REG-G2, REG-P1, OUT-4, REG-P2, session
recording, playback calibration.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType

sys.path.insert(0, os.path.dirname(__file__))

from playback_support import play_file_and_wait  # noqa: E402
from parity_oracle import (  # noqa: E402  (follows the src path insert, like the imports above)
    TOLERANCES,
    calibration,
    case,
    fixture,
    peak,
)

# ---------------------------------------------------------------------------
# Expected values - ALL from the shared oracle (tests/parity-oracle.json)
#
# These used to be literals here, typed out again in the Swift suite and a third
# time in the web suite. Three copies of one contract kept equal by hand is the
# drift the oracle exists to remove: change a number in one place now and the
# other editions see it on their next sync-oracle run.
# ---------------------------------------------------------------------------

# brace-umik-1-swift-mac-1778816093.wav — Brace bar, UMIK-1 mic, 48 kHz.
# Full-session recording (mono float32, 48 kHz). The oracle's values originally came from the
# matching .guitartap file (Tests/Brace/brace-umik-1-swift-mac-1778816093.guitartap).
# Python asserts the oracle's values at the cross-edition `tolerances` — whether it agrees with Swift,
# which mints them and asserts them at zero; Python's own zero-bar check is its self-regression.
_B1 = peak("REG-B1", "longitudinal")
BRACE_EXPECTED_FREQ = _B1["frequency"]
BRACE_EXPECTED_MAG = _B1["magnitude"]
BRACE_EXPECTED_Q = _B1["q"]
BRACE_TAP_THRESHOLD = case("REG-B1")["settings"]["tapDetectionThreshold"]
FREQ_TOLERANCE = TOLERANCES["freqHz"]
MAG_TOLERANCE = TOLERANCES["magDb"]

# WAV file path — same file used in the Swift test suite.
BRACE_WAV = fixture("REG-B1")

# REG-B2 — the brace counterpart to REG-P2: three taps, averaged. REG-P2 pins PLATE multi-tap and
# REG-B1 is single-tap brace, so this is the case that exercises brace averaging. Deliberately harder
# than the other material fixtures — the UMIK-1 is on its 18 dB gain path, so the peak sits at
# -65.5 dB against a -63.9 dB detection threshold.
_B2 = peak("REG-B2", "longitudinal")
BRACE3_EXPECTED_FREQ = _B2["frequency"]
BRACE3_EXPECTED_MAG = _B2["magnitude"]
BRACE3_EXPECTED_Q = _B2["q"]
BRACE3_TAP_THRESHOLD = case("REG-B2")["settings"]["tapDetectionThreshold"]
BRACE3_TAP_COUNT = case("REG-B2")["settings"]["numberOfTaps"]
BRACE3_WAV = fixture("REG-B2")

# UMIK-1 calibration file — used for brace and plate measurements.
CALIBRATION_FILE = calibration("REG-B1")
assert CALIBRATION_FILE is not None  # REG-B1 declares 7108913.txt

# plate-umik-1-swift-mac-1778816330.wav — Plate, UMIK-1 mic, 48 kHz, full session. The oracle's
# values originally came from the matching .guitartap file
# (Tests/Plate/plate-umik-1-swift-mac-1778816330.guitartap).
# The single WAV exercises all three plate phases; on file playback the
# pipeline auto-advances between phases so all three peaks are populated.
PLATE_WAV = fixture("REG-P1")
_P1_L, _P1_C, _P1_FLC = (
    peak("REG-P1", "longitudinal"),
    peak("REG-P1", "cross"),
    peak("REG-P1", "flc"),
)
PLATE_L_EXPECTED_FREQ = _P1_L["frequency"]
PLATE_L_EXPECTED_MAG = _P1_L["magnitude"]
PLATE_L_EXPECTED_Q = _P1_L["q"]

PLATE_C_EXPECTED_FREQ = _P1_C["frequency"]
PLATE_C_EXPECTED_MAG = _P1_C["magnitude"]
PLATE_C_EXPECTED_Q = _P1_C["q"]

PLATE_FLC_EXPECTED_FREQ = _P1_FLC["frequency"]
PLATE_FLC_EXPECTED_MAG = _P1_FLC["magnitude"]
PLATE_FLC_EXPECTED_Q = _P1_FLC["q"]

PLATE_TAP_THRESHOLD = case("REG-P1")["settings"]["tapDetectionThreshold"]

# ---------------------------------------------------------------------------
# plate-umik-1-noisy-52.wav — OUT-4: the ONE fixture that separates the two
# detection models.  It is PLATE_WAV with broadband noise mixed in to raise its
# noise floor from -77 dBFS to -52 dBFS, i.e. ABOVE the -53.34 dB tap threshold.
#
# All three editions detect material taps against an EMA-tracked noise floor, not a
# fixed absolute dBFS threshold.  The relative rule reduces to
#     rising = max(tap_detection_threshold, noise_floor + 10 dB)
# so the two are the SAME FUNCTION until the floor climbs within 10 dB of the
# threshold.  Every other fixture sits at -64..-69 dBFS, far below that — which
# is why no test has ever been able to separate them.
#
# At a -52 floor the ABSOLUTE detector SATURATES: the level never drops below the
# threshold, so no rising edge can ever be confirmed and it captures NOTHING.
# The RELATIVE detector floats its threshold to floor+10 = -42 dB and still finds
# every tap (they peak at -24..-27 dBFS chunk-RMS).  That is precisely the failure
# the relative model exists to prevent: "keeps detection working when ambient
# noise is elevated".
#
# Assert the PHASE COUNT, not peak values: the added noise sums into the gated FFT,
# so fL/fC/fLC shift slightly.  A tight peak assertion here would be measuring the
# noise, not the detector.  The clean fixtures keep the strict peak assertions.
#
# Regenerate: python3 GuitarTapWeb/tooling/make-noisy-fixture.py (deterministic).
# ---------------------------------------------------------------------------
PLATE_NOISY_WAV = os.path.join(
    os.path.dirname(__file__),
    "plate-umik-1-noisy-52.wav",
)
Q_TOLERANCE = TOLERANCES["q"]

# ---------------------------------------------------------------------------
# plate-umik-1-web-mac-3-taps.wav — Plate, UMIK-1 mic, 48 kHz, recorded by the WEB app (Chrome)
# with number_of_taps = 3, i.e. 3 taps PER PHASE (9 taps total). Replaying it at number_of_taps=3
# averages each phase; the peak must come off the averaged spectrum, not the last tap.
PLATE_3TAP_WAV = fixture("REG-P2")
PLATE_3TAP_THRESHOLD = case("REG-P2")["settings"]["tapDetectionThreshold"]
_P2_L, _P2_C, _P2_FLC = (
    peak("REG-P2", "longitudinal"),
    peak("REG-P2", "cross"),
    peak("REG-P2", "flc"),
)
PLATE_3TAP_L_FREQ, PLATE_3TAP_L_MAG, PLATE_3TAP_L_Q = (
    _P2_L["frequency"], _P2_L["magnitude"], _P2_L["q"],
)
PLATE_3TAP_C_FREQ, PLATE_3TAP_C_MAG, PLATE_3TAP_C_Q = (
    _P2_C["frequency"], _P2_C["magnitude"], _P2_C["q"],
)
PLATE_3TAP_FLC_FREQ, PLATE_3TAP_FLC_MAG, PLATE_3TAP_FLC_Q = (
    _P2_FLC["frequency"], _P2_FLC["magnitude"], _P2_FLC["q"],
)

# ---------------------------------------------------------------------------
# Recording 5.wav — Generic guitar, single-tap, 48 kHz.
# The oracle's values originally came from the Recording 5.guitartap file (Tests/O'Brien/).
# Settings: peak_min_threshold = -76, tap_detection_threshold = -40,
#           measurement_type = GENERIC, number_of_taps = 1.
#           FFT size is a constant (65536) inside RealtimeFFTAnalyzer.
# ---------------------------------------------------------------------------

G1_WAV = fixture("REG-G1")
G1_PEAK_MIN_THRESHOLD = case("REG-G1")["settings"]["peakMinThreshold"]
G1_TAP_THRESHOLD = case("REG-G1")["settings"]["tapDetectionThreshold"]

_G1_AIR, _G1_TOP, _G1_BACK = (
    peak("REG-G1", "air"),
    peak("REG-G1", "top"),
    peak("REG-G1", "back"),
)
G1_AIR_FREQ, G1_AIR_MAG = _G1_AIR["frequency"], _G1_AIR["magnitude"]
G1_TOP_FREQ, G1_TOP_MAG = _G1_TOP["frequency"], _G1_TOP["magnitude"]
G1_BACK_FREQ, G1_BACK_MAG = _G1_BACK["frequency"], _G1_BACK["magnitude"]
G1_RING_OUT_SEC = case("REG-G1")["ringOutSec"]
RING_OUT_TOLERANCE = TOLERANCES["ringOutSec"]

# ---------------------------------------------------------------------------
# Recording.wav — Generic guitar, 8-tap multi-tap, 48 kHz.
# The oracle's values originally came from the Recording.guitartap file (Tests/O'Brien/).
# Settings: peak_min_threshold = -76, tap_detection_threshold = -40,
#           measurement_type = GENERIC, number_of_taps = 8.
#           FFT size is a constant (65536) inside RealtimeFFTAnalyzer.
# ---------------------------------------------------------------------------

GUITAR_WAV = fixture("REG-G2")
GUITAR_PEAK_MIN_THRESHOLD = case("REG-G2")["settings"]["peakMinThreshold"]
GUITAR_TAP_THRESHOLD = case("REG-G2")["settings"]["tapDetectionThreshold"]

# Average peaks
_G2_AIR, _G2_TOP, _G2_BACK = (
    peak("REG-G2", "air", "averagedPeaks"),
    peak("REG-G2", "top", "averagedPeaks"),
    peak("REG-G2", "back", "averagedPeaks"),
)
GUITAR_AVG_AIR_FREQ, GUITAR_AVG_AIR_MAG = _G2_AIR["frequency"], _G2_AIR["magnitude"]
GUITAR_AVG_TOP_FREQ, GUITAR_AVG_TOP_MAG = _G2_TOP["frequency"], _G2_TOP["magnitude"]
GUITAR_AVG_BACK_FREQ, GUITAR_AVG_BACK_MAG = _G2_BACK["frequency"], _G2_BACK["magnitude"]

# Per-tap expected values: (air_freq, air_mag, top_freq, top_mag, back_freq, back_mag).
# Taps 1 and 7 pin Back at ~296.5 Hz rather than ~240.6 - real behaviour of the shared
# selection path on this fixture, pinned deliberately (see _perTapNote in the oracle).
def _per_tap_row(entry: dict[str, object]) -> tuple[float, ...]:
    by_role = {p["role"]: p for p in entry["peaks"]}  # type: ignore[attr-defined]
    return tuple(
        float(by_role[role][key])
        for role in ("air", "top", "back")
        for key in ("frequency", "magnitude")
    )


GUITAR_PER_TAP = [_per_tap_row(entry) for entry in case("REG-G2")["perTap"]]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _wav_rate(path: str) -> int:
    """Sample rate of a WAV fixture. The harness derives the analyzer rate from the
    file itself rather than hardcoding 48 kHz, so a future non-48 kHz fixture stays
    consistent (mirrors Swift forTesting() taking the rate from the played file)."""
    import soundfile as sf
    return int(sf.info(path).samplerate)


@pytest.fixture
def brace3_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(BRACE3_WAV))


@pytest.fixture
def brace_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(BRACE_WAV))


@pytest.fixture
def g1_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))


@pytest.fixture
def guitar_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(GUITAR_WAV))


@pytest.fixture
def plate_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(PLATE_WAV))


# ---------------------------------------------------------------------------
# Tests — in Swift's order (FilePlaybackRegressionTests), then the session-recording cases
# ---------------------------------------------------------------------------

class TestFilePlaybackRegression:
    """Full-pipeline file playback regression tests."""

    def test_REG_B2_brace_three_taps_averages_to_expected_peak(
        self, brace3_analyzer
    ):
        """Brace at number_of_taps=3 — the three taps average into one spectrum.

        The brace counterpart to REG-P2. The peak must be read off the AVERAGED spectrum,
        not the last tap: the three taps here differ by ~6 dB, so a regression to last-tap
        selection lands well outside the tolerance rather than hiding inside it.
        """
        assert os.path.exists(BRACE3_WAV), f"Test WAV not found: {BRACE3_WAV}"

        sut = brace3_analyzer
        sut.tap_detection_threshold = BRACE3_TAP_THRESHOLD
        play_file_and_wait(
            sut, path=BRACE3_WAV,
            measurement_type=MeasurementType.BRACE,
            number_of_taps=BRACE3_TAP_COUNT,
            calibration_path=CALIBRATION_FILE,
        )

        assert sut.material_tap_phase == MaterialTapPhase.COMPLETE, (
            f"material_tap_phase should be COMPLETE, got {sut.material_tap_phase}"
        )
        assert sut.is_measurement_complete, "is_measurement_complete should be True"
        assert sut.selected_longitudinal_peak is not None, "the fL peak should be identified"

        dominant = sut.selected_longitudinal_peak

        freq_delta = abs(dominant.frequency - BRACE3_EXPECTED_FREQ)
        assert freq_delta <= FREQ_TOLERANCE, (
            f"Peak frequency: expected {BRACE3_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {dominant.frequency} Hz (delta {freq_delta:.5f})"
        )

        mag_delta = abs(dominant.magnitude - BRACE3_EXPECTED_MAG)
        assert mag_delta <= MAG_TOLERANCE, (
            f"Peak magnitude: expected {BRACE3_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {dominant.magnitude} dB (delta {mag_delta:.5f})"
        )

        q_delta = abs(dominant.quality - BRACE3_EXPECTED_Q)
        assert q_delta <= Q_TOLERANCE, (
            f"Peak Q factor: expected {BRACE3_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {dominant.quality} (delta {q_delta:.5f})"
        )

    def test_REG_B1_brace_single_tap_produces_expected_peak(
        self, brace_analyzer
    ):
        """Brace single-tap — known WAV produces expected fL peak.

        Loads a full-session brace recording WAV (~12.6 s, 48 kHz) and plays it
        through the full pipeline with measurement_type = BRACE.  Verifies that:
          1. The pipeline completes (material_tap_phase == COMPLETE)
          2. At least one longitudinal peak is detected
          3. The dominant peak's frequency, magnitude and Q match the oracle
        """
        assert os.path.exists(BRACE_WAV), (
            f"Test WAV not found: {BRACE_WAV}"
        )

        sut = brace_analyzer
        sut.tap_detection_threshold = BRACE_TAP_THRESHOLD
        play_file_and_wait(
            sut, path=BRACE_WAV,
            measurement_type=MeasurementType.BRACE,
            calibration_path=CALIBRATION_FILE,
        )

        # 1. Pipeline should reach COMPLETE for brace (single-tap mode).
        assert sut.material_tap_phase == MaterialTapPhase.COMPLETE, (
            f"material_tap_phase should be COMPLETE, "
            f"got {sut.material_tap_phase}"
        )

        assert sut.is_measurement_complete, (
            "is_measurement_complete should be True"
        )

        # 2. The fL peak should be identified.
        assert sut.selected_longitudinal_peak is not None, "the fL peak should be identified"

        # 3. Verify the fL peak's frequency.
        dominant = sut.selected_longitudinal_peak
        freq_delta = abs(dominant.frequency - BRACE_EXPECTED_FREQ)
        assert freq_delta <= FREQ_TOLERANCE, (
            f"Peak frequency: expected {BRACE_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {dominant.frequency} Hz "
            f"(delta {freq_delta:.2f})"
        )

        # 4. Verify dominant peak magnitude.
        mag_delta = abs(dominant.magnitude - BRACE_EXPECTED_MAG)
        assert mag_delta <= MAG_TOLERANCE, (
            f"Peak magnitude: expected {BRACE_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {dominant.magnitude} dB "
            f"(delta {mag_delta:.2f})"
        )

        # 5. Verify dominant peak Q factor.
        q_delta = abs(dominant.quality - BRACE_EXPECTED_Q)
        assert q_delta <= Q_TOLERANCE, (
            f"Peak Q factor: expected {BRACE_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {dominant.quality} "
            f"(delta {q_delta:.2f})"
        )

    def test_REG_G1_generic_guitar_single_tap_produces_expected_peaks(
        self, g1_analyzer
    ):
        """Generic guitar single-tap — validates Air/Top/Back peaks.

        Loads a single-tap generic guitar recording and plays it through the
        full pipeline.  Verifies that:
          1. The pipeline completes with 1 tap entry
          2. Air, Top, Back frequencies and magnitudes match the oracle
        """
        from guitar_tap.models.guitar_mode import GuitarMode

        assert os.path.exists(G1_WAV), f"Test WAV not found: {G1_WAV}"

        sut = g1_analyzer
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        play_file_and_wait(
            sut, path=G1_WAV,
            measurement_type=MeasurementType.GENERIC,
            number_of_taps=1,
        )

        # 1. Pipeline should complete with 1 captured tap.
        #    (tap_entries is only populated for multi-tap sessions; single-tap
        #     uses captured_taps directly.)
        assert sut.is_measurement_complete, "is_measurement_complete should be True"
        assert len(sut.captured_taps) == 1, (
            f"Expected 1 captured tap, got {len(sut.captured_taps)}"
        )

        # 2. Peaks — use get_peak(), the same API the Results panel uses.
        air_peak = sut.get_peak(GuitarMode.AIR)
        assert air_peak is not None, "No Air peak found"
        assert abs(air_peak.frequency - G1_AIR_FREQ) <= FREQ_TOLERANCE, (
            f"Air freq: expected {G1_AIR_FREQ} "
            f"±{FREQ_TOLERANCE}, got {air_peak.frequency}"
        )
        assert abs(air_peak.magnitude - G1_AIR_MAG) <= MAG_TOLERANCE, (
            f"Air mag: expected {G1_AIR_MAG} "
            f"±{MAG_TOLERANCE}, got {air_peak.magnitude}"
        )

        top_peak = sut.get_peak(GuitarMode.TOP)
        assert top_peak is not None, "No Top peak found"
        assert abs(top_peak.frequency - G1_TOP_FREQ) <= FREQ_TOLERANCE, (
            f"Top freq: expected {G1_TOP_FREQ} "
            f"±{FREQ_TOLERANCE}, got {top_peak.frequency}"
        )
        assert abs(top_peak.magnitude - G1_TOP_MAG) <= MAG_TOLERANCE, (
            f"Top mag: expected {G1_TOP_MAG} "
            f"±{MAG_TOLERANCE}, got {top_peak.magnitude}"
        )

        back_peak = sut.get_peak(GuitarMode.BACK)
        assert back_peak is not None, "No Back peak found"
        assert abs(back_peak.frequency - G1_BACK_FREQ) <= FREQ_TOLERANCE, (
            f"Back freq: expected {G1_BACK_FREQ} "
            f"±{FREQ_TOLERANCE}, got {back_peak.frequency}"
        )
        assert abs(back_peak.magnitude - G1_BACK_MAG) <= MAG_TOLERANCE, (
            f"Back mag: expected {G1_BACK_MAG} "
            f"±{MAG_TOLERANCE}, got {back_peak.magnitude}"
        )

    # REG-G ring-out — Recording 5.wav's post-tap level decays to peak-15 dB, measured on the audio
    # clock. The value is the oracle's, shared by all three editions.
    def test_REG_G_generic_guitar_ringout(self, g1_analyzer):
        """Ring-out time for Recording 5.wav matches the cross-platform golden."""
        sut = g1_analyzer
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        play_file_and_wait(
            sut, path=G1_WAV, measurement_type=MeasurementType.GENERIC, number_of_taps=1
        )
        assert sut.current_decay_time is not None, "No ring-out measured"
        assert abs(sut.current_decay_time - G1_RING_OUT_SEC) <= RING_OUT_TOLERANCE, (
            f"Ring-out: expected {G1_RING_OUT_SEC} ±{RING_OUT_TOLERANCE}, "
            f"got {sut.current_decay_time}"
        )

    def test_REG_G2_generic_guitar_8tap_produces_expected_peaks(
        self, guitar_analyzer
    ):
        """Generic guitar 8-tap — validates averaged and per-tap Air/Top/Back.

        Loads a live 8-tap generic guitar recording and plays it through the
        full pipeline.  Verifies that:
          1. The pipeline completes with 8 tap entries
          2. Averaged Air, Top, Back frequencies and magnitudes match the oracle
          3. All 8 individual taps' Air, Top, Back freq+mag match the oracle
        """
        from guitar_tap.models.guitar_mode import GuitarMode
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

        assert os.path.exists(GUITAR_WAV), f"Test WAV not found: {GUITAR_WAV}"

        sut = guitar_analyzer
        sut.peak_min_threshold = GUITAR_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = GUITAR_TAP_THRESHOLD
        play_file_and_wait(
            sut, path=GUITAR_WAV,
            measurement_type=MeasurementType.GENERIC,
            number_of_taps=8,
        )

        # 1. Pipeline should complete with 8 tap entries.
        assert sut.is_measurement_complete, "is_measurement_complete should be True"
        assert len(sut.tap_entries) == 8, (
            f"Expected 8 tap entries, got {len(sut.tap_entries)}"
        )

        # 2. Averaged peaks — use get_peak(), the same API the Results panel uses.
        air_peak = sut.get_peak(GuitarMode.AIR)
        assert air_peak is not None, "No averaged Air peak found"
        assert abs(air_peak.frequency - GUITAR_AVG_AIR_FREQ) <= FREQ_TOLERANCE, (
            f"Avg Air freq: expected {GUITAR_AVG_AIR_FREQ} "
            f"±{FREQ_TOLERANCE}, got {air_peak.frequency}"
        )
        assert abs(air_peak.magnitude - GUITAR_AVG_AIR_MAG) <= MAG_TOLERANCE, (
            f"Avg Air mag: expected {GUITAR_AVG_AIR_MAG} "
            f"±{MAG_TOLERANCE}, got {air_peak.magnitude}"
        )

        top_peak = sut.get_peak(GuitarMode.TOP)
        assert top_peak is not None, "No averaged Top peak found"
        assert abs(top_peak.frequency - GUITAR_AVG_TOP_FREQ) <= FREQ_TOLERANCE, (
            f"Avg Top freq: expected {GUITAR_AVG_TOP_FREQ} "
            f"±{FREQ_TOLERANCE}, got {top_peak.frequency}"
        )
        assert abs(top_peak.magnitude - GUITAR_AVG_TOP_MAG) <= MAG_TOLERANCE, (
            f"Avg Top mag: expected {GUITAR_AVG_TOP_MAG} "
            f"±{MAG_TOLERANCE}, got {top_peak.magnitude}"
        )

        back_peak = sut.get_peak(GuitarMode.BACK)
        assert back_peak is not None, "No averaged Back peak found"
        assert abs(back_peak.frequency - GUITAR_AVG_BACK_FREQ) <= FREQ_TOLERANCE, (
            f"Avg Back freq: expected {GUITAR_AVG_BACK_FREQ} "
            f"±{FREQ_TOLERANCE}, got {back_peak.frequency}"
        )
        assert abs(back_peak.magnitude - GUITAR_AVG_BACK_MAG) <= MAG_TOLERANCE, (
            f"Avg Back mag: expected {GUITAR_AVG_BACK_MAG} "
            f"±{MAG_TOLERANCE}, got {back_peak.magnitude}"
        )

        # 3. Per-tap peaks — uses TapEntry.resolved_mode_peaks(), the same
        #    code path as MultiTapComparisonResultsView and PDF export.
        for index, entry in enumerate(sut.tap_entries):
            exp = GUITAR_PER_TAP[index]
            exp_air_freq, exp_air_mag = exp[0], exp[1]
            exp_top_freq, exp_top_mag = exp[2], exp[3]
            exp_back_freq, exp_back_mag = exp[4], exp[5]
            tap_label = f"Tap {index + 1}"

            mode_peaks = entry.resolved_mode_peaks()

            # Air
            air = mode_peaks.get(GuitarMode.AIR)
            assert air is not None, f"{tap_label}: no Air peak in selected peaks"
            assert abs(air.frequency - exp_air_freq) <= FREQ_TOLERANCE, (
                f"{tap_label} Air freq: expected {exp_air_freq} "
                f"±{FREQ_TOLERANCE}, got {air.frequency}"
            )
            assert abs(air.magnitude - exp_air_mag) <= MAG_TOLERANCE, (
                f"{tap_label} Air mag: expected {exp_air_mag} "
                f"±{MAG_TOLERANCE}, got {air.magnitude}"
            )

            # Top
            top = mode_peaks.get(GuitarMode.TOP)
            assert top is not None, f"{tap_label}: no Top peak in selected peaks"
            assert abs(top.frequency - exp_top_freq) <= FREQ_TOLERANCE, (
                f"{tap_label} Top freq: expected {exp_top_freq} "
                f"±{FREQ_TOLERANCE}, got {top.frequency}"
            )
            assert abs(top.magnitude - exp_top_mag) <= MAG_TOLERANCE, (
                f"{tap_label} Top mag: expected {exp_top_mag} "
                f"±{MAG_TOLERANCE}, got {top.magnitude}"
            )

            # Back
            back = mode_peaks.get(GuitarMode.BACK)
            assert back is not None, f"{tap_label}: no Back peak in selected peaks"
            assert abs(back.frequency - exp_back_freq) <= FREQ_TOLERANCE, (
                f"{tap_label} Back freq: expected {exp_back_freq} "
                f"±{FREQ_TOLERANCE}, got {back.frequency}"
            )
            assert abs(back.magnitude - exp_back_mag) <= MAG_TOLERANCE, (
                f"{tap_label} Back mag: expected {exp_back_mag} "
                f"±{MAG_TOLERANCE}, got {back.magnitude}"
            )

    def test_REG_P1_plate_full_session_produces_expected_peaks(
        self, plate_analyzer
    ):
        """Plate full-session — single WAV exercises all three plate phases.

        Loads a full-session plate recording and plays it through the
        pipeline with measurement_type = PLATE.  On file playback the
        pipeline auto-advances between phases (no review/cooldown gap),
        so a single WAV reaches .complete with all three peaks
        populated.  Verifies:
          1. The pipeline reaches COMPLETE
          2. fL / fC / fLC peaks are each populated
          3. Each auto-selected peak's frequency, magnitude, and Q
             factor matches the oracle within the cross-edition tolerances
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings

        assert os.path.exists(PLATE_WAV), f"Test WAV not found: {PLATE_WAV}"

        # FLC must be enabled — the saved measurement was captured with
        # all three phases, and the playback pipeline reads this flag to
        # decide whether to advance C → FLC or finish after C.
        # Save/restore so the test doesn't bleed state into other tests.
        original_measure_flc = TapDisplaySettings.measure_flc()
        TapDisplaySettings.set_measure_flc(True)
        try:
            sut = plate_analyzer
            sut.tap_detection_threshold = PLATE_TAP_THRESHOLD
            play_file_and_wait(
            sut, path=PLATE_WAV,
                measurement_type=MeasurementType.PLATE,
                calibration_path=CALIBRATION_FILE,
            )
        finally:
            TapDisplaySettings.set_measure_flc(original_measure_flc)

        # 1. Pipeline should reach COMPLETE after all three phases.
        assert sut.material_tap_phase == MaterialTapPhase.COMPLETE, (
            f"material_tap_phase should be COMPLETE, got {sut.material_tap_phase}"
        )
        assert sut.is_measurement_complete, (
            "is_measurement_complete should be True"
        )

        # 2. All three peak arrays populated.
        assert sut.selected_longitudinal_peak is not None, "the fL peak should be identified"
        assert sut.selected_cross_peak is not None, "the fC peak should be identified"
        assert sut.selected_flc_peak is not None, "the fLC peak should be identified"

        # 3a. fL peak.
        l_peak = sut.selected_longitudinal_peak
        assert l_peak is not None, "selected_longitudinal_peak is None"
        l_freq_delta = abs(l_peak.frequency - PLATE_L_EXPECTED_FREQ)
        assert l_freq_delta <= FREQ_TOLERANCE, (
            f"fL frequency: expected {PLATE_L_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {l_peak.frequency} Hz "
            f"(delta {l_freq_delta:.2f})"
        )
        l_mag_delta = abs(l_peak.magnitude - PLATE_L_EXPECTED_MAG)
        assert l_mag_delta <= MAG_TOLERANCE, (
            f"fL magnitude: expected {PLATE_L_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {l_peak.magnitude} dB "
            f"(delta {l_mag_delta:.2f})"
        )
        l_q_delta = abs(l_peak.quality - PLATE_L_EXPECTED_Q)
        assert l_q_delta <= Q_TOLERANCE, (
            f"fL Q factor: expected {PLATE_L_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {l_peak.quality} "
            f"(delta {l_q_delta:.2f})"
        )

        # 3b. fC peak.
        c_peak = sut.selected_cross_peak
        assert c_peak is not None, "selected_cross_peak is None"
        c_freq_delta = abs(c_peak.frequency - PLATE_C_EXPECTED_FREQ)
        assert c_freq_delta <= FREQ_TOLERANCE, (
            f"fC frequency: expected {PLATE_C_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {c_peak.frequency} Hz "
            f"(delta {c_freq_delta:.2f})"
        )
        c_mag_delta = abs(c_peak.magnitude - PLATE_C_EXPECTED_MAG)
        assert c_mag_delta <= MAG_TOLERANCE, (
            f"fC magnitude: expected {PLATE_C_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {c_peak.magnitude} dB "
            f"(delta {c_mag_delta:.2f})"
        )
        c_q_delta = abs(c_peak.quality - PLATE_C_EXPECTED_Q)
        assert c_q_delta <= Q_TOLERANCE, (
            f"fC Q factor: expected {PLATE_C_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {c_peak.quality} "
            f"(delta {c_q_delta:.2f})"
        )

        # 3c. fLC peak.
        flc_peak = sut.selected_flc_peak
        assert flc_peak is not None, "selected_flc_peak is None"
        flc_freq_delta = abs(flc_peak.frequency - PLATE_FLC_EXPECTED_FREQ)
        assert flc_freq_delta <= FREQ_TOLERANCE, (
            f"fLC frequency: expected {PLATE_FLC_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {flc_peak.frequency} Hz "
            f"(delta {flc_freq_delta:.2f})"
        )
        flc_mag_delta = abs(flc_peak.magnitude - PLATE_FLC_EXPECTED_MAG)
        assert flc_mag_delta <= MAG_TOLERANCE, (
            f"fLC magnitude: expected {PLATE_FLC_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {flc_peak.magnitude} dB "
            f"(delta {flc_mag_delta:.2f})"
        )
        flc_q_delta = abs(flc_peak.quality - PLATE_FLC_EXPECTED_Q)
        assert flc_q_delta <= Q_TOLERANCE, (
            f"fLC Q factor: expected {PLATE_FLC_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {flc_peak.quality} "
            f"(delta {flc_q_delta:.2f})"
        )

    def test_OUT4_noisy_plate_relative_noise_floor_still_captures_all_phases(
        self, plate_analyzer
    ):
        """OUT-4 — the relative noise-floor detector survives an elevated ambient floor.

        The same plate session with its noise floor raised to -52 dBFS, ABOVE the -53.34 dB
        tap-detection threshold.  An ABSOLUTE-threshold detector would saturate here and capture
        nothing.  The noise-floor-RELATIVE detector floats its threshold to floor+10 and still captures all
        three phases.

        File playback lets the noise floor track the audio rather than pinning
        noise_floor_estimate = -100, which would collapse `rising` onto the absolute threshold and
        disable the relative model.

        Asserts the PHASE COUNT, not peak values — the noise shifts the peaks slightly, and a
        tight peak assertion would be measuring the noise rather than the detector.
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings

        assert os.path.exists(PLATE_NOISY_WAV), f"Test WAV not found: {PLATE_NOISY_WAV}"

        original_measure_flc = TapDisplaySettings.measure_flc()
        TapDisplaySettings.set_measure_flc(True)
        try:
            sut = plate_analyzer
            sut.tap_detection_threshold = PLATE_TAP_THRESHOLD
            play_file_and_wait(
            sut, path=PLATE_NOISY_WAV,
                measurement_type=MeasurementType.PLATE,
                calibration_path=CALIBRATION_FILE,
            )
        finally:
            TapDisplaySettings.set_measure_flc(original_measure_flc)

        captured = [
            name
            for name, spec in (
                ("L", sut.longitudinal_spectrum),
                ("C", sut.cross_spectrum),
                ("FLC", sut.flc_spectrum),
            )
            if spec is not None
        ]
        assert len(captured) == 3, (
            "absolute-threshold detection saturates on an elevated noise floor and captures "
            "nothing; the noise-floor-relative detector must still find all three taps. "
            f"Captured: {captured}, noise_floor_estimate={sut.noise_floor_estimate:.1f} dBFS"
        )

        # The floor must have actually CONVERGED to the noisy ambient — if it is still pinned
        # near -100 the relative model has silently degraded to the absolute one and this test
        # would be passing for the wrong reason.
        assert -60.0 < sut.noise_floor_estimate < -40.0, (
            "noise_floor_estimate should have converged to the fixture's ~-52 dBFS floor; "
            f"got {sut.noise_floor_estimate:.1f} (pinned at -100 means relative detection is OFF)"
        )

    def test_REG_P2_plate_three_taps_per_phase_averages(self, plate_analyzer):
        """Plate at number_of_taps=3 — each phase (L/C/FLC) averages 3 taps.

        plate-umik-1-web-mac-3-taps.wav is a 3-taps-per-phase plate session
        recorded by the web app (Chrome, UMIK-1).  Replaying it at
        number_of_taps=3 must average each phase and reproduce the oracle's
        peaks.  Exercises the multi-tap-per-phase path (mirrors Swift
        handleLongitudinalGatedProgress: collect number_of_taps, then
        averageSpectra).
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings

        assert os.path.exists(PLATE_3TAP_WAV), f"Test WAV not found: {PLATE_3TAP_WAV}"

        original_measure_flc = TapDisplaySettings.measure_flc()
        TapDisplaySettings.set_measure_flc(True)
        try:
            sut = plate_analyzer
            sut.tap_detection_threshold = PLATE_3TAP_THRESHOLD
            play_file_and_wait(
            sut, path=PLATE_3TAP_WAV,
                measurement_type=MeasurementType.PLATE,
                number_of_taps=3,
                calibration_path=CALIBRATION_FILE,
            )
        finally:
            TapDisplaySettings.set_measure_flc(original_measure_flc)

        assert sut.material_tap_phase == MaterialTapPhase.COMPLETE, (
            f"material_tap_phase should be COMPLETE, got {sut.material_tap_phase}"
        )
        assert sut.is_measurement_complete, "is_measurement_complete should be True"

        for name, peak, ef, em, eq in (
            ("fL", sut.selected_longitudinal_peak,
             PLATE_3TAP_L_FREQ, PLATE_3TAP_L_MAG, PLATE_3TAP_L_Q),
            ("fC", sut.selected_cross_peak,
             PLATE_3TAP_C_FREQ, PLATE_3TAP_C_MAG, PLATE_3TAP_C_Q),
            ("fLC", sut.selected_flc_peak,
             PLATE_3TAP_FLC_FREQ, PLATE_3TAP_FLC_MAG, PLATE_3TAP_FLC_Q),
        ):
            assert peak is not None, f"{name} peak is None"
            assert abs(peak.frequency - ef) <= FREQ_TOLERANCE, (
                f"{name} freq: expected {ef} Hz ±{FREQ_TOLERANCE}, got {peak.frequency}"
            )
            assert abs(peak.magnitude - em) <= MAG_TOLERANCE, (
                f"{name} mag: expected {em} dB ±{MAG_TOLERANCE}, got {peak.magnitude}"
            )
            assert abs(peak.quality - eq) <= Q_TOLERANCE, (
                f"{name} Q: expected {eq} ±{Q_TOLERANCE}, got {peak.quality}"
            )

    # ── Session recording ─────────────────────────────────────────────────────────────────────
    # With "save capture audio" on, a guitar measurement writes ONE session WAV labelled
    # "Guitar_<n>tap" covering the audio that flowed through the pipeline (arm → final tap); off, it
    # writes nothing. The dump folder is test-sandboxed (WavDumpFolder.default_folder), so the WAVs are
    # read back from there. Twins of the web's and Swift's session-recording cases.

    _SESSION_PREFIX = "python_session_"

    @classmethod
    def _session_wavs(cls):
        """The session WAVs in the sandboxed dump folder: (label, sample_rate, sample_count)."""
        import struct
        from guitar_tap.models.wav_dump_folder import WavDumpFolder
        folder = WavDumpFolder.default_folder()
        out = []
        if not folder.is_dir():
            return out
        for path in sorted(folder.glob(cls._SESSION_PREFIX + "*.wav")):
            data = path.read_bytes()
            if len(data) < 44:
                continue
            rate = struct.unpack_from("<I", data, 24)[0]
            nbytes = struct.unpack_from("<I", data, 40)[0]
            # "python_session_Guitar_1tap_<timestamp>.wav" → "Guitar_1tap"
            label = "_".join(path.name[len(cls._SESSION_PREFIX):].split("_")[:2])
            out.append((label, rate, nbytes // 4))
        return out

    @classmethod
    def _play_guitar_session(cls, path: str, number_of_taps: int, dump: bool):
        """Play a generic-guitar fixture with "save capture audio" set to ``dump``; return the
        session WAVs."""
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        from guitar_tap.models.wav_dump_folder import WavDumpFolder
        folder = WavDumpFolder.default_folder()
        if folder.is_dir():
            for old in folder.glob(cls._SESSION_PREFIX + "*.wav"):
                old.unlink()
        saved = TapDisplaySettings.dump_capture_audio()
        TapDisplaySettings.set_dump_capture_audio(dump)
        try:
            sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(path))
            sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
            sut.tap_detection_threshold = G1_TAP_THRESHOLD
            play_file_and_wait(
                sut, path=path, measurement_type=MeasurementType.GENERIC, number_of_taps=number_of_taps
            )
        finally:
            TapDisplaySettings.set_dump_capture_audio(saved)
        return cls._session_wavs()

    def test_REG_G1_session_recording_dump_on_writes_one_guitar_1tap_wav(self):
        import soundfile as sf
        sessions = self._play_guitar_session(G1_WAV, 1, dump=True)
        assert len(sessions) == 1, f"one session WAV, got {[s[0] for s in sessions]}"
        label, rate, samples = sessions[0]
        assert label == "Guitar_1tap"
        assert rate == _wav_rate(G1_WAV)
        # Covers the arm → tap → capture span: many chunks, and never more than the whole file.
        assert samples > 8192, f"a continuous run of many chunks, got {samples}"
        assert samples <= sf.info(G1_WAV).frames, f"bounded by the file, got {samples}"

    def test_REG_G2_session_recording_is_labelled_by_the_tap_count(self):
        sessions = self._play_guitar_session(GUITAR_WAV, 8, dump=True)
        assert len(sessions) == 1, f"one session WAV, got {[s[0] for s in sessions]}"
        assert sessions[0][0] == "Guitar_8tap"

    def test_session_recording_dump_off_writes_nothing(self):
        sessions = self._play_guitar_session(G1_WAV, 1, dump=False)
        assert sessions == [], f"no session WAV with the setting off, got {[s[0] for s in sessions]}"

    # ── Stopping a playback ──────────────────────────────────────────────────────────────────────
    # Cancel during a playback stops the file and restarts the sequence on live input; a measurement-type
    # change stops it before arming the new type. Nothing from the rest of the file reaches the new
    # sequence, and the playback's finished callback runs (the input's calibration returns). Twins of
    # Swift's stopping-a-playback cases.

    @staticmethod
    def _stop_playback_after_first_tap(stop):
        """Start "Recording" (8 guitar taps) with the input calibration set, wait for the first tap, run
        ``stop(sut)``; return the analyzer, whether the playback finished, and the input calibration."""
        import threading
        import time
        from PySide6 import QtWidgets
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        input_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(GUITAR_WAV))
        sut.peak_min_threshold = GUITAR_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = GUITAR_TAP_THRESHOLD
        sut.set_temporary_calibration(input_calibration)
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut.number_of_taps = 8
        finished = threading.Event()
        sut.play_file(GUITAR_WAV, on_finished=finished.set)
        deadline = time.monotonic() + 20
        while sut.current_tap_count < 1 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert sut.current_tap_count >= 1, "precondition: a tap before the stop"
        stop(sut)
        return sut, finished.is_set(), input_calibration

    @staticmethod
    def _run_on_for(seconds):
        import time
        from PySide6 import QtWidgets
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.005)

    def test_cancel_during_playback_stops_the_file_and_restarts_on_live_input(self):
        from guitar_tap.models.detection_state import DetectionState
        sut, finished, input_calibration = self._stop_playback_after_first_tap(lambda a: a.cancel_tap_sequence())
        assert not sut.mic.is_playing_file, "the file is stopped"
        assert sut.mic.playing_file_name is None, "the chart no longer names the file"
        assert finished, "the playback's finished callback ran"
        assert sut._calibration_profile is input_calibration, "the input's calibration is back"
        assert sut.detection_state == DetectionState.LISTENING, "a fresh sequence is armed"
        assert sut.current_tap_count == 0 and not sut.captured_taps, "the partial result is discarded"
        # The rest of the file must not reach the fresh sequence.
        self._run_on_for(2.0)
        assert sut.current_tap_count == 0 and not sut.captured_taps and not sut.is_measurement_complete, \
            f"no tap from the abandoned file, got {sut.current_tap_count}"

    def test_measurement_type_change_during_playback_stops_the_file_before_arming_the_new_type(self):
        from guitar_tap.models.material_tap_phase import MaterialTapPhase
        from guitar_tap.models.tap_display_settings import TapDisplaySettings

        def change_type(sut):
            TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
            sut.request_start_tap_sequence()   # what the settings Apply does for a changed type

        try:
            sut, finished, _ = self._stop_playback_after_first_tap(change_type)
            assert not sut.mic.is_playing_file, "the file is stopped"
            assert finished, "the playback's finished callback ran"
            assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_LONGITUDINAL, "the plate sequence is armed"
            self._run_on_for(2.0)
            assert sut.longitudinal_spectrum is None and not sut.captured_taps, \
                "no guitar tap from the abandoned file reaches the plate measurement"
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)

    # ── The end-of-file step runs on the main thread ─────────────────────────────────────────────
    # The flush of an unfinished capture, its finish and the release of the pending audio actions are one
    # step on the main thread, with the playback worker waiting for it — as Swift's worker waits in
    # DispatchQueue.main.sync. (Swift and the web get this by construction; Python's worker is a thread.)
    def test_the_end_of_file_step_runs_on_the_main_thread(self):
        import threading
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        threads = []
        flush = sut.mic._on_pre_mic_restart

        def recording_flush():
            threads.append(threading.current_thread())
            flush()

        sut.mic._on_pre_mic_restart = recording_flush
        play_file_and_wait(sut, path=G1_WAV, measurement_type=MeasurementType.GENERIC, number_of_taps=1)
        assert threads == [threading.main_thread()], f"the end-of-file step ran on {threads}"
        assert sut.is_measurement_complete

    # ── Provenance of a played file ──────────────────────────────────────────────────────────────
    # A result made from a played file is saved with the file's provenance: the calibration it was played
    # with (or none), the file's sample rate, and no microphone — the microphone that recorded a file is
    # unknown. A new sequence listens to the input again, and saves the input's. Twins of Swift's cases.

    def test_save_after_playback_records_the_files_provenance_and_an_unknown_microphone(self, brace_analyzer):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        sut = brace_analyzer
        sut.tap_detection_threshold = BRACE_TAP_THRESHOLD
        play_file_and_wait(sut, path=BRACE_WAV, measurement_type=MeasurementType.BRACE,
                           calibration_path=CALIBRATION_FILE)
        assert sut.is_measurement_complete, "precondition: the brace completed"
        file_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)

        sut.save_measurement()
        saved = sut.saved_measurements[-1]
        assert saved.microphone_name is None and saved.microphone_uid is None, "the microphone is unknown"
        assert saved.calibration_name == file_calibration.name, "the file's calibration"
        assert saved.sample_rate == float(_wav_rate(BRACE_WAV)), "the file's sample rate"
        assert saved.selected_longitudinal_peak_id == sut.effective_longitudinal_peak_id, \
            "fL's role, read by the save"

    def test_a_new_sequence_after_playback_saves_the_inputs_provenance(self, g1_analyzer):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        sut = g1_analyzer
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        input_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        sut.set_temporary_calibration(input_calibration)
        play_file_and_wait(sut, path=G1_WAV, measurement_type=MeasurementType.GENERIC, number_of_taps=1)
        assert sut.capture_calibration_name is None, "precondition: the file played uncalibrated"

        sut.start_tap_sequence()
        assert sut.capture_calibration_name == input_calibration.name, "the input's calibration again"

    def test_a_loaded_measurement_reports_its_recorded_provenance_and_a_re_save_keeps_it(self, brace_analyzer):
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        # A played-file result saved with an unknown microphone and the file's calibration and rate.
        source = brace_analyzer
        source.tap_detection_threshold = BRACE_TAP_THRESHOLD
        play_file_and_wait(source, path=BRACE_WAV, measurement_type=MeasurementType.BRACE,
                           calibration_path=CALIBRATION_FILE)
        source.save_measurement()
        saved = source.saved_measurements[-1]

        # Loaded by an analyzer whose input has no calibration: the loaded result reports the file's.
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(BRACE_WAV))
        sut.load_measurement(saved)
        assert sut.capture_microphone_name is None and sut.result_provenance is not None, \
            "the microphone is unknown"
        assert sut.capture_calibration_name == saved.calibration_name, "the recorded calibration"
        assert sut.capture_sample_rate == saved.sample_rate, "the recorded sample rate"

        sut.save_measurement()
        re_saved = sut.saved_measurements[-1]
        assert re_saved.microphone_name is None, "a re-save keeps the unknown microphone"
        assert re_saved.calibration_name == saved.calibration_name, "and the recorded calibration"
        assert re_saved.sample_rate == saved.sample_rate, "and the recorded sample rate"

    # ── Playback calibration ─────────────────────────────────────────────────────────────────────
    # A file plays with the calibration given for it, or with none: the microphone it was recorded with
    # is unknown, so the live input's calibration never applies to it. The input's calibration is back
    # once playback ends. Twins of Swift's playback-calibration cases.

    @staticmethod
    def _playback_calibrations(input_calibration, calibration_path):
        """Play G1 with ``calibration_path``; return the active calibration during and after playback."""
        import threading
        import time
        from PySide6 import QtWidgets
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))
        sut.set_temporary_calibration(input_calibration)
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        ended = threading.Event()
        sut.play_file(G1_WAV, calibration_path=calibration_path, on_finished=ended.set)
        during = sut._calibration_profile
        while not ended.is_set():
            app.processEvents()
            time.sleep(0.005)
        return during, sut._calibration_profile

    def test_playback_without_a_calibration_file_is_uncalibrated_and_the_inputs_calibration_returns(self):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        input_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        during, after = self._playback_calibrations(input_calibration, None)
        assert during is None, "no calibration file → uncalibrated"
        assert after is input_calibration, "the input's calibration is restored after playback"

    def test_playback_with_a_calibration_file_uses_it_and_the_inputs_calibration_returns(self):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        file_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        during, after = self._playback_calibrations(None, CALIBRATION_FILE)
        assert during is not None and during.correction_points == file_calibration.correction_points, \
            "the file's calibration is applied"
        assert after is None, "the input's (absent) calibration is restored after playback"
