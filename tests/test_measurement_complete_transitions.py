# @parity test/measurement-complete
"""
``is_measurement_complete`` gates whether the spectrum freezes or keeps showing live frames, so every
path that should set it True or False is a case here — a new completion path without one is a gap —
and so are the paths that move the loaded-settings warning with it. The shared cases in
measurement-complete.json (MC1-MC18), the same as Swift and the web; below them, the cases about
Python's own signal and setter.
"""

from __future__ import annotations

import datetime
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "measurement-complete.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_type():
    """The measurement type is global; put it back afterwards."""
    saved = TapDisplaySettings.measurement_type()
    yield
    TapDisplaySettings.set_measurement_type(saved)


def _make_sut() -> TapToneAnalyzer:
    """A fresh analyzer: Classical Guitar, 1 tap, threshold -40, warm-up passed."""
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    sut = TapToneAnalyzer.for_testing()
    sut.number_of_taps = 1
    sut.tap_detection_threshold = -40.0
    sut.warmup_start_audio_time = -2.0
    sut.just_exited_warmup = False
    return sut


def _captured_tap(peak_db: float):
    """A captured tap: 64 bins at 31.25 Hz, -80 dB but bin 16 at ``peak_db``."""
    mags = np.full(64, -80.0)
    mags[16] = peak_db
    return (mags, np.arange(64) * 31.25, datetime.datetime.now())


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_transitions(row, qapp):
    sut = _make_sut()
    for step in row["steps"]:
        if "numberOfTaps" in step:
            sut.number_of_taps = step["numberOfTaps"]
        elif "captureTaps" in step:
            sut.captured_taps = [_captured_tap(db) for db in step["captureTaps"]]
        elif step.get("processTaps"):
            sut.process_multiple_taps()
        elif step.get("newTap"):
            sut.start_tap_sequence()
        elif step.get("cancel"):
            sut.cancel_tap_sequence()
        elif "load" in step:
            sut.load_measurement(measurements_from_json(json.dumps(DATA["files"][step["load"]]))[0])
        elif step.get("warning"):
            sut.show_loaded_settings_warning = True
        elif "setTaps" in step:
            sut.set_tap_num(step["setTaps"])
        elif "setThreshold" in step:
            sut.tap_detection_threshold = float(step["setThreshold"])
    for field, want in row["expect"].items():
        if field == "complete":
            assert sut.is_measurement_complete is want, field
        elif field == "frozenSpectrum":
            assert (len(sut.frozen_magnitudes) > 0 and len(sut.frozen_frequencies) > 0) is want, field
        elif field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "loadedSettingsWarning":
            assert sut.show_loaded_settings_warning is want, field
        elif field == "numberOfTaps":
            assert sut.number_of_taps == want, field
        else:
            pytest.fail(f"unknown field {field}")


# ---------------------------------------------------------------------------
# Python only: the measurementComplete signal, the setter, and the live frame after completion
# ---------------------------------------------------------------------------

def _completed(qapp) -> TapToneAnalyzer:
    sut = _make_sut()
    sut.captured_taps = [_captured_tap(-30.0)]
    sut.process_multiple_taps()
    assert sut.is_measurement_complete is True
    return sut


def test_completing_emits_measurement_complete(qapp):
    sut = _make_sut()
    received: list[bool] = []
    sut.measurementComplete.connect(received.append)
    sut.captured_taps = [_captured_tap(-30.0)]
    sut.process_multiple_taps()
    assert True in received


def test_a_new_sequence_emits_measurement_complete_false(qapp):
    sut = _completed(qapp)
    received: list[bool] = []
    sut.measurementComplete.connect(received.append)
    sut.start_tap_sequence()
    assert False in received


def test_a_live_frame_after_completion_leaves_the_frozen_spectrum(qapp):
    """The chart draws each frame from the engine's live frame and shows the frozen spectrum once the
    measurement is complete; the analyzer neither changes the frozen spectrum for a frame nor announces one."""
    sut = _completed(qapp)
    frozen = np.array(sut.frozen_magnitudes, copy=True)
    spectra: list[tuple] = []
    sut.spectrumUpdated.connect(lambda f, m: spectra.append((f, m)))
    sut.on_fft_frame(mag_y_db=np.full(64, -20.0), peak_db=-20.0)
    assert np.array_equal(sut.frozen_magnitudes, frozen), "a live frame changed the frozen spectrum"
    assert spectra == [], "the analyzer announced a spectrum for a live frame"


def test_leaving_completion_does_not_reset_the_frozen_spectrum(qapp):
    """The setter only assigns the flag and emits, as Swift's didSet; start_tap_sequence() resets."""
    sut = _completed(qapp)
    sut.set_measurement_complete(False)
    assert sut.is_measurement_complete is False
    assert len(sut.frozen_magnitudes) > 0 and len(sut.frozen_frequencies) > 0


@pytest.mark.parametrize("value", [True, False])
def test_the_setter_emits(value, qapp):
    sut = _make_sut()
    received: list[bool] = []
    sut.measurementComplete.connect(received.append)
    sut.set_measurement_complete(value)
    assert value in received


def test_assigning_the_flag_clears_the_warning(qapp):
    """A bare assignment enforces the rule: the flag is a property, as Swift's didSet."""
    sut = _make_sut()
    sut.show_loaded_settings_warning = True
    sut.is_measurement_complete = True
    assert sut.show_loaded_settings_warning is False
