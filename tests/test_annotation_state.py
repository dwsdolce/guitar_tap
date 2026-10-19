# @parity test/annotation-state
"""The per-peak state the user edits and the views read: dragged label positions, selection, which
peaks are annotated, mode labels (the user's own and the auto-detected), the one definitive
Air/Top/Back and the tap-tone ratio, and what clears it all. The shared cases in annotation-state.json
(AS1-AS41), the same as Swift and the web: each loads its peaks as the app loads a file and edits them
as the views do.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode  # noqa: E402
from guitar_tap.models.guitar_mode import GuitarMode  # noqa: E402
from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "annotation-state.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

# The modes by Swift's case names, as the case file names them.
_MODES = {"air": GuitarMode.AIR, "top": GuitarMode.TOP, "back": GuitarMode.BACK, "dipole": GuitarMode.DIPOLE,
          "ringMode": GuitarMode.RING_MODE, "upperModes": GuitarMode.UPPER_MODES, "unknown": GuitarMode.UNKNOWN}
_MODE_NAMES = {mode: name for name, mode in _MODES.items()}


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Show Unknown Modes are global; put them back afterwards."""
    from guitar_tap.views.utilities.tap_settings_view import AppSettings as AS
    saved = (TDS.measurement_type(), AS.show_unknown_modes())
    yield
    TDS.set_measurement_type(saved[0])
    AS.set_show_unknown_modes(saved[1])


class _Case:
    """One case's analyzer and the names it gives its peaks."""

    def __init__(self, row: dict):
        self.sut = make_steps_analyzer()
        self.ids = {name: pid.upper() for name, pid in row["peakIds"].items()}
        self.names = {pid: name for name, pid in self.ids.items()}
        self.files = row["files"]

    def peak(self, name: str):
        """The analyzer's peak of that name, or — for a name the file does not hold — a peak at 220 Hz
        with that id, which the analyzer does not know."""
        pid = self.ids[name]
        for p in self.sut.all_peaks:
            if str(p.id).upper() == pid:
                return p
        return ResonantPeak(frequency=220.0, magnitude=-20.0, id=pid)

    def peak_id(self, name: str) -> str:
        """The id the analyzer holds for that name (its own spelling of it)."""
        for p in self.sut.all_peaks:
            if str(p.id).upper() == self.ids[name]:
                return p.id
        return self.ids[name]

    def name_of(self, pid) -> str:
        return self.names.get(str(pid).upper(), str(pid))

    def run(self, step: dict) -> bool:
        sut = self.sut
        if "load" in step:
            sut.load_measurement(measurements_from_json(json.dumps(self.files[step["load"]]))[0])
        elif "toggle" in step:
            sut.toggle_peak_selection(self.peak_id(step["toggle"]))
        elif step.get("selectNone"):
            sut.select_no_peaks()
        elif step.get("resetToAuto"):
            sut.reset_to_auto_selection()
        elif "override" in step:
            name, label = step["override"]
            sut.set_mode_override(label, self.peak_id(name))
        elif "resetOverride" in step:
            sut.reset_mode_override(self.peak_id(step["resetOverride"]))
        elif "offset" in step:
            name, hz, db = step["offset"]
            sut.update_annotation_offset(self.peak_id(name), (float(hz), float(db)))
        elif "resetOffset" in step:
            sut.reset_annotation_offset(self.peak_id(step["resetOffset"]))
        elif step.get("resetAllOffsets"):
            sut.reset_all_annotation_offsets()
        elif "visibility" in step:
            sut.annotation_visibility_mode = AnnotationVisibilityMode(step["visibility"])
        elif step.get("cycleVisibility"):
            sut.cycle_annotation_visibility()
        elif "guitarTypeChange" in step:
            TDS.set_measurement_type(MeasurementType(step["guitarTypeChange"]))
            sut.reclassify_for_guitar_type_change()
        else:
            return run_analyzer_step(step, sut)
        return True

    def check(self, fields: dict) -> None:
        sut = self.sut
        for field, want in fields.items():
            if field == "selected":
                assert sorted(self.name_of(i) for i in sut.selected_peak_ids) == sorted(want), field
            elif field == "userModified":
                assert sut.user_has_modified_peak_selection is want, field
            elif field == "visible":
                assert sorted(float(p.frequency) for p in sut.visible_peaks) == [float(v) for v in want], field
            elif field == "visibility":
                assert sut.annotation_visibility_mode.value == want, field
            elif field == "savedVisibility":
                assert TDS.annotation_visibility_mode().value == want, field
            elif field == "label":
                for name, label in want.items():
                    assert sut.effective_mode_label(self.peak(name)) == label, f"{field} {name}"
            elif field == "mode":
                for name, mode in want.items():
                    assert _MODE_NAMES[sut.peak_mode(self.peak(name))] == mode, f"{field} {name}"
            elif field == "autoMode":
                for name, mode in want.items():
                    assert _MODE_NAMES[sut.auto_detected_mode(self.peak(name))] == mode, f"{field} {name}"
            elif field == "manualOverride":
                for name, flag in want.items():
                    assert sut.has_manual_override(self.peak_id(name)) is flag, f"{field} {name}"
            elif field == "overrides":
                got = {self.name_of(i): label for i, label in sut.peak_mode_overrides.items()}
                assert got == want, f"{field}: {got}"
            elif field == "offsets":
                got = {self.name_of(i): [float(xy[0]), float(xy[1])] for i, xy in sut.peak_annotation_offsets.items()}
                assert got == {n: [float(v) for v in xy] for n, xy in want.items()}, f"{field}: {got}"
            elif field == "offsetCount":
                assert len(sut.peak_annotation_offsets) == want, field
            elif field == "getPeak":
                for mode, name in want.items():
                    peak = sut.get_peak(_MODES[mode])
                    assert (self.name_of(peak.id) if peak else None) == name, f"{field} {mode}"
            elif field == "hasRatio":
                assert (sut.calculate_tap_tone_ratio() is not None) is want, field
            elif field == "definitive":
                info = sut.definitive_mode_info()
                for mode, entry in want.items():
                    got = info.get(_MODES[mode])
                    if entry is None:
                        assert got is None, f"{field} {mode}: {got}"
                    else:
                        assert got is not None and float(got[0]) == pytest.approx(entry["hz"]) \
                            and got[1] is entry["isOverride"], f"{field} {mode}: {got}"
            elif field == "selectedIsAuto":
                auto = sut.guitar_mode_selected_peak_ids(sut.all_peaks)
                assert (set(sut.selected_peak_ids) == set(auto)) is want, field
            elif field == "materialPeakMode":
                fl = sut.selected_longitudinal_peak
                assert fl is not None, f"{field}: a captured fL peak"
                assert _MODE_NAMES[sut.peak_mode(fl)] == want, field
            else:
                pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_annotation_state(row, qapp):
    case = _Case(row)
    for step in row["steps"]:
        if "check" in step:
            case.check(step["check"])
        else:
            assert case.run(step), f"unknown step {step}"
    case.check(row["expect"])
