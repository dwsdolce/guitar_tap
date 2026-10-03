# @parity test/pitch
"""Equal-temperament pitch against the shared case file, ``pitch.json`` — the same cases the Swift and web
suites run. Pitch is a general package: pitch_range, formatted_note and is_in_tune have no call site in the
app, and are tested because the package's API is the contract."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.pitch import Pitch

with open(os.path.join(os.path.dirname(__file__), "pitch.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

TOLERANCE = DATA["tolerance"]


def _number(value) -> float:
    """A number from the file: NaN and the infinities are written as strings."""
    return float(value)  # float() reads "NaN", "Infinity" and "-Infinity"


def _close(actual: float, expected) -> bool:
    return abs(actual - _number(expected)) <= TOLERANCE


@pytest.mark.parametrize("row", DATA["frequencies"], ids=lambda r: r["id"])
def test_frequency(row):
    e = row["expect"]
    p = Pitch(a4=_number(row["a4"]))
    f = _number(row["frequency"])
    upper, lower = p.pitch_range(f)
    assert p.has_pitch(f) == e["hasPitch"]
    assert p.pitch(f) == (e["pitch"]["note"], e["pitch"]["octave"])
    assert p.note(f) == e["note"]
    assert _close(p.cents(f), e["cents"]), f"cents {p.cents(f)}"
    assert _close(p.freq0(f), e["freq0"]), f"freq0 {p.freq0(f)}"
    assert _close(upper, e["pitchRange"]["upper"]), f"pitch_range upper {upper}"
    assert _close(lower, e["pitchRange"]["lower"]), f"pitch_range lower {lower}"
    assert p.formatted_note(f) == e["formattedNote"]
    assert p.is_in_tune(f) == e["isInTune"]


@pytest.mark.parametrize("row", DATA["isInTune"], ids=lambda r: r["id"])
def test_is_in_tune(row):
    p = Pitch(a4=_number(row["a4"]))
    assert p.is_in_tune(_number(row["frequency"]), threshold=_number(row["threshold"])) == row["expect"]


@pytest.mark.parametrize("row", DATA["isInTuneAtOwnCents"], ids=lambda r: r["id"])
def test_is_in_tune_at_own_cents(row):
    p = Pitch(a4=_number(row["a4"]))
    f = _number(row["frequency"])
    cents = p.cents(f)
    assert _close(cents, row["cents"]), f"cents {cents}"
    assert p.is_in_tune(f, threshold=cents) == row["expectAtCents"]
    assert p.is_in_tune(f, threshold=cents - 1e-9) == row["expectJustUnder"]


@pytest.mark.parametrize("row", DATA["freq"], ids=lambda r: r["id"])
def test_freq(row):
    p = Pitch(a4=_number(row["a4"]))
    assert _close(p.freq(row["note"], row["octave"]), row["expect"])


def test_format_cents():
    for row in DATA["formatCents"]:
        assert Pitch.format_cents(_number(row["cents"])) == row["expect"], row["cents"]
