# @parity test/measurement-name
"""The required-name rule — what enables Save (is_valid_name) and what is stored for the name and the notes
(normalized_name, normalized_notes) — against the shared case file ``measurement-name.json``, the same cases
the Swift and web suites run."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement as M

with open(os.path.join(os.path.dirname(__file__), "measurement-name.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("text,expected", DATA["isValidName"])
def test_is_valid_name(text, expected):
    assert M.is_valid_name(text) is expected


@pytest.mark.parametrize("text,expected", DATA["normalizedName"])
def test_normalized_name(text, expected):
    assert M.normalized_name(text) == expected


@pytest.mark.parametrize("text,expected", DATA["normalizedNotes"])
def test_normalized_notes(text, expected):
    assert M.normalized_notes(text) == expected
