# @parity test/import-persistence
"""The saved-measurement library: importing through the app's import (``import_and_load_measurements``),
editing an entry, saving, and the message an import shows. The shared cases in import-persistence.json
(IP1-IP9, IM1-IM3), the same as Swift and the web; IP8 is the web's alone. Mirrors Swift
ImportPersistenceTests.

The library file is redirected to a temporary file under pytest (measurements_file()), so these never
touch the user's measurements.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402
from guitar_tap.views.tap_analysis_results_view import load_all_measurements, measurements_file  # noqa: E402

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "import-persistence.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

MEASUREMENTS = DATA["measurements"]
FILE_IDS = {name: m["id"] for name, m in MEASUREMENTS.items()}
# The cases for the natives: all but those marked for the web alone.
CASES = [c for c in DATA["cases"] if c.get("only") != "web"]


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["id"])
def test_library(row, qapp):
    if os.path.exists(measurements_file()):
        os.remove(measurements_file())
    sut = TapToneAnalyzer.for_testing()
    sut.saved_measurements.clear()
    message = None
    for step in row["steps"]:
        if "import" in step:
            data = json.dumps([MEASUREMENTS[n] for n in step["import"]]).encode("utf-8")
            message = sut.import_and_load_measurements(data)
        elif "edit" in step:
            edit = step["edit"]
            sut.update_measurement(at=edit["entry"], measurement_name=edit["name"], notes=edit["notes"])
        elif "save" in step:
            sut.save_measurement(measurement_name=step["save"])
        elif step.get("deleteAll"):
            sut.delete_all_measurements()
        elif "warning" in step:
            sut.microphone_warning = step["warning"]

    library = sut.saved_measurements
    for field, want in row["expect"].items():
        if field == "library":
            assert [m.measurement_name or "" for m in library] == want, field
        elif field == "notes":
            assert [m.notes for m in library] == want, field
        elif field == "persisted":
            assert [m.measurement_name or "" for m in load_all_measurements()] == want, field
        elif field == "ids":
            assert len(library) == len(want), f"{field}: count"
            for entry, name in zip(library, want):
                actual = str(entry.id).upper()
                if name == "new":
                    assert actual not in FILE_IDS.values(), f"{field}: a new id, not a file's"
                else:
                    assert actual == FILE_IDS[name], f"{field}: {name}'s own id"
        elif field == "message":
            assert message == want, f"{field}: {message!r}"
        elif field == "messageStartsWith":
            assert message is not None and message.startswith(want), f"{field}: {message!r}"
        elif field == "microphoneWarning":
            assert (sut.microphone_warning is not None) is want, field
        else:
            pytest.fail(f"unknown field {field}")
