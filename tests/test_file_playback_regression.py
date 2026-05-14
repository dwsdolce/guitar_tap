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

Test plan coverage: REG-G1, REG-B1, REG-G2
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

# brace-umik-1-python-mac-1778452289.wav — Brace bar, UMIK-1 mic, 48 kHz.
# Saved gated capture: 19200 frames (400 ms) at 48000 Hz.
# Reference values from the .guitartap file and confirmed by running
# play_file_for_testing in both Swift and Python:
#   Peak frequency: 512.59 Hz
#   Peak magnitude: -65.69 dB
#   Tap detection threshold: -62 dB (from the .guitartap reference file)
# The test uses tolerances per the test plan: ±1.0 Hz, ±1.0 dB.
BRACE_EXPECTED_FREQ = 512.59  # Hz
BRACE_EXPECTED_MAG = -65.69   # dB
BRACE_TAP_THRESHOLD = -62.0   # dB — matches original measurement
FREQ_TOLERANCE = 1.0           # Hz
MAG_TOLERANCE = 1.0            # dB

# WAV file path — same file used in the Swift test suite.
BRACE_WAV = os.path.join(
    os.path.dirname(__file__),
    "brace-umik-1-python-mac-1778452289.wav",
)

# UMIK-1 calibration file — used for brace and plate measurements.
CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "7108913.txt")

# Plate longitudinal (L) capture WAV — saved gated capture from interactive
# measurement.  19200 frames (400 ms) at 48000 Hz, IEEE float 32-bit mono.
# Reference values from the interactive measurement session:
#   fL frequency: 66.6 Hz
#   fL magnitude: -58.4 dB
#   fL Q factor:  15.0
PLATE_L_WAV = os.path.join(
    os.path.dirname(__file__),
    "swift_Capturing_Longitudinal_2026-05-13T17-35-52Z.wav",
)
PLATE_L_EXPECTED_FREQ = 66.6   # Hz
PLATE_L_EXPECTED_MAG = -58.4   # dB
PLATE_L_EXPECTED_Q = 15.0
Q_TOLERANCE = 1.0              # dimensionless

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

@pytest.fixture
def brace_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=48000)


@pytest.fixture
def g1_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=48000)


@pytest.fixture
def guitar_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=48000)


@pytest.fixture
def plate_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=48000)


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

        Loads a saved brace capture WAV (400 ms, 48 kHz) and plays it through
        the full pipeline with measurement_type = BRACE.  Verifies that:
          1. The pipeline completes (material_tap_phase == COMPLETE)
          2. At least one longitudinal peak is detected
          3. The dominant peak frequency matches the .guitartap reference ± 1 Hz
          4. The dominant peak magnitude matches the reference ± 1 dB
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

    def test_REG_P1_plate_longitudinal_single_tap_produces_expected_peak(
        self, plate_analyzer
    ):
        """Plate longitudinal single-tap — known WAV produces expected fL peak.

        Loads a saved plate longitudinal capture WAV (400 ms, 48 kHz) and plays
        it through the full pipeline with measurement_type = PLATE.  Verifies:
          1. The pipeline auto-advances past L
          2. At least one longitudinal peak is detected
          3. The dominant peak frequency matches the reference ± 1 Hz
          4. The dominant peak magnitude matches the reference ± 1 dB
          5. The Q factor matches the reference ± 1
        """
        assert os.path.exists(PLATE_L_WAV), (
            f"Test WAV not found: {PLATE_L_WAV}"
        )

        sut = plate_analyzer
        sut.tap_detection_threshold = -62.0
        sut.play_file_for_testing(
            path=PLATE_L_WAV,
            measurement_type=MeasurementType.PLATE,
            calibration_path=CALIBRATION_FILE,
        )

        # 1. Pipeline should auto-advance past L.
        phase = sut.material_tap_phase
        assert phase != MaterialTapPhase.CAPTURING_LONGITUDINAL, (
            f"material_tap_phase should have advanced past L, got {phase}"
        )
        assert phase != MaterialTapPhase.NOT_STARTED, (
            f"material_tap_phase should have advanced past NOT_STARTED, got {phase}"
        )

        # 2. Longitudinal peaks should be populated.
        assert len(sut.longitudinal_peaks) > 0, (
            "longitudinal_peaks should not be empty"
        )

        # 3. Verify the auto-selected longitudinal peak.
        dominant = sut.selected_longitudinal_peak
        assert dominant is not None, "selected_longitudinal_peak is None"

        # 4. Verify frequency.
        freq_delta = abs(dominant.frequency - PLATE_L_EXPECTED_FREQ)
        assert freq_delta < FREQ_TOLERANCE, (
            f"fL frequency: expected {PLATE_L_EXPECTED_FREQ} Hz "
            f"±{FREQ_TOLERANCE}, got {dominant.frequency} Hz "
            f"(delta {freq_delta:.2f})"
        )

        # 5. Verify magnitude.
        mag_delta = abs(dominant.magnitude - PLATE_L_EXPECTED_MAG)
        assert mag_delta < MAG_TOLERANCE, (
            f"fL magnitude: expected {PLATE_L_EXPECTED_MAG} dB "
            f"±{MAG_TOLERANCE}, got {dominant.magnitude} dB "
            f"(delta {mag_delta:.2f})"
        )

        # 6. Verify Q factor.
        q_delta = abs(dominant.quality - PLATE_L_EXPECTED_Q)
        assert q_delta < Q_TOLERANCE, (
            f"fL Q factor: expected {PLATE_L_EXPECTED_Q} "
            f"±{Q_TOLERANCE}, got {dominant.quality} "
            f"(delta {q_delta:.2f})"
        )
