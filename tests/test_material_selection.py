# @parity test/material-selection
"""Lock the material (plate/brace) selection HEAL against the real iPad save-corruption bug.

Fixture `plate-umik-1-3-tap-swift-ipad-1784314709.guitartap` is a genuine iPad-saved plate whose
`selectedPeakIDs` aggregate was clobbered to just the cross peak (the intermittent iPad Release
glitch), while `peaks[]` correctly holds all three (L ~67, C ~117, FLC ~36 Hz). Material has no
per-peak selection, so `effective_selected_peak_ids` must ignore the corrupt aggregate and resolve
to all three — healing the file on read. Swift + web pin the same fixture in this parity group.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

_FIXTURE = "plate-umik-1-3-tap-swift-ipad-1784314709.guitartap"


def _load() -> TapToneMeasurement:
    # Look next to this test file, mirroring Swift URL(fileURLWithPath: #filePath).
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, _FIXTURE), encoding="utf-8") as f:
        raw = json.load(f)  # a .guitartap is a JSON array of measurements
    return TapToneMeasurement.from_dict(raw[0])


def test_corrupt_ipad_plate_effective_selection_heals_to_all_three():
    m = _load()

    # Preconditions: a material measurement, all three peaks present, corrupt aggregate = cross only.
    assert m.is_material
    assert len(m.peaks) == 3
    assert len(m.selected_peak_ids or []) == 1

    # The heal: the corrupt aggregate is ignored for material → all three peaks resolve.
    assert m.effective_selected_peak_ids == {p.id for p in m.peaks}
    assert len(m.effective_selected_peak_ids) == 3