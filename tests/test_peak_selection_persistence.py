# @parity test/peak-selection-persistence
"""Whether a guitar measurement's peak selection was the user's own (manual) or the app's (automatic)
is saved with it: a loaded manual selection — or one from a file saved before the flag existed —
enables the Reset to automatic selection (wand) button, and the wand makes it automatic again.

The cases are the shared ones in peak-selection-persistence.json (PSP1-PSP6), the same as Swift and
the web. They use the real swift-mac capture, saved with the automatic selection at Peak Min -60,
which leaves out the Air peak at 97.26 Hz / -64.21 dB; the automatic selection over all the peaks
includes it.

Mirrors Swift PeakSelectionPersistenceTests.
"""
from __future__ import annotations

import base64
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement  # noqa: E402

import pytest  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "peak-selection-persistence.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _fixture_spectrum():
    with open(os.path.join(os.path.dirname(__file__), DATA["fixture"]), encoding="utf-8") as f:
        sn = json.load(f)[0]["spectrumSnapshot"]
    mags = np.frombuffer(base64.b64decode(sn["magnitudesData"]), dtype="<f4").astype(float).tolist()
    freqs = np.frombuffer(base64.b64decode(sn["frequenciesData"]), dtype="<f4").astype(float).tolist()
    return mags, freqs


def _analyzer() -> TapToneAnalyzer:
    TDS.set_guitar_type("Generic")
    sut = TapToneAnalyzer.for_testing()
    sut.min_frequency = DATA["minHz"]
    sut.max_frequency = DATA["maxHz"]
    return sut


def _make_measurement(user_modified):
    sut = _analyzer()
    mags, freqs = _fixture_spectrum()
    full = sut.find_peaks(mags, freqs, min_hz=DATA["minHz"], max_hz=DATA["maxHz"], peak_min_override=-100)
    displayed = [p for p in full if p.magnitude >= DATA["savedPeakMin"]]
    winners = sut.guitar_mode_selected_peak_ids(displayed)
    snap = SpectrumSnapshot(
        frequencies=freqs, magnitudes=mags, min_freq=75.0, max_freq=350.0,
        min_db=-100.0, max_db=0.0, is_logarithmic=False,
        guitar_type="Generic", measurement_type="Generic Guitar",
    )
    m = TapToneMeasurement.create(
        peaks=full,
        spectrum_snapshot=snap,
        tap_detection_threshold=-49.0,
        number_of_taps=1,
        peak_min_threshold=DATA["savedPeakMin"],
        selected_peak_ids=list(winners),
        selected_peak_frequencies=[p.frequency for p in displayed if p.id in winners],
        user_modified_selection=user_modified,
    )
    air_selected_in_save = any(p.id in winners and abs(p.frequency - DATA["airHz"]) < 1 for p in full)
    return m, air_selected_in_save


@pytest.mark.parametrize("row", DATA["load"], ids=lambda r: r["id"])
def test_load(row):
    m, air_in_save = _make_measurement(row["userModified"])
    assert not air_in_save, "precondition: Air is not in the saved selection"
    sut = _analyzer()
    sut.load_measurement(m)
    air = next((p for p in sut.all_peaks if abs(p.frequency - DATA["airHz"]) < 1), None)
    assert air is not None, "the Air peak is loaded"
    assert sut.user_has_modified_peak_selection is row["expectManual"], "manual (the wand enabled)"
    assert (air.id in set(sut.selected_peak_ids)) is row["expectAirSelected"], "Air selected"
    sut.reset_to_auto_selection()
    assert sut.user_has_modified_peak_selection is row["expectManualAfterReset"], "manual after the wand"
    assert (air.id in set(sut.selected_peak_ids)) is row["expectAirSelectedAfterReset"], "Air selected after the wand"


@pytest.mark.parametrize("row", DATA["roundTrip"], ids=lambda r: r["id"])
def test_round_trip(row):
    m, _ = _make_measurement(row["userModified"])
    d = m.to_dict()
    assert ("userModifiedSelection" in d) is row["expectWritten"], "written"
    back = TapToneMeasurement.from_dict(json.loads(json.dumps(d)))
    assert back.user_modified_selection == row["expectRead"], "read back"
