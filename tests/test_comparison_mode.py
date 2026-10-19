# @parity test/comparison
"""Comparing saved measurements: the entries a comparison holds, their labels and range, the mode,
detection standing down, the per-tap overlay giving way, each entry's Air/Top/Back taken from its
source, and saving and loading a comparison. The shared cases in comparison.json (CM1-CM25), the same
as Swift and the web. Below them, Python's own comparisonChanged signal.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6 import QtWidgets

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_file, measurements_from_json  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "comparison.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)
_PEAK_NAMES = {k.upper(): v for k, v in DATA["peakNames"].items()}


@pytest.fixture(autouse=True)
def _restore_type():
    """The measurement type, and the display ranges a case's settings step writes, are global; put
    them back afterwards."""
    from guitar_tap.models.measurement_type import MeasurementType
    saved = TDS.measurement_type()
    saved_ranges = [(t, TDS.min_frequency_for(t), TDS.max_frequency_for(t)) for t in MeasurementType]
    saved_db = (TDS.min_magnitude(), TDS.max_magnitude())
    yield
    TDS.set_measurement_type(saved)
    for t, min_hz, max_hz in saved_ranges:
        TDS.set_min_frequency_for(min_hz, t)
        TDS.set_max_frequency_for(max_hz, t)
    TDS.set_min_magnitude(saved_db[0])
    TDS.set_max_magnitude(saved_db[1])


def _measurement(name: str):
    return measurements_from_json(json.dumps(DATA["files"][name]))[0]


def _peak_name(pid) -> str:
    return _PEAK_NAMES.get(str(pid).upper(), str(pid))


def _check(fields: dict, sut, ranges: list) -> None:
    entries = sut._comparison_data
    for field, want in fields.items():
        if field == "entries":
            assert len(entries) == want, field
        elif field == "labels":
            assert [e["label"] for e in entries] == want, field
        elif field == "chartPeaks":
            assert (sut.chart_peaks is not None) is want, field
        elif field == "chartLabels":
            assert (sut.chart_annotation_peaks is not None) is want, field
        elif field == "modeLines":
            assert sut.shows_mode_boundaries is want, field
        elif field == "mode":
            assert (sut.display_mode == AnalysisDisplayMode.COMPARISON) is (want == "comparison"), field
        elif field == "loadedRange":
            assert ranges and ranges[-1] == pytest.approx(tuple(want)), f"{field}: {ranges[-1] if ranges else None}"
        elif field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "multiTap":
            assert sut.showing_multi_tap_comparison is want, field
        elif field == "tapEntries":
            assert len(sut.tap_entries) == want, field
        elif field == "savedComparison":
            assert sut.is_saved_measurement_comparison is want, field
        elif field == "modeIds":
            got = {mode: _peak_name(pid) for mode, pid in (entries[0]["mode_ids"] if entries else {}).items()}
            assert got == want, f"{field}: {got}"
        elif field == "entryGuitarType":
            assert (entries[0]["guitar_type"] if entries else None) == want, field
        elif field == "entryPeaks":
            got = sorted(_peak_name(p.id) for p in (entries[0]["peaks"] if entries else []))
            assert got == sorted(want), f"{field}: {got}"
        elif field == "savedRange":
            assert sut.saved_measurements[-1].comparison_range == pytest.approx(tuple(want)), field
        elif field == "savedRecord":
            if want is None:
                assert len(sut.saved_measurements) == 0, f"{field}: none added"
            else:
                assert len(sut.saved_measurements) == 1, f"{field}: a record added"
                last = sut.saved_measurements[-1]
                assert last.measurement_name == want["name"], f"{field} name"
                assert len(last.comparison_entries or []) == want["entries"], f"{field} entries"
        elif field == "phase":
            assert sut.material_tap_phase.value == want, field
        elif field == "complete":
            assert sut.is_measurement_complete is want, field
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_comparison(row, qapp):
    if os.path.exists(measurements_file()):
        os.remove(measurements_file())
    sut = make_steps_analyzer()
    sut.saved_measurements.clear()
    ranges: list = []
    sut.loadedAxisRangeChanged.connect(lambda *r: ranges.append(r))
    for step in row["steps"]:
        if "compare" in step:
            sut.load_comparison([_measurement(n) for n in step["compare"]])
        elif "load" in step:
            sut.load_measurement(_measurement(step["load"]))
        elif "multiTap" in step:
            sut.apply_multi_tap_comparison_overlays(enabled=step["multiTap"])  # the Taps toggle
        elif "saveComparison" in step:
            view = step.get("view") or [None] * 4
            sut.save_comparison(measurement_name=step["saveComparison"], min_freq=view[0],
                                max_freq=view[1], min_db=view[2], max_db=view[3])
        elif step.get("loadSaved"):
            sut.load_measurement(sut.saved_measurements[-1])
        elif "check" in step:
            _check(step["check"], sut, ranges)
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    _check(row["expect"], sut, ranges)


# ---------------------------------------------------------------------------
# Python's own: the comparisonChanged signal
# ---------------------------------------------------------------------------

_APP: "QtWidgets.QApplication | None" = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot


def _analyzer():
    """The real analyzer, on a test FFT engine; saves go to the per-process test sandbox."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(
    min_freq: float = 80.0, max_freq: float = 1200.0,
    min_db: float = -90.0, max_db: float = -10.0,
) -> SpectrumSnapshot:
    return SpectrumSnapshot(
        frequencies=[100.0, 200.0, 300.0, 400.0],
        magnitudes=[-40.0, -35.0, -45.0, -50.0],
        min_freq=min_freq, max_freq=max_freq,
        min_db=min_db, max_db=max_db,
    )


def _make_measurement(
    measurement_name: str | None = None,
    with_snapshot: bool = True,
) -> TapToneMeasurement:
    return TapToneMeasurement.create(
        peaks=[],
        measurement_name=measurement_name,
        spectrum_snapshot=_make_snapshot() if with_snapshot else None,
    )


# ---------------------------------------------------------------------------
# loadComparison tests  (CP-U1–CP-U5)
# ---------------------------------------------------------------------------

class TestComparisonChangedSignal:
    def test_comparison_changed_signal_emitted_on_load(self):
        sut = _analyzer()
        events: list[bool] = []
        sut.comparisonChanged.connect(lambda v: events.append(v))
        sut.load_comparison([_make_measurement(), _make_measurement()])
        assert events == [True], f"Should emit True on load; got {events}"

    def test_comparison_changed_signal_emitted_on_clear(self):
        sut = _analyzer()
        sut.load_comparison([_make_measurement(), _make_measurement()])
        events: list[bool] = []
        sut.comparisonChanged.connect(lambda v: events.append(v))
        sut.clear_comparison()
        assert events == [False], f"Should emit False on clear; got {events}"
