"""
Tests for is_measurement_complete state transitions.

Mirrors Swift TapDetectionTests / isMeasurementComplete didSet behaviour.

## Why this file exists

`is_measurement_complete` is the single boolean that gates whether the spectrum
display freezes or continues to paint live FFT frames.  It must be set True by
every capture-completion path and False by every reset/cancel path.

A previous bug (frozen spectrum not freezing after guitar tap) was caused by
`_finish_capture()` setting `frozen_magnitudes` directly but never calling
`set_measurement_complete(True)`.  The audit (§5) had declared "Full method
parity" without a line-by-line assignment check on this critical flag.

These tests are the automated guard against that class of regression:
every path in and out of is_measurement_complete = True is exercised and
asserted.

## Critical-flag rule (from audit guidelines Rule 8)

For `is_measurement_complete` (and any other critical state flag), EVERY code
path that should set it True or False must have a corresponding test here.
Adding a new completion path in Python without adding a test here is a gap.
"""

from __future__ import annotations

import sys
import os
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from PySide6 import QtCore, QtWidgets

from models.tap_tone_analyzer import TapToneAnalyzer
from models.tap_display_settings import TapDisplaySettings
from models.measurement_type import MeasurementType

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _make_guitar_sut(number_of_taps: int = 1) -> TapToneAnalyzer:
    """Return a TapToneAnalyzer primed for guitar-mode tap detection."""
    _get_app()
    sut = TapToneAnalyzer()
    sut.number_of_taps = number_of_taps
    sut.tap_detection_threshold = -40.0
    sut.hysteresis_margin = 5.0
    # Defeat warm-up guard
    sut.analyzer_start_time = time.monotonic() - 2.0
    sut.just_exited_warmup = False
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    # Arm detection
    sut.is_detecting = True
    sut.is_detection_paused = False
    sut.is_measurement_complete = False
    # Pre-populate freq so _finish_capture / frozen_frequencies assignment works
    sut.freq = np.linspace(0, 2000, 256)
    return sut


def _fake_spectrum(n: int = 256, peak_db: float = -30.0) -> np.ndarray:
    """Return a spectrum with a single peak at bin n//4."""
    mags = np.full(n, -80.0)
    mags[n // 4] = peak_db
    return mags


def _pump_events() -> None:
    """Drain the Qt event loop so QTimer.singleShot callbacks fire."""
    for _ in range(10):
        _get_app().processEvents()
        time.sleep(0.02)
        _get_app().processEvents()


# ---------------------------------------------------------------------------
# Path 1: guitar single-tap → _finish_capture sets is_measurement_complete True
# ---------------------------------------------------------------------------

class TestGuitarSingleTapCompletion:
    """Mirrors Swift processMultipleTaps() setting isMeasurementComplete = true."""

    def test_finish_capture_sets_measurement_complete(self):
        """After _finish_capture fires, is_measurement_complete must be True."""
        sut = _make_guitar_sut(number_of_taps=1)
        sut.captured_taps = [_fake_spectrum()]
        sut._finish_capture()
        assert sut.is_measurement_complete is True

    def test_finish_capture_emits_measurementComplete_signal(self):
        """measurementComplete(True) must be emitted by _finish_capture."""
        sut = _make_guitar_sut(number_of_taps=1)
        sut.captured_taps = [_fake_spectrum()]
        received: list[bool] = []
        sut.measurementComplete.connect(received.append)
        sut._finish_capture()
        assert True in received, "measurementComplete(True) was not emitted"

    def test_finish_capture_freezes_spectrum(self):
        """frozen_magnitudes must be populated when measurement completes."""
        sut = _make_guitar_sut(number_of_taps=1)
        mag = _fake_spectrum()
        sut.captured_taps = [mag]
        sut._finish_capture()
        assert len(sut.frozen_magnitudes) > 0
        assert len(sut.frozen_frequencies) > 0

    def test_on_fft_frame_stops_live_updates_after_complete(self):
        """After _finish_capture, on_fft_frame must not call analyze_magnitudes."""
        sut = _make_guitar_sut(number_of_taps=1)
        sut.captured_taps = [_fake_spectrum()]
        sut._finish_capture()
        assert sut.is_measurement_complete is True

        # Track spectrum emissions — after complete, only frozen data should emit
        spectra_received: list[tuple] = []
        sut.spectrumUpdated.connect(lambda f, m: spectra_received.append((f, m)))

        live_mag = _fake_spectrum(peak_db=-20.0)  # distinctly different from frozen
        sut.on_fft_frame(
            mag_y_db=live_mag,
            mag_y=np.power(10.0, live_mag / 20.0),
            fft_peak_amp=80,
            rms_amp=70,
            fps=2.7,
            sample_dt=0.37,
            processing_dt=0.01,
        )
        # Every emitted spectrum must be the frozen one, not the live one
        for freqs, mags in spectra_received:
            assert np.array_equal(mags, sut.frozen_magnitudes), (
                "Live FFT data painted over frozen spectrum after measurement complete"
            )


# ---------------------------------------------------------------------------
# Path 2: guitar multi-tap → _finish_capture after N taps
# ---------------------------------------------------------------------------

class TestGuitarMultiTapCompletion:
    """Two captured taps averaged — is_measurement_complete must still be True."""

    def test_two_tap_average_sets_measurement_complete(self):
        sut = _make_guitar_sut(number_of_taps=2)
        sut.captured_taps = [_fake_spectrum(peak_db=-32.0), _fake_spectrum(peak_db=-28.0)]
        sut._finish_capture()
        assert sut.is_measurement_complete is True

    def test_two_tap_average_frozen_spectrum_populated(self):
        sut = _make_guitar_sut(number_of_taps=2)
        sut.captured_taps = [_fake_spectrum(peak_db=-32.0), _fake_spectrum(peak_db=-28.0)]
        sut._finish_capture()
        assert len(sut.frozen_magnitudes) == 256


# ---------------------------------------------------------------------------
# Path 3: start_tap_sequence resets is_measurement_complete to False
# ---------------------------------------------------------------------------

class TestStartTapSequenceResetsComplete:
    """start_tap_sequence must set is_measurement_complete = False (mirrors Swift)."""

    def test_start_tap_sequence_clears_measurement_complete(self):
        sut = _make_guitar_sut(number_of_taps=1)
        # Simulate a completed measurement
        sut.captured_taps = [_fake_spectrum()]
        sut._finish_capture()
        assert sut.is_measurement_complete is True

        # Now start a new sequence — must reset the flag
        sut.start_tap_sequence()
        assert sut.is_measurement_complete is False

    def test_start_tap_sequence_emits_measurementComplete_false(self):
        sut = _make_guitar_sut(number_of_taps=1)
        sut.captured_taps = [_fake_spectrum()]
        sut._finish_capture()

        received: list[bool] = []
        sut.measurementComplete.connect(received.append)
        sut.start_tap_sequence()
        assert False in received, "measurementComplete(False) was not emitted by start_tap_sequence"


# ---------------------------------------------------------------------------
# Path 4: cancel_tap_sequence clears frozen spectrum (is_measurement_complete stays True)
# ---------------------------------------------------------------------------

class TestCancelTapSequenceResetsComplete:
    """cancel_tap_sequence clears the frozen spectrum (mirrors Swift cancelTapSequence).

    NOTE: cancel does NOT set is_measurement_complete = False — this matches Swift,
    where cancelTapSequence() only calls setFrozenSpectrum([], []) and leaves
    isMeasurementComplete as-is.  The display shows nothing because both frozen
    arrays are empty; the flag is cleared on the next startTapSequence() call.
    """

    def test_cancel_clears_frozen_spectrum(self):
        """cancel_tap_sequence must clear frozen arrays (mirrors Swift line 289)."""
        sut = _make_guitar_sut(number_of_taps=1)
        sut.captured_taps = [_fake_spectrum()]
        sut._finish_capture()
        assert len(sut.frozen_magnitudes) > 0

        sut.cancel_tap_sequence()
        assert len(sut.frozen_magnitudes) == 0
        assert len(sut.frozen_frequencies) == 0


# ---------------------------------------------------------------------------
# Path 5: set_measurement_complete(False) clears frozen spectrum and captured taps
# ---------------------------------------------------------------------------

class TestSetMeasurementCompleteDirectly:
    """set_measurement_complete is the canonical setter — verify its contract."""

    def test_set_false_clears_frozen_arrays(self):
        sut = _make_guitar_sut()
        sut.captured_taps = [_fake_spectrum()]
        sut._finish_capture()
        assert len(sut.frozen_magnitudes) > 0

        sut.set_measurement_complete(False)
        assert len(sut.frozen_magnitudes) == 0
        assert len(sut.frozen_frequencies) == 0

    def test_set_true_emits_signal(self):
        sut = _make_guitar_sut()
        received: list[bool] = []
        sut.measurementComplete.connect(received.append)
        sut.set_measurement_complete(True)
        assert True in received

    def test_set_false_emits_signal(self):
        sut = _make_guitar_sut()
        received: list[bool] = []
        sut.measurementComplete.connect(received.append)
        sut.set_measurement_complete(False)
        assert False in received


# ---------------------------------------------------------------------------
# Path 6: load_measurement sets is_measurement_complete to True
# ---------------------------------------------------------------------------

class TestLoadMeasurementSetsComplete:
    """Loading a saved measurement must freeze the display (mirrors Swift loadMeasurement)."""

    def test_load_measurement_sets_measurement_complete(self):
        from models.tap_tone_measurement import TapToneMeasurement
        from models.spectrum_snapshot import SpectrumSnapshot

        sut = _make_guitar_sut()
        assert sut.is_measurement_complete is False

        # Build a minimal measurement with a spectrum snapshot.
        # TapToneMeasurement.create() takes measurement_type as a str and
        # generates its own timestamp — no timestamp parameter needed.
        freqs = list(np.linspace(0, 2000, 64))
        mags = list(_fake_spectrum(n=64))
        snap = SpectrumSnapshot(
            frequencies=freqs,
            magnitudes=mags,
            measurement_type="Classical Guitar",
        )
        m = TapToneMeasurement.create(
            measurement_type="Classical Guitar",
            guitar_type=None,
            peaks=[],
            spectrum_snapshot=snap,
            number_of_taps=1,
        )
        sut.load_measurement(m)
        assert sut.is_measurement_complete is True
