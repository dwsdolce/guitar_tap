# @parity test/peak-heal
"""Healing files saved with a duplicate peak, against the shared case file ``peak-heal.json`` — the same cases
the Swift and web suites run.

Loaded peaks are authoritative — never re-derived — so a file saved with a duplicate peak would keep it forever.
The repair happens at decode (``TapToneMeasurement.from_dict``), so it covers both a .guitartap file and the
saved-measurements store. Rule: collapse peaks closer than the proximity window, keeping (1) the peak whose id is
selected, else (2) the higher magnitude, else (3) the first. find_peaks' own spacing keeps saved peaks at least
that far apart, so any closer pair is corruption.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement  # noqa: E402

TESTS_DIR = os.path.dirname(__file__)
with open(os.path.join(TESTS_DIR, "peak-heal.json"), encoding="utf-8") as _f:
    CASES = json.load(_f)["cases"]


def _decode(row) -> TapToneMeasurement:
    with open(os.path.join(TESTS_DIR, row["fixture"] + ".guitartap"), encoding="utf-8") as fh:
        return TapToneMeasurement.from_dict(json.load(fh)[0])


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["fixture"])
def test_decoded_measurement_has_no_duplicate_peaks(row):
    m = _decode(row)
    offenders = [
        f"{a.frequency:.5f} Hz / {b.frequency:.5f} Hz ({abs(a.frequency - b.frequency):.5f} apart)"
        for i, a in enumerate(m.peaks) for b in m.peaks[i + 1:]
        if abs(a.frequency - b.frequency) < row["proximityHz"]
    ]
    assert not offenders, f"decode must collapse duplicate peaks — found {'; '.join(offenders)}"
    assert len(m.peaks) == row["peakCount"]


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["fixture"])
def test_heal_keeps_the_selected_twin(row):
    """The surviving twin is the selected one; otherwise the selection points at a peak that no longer exists."""
    m = _decode(row)
    survivors = [p for p in m.peaks if abs(p.frequency - row["twinHz"]) < row["twinTolerance"]]
    assert len(survivors) == 1, f"expected exactly one peak at {row['twinHz']} Hz, got {len(survivors)}"
    assert survivors[0].id in set(m.selected_peak_ids or []), "the heal kept the unselected twin — selection now dangles"


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["fixture"])
def test_heal_leaves_no_dangling_ids(row):
    m = _decode(row)
    ids = {p.id for p in m.peaks}
    for pid in (m.selected_peak_ids or []):
        assert pid in ids, f"selected_peak_ids references a removed peak: {pid}"
    for pid in (m.annotation_offsets or {}):
        assert pid in ids, f"annotation_offsets references a removed peak: {pid}"
    for pid in (m.peak_mode_overrides or {}):
        assert pid in ids, f"peak_mode_overrides references a removed peak: {pid}"


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["fixture"])
def test_heal_is_reported_so_the_store_can_force_a_save(row):
    """The saved-measurements store repairs itself on load, so decode reports that it healed something."""
    assert _decode(row).was_healed is True


@pytest.mark.parametrize("row", CASES, ids=lambda r: r["fixture"])
def test_heal_flag_is_not_serialised(row):
    """The heal marker is transient state, not part of the file format; the corrected peaks are what is written."""
    m = _decode(row)
    encoded = json.dumps([m.to_dict()])
    assert "wasHealed" not in encoded and "was_healed" not in encoded
    round_tripped = TapToneMeasurement.from_dict(json.loads(encoded)[0])
    assert len(round_tripped.peaks) == len(m.peaks), "re-encoding a healed measurement must persist the corrected peak list"
