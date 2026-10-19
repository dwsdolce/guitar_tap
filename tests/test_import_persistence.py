# @parity test/import-persistence
"""The saved-measurement library: importing through the app's import (``import_and_load_measurements``),
editing an entry, saving, and the message an import shows. The shared cases in import-persistence.json
(IP1-IP9, IM1-IM3), the same as Swift and the web; IP8 is the web's alone. Mirrors Swift
ImportPersistenceTests.

The library file is redirected to a temporary file under pytest (measurements_file()), so these never
touch the user's measurements.
"""
from __future__ import annotations

import contextlib
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
FILE_IDS = {name: m.get("id") for name, m in MEASUREMENTS.items()}
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
        elif "importFails" in step:
            data = json.dumps([MEASUREMENTS[n] for n in step["importFails"]]).encode("utf-8")
            with pytest.raises(Exception) as failure:
                sut.import_and_load_measurements(data)
            if "message" in step:
                got = sut.import_error_message(failure.value, step["file"])
                assert got == step["message"], f"{row['id']}: message {got}"
        elif "edit" in step:
            edit = step["edit"]
            sut.update_measurement(at=edit["entry"], measurement_name=edit["name"], notes=edit["notes"])
        elif "save" in step:
            sut.save_measurement(measurement_name=step["save"])
        elif step.get("deleteAll"):
            sut.delete_all_measurements()
        elif "warning" in step:
            sut.microphone_warning = step["warning"]
        else:
            pytest.fail(f"{row['id']}: unknown step {step}")

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


# ── A library that cannot be read ───────────────────────────────────────────────────────────────


# The shared measurement a whole library holds that makes it unreadable.
_UNREADABLE_MEASUREMENT = {"bad id": "bad-id", "no spectrum": "no-spectrum", "empty spectrum": "empty-spectrum"}
_UNREADABLE_KINDS = ["cut short", *_UNREADABLE_MEASUREMENT]


def _unreadable_library(kind: str) -> bytes:
    """A library that cannot be read: one cut short mid-write, or whole but holding an id that is not a UUID
    or a measurement with no spectrum, or one whose spectrum has no points."""
    if kind in _UNREADABLE_MEASUREMENT:
        return json.dumps([MEASUREMENTS[_UNREADABLE_MEASUREMENT[kind]]]).encode("utf-8")
    whole = json.dumps([MEASUREMENTS["A"]]).encode("utf-8")
    return whole[: len(whole) // 2]


def _kept_files(folder: str) -> list[str]:
    return sorted(f for f in os.listdir(folder) if f.startswith("saved_measurements-unreadable-"))


@pytest.fixture
def _library_folder():
    """The test library's folder, with no library and no kept copies before or after."""
    folder = os.path.dirname(measurements_file())

    def clean():
        if os.path.exists(measurements_file()):
            os.remove(measurements_file())
        for f in _kept_files(folder):
            os.remove(os.path.join(folder, f))

    clean()
    yield folder
    os.chmod(folder, 0o755)
    clean()


@pytest.mark.parametrize("kind", _UNREADABLE_KINDS)
def test_an_unreadable_library_is_kept_aside_and_not_written_over(kind, _library_folder, qapp):
    """The library could not be read: it is kept beside itself, renamed, the library starts empty and the
    user is told; the next save writes a new library and leaves the kept one as it was."""
    damaged = _unreadable_library(kind)
    with open(measurements_file(), "wb") as f:
        f.write(damaged)

    sut = TapToneAnalyzer.for_testing()

    assert sut.saved_measurements == []
    assert "saved_measurements-unreadable-" in (sut.library_load_failure or "")
    kept = _kept_files(_library_folder)
    assert len(kept) == 1
    with open(os.path.join(_library_folder, kept[0]), "rb") as f:
        assert f.read() == damaged, "kept as it was"

    sut.import_and_load_measurements(json.dumps([MEASUREMENTS["A"]]).encode("utf-8"))
    assert len(load_all_measurements()) == 1, "a new library is written"
    with open(os.path.join(_library_folder, kept[0]), "rb") as f:
        assert f.read() == damaged, "and the kept one is not touched"


@contextlib.contextmanager
def _unmovable(folder: str):
    """The library cannot be renamed while inside: its folder read-only on macOS and Linux; on
    Windows, which ignores a folder's read-only flag, the file held open, which Windows will not
    rename."""
    if sys.platform == "win32":
        with open(measurements_file(), "rb"):
            yield
    else:
        os.chmod(folder, 0o555)
        try:
            yield
        finally:
            os.chmod(folder, 0o755)


@pytest.mark.parametrize("kind", _UNREADABLE_KINDS)
def test_an_unreadable_library_that_cannot_be_moved_is_not_written(kind, _library_folder, qapp):
    """The library could not be read and could not be renamed: it stays where it is, the user is told,
    and nothing is written over it this session."""
    damaged = _unreadable_library(kind)
    with open(measurements_file(), "wb") as f:
        f.write(damaged)

    with _unmovable(_library_folder):
        sut = TapToneAnalyzer.for_testing()
        assert sut.library_load_failure
        assert sut.is_library_write_blocked

    sut.import_and_load_measurements(json.dumps([MEASUREMENTS["A"]]).encode("utf-8"))
    with open(measurements_file(), "rb") as f:
        assert f.read() == damaged, "REGRESSION: a save wrote over the only copy"
