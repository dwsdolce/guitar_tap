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

Test plan coverage: REG-B1
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def brace_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(fft_size=16384, sample_rate=48000)


# ---------------------------------------------------------------------------
# Tests  (REG-B1)
# ---------------------------------------------------------------------------

class TestFilePlaybackRegression:
    """Full-pipeline file playback regression tests."""

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
