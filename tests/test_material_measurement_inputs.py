# @parity test/material-measurement-inputs
"""A material measurement's own dimensions (Store B, ``TapToneAnalyzer.material_inputs``) and its notes:
taken from the Settings defaults (Store A) at completion, from the file on a load — which never writes
the Settings defaults — and written by a save. The shared cases in material-measurement-inputs.json
(M1-M13), the same as Swift and the web. Mirrors Swift MaterialMeasurementInputsTests.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "material-measurement-inputs.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

# The settings a case may set, by their Swift TapDisplaySettings names.
_SETTING_NAMES = ["measurementType", "plateLength", "plateWidth", "plateThickness", "plateMass",
                  "braceLength", "braceWidth", "braceThickness", "braceMass",
                  "guitarBodyLength", "guitarBodyWidth", "plateStiffnessPreset", "customPlateStiffness"]

# Store B's fields by the case file's names (Swift's).
_INPUT_FIELDS = {"lengthMM": "length_mm", "widthMM": "width_mm", "thicknessMM": "thickness_mm",
                 "massG": "mass_g", "bodyLengthMM": "body_length_mm", "bodyWidthMM": "body_width_mm",
                 "customStiffness": "custom_stiffness"}


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _setting(name: str):
    if name == "measurementType":
        return TDS.measurement_type().value
    return getattr(TDS, _snake(name))()


def _set_setting(name: str, value) -> None:
    if name == "measurementType":
        TDS.set_measurement_type(MeasurementType(value))
    else:
        getattr(TDS, "set_" + _snake(name))(value)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The settings are global; put them back afterwards."""
    saved = [(n, _setting(n)) for n in _SETTING_NAMES]
    yield
    for name, value in saved:
        _set_setting(name, value)


def _measurement(step: dict):
    """The inline file a load step names, with its notes replaced when the step gives them."""
    file = json.loads(json.dumps(DATA["files"][step["load"]]))
    if "notes" in step:
        file[0]["notes"] = step["notes"]
    return measurements_from_json(json.dumps(file))[0]


def _preset_name(preset) -> str:
    return preset.value if hasattr(preset, "value") else preset


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_material_inputs(row, qapp):
    sut = TapToneAnalyzer.for_testing()
    saved_record = None
    for step in row["steps"]:
        if "settings" in step:
            settings = step["settings"]
            # The type first, as a load applies it before the rest.
            if "measurementType" in settings:
                _set_setting("measurementType", settings["measurementType"])
            for name, value in settings.items():
                if name != "measurementType":
                    _set_setting(name, value)
        elif step.get("complete"):
            sut.set_measurement_complete(True)
        elif "loading" in step:
            sut.is_loading_measurement = step["loading"]
        elif step.get("clearInputs"):
            sut.material_inputs = None
        elif "hasInputs" in step:
            assert (sut.material_inputs is not None) is step["hasInputs"], "precondition: has dimensions"
        elif "load" in step:
            sut.load_measurement(_measurement(step))
        elif step.get("save"):
            saved_record = sut.make_measurement()

    for field, want in row["expect"].items():
        if field == "inputs":
            if want is None:
                assert sut.material_inputs is None, f"inputs: {sut.material_inputs}"
                continue
            mi = sut.material_inputs
            assert mi is not None, "dimensions"
            for key, value in want.items():
                if key == "stiffnessPreset":
                    assert _preset_name(mi.stiffness_preset) == value, key
                else:
                    assert getattr(mi, _INPUT_FIELDS[key]) == pytest.approx(value, abs=1e-4), key
        elif field == "settings":
            for name, value in want.items():
                assert _setting(name) == pytest.approx(value, abs=1e-4), f"setting {name}"
        elif field == "saved":
            snap = saved_record.longitudinal_snapshot
            assert snap is not None, "saved snapshot"
            for key, value in want.items():
                actual = getattr(snap, _snake(key))
                if key == "plateStiffnessPreset":
                    assert _preset_name(actual) == value, key
                else:
                    assert actual == pytest.approx(value, abs=1e-4), key
        elif field == "loadedNotes":
            assert sut.loaded_notes == want, f"loadedNotes: {sut.loaded_notes!r}"
        else:
            raise AssertionError(f"unknown field {field}")
