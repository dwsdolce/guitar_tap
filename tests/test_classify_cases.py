# @parity test/classify
"""Guitar mode classification against the shared case file, ``classify.json`` — the same cases the Swift
and web suites run. The file's spellings are Swift's case names; ``_mode`` and ``_type`` map them."""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode
from guitar_tap.models.guitar_type import GuitarType
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin

with open(os.path.join(os.path.dirname(__file__), "classify.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def _mode(name: str) -> GuitarMode:
    return GuitarMode[_snake(name)]


def _type(name: str) -> GuitarType:
    return GuitarType[_snake(name)]


def _peaks(row: dict) -> list[ResonantPeak]:
    return [ResonantPeak(frequency=float(f), magnitude=float(m)) for f, m in row["peaks"]]


@pytest.mark.parametrize("row", DATA["classifyAll"], ids=lambda r: r["id"])
def test_classify_all(row):
    peaks = _peaks(row)
    result = GuitarMode.classify_all(peaks, _type(row["guitarType"]))
    assert len(result) == len(peaks)
    assert [result[p.id] for p in peaks] == [_mode(m) for m in row["expect"]]


@pytest.mark.parametrize("row", DATA["resolvedModePeaks"], ids=lambda r: r["id"])
def test_resolved_mode_peaks(row):
    peaks = _peaks(row)
    resolved = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(peaks, guitar_type=_type(row["guitarType"]).value)
    assert {mode: peak.id for mode, peak in resolved.items()} == {
        _mode(mode): peaks[index].id for mode, index in row["expect"].items()}


@pytest.mark.parametrize("guitar_type", sorted(DATA["bands"]))
def test_bands(guitar_type):
    gt = _type(guitar_type)
    for mode, lo, hi in DATA["bands"][guitar_type]:
        assert tuple(_mode(mode).mode_range(gt)) == (lo, hi), mode


@pytest.mark.parametrize("label,expected", DATA["fromDisplayName"], ids=lambda v: str(v))
def test_from_display_name(label, expected):
    assert GuitarMode.from_display_name(label) == (None if expected is None else _mode(expected))


def test_additional_mode_labels():
    assert list(GuitarMode.additional_mode_labels) == DATA["additionalModeLabels"]


@pytest.mark.parametrize("row", DATA["effectiveMode"], ids=lambda r: repr(r["override"]))
def test_effective_mode(row):
    assert GuitarMode.effective_mode(row["override"], _mode(row["auto"])) == _mode(row["expect"])


@pytest.mark.parametrize("mode,name", DATA["displayName"])
def test_display_name(mode, name):
    assert _mode(mode).display_name == name


@pytest.mark.parametrize("mode,abbreviation", DATA["abbreviation"])
def test_abbreviation(mode, abbreviation):
    assert _mode(mode).abbreviation == abbreviation

