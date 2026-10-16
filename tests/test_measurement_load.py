# @parity test/measurement-load
"""Loading a saved measurement: the whole load is the model's — its own settings, its peaks shown under
them, its spectra, label positions and microphone warning, and the detection state. The shared cases in
measurement-load.json (LD1-LD6), the same as Swift and the web. Mirrors Swift MeasurementLoadTests.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402
from guitar_tap.views.utilities.tap_settings_view import AppSettings as AS  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "measurement-load.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The settings a load writes are global; put them back afterwards."""
    saved = (TDS.measurement_type(), AS.show_unknown_modes(), AS.peak_min_threshold(),
             TDS.tap_detection_threshold(), AS.annotation_visibility_mode())
    yield
    TDS.set_measurement_type(saved[0])
    AS.set_show_unknown_modes(saved[1])
    AS.set_peak_min_threshold(saved[2])
    TDS.set_tap_detection_threshold(saved[3])
    AS.set_annotation_visibility_mode(saved[4])


def _measurement(name: str):
    """The measurement a load step names: an inline file of the case table, or a fixture."""
    inline = DATA.get("files", {}).get(name)
    if inline is not None:
        return measurements_from_json(json.dumps(inline))[0]
    with open(os.path.join(_HERE, name), encoding="utf-8") as f:
        return measurements_from_json(f.read())[0]


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_load(row, qapp):
    sut = TapToneAnalyzer.for_testing()
    for step in row["steps"]:
        if step.get("newTap"):
            sut.start_tap_sequence()
            assert sut.is_detecting, "precondition: a new tap sequence arms detection"
        elif "peakMin" in step:
            sut.peak_min_threshold = float(step["peakMin"])
        elif "load" in step:
            sut.load_measurement(_measurement(step["load"]))
        elif step.get("highlightFirstPeak"):
            sut.toggle_highlighted_peak(sut.peaks_above_peak_min[0].id)
            assert sut.highlighted_peak_id is not None, "precondition: a peak is highlighted"
        elif "compare" in step:
            sut.load_comparison([_measurement(n) for n in step["compare"]])
    is_guitar = TDS.measurement_type().is_guitar
    for field, want in row["expect"].items():
        if field == "measurementType":
            assert TDS.measurement_type().value == want, field
        elif field == "peakMinThreshold":
            assert sut.peak_min_threshold == want, field
        elif field == "tapDetectionThreshold":
            assert sut.tap_detection_threshold == pytest.approx(want, abs=1e-4), field
        elif field == "showUnknownModes":
            assert AS.show_unknown_modes() is want, field
        elif field == "shownPeaks":
            shown = len(sut.peaks_above_peak_min) if is_guitar else len(sut.material_identified_peaks)
            assert shown == want, field
        elif field == "frozenSpectrum":
            assert (len(sut.frozen_frequencies) > 0) is want, field
        elif field == "phaseSpectra":
            count = sum(s is not None for s in (sut.longitudinal_spectrum, sut.cross_spectrum, sut.flc_spectrum))
            assert count == want, field
        elif field == "complete":
            assert sut.is_measurement_complete is want, field
        elif field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "comparison":
            assert sut.is_comparing is want, field
        elif field == "microphoneWarning":
            assert (sut.microphone_warning is not None) is want, field
        elif field == "highlightedPeak":
            assert (sut.highlighted_peak_id is not None) is want, field
        elif field == "recordedMicrophone":
            assert (sut.result_provenance is not None) is want, field
        elif field == "labelPositions":
            assert len(sut.peak_annotation_offsets) == want, field
        else:
            pytest.fail(f"unknown field {field}")
