# @parity test/file-playback
"""
Full-pipeline file playback regression tests.

Unlike test_file_playback.py (FP1–FP15) which test the FFT → peak_detection
path directly, these tests exercise the FULL pipeline:
  WAV read → chunk pacing → RMS → tap detection → gated capture →
  Hann window → FFT → peak selection → mode identification

The analyzer is created via ``TapToneAnalyzer.for_testing()`` (no audio
hardware) and fed via ``play_file_for_testing(path, measurement_type)``.

Expected values were established by running the file through the app
and recording the displayed peak frequency and magnitude values.
Both Swift and Python test suites use the same WAV files and expected
values so that passing both suites guarantees cross-platform parity.

Test plan coverage: REG-G1, REG-B1, REG-G2, REG-P1
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from models.measurement_type import MeasurementType
from models.material_tap_phase import MaterialTapPhase

# ---------------------------------------------------------------------------
# Expected values
# ---------------------------------------------------------------------------

# brace-umik-1-swift-mac-1778816093.wav — Brace bar, UMIK-1 mic, 48 kHz.
# Full-session recording (mono float32, 48 kHz).
# Reference values from the matching .guitartap file
# (Tests/Brace/brace-umik-1-swift-mac-1778816093.guitartap):
#   Peak frequency: 512.68880 Hz
#   Peak magnitude: -70.93484 dB
#   Peak Q factor:  87.5
#   Tap detection threshold: -53.33838 dB
# The test uses tolerances per the test plan: ±1.0 Hz, ±1.0 dB, ±1.0 Q.
BRACE_EXPECTED_FREQ = 512.68880   # Hz
BRACE_EXPECTED_MAG = -70.93484    # dB
BRACE_EXPECTED_Q = 87.5            # dimensionless
BRACE_TAP_THRESHOLD = -53.33838   # dB — matches .guitartap reference
FREQ_TOLERANCE = 1.0               # Hz
MAG_TOLERANCE = 1.0                # dB

# WAV file path — same file used in the Swift test suite.
BRACE_WAV = os.path.join(
    os.path.dirname(__file__),
    "brace-umik-1-swift-mac-1778816093.wav",
)

# UMIK-1 calibration file — used for brace and plate measurements.
CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "7108913.txt")

# plate-umik-1-swift-mac-1778816330.wav — Plate, UMIK-1 mic, 48 kHz, full session.
# Reference values from the matching .guitartap file
# (Tests/Plate/plate-umik-1-swift-mac-1778816330.guitartap):
#   fL  frequency: 67.11537 Hz   magnitude: -60.36113 dB   Q: 15.333
#   fC  frequency: 116.27016 Hz  magnitude: -52.80130 dB   Q: 26.333
#   fLC frequency: 35.35375 Hz   magnitude: -58.28925 dB   Q: 6.000
#   Tap detection threshold: -53.33838 dB
# The single WAV exercises all three plate phases; on file playback the
# pipeline auto-advances between phases so all three peaks are populated.
PLATE_WAV = os.path.join(
    os.path.dirname(__file__),
    "plate-umik-1-swift-mac-1778816330.wav",
)
PLATE_L_EXPECTED_FREQ = 67.11537    # Hz
PLATE_L_EXPECTED_MAG = -60.36113    # dB
PLATE_L_EXPECTED_Q = 15.333

PLATE_C_EXPECTED_FREQ = 116.27016   # Hz
PLATE_C_EXPECTED_MAG = -52.80130    # dB
PLATE_C_EXPECTED_Q = 26.333

PLATE_FLC_EXPECTED_FREQ = 35.35375  # Hz
PLATE_FLC_EXPECTED_MAG = -58.28925  # dB
PLATE_FLC_EXPECTED_Q = 6.000

PLATE_TAP_THRESHOLD = -53.33838     # dB — matches .guitartap reference

# ---------------------------------------------------------------------------
# plate-umik-1-noisy-52.wav — OUT-4: the ONE fixture that separates the two
# detection models.  It is PLATE_WAV with broadband noise mixed in to raise its
# noise floor from -77 dBFS to -52 dBFS, i.e. ABOVE the -53.34 dB tap threshold.
#
# Swift/Python detect material taps against an EMA-tracked noise floor; the web
# port uses a fixed absolute dBFS threshold.  The relative rule reduces to
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
# Analysis:   GuitarTapWeb/Development/OUT-4-DETECTION-SPEC.md
# ---------------------------------------------------------------------------
PLATE_NOISY_WAV = os.path.join(
    os.path.dirname(__file__),
    "plate-umik-1-noisy-52.wav",
)
Q_TOLERANCE = 1.0                    # dimensionless

# ---------------------------------------------------------------------------
# plate-umik-1-web-mac-3-taps.wav — Plate, UMIK-1 mic, 48 kHz, recorded by the WEB app (Chrome)
# with number_of_taps = 3, i.e. 3 taps PER PHASE (9 taps total). Replaying it at number_of_taps=3
# averages each phase (L/C/FLC) and reads the dominant peak OFF THE AVERAGED spectrum (like guitar).
# Expected values are the averaged-spectrum peaks (the web .guitartap, same recording). NB: Swift/Python
# historically read material peaks off the LAST tap (a buildAllPeaks UUID-hack side-effect) — a latent
# bug fixed alongside this so all three read the averaged peak (fLC -63.6008, not the last tap's -60.98).
PLATE_3TAP_WAV = os.path.join(
    os.path.dirname(__file__),
    "plate-umik-1-web-mac-3-taps.wav",
)
PLATE_3TAP_THRESHOLD = -40.0          # dB — matches the .guitartap reference
PLATE_3TAP_L_FREQ, PLATE_3TAP_L_MAG, PLATE_3TAP_L_Q = 68.2587, -71.5858, 15.667
PLATE_3TAP_C_FREQ, PLATE_3TAP_C_MAG, PLATE_3TAP_C_Q = 117.4681, -56.5436, 26.667
PLATE_3TAP_FLC_FREQ, PLATE_3TAP_FLC_MAG, PLATE_3TAP_FLC_Q = 35.3011, -63.6008, 6.000
# REG-P2 uses a tighter magnitude tolerance than the generic ±1.0 dB.  The
# averaged values are deterministic across platforms, so they agree far more
# closely than a single tap would; ±0.5 dB still leaves headroom for FFT-library
# differences while reliably catching a regression to last-tap selection (the
# masked deltas were fL 0.94, fC 0.81, fLC 2.62 dB — all caught at 0.5).
PLATE_3TAP_MAG_TOLERANCE = 0.5         # dB

# ---------------------------------------------------------------------------
# Recording 5.wav — Generic guitar, single-tap, 48 kHz.
# Reference values from the Recording 5.guitartap file (Tests/O'Brien/).
# Settings: peak_min_threshold = -76, tap_detection_threshold = -40,
#           measurement_type = GENERIC, number_of_taps = 1.
#           FFT size is a constant (65536) inside RealtimeFFTAnalyzer.
# ---------------------------------------------------------------------------

G1_WAV = os.path.join(os.path.dirname(__file__), "Recording 5.wav")
G1_PEAK_MIN_THRESHOLD = -76.0   # dB
G1_TAP_THRESHOLD = -40.0        # dB

G1_AIR_FREQ = 87.30731;    G1_AIR_MAG = -45.351357
G1_TOP_FREQ = 164.09756;   G1_TOP_MAG = -36.67097
G1_BACK_FREQ = 240.5668;   G1_BACK_MAG = -54.567883

# ---------------------------------------------------------------------------
# Recording.wav — Generic guitar, 8-tap multi-tap, 48 kHz.
# Reference values from the Recording.guitartap file (Tests/O'Brien/).
# Settings: peak_min_threshold = -76, tap_detection_threshold = -40,
#           measurement_type = GENERIC, number_of_taps = 8.
#           FFT size is a constant (65536) inside RealtimeFFTAnalyzer.
# ---------------------------------------------------------------------------

GUITAR_WAV = os.path.join(os.path.dirname(__file__), "Recording.wav")
GUITAR_PEAK_MIN_THRESHOLD = -76.0   # dB
GUITAR_TAP_THRESHOLD = -40.0        # dB

# Average peaks
GUITAR_AVG_AIR_FREQ = 87.233154;   GUITAR_AVG_AIR_MAG = -44.34529
GUITAR_AVG_TOP_FREQ = 164.04662;   GUITAR_AVG_TOP_MAG = -35.105385
GUITAR_AVG_BACK_FREQ = 240.57095;  GUITAR_AVG_BACK_MAG = -55.152287

# Per-tap expected values: (air_freq, air_mag, top_freq, top_mag, back_freq, back_mag)
GUITAR_PER_TAP = [
    (87.20365, -46.083164, 164.15787, -37.15723,  296.5797,  -57.117817),  # Tap 1
    (87.22049, -43.714653, 163.98953, -34.96168,  240.6308,  -54.930405),  # Tap 2
    (87.21567, -44.400375, 164.00642, -36.064285, 240.54478, -56.384575),  # Tap 3
    (87.23355, -43.930878, 164.02281, -34.72927,  240.58727, -55.048416),  # Tap 4
    (87.23911, -44.447514, 164.09766, -36.650166, 240.52957, -54.569893),  # Tap 5
    (87.258545,-44.08946,  164.05678, -34.239933, 240.63478, -54.847008),  # Tap 6
    (87.2434,  -43.969948, 164.05476, -33.775253, 296.5151,  -54.0257),    # Tap 7
    (87.24372, -44.523045, 164.0366,  -34.412136, 240.49031, -54.849174),  # Tap 8
]


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
def brace_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(BRACE_WAV))


@pytest.fixture
def g1_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))


@pytest.fixture
def guitar_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(GUITAR_WAV))


@pytest.fixture
def plate_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(PLATE_WAV))


# ---------------------------------------------------------------------------
# Tests  (REG-G1, REG-B1, REG-G2, REG-P1)
# ---------------------------------------------------------------------------

class TestFilePlaybackRegression:
    """Full-pipeline file playback regression tests."""

    def test_REG_G1_generic_guitar_single_tap_produces_expected_peaks(
        self, g1_analyzer
    ):
        """Generic guitar single-tap — validates Air/Top/Back peaks.

        Loads a single-tap generic guitar recording and plays it through the
        full pipeline.  Verifies that:
          1. The pipeline completes with 1 tap entry
          2. Air, Top, Back frequencies and magnitudes match reference ± 1
        """
        from models.guitar_mode import GuitarMode

        assert os.path.exists(G1_WAV), f"Test WAV not found: {G1_WAV}"

        sut = g1_analyzer
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        sut.play_file_for_testing(
            path=G1_WAV,
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
        assert abs(air_peak.frequency - G1_AIR_FREQ) < FREQ_TOLERANCE, (
            f"Air freq: expected {G1_AIR_FREQ} "
            f"±{FREQ_TOLERANCE}, got {air_peak.frequency}"
        )
        assert abs(air_peak.magnitude - G1_AIR_MAG) < MAG_TOLERANCE, (
            f"Air mag: expected {G1_AIR_MAG} "
            f"±{MAG_TOLERANCE}, got {air_peak.magnitude}"
        )

        top_peak = sut.get_peak(GuitarMode.TOP)
        assert top_peak is not None, "No Top peak found"
        assert abs(top_peak.frequency - G1_TOP_FREQ) < FREQ_TOLERANCE, (
            f"Top freq: expected {G1_TOP_FREQ} "
            f"±{FREQ_TOLERANCE}, got {top_peak.frequency}"
        )
        assert abs(top_peak.magnitude - G1_TOP_MAG) < MAG_TOLERANCE, (
            f"Top mag: expected {G1_TOP_MAG} "
            f"±{MAG_TOLERANCE}, got {top_peak.magnitude}"
        )

        back_peak = sut.get_peak(GuitarMode.BACK)
        assert back_peak is not None, "No Back peak found"
        assert abs(back_peak.frequency - G1_BACK_FREQ) < FREQ_TOLERANCE, (
            f"Back freq: expected {G1_BACK_FREQ} "
            f"±{FREQ_TOLERANCE}, got {back_peak.frequency}"
        )
        assert abs(back_peak.magnitude - G1_BACK_MAG) < MAG_TOLERANCE, (
            f"Back mag: expected {G1_BACK_MAG} "
            f"±{MAG_TOLERANCE}, got {back_peak.magnitude}"
        )

    def test_REG_B1_brace_single_tap_produces_expected_peak(
        self, brace_analyzer
    ):
        """Brace single-tap — known WAV produces expected fL peak.

        Loads a full-session brace recording WAV (~12.6 s, 48 kHz) and plays it
        through the full pipeline with measurement_type = BRACE.  Verifies that:
          1. The pipeline completes (material_tap_phase == COMPLETE)
          2. At least one longitudinal peak is detected
          3. The dominant peak frequency matches the .guitartap reference ± 1 Hz
          4. The dominant peak magnitude matches the reference ± 1 dB
          5. The dominant peak Q factor matches the reference ± 1
        """
        assert os.path.exists(BRACE_WAV), (
            f"Test WAV not found: {BRACE_WAV}"
        )

        sut = brace_analyzer
        sut.tap_detection_threshold = BRACE_TAP_THRESHOLD
        sut.play_file_for_testing(
            path=BRACE_WAV,
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

        # 2. Longitudinal peaks should be populated.
        assert len(sut.longitudinal_peaks) > 0, (
            "longitudinal_peaks should not be empty"
        )

        # 3. Verify dominant peak frequency.
        dominant = sut.longitudinal_peaks[0]
        freq_delta = abs(dominant.frequency - BRACE_EXPECTED_FREQ)
        assert freq_delta < FREQ_TOLERANCE, (
            f"Peak frequency: expected {BRACE_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {dominant.frequency} Hz "
            f"(delta {freq_delta:.2f})"
        )

        # 4. Verify dominant peak magnitude.
        mag_delta = abs(dominant.magnitude - BRACE_EXPECTED_MAG)
        assert mag_delta < MAG_TOLERANCE, (
            f"Peak magnitude: expected {BRACE_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {dominant.magnitude} dB "
            f"(delta {mag_delta:.2f})"
        )

        # 5. Verify dominant peak Q factor.
        q_delta = abs(dominant.quality - BRACE_EXPECTED_Q)
        assert q_delta < Q_TOLERANCE, (
            f"Peak Q factor: expected {BRACE_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {dominant.quality} "
            f"(delta {q_delta:.2f})"
        )

    def test_REG_G2_generic_guitar_8tap_produces_expected_peaks(
        self, guitar_analyzer
    ):
        """Generic guitar 8-tap — validates averaged and per-tap Air/Top/Back.

        Loads a live 8-tap generic guitar recording and plays it through the
        full pipeline.  Verifies that:
          1. The pipeline completes with 8 tap entries
          2. Averaged Air, Top, Back frequencies and magnitudes match reference ± 1
          3. All 8 individual taps' Air, Top, Back freq+mag match reference ± 1
        """
        from models.guitar_mode import GuitarMode
        from models.tap_tone_analyzer import TapToneAnalyzer

        assert os.path.exists(GUITAR_WAV), f"Test WAV not found: {GUITAR_WAV}"

        sut = guitar_analyzer
        sut.peak_min_threshold = GUITAR_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = GUITAR_TAP_THRESHOLD
        sut.play_file_for_testing(
            path=GUITAR_WAV,
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
        assert abs(air_peak.frequency - GUITAR_AVG_AIR_FREQ) < FREQ_TOLERANCE, (
            f"Avg Air freq: expected {GUITAR_AVG_AIR_FREQ} "
            f"±{FREQ_TOLERANCE}, got {air_peak.frequency}"
        )
        assert abs(air_peak.magnitude - GUITAR_AVG_AIR_MAG) < MAG_TOLERANCE, (
            f"Avg Air mag: expected {GUITAR_AVG_AIR_MAG} "
            f"±{MAG_TOLERANCE}, got {air_peak.magnitude}"
        )

        top_peak = sut.get_peak(GuitarMode.TOP)
        assert top_peak is not None, "No averaged Top peak found"
        assert abs(top_peak.frequency - GUITAR_AVG_TOP_FREQ) < FREQ_TOLERANCE, (
            f"Avg Top freq: expected {GUITAR_AVG_TOP_FREQ} "
            f"±{FREQ_TOLERANCE}, got {top_peak.frequency}"
        )
        assert abs(top_peak.magnitude - GUITAR_AVG_TOP_MAG) < MAG_TOLERANCE, (
            f"Avg Top mag: expected {GUITAR_AVG_TOP_MAG} "
            f"±{MAG_TOLERANCE}, got {top_peak.magnitude}"
        )

        back_peak = sut.get_peak(GuitarMode.BACK)
        assert back_peak is not None, "No averaged Back peak found"
        assert abs(back_peak.frequency - GUITAR_AVG_BACK_FREQ) < FREQ_TOLERANCE, (
            f"Avg Back freq: expected {GUITAR_AVG_BACK_FREQ} "
            f"±{FREQ_TOLERANCE}, got {back_peak.frequency}"
        )
        assert abs(back_peak.magnitude - GUITAR_AVG_BACK_MAG) < MAG_TOLERANCE, (
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
            assert abs(air.frequency - exp_air_freq) < FREQ_TOLERANCE, (
                f"{tap_label} Air freq: expected {exp_air_freq} "
                f"±{FREQ_TOLERANCE}, got {air.frequency}"
            )
            assert abs(air.magnitude - exp_air_mag) < MAG_TOLERANCE, (
                f"{tap_label} Air mag: expected {exp_air_mag} "
                f"±{MAG_TOLERANCE}, got {air.magnitude}"
            )

            # Top
            top = mode_peaks.get(GuitarMode.TOP)
            assert top is not None, f"{tap_label}: no Top peak in selected peaks"
            assert abs(top.frequency - exp_top_freq) < FREQ_TOLERANCE, (
                f"{tap_label} Top freq: expected {exp_top_freq} "
                f"±{FREQ_TOLERANCE}, got {top.frequency}"
            )
            assert abs(top.magnitude - exp_top_mag) < MAG_TOLERANCE, (
                f"{tap_label} Top mag: expected {exp_top_mag} "
                f"±{MAG_TOLERANCE}, got {top.magnitude}"
            )

            # Back
            back = mode_peaks.get(GuitarMode.BACK)
            assert back is not None, f"{tap_label}: no Back peak in selected peaks"
            assert abs(back.frequency - exp_back_freq) < FREQ_TOLERANCE, (
                f"{tap_label} Back freq: expected {exp_back_freq} "
                f"±{FREQ_TOLERANCE}, got {back.frequency}"
            )
            assert abs(back.magnitude - exp_back_mag) < MAG_TOLERANCE, (
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
             factor matches the .guitartap reference within tolerance
        """
        from models.tap_display_settings import TapDisplaySettings

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
            sut.play_file_for_testing(
                path=PLATE_WAV,
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
        assert len(sut.longitudinal_peaks) > 0, "longitudinal_peaks should not be empty"
        assert len(sut.cross_peaks) > 0, "cross_peaks should not be empty"
        assert len(sut.flc_peaks) > 0, "flc_peaks should not be empty"

        # 3a. fL peak.
        l_peak = sut.selected_longitudinal_peak
        assert l_peak is not None, "selected_longitudinal_peak is None"
        l_freq_delta = abs(l_peak.frequency - PLATE_L_EXPECTED_FREQ)
        assert l_freq_delta < FREQ_TOLERANCE, (
            f"fL frequency: expected {PLATE_L_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {l_peak.frequency} Hz "
            f"(delta {l_freq_delta:.2f})"
        )
        l_mag_delta = abs(l_peak.magnitude - PLATE_L_EXPECTED_MAG)
        assert l_mag_delta < MAG_TOLERANCE, (
            f"fL magnitude: expected {PLATE_L_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {l_peak.magnitude} dB "
            f"(delta {l_mag_delta:.2f})"
        )
        l_q_delta = abs(l_peak.quality - PLATE_L_EXPECTED_Q)
        assert l_q_delta < Q_TOLERANCE, (
            f"fL Q factor: expected {PLATE_L_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {l_peak.quality} "
            f"(delta {l_q_delta:.2f})"
        )

        # 3b. fC peak.
        c_peak = sut.selected_cross_peak
        assert c_peak is not None, "selected_cross_peak is None"
        c_freq_delta = abs(c_peak.frequency - PLATE_C_EXPECTED_FREQ)
        assert c_freq_delta < FREQ_TOLERANCE, (
            f"fC frequency: expected {PLATE_C_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {c_peak.frequency} Hz "
            f"(delta {c_freq_delta:.2f})"
        )
        c_mag_delta = abs(c_peak.magnitude - PLATE_C_EXPECTED_MAG)
        assert c_mag_delta < MAG_TOLERANCE, (
            f"fC magnitude: expected {PLATE_C_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {c_peak.magnitude} dB "
            f"(delta {c_mag_delta:.2f})"
        )
        c_q_delta = abs(c_peak.quality - PLATE_C_EXPECTED_Q)
        assert c_q_delta < Q_TOLERANCE, (
            f"fC Q factor: expected {PLATE_C_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {c_peak.quality} "
            f"(delta {c_q_delta:.2f})"
        )

        # 3c. fLC peak.
        flc_peak = sut.selected_flc_peak
        assert flc_peak is not None, "selected_flc_peak is None"
        flc_freq_delta = abs(flc_peak.frequency - PLATE_FLC_EXPECTED_FREQ)
        assert flc_freq_delta < FREQ_TOLERANCE, (
            f"fLC frequency: expected {PLATE_FLC_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {flc_peak.frequency} Hz "
            f"(delta {flc_freq_delta:.2f})"
        )
        flc_mag_delta = abs(flc_peak.magnitude - PLATE_FLC_EXPECTED_MAG)
        assert flc_mag_delta < MAG_TOLERANCE, (
            f"fLC magnitude: expected {PLATE_FLC_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {flc_peak.magnitude} dB "
            f"(delta {flc_mag_delta:.2f})"
        )
        flc_q_delta = abs(flc_peak.quality - PLATE_FLC_EXPECTED_Q)
        assert flc_q_delta < Q_TOLERANCE, (
            f"fLC Q factor: expected {PLATE_FLC_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {flc_peak.quality} "
            f"(delta {flc_q_delta:.2f})"
        )

    def test_REG_P2_plate_three_taps_per_phase_averages(self, plate_analyzer):
        """Plate at number_of_taps=3 — each phase (L/C/FLC) averages 3 taps.

        plate-umik-1-web-mac-3-taps.wav is a 3-taps-per-phase plate session
        recorded by the web app (Chrome, UMIK-1).  Replaying it at
        number_of_taps=3 must average each phase and reproduce the companion
        .guitartap peaks.  Exercises the multi-tap-per-phase path (mirrors
        Swift handleLongitudinalGatedProgress: collect number_of_taps, then
        averageSpectra).  Same fixture + expected values as the web REG-P2.
        """
        from models.tap_display_settings import TapDisplaySettings

        assert os.path.exists(PLATE_3TAP_WAV), f"Test WAV not found: {PLATE_3TAP_WAV}"

        original_measure_flc = TapDisplaySettings.measure_flc()
        TapDisplaySettings.set_measure_flc(True)
        try:
            sut = plate_analyzer
            sut.tap_detection_threshold = PLATE_3TAP_THRESHOLD
            sut.play_file_for_testing(
                path=PLATE_3TAP_WAV,
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
            assert abs(peak.frequency - ef) < FREQ_TOLERANCE, (
                f"{name} freq: expected {ef} Hz ±{FREQ_TOLERANCE}, got {peak.frequency}"
            )
            assert abs(peak.magnitude - em) < PLATE_3TAP_MAG_TOLERANCE, (
                f"{name} mag: expected {em} dB ±{PLATE_3TAP_MAG_TOLERANCE}, got {peak.magnitude}"
            )
            assert abs(peak.quality - eq) < Q_TOLERANCE, (
                f"{name} Q: expected {eq} ±{Q_TOLERANCE}, got {peak.quality}"
            )

    def test_OUT4_noisy_plate_relative_noise_floor_still_captures_all_phases(
        self, plate_analyzer
    ):
        """OUT-4 — the relative noise-floor detector survives an elevated ambient floor.

        The same plate session with its noise floor raised to -52 dBFS, ABOVE the -53.34 dB
        tap-detection threshold.  An ABSOLUTE-threshold detector saturates here and captures
        nothing (the web port does exactly that — this is its failing counterpart test).  The
        noise-floor-RELATIVE detector floats its threshold to floor+10 and still captures all
        three phases.

        This test only became possible once file playback stopped pinning
        noise_floor_estimate = -100 (which collapsed `rising` onto the absolute threshold and
        silently disabled the relative model in playback on every platform).

        Asserts the PHASE COUNT, not peak values — the noise shifts the peaks slightly, and a
        tight peak assertion would be measuring the noise rather than the detector.
        """
        from models.tap_display_settings import TapDisplaySettings

        assert os.path.exists(PLATE_NOISY_WAV), f"Test WAV not found: {PLATE_NOISY_WAV}"

        original_measure_flc = TapDisplaySettings.measure_flc()
        TapDisplaySettings.set_measure_flc(True)
        try:
            sut = plate_analyzer
            sut.tap_detection_threshold = PLATE_TAP_THRESHOLD
            sut.play_file_for_testing(
                path=PLATE_NOISY_WAV,
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


# REG-G ring-out (decay) — Recording 5.wav post-tap level decays to peak-15 dB. Shared
# cross-platform golden (web g4d-decay + Swift FilePlaybackRegression assert the same value):
# 0.0853 s ± 0.03 s. The web is audio-clock-deterministic; Python's wall-clock decay reaches the
# same crossing because file playback runs at real-time pace (wall-clock ≈ audio time 1:1). The
# loose tolerance covers per-platform chunk-granularity + clock jitter (web 0.0853, Python ~0.091).
G1_RING_OUT_SEC = 0.0853
RING_OUT_TOLERANCE = 0.03


def test_REG_G_generic_guitar_ringout(g1_analyzer):
    """Ring-out time for Recording 5.wav matches the cross-platform golden."""
    sut = g1_analyzer
    sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
    sut.tap_detection_threshold = G1_TAP_THRESHOLD
    sut.play_file_for_testing(
        path=G1_WAV, measurement_type=MeasurementType.GENERIC, number_of_taps=1
    )
    assert sut.current_decay_time is not None, "No ring-out measured"
    assert abs(sut.current_decay_time - G1_RING_OUT_SEC) < RING_OUT_TOLERANCE, (
        f"Ring-out: expected {G1_RING_OUT_SEC} ±{RING_OUT_TOLERANCE}, "
        f"got {sut.current_decay_time}"
    )
