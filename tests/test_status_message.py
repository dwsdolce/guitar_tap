# @parity test/status-message
"""The status line's words, each reached through the app's own path. The shared cases in
status-message.json (SM1-SM24), the same as Swift and the web.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))


from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import measurements_from_json  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "status-message.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TDS.measurement_type(), TDS.measure_flc())
    yield
    TDS.set_measurement_type(saved[0])
    TDS.set_measure_flc(saved[1])


def _check(fields: dict, sut, before: str, writes: list) -> None:
    status = sut.status_message
    for field, want in fields.items():
        if field == "statusMessage":
            assert status == want, f"{field}: {status!r}"
        elif field == "statusPrefix":
            assert status.startswith(want), f"{field}: {status!r}"
        elif field == "statusSuffix":
            assert status.endswith(want), f"{field}: {status!r}"
        elif field == "statusContains":
            assert want in status, f"{field}: {status!r}"
        elif field == "statusUnchangedByLastStep":
            assert (status == before) is want, f"{field}: {before!r} -> {status!r}"
        elif field == "detecting":
            assert sut.is_detecting is want, field
        elif field == "tapCount":
            assert sut.current_tap_count == want, field
        elif field == "statusWrites":
            assert len(writes) == want, f"{field}: {writes}"
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_status(row, qapp):
    sut = make_steps_analyzer()
    before = sut.status_message
    writes: list[str] = []
    for step in row["steps"]:
        if "check" in step:
            _check(step["check"], sut, before, writes)
            continue
        before = sut.status_message
        if "clipping" in step:
            sut.mic.level.clippingChanged.emit(step["clipping"])  # as the input level reports it
        elif step.get("deviceChange"):
            sut.handle_route_change_restart()
        elif "load" in step:
            sut.load_measurement(measurements_from_json(json.dumps(DATA["files"][step["load"]]))[0])
        elif step.get("playingFile"):
            sut.mic.is_playing_file = True
        elif step.get("drainMainQueue"):
            for _ in range(10):  # each pass runs everything queued before it
                qapp.processEvents()
        elif step.get("countStatusWrites"):
            sut.statusMessageChanged.connect(writes.append)
        else:
            assert run_analyzer_step(step, sut), f"unknown step {step}"
    _check(row["expect"], sut, before, writes)
