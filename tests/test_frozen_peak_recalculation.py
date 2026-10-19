# @parity test/frozen-peak-recalc
"""Frozen peaks: Re-analyze's re-detection, Peak Min's projection, and what a load, a live frame, a
capture, Save and Redo do to a measurement's peaks and their per-peak state — each through the app's own
path. A measurement is put in place by writing a .guitartap document and loading it as the app loads a
file. The shared cases in frozen-peak-recalc.json, the same as Swift and the web.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402
from test_peak_finding import _spectrum  # noqa: E402

from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_measurement import TapEntry  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "frozen-peak-recalc.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TDS.measurement_type(), TDS.measure_flc())
    yield
    TDS.set_measurement_type(saved[0])
    TDS.set_measure_flc(saved[1])


# ── The document a load step describes ──────────────────────────────────────────────────────────


class _Run:
    """What a case's run keeps between steps: the ids a load wrote and the state a mark recorded."""

    def __init__(self):
        self.next_id = 1
        self.loaded_ids: list[uuid.UUID] = []
        self.marked_ids: list[str] = []
        self.marked_selection: set = set()
        self.marked_tap_entries: list = []
        self.marked_tap_selections: list = []

    def new_id(self) -> str:
        self.next_id += 1
        return f"00000000-0000-0000-0000-{self.next_id - 1:012d}"


def _snapshot(spec: dict | None, mtype: str) -> dict:
    mags, freqs = _spectrum(spec) if spec is not None else ([-100.0] * 4, [0.0, 100.0, 200.0, 300.0])
    return {"frequencies": list(freqs), "magnitudes": list(mags), "minFreq": 0, "maxFreq": 600,
            "minDB": -100, "maxDB": 0, "isLogarithmic": False,
            "measurementType": mtype, "guitarType": mtype.split(" ")[0]}


def _peaks(rows: list, run: _Run):
    """The peaks of a load step, written as the file writes them, with each one's id by frequency."""
    out, ids = [], []
    for hz, db in rows:
        pid = run.new_id()
        out.append({"id": pid, "frequency": hz, "magnitude": db, "quality": 10,
                    "bandwidth": hz / 10, "timestamp": "2026-01-01T00:00:00Z"})
        ids.append((hz, pid))
    return out, ids


def _id(hz, ids) -> str:
    return next(pid for f, pid in ids if abs(f - float(hz)) <= 1)


def _document(load: dict, run: _Run) -> dict:
    mtype = load["type"]
    snap = _snapshot(load.get("spectrum"), mtype)
    if "showUnknownModes" in load:
        snap["showUnknownModes"] = load["showUnknownModes"]
    peaks, ids = _peaks(load["peaks"], run)
    doc = {"id": run.new_id(), "timestamp": "2026-01-01T00:00:00Z", "peaks": peaks}
    if "spectrum" in load:
        doc["spectrumSnapshot"] = snap
    if "selected" in load:
        doc["selectedPeakIDs"] = [_id(hz, ids) for hz in load["selected"]]
    if "userModified" in load:
        doc["userModifiedSelection"] = load["userModified"]
    if "overrides" in load:
        doc["peakModeOverrides"] = [x for hz, label in load["overrides"].items()
                                    for x in (_id(hz, ids), {"label": label, "type": "assigned"})]
    if "offsets" in load:
        doc["peakAnnotationOffsets"] = [x for hz, (px, py) in load["offsets"].items()
                                        for x in (_id(hz, ids), {"absFreqHz": px, "absDB": py})]
    if "tapEntries" in load:
        entries = []
        for i, e in enumerate(load["tapEntries"]):
            epeaks, eids = _peaks(e["peaks"], run)
            entries.append({"id": run.new_id(), "tapIndex": i + 1, "snapshot": snap, "peaks": epeaks,
                            "selectedPeakIDs": [_id(hz, eids) for hz in e["selected"]]})
        doc["tapEntries"] = entries
    run.loaded_ids = [uuid.UUID(pid) for _, pid in ids]
    return doc


# ── Peaks named by frequency ────────────────────────────────────────────────────────────────────


def _known(sut) -> list:
    """Every peak the state can name: the measurement's peaks and a material measurement's identified ones."""
    return list(sut.all_peaks) + list(sut.material_identified_peaks)


def _peak_at(hz, sut):
    return next(p for p in _known(sut) if abs(p.frequency - float(hz)) <= 1)


def _same_freqs(got, want) -> bool:
    g, w = sorted(got), sorted(float(x) for x in want)
    return len(g) == len(w) and all(abs(a - b) <= 1 for a, b in zip(g, w))


def _same_map(got: dict, want: dict, sut, equal, peaks=None) -> bool:
    """An id-keyed map, by its peaks' frequencies (the analyzer's, or ``peaks``), against the case's
    frequency-keyed one."""
    if len(got or {}) != len(want):
        return False
    for pid, value in (got or {}).items():
        p = next((q for q in (peaks if peaks is not None else _known(sut)) if q.id == pid), None)
        key = None if p is None else next((k for k in want if abs(float(k) - p.frequency) <= 1), None)
        if key is None or not equal(value, want[key]):
            return False
    return True


# ── Steps and checks ────────────────────────────────────────────────────────────────────────────


def _check_saved(saved, want: dict, sut, msg: str) -> None:
    """The last saved measurement against the case's 'saved' fields."""
    snap = saved.spectrum_snapshot or saved.longitudinal_snapshot
    for key, w in want.items():
        m = f"{msg} {key}"
        if key == "peaks":
            assert _same_freqs([p.frequency for p in saved.peaks], w), m
        elif key == "selectedAll":
            assert (set(saved.selected_peak_ids or []) == {p.id for p in saved.peaks}) is w, m
        elif key == "selected":
            ids = set(saved.selected_peak_ids or [])
            got = [p.frequency for p in saved.peaks if p.id in ids]
            assert _same_freqs(got, w), f"{m}: {got}"
        elif key == "overrides":
            assert _same_map(saved.peak_mode_overrides, w, sut, lambda v, x: v == x, saved.peaks), \
                f"{m}: {saved.peak_mode_overrides}"
        elif key == "offsets":
            assert _same_map(saved.annotation_offsets, w, sut,
                             lambda v, x: (float(v[0]), float(v[1])) == (float(x[0]), float(x[1])), saved.peaks), \
                f"{m}: {saved.annotation_offsets}"
        elif key == "name":
            assert saved.measurement_name == w, f"{m}: {saved.measurement_name}"
        elif key == "notes":
            assert saved.notes == w, f"{m}: {saved.notes}"
        elif key == "tapThreshold":
            assert saved.tap_detection_threshold == pytest.approx(w), f"{m}: {saved.tap_detection_threshold}"
        elif key == "peakMin":
            assert saved.peak_min_threshold == pytest.approx(w), f"{m}: {saved.peak_min_threshold}"
        elif key == "numberOfTaps":
            assert saved.number_of_taps == w, f"{m}: {saved.number_of_taps}"
        elif key == "measurementType":
            assert snap is not None and snap.measurement_type == w, f"{m}: {snap and snap.measurement_type}"
        elif key == "guitarType":
            assert snap is not None and snap.guitar_type == w, f"{m}: {snap and snap.guitar_type}"
        elif key == "showUnknownModes":
            assert snap is not None and snap.show_unknown_modes is w, f"{m}: {snap and
            snap.show_unknown_modes}"
        elif key == "phaseSpectra":
            got = [n for n, sp in (("L", saved.longitudinal_snapshot), ("C", saved.cross_snapshot),
                                   ("FLC", saved.flc_snapshot)) if sp is not None]
            assert got == w, f"{m}: {got}"
        elif key == "tapEntries":
            assert len(saved.tap_entries or []) == w, f"{m}: {len(saved.tap_entries or [])}"
        elif key == "offsetsInFile":
            from guitar_tap.views.tap_analysis_results_view import measurements_to_json
            file = json.loads(measurements_to_json([saved]))
            assert ("peakAnnotationOffsets" in file[0]) is w, \
                f"{m}: {file[0].get('peakAnnotationOffsets')}"
        elif key == "comparisonColors":
            got = [list(e.color_components) for e in saved.multi_tap_comparison_entries]
            assert len(got) == len(w) and all(g == pytest.approx(x, abs=1e-6) for g, x in zip(got, w)), \
                f"{m}: {got}"
        else:
            pytest.fail(f"{msg}: unknown saved field {key}")


def _check(fields: dict, sut, run: _Run, case_id: str) -> None:
    for field, want in fields.items():
        msg = f"{case_id} {field}"
        if field == "peaks":
            assert _same_freqs([p.frequency for p in sut.all_peaks], want), f"{msg}: {[p.frequency for p in sut.all_peaks]}"
        elif field == "shown":
            got = [p.frequency for p in sut.peaks_above_peak_min]
            assert _same_freqs(got, want), f"{msg}: {got}"
        elif field == "selected":
            got = [p.frequency for p in sut.selected_peaks]
            assert _same_freqs(got, want), f"{msg}: {got}"
        elif field == "overrides":
            assert _same_map(sut.peak_mode_overrides, want, sut, lambda v, w: v == w), f"{msg}: {sut.peak_mode_overrides}"
        elif field == "offsets":
            assert _same_map(sut.peak_annotation_offsets, want, sut,
                             lambda v, w: (float(v[0]), float(v[1])) == (float(w[0]), float(w[1]))), \
                f"{msg}: {sut.peak_annotation_offsets}"
        elif field == "labels":
            for hz, label in want.items():
                p = next((q for q in _known(sut) if abs(q.frequency - float(hz)) <= 1), None)
                got = None if p is None else sut.effective_mode_label(p)
                assert got == label, f"{msg} {hz}: {got}"
        elif field == "modes":
            modes = {e["peak"].id: e["mode"].value for e in sut.identified_modes}
            assert _same_map(modes, want, sut, lambda v, w: v == w), f"{msg}: {modes}"
        elif field == "tapEntries":
            assert len(sut.tap_entries) == len(want), f"{msg}: count"
            for e, w in zip(sut.tap_entries, want):
                assert _same_freqs([p.frequency for p in e.peaks], w["peaks"]), f"{msg} peaks"
                sel = [p.frequency for p in e.peaks if p.id in e.selected_peak_ids]
                assert _same_freqs(sel, w["selected"]), f"{msg} selected"
        elif field == "idsAsMarked":
            assert ([p.id for p in sut.all_peaks] == run.marked_ids) is want, msg
        elif field == "selectedIdsAsMarked":
            assert (set(sut.selected_peak_ids) == run.marked_selection) is want, msg
        elif field == "tapEntriesAsMarked":
            same = ([[p.id for p in e.peaks] for e in sut.tap_entries] == run.marked_tap_entries
                    and [list(e.selected_peak_ids) for e in sut.tap_entries] == run.marked_tap_selections)
            assert same is want, msg
        elif field == "idsAsLoaded":
            assert ({p.id for p in sut.all_peaks} == set(run.loaded_ids)) is want, msg
        elif field == "canReanalyze":
            assert sut.can_reanalyze is want, msg
        elif field == "complete":
            assert sut.is_measurement_complete is want, msg
        elif field == "tapCount":
            assert sut.current_tap_count == want, f"{msg}: {sut.current_tap_count}"
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{msg}: {sut.material_tap_phase}"
        elif field in ("fL", "fC"):
            p = sut.selected_longitudinal_peak if field == "fL" else sut.selected_cross_peak
            if want is None:
                assert p is None, f"{msg}: {p}"
            else:
                assert p is not None and abs(p.frequency - want) <= 1, f"{msg}: {p}"
        elif field == "materialPeaks":
            assert _same_freqs([p.frequency for p in sut.material_identified_peaks], want), msg
        elif field == "saved":
            _check_saved(sut.saved_measurements[-1], want, sut, msg)
        else:
            pytest.fail(f"{case_id}: unknown field {field}")


def _step(step: dict, sut, run: _Run, case_id: str) -> None:
    if "load" in step:
        sut.load_measurement(measurements_from_json(json.dumps([_document(step["load"], run)]))[0])
    elif step.get("reanalyze"):
        sut.reanalyze_peaks()
    elif "toggleSelection" in step:
        sut.toggle_peak_selection(_peak_at(step["toggleSelection"], sut).id)
    elif "nameMode" in step:
        sut.set_mode_override(step["nameMode"]["label"], _peak_at(step["nameMode"]["at"], sut).id)
    elif "dragLabel" in step:
        x, y = step["dragLabel"]["to"]
        sut.update_annotation_offset(_peak_at(step["dragLabel"]["at"], sut).id, (float(x), float(y)))
    elif "liveFrame" in step:
        mags, freqs = _spectrum(step["liveFrame"])
        sut.analyze_magnitudes(list(mags), list(freqs), max(mags))
    elif step.get("save"):
        given = step["save"] if isinstance(step["save"], dict) else {}
        sut.save_measurement(measurement_name=given.get("name"), notes=given.get("notes"))
    elif step.get("loadSaved"):
        sut.load_measurement(sut.saved_measurements[-1])
    elif step.get("mark"):
        run.marked_ids = [p.id for p in sut.all_peaks]
        run.marked_selection = set(sut.selected_peak_ids)
        run.marked_tap_entries = [[p.id for p in e.peaks] for e in sut.tap_entries]
        run.marked_tap_selections = [list(e.selected_peak_ids) for e in sut.tap_entries]
    else:
        assert run_analyzer_step(step, sut), f"{case_id}: unknown step {step}"


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_frozen_peaks(row, qapp):
    sut = make_steps_analyzer()
    run = _Run()
    for step in row["steps"]:
        if "check" in step:
            _check(step["check"], sut, run, row["id"])
        else:
            _step(step, sut, run, row["id"])
    _check(row["expect"], sut, run, row["id"])


@pytest.mark.parametrize("row", DATA["tapEntryModes"], ids=lambda r: r["id"])
def test_tap_entry_modes(row):
    run = _Run()
    peaks, ids = _peaks(row["peaks"], run)
    entry = TapEntry.from_dict({"id": run.new_id(), "tapIndex": 1, "snapshot": _snapshot(None, "Generic Guitar"),
                                "peaks": peaks, "selectedPeakIDs": [_id(hz, ids) for hz in row["selected"]]})
    modes = entry.resolved_mode_peaks(guitar_type=row["guitarType"])
    got = {mode.value: peak.frequency for mode, peak in modes.items()}
    assert got == {k: float(v) for k, v in row["expect"].items()}, f"{row['id']}: {got}"
