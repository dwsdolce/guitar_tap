# @parity test/button-enablement
"""The Pause / New Tap / Cancel enablement rule — ``button_rule``, the production function
``_update_tap_buttons`` calls — against the shared case file ``button-enablement.json`` (B1–B16), the same
cases the Swift and web suites run; and the analyzer's Save / export rule, which drives a live analyzer.
Names in the file are Swift's."""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode
from guitar_tap.models.button_enablement import ButtonState, button_rule
from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType

with open(os.path.join(os.path.dirname(__file__), "button-enablement.json"), encoding="utf-8") as _f:
    CASES = json.load(_f)["buttonRule"]


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).upper()


def _state(s: dict) -> ButtonState:
    """A case's state: the fields it sets, the rest left at ButtonState's defaults."""
    kw = {
        "detection_state": DetectionState[s["detectionState"].upper()],
        "is_measurement_complete": s["isMeasurementComplete"],
        "display_mode": AnalysisDisplayMode[s["displayMode"].upper()],
    }
    if "isReadyForDetection" in s:
        kw["is_ready_for_detection"] = s["isReadyForDetection"]
    if "fftIsRunning" in s:
        kw["fft_is_running"] = s["fftIsRunning"]
    if "measurementType" in s:
        kw["measurement_type"] = MeasurementType[s["measurementType"].upper()]
    if "materialTapPhase" in s:
        kw["material_tap_phase"] = MaterialTapPhase[_snake(s["materialTapPhase"])]
    if "numberOfTaps" in s:
        kw["number_of_taps"] = s["numberOfTaps"]
    if "isPlayingFile" in s:
        kw["is_playing_file"] = s["isPlayingFile"]
    return ButtonState(**kw)


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["id"])
def test_button_rule(row):
    out = button_rule(_state(row["state"]))
    names = {"pauseEnabled": "pause_enabled", "newTapDisabled": "new_tap_disabled", "cancelEnabled": "cancel_enabled"}
    for key, expected in row["expect"].items():
        assert getattr(out, names[key]) is expected, key


def test_has_result_to_save_or_export_only_for_a_complete_measurement_or_a_comparison():
    """Save and the exports: enabled only when there is something to save or export — a complete
    measurement or a comparison. One analyzer rule, read by the Save and export buttons and the menu."""
    from PySide6 import QtWidgets

    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    sut = TapToneAnalyzer()
    assert not sut.has_result_to_save_or_export, "nothing to save or export while live"
    sut.is_measurement_complete = True
    assert sut.has_result_to_save_or_export, "a complete measurement"
    sut.is_measurement_complete = False
    sut.display_mode = AnalysisDisplayMode.COMPARISON
    assert sut.has_result_to_save_or_export, "a comparison"
