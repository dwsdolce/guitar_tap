# @parity test/display-range
"""The chart widens its frequency axis onto a newly identified material peak.

A plate or brace scans a wide band (brace: 100-1200 Hz) and the display range is
per-measurement-type and persisted, so the fL / fC / fFLC a measurement just produced can land off
the edge of the chart. Swift has widened the axis since the feature was written; Python and web did
neither, so the same measurement showed the peak on one edition and hid it on two. Ported
2026-09-20 (project issue #8) — user-visible behaviour, not an implementation difference.

Mirrors Swift DisplayRangeExpansionTests / web display-range.test.ts.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.display_range import FLOOR_HZ, expanded_to_include


def test_peak_above_the_range_widens_the_maximum_with_padding():
    lo, hi = expanded_to_include(1000.0, 100.0, 800.0)
    assert hi == 1100.0, "1000 Hz + 10% padding"
    assert lo == 100.0, "the minimum is untouched"


def test_peak_below_the_range_widens_the_minimum_with_padding():
    lo, hi = expanded_to_include(50.0, 100.0, 800.0)
    assert lo == 45.0, "50 Hz - 10% padding"
    assert hi == 800.0, "the maximum is untouched"


def test_peak_inside_the_range_leaves_it_alone():
    lo, hi = expanded_to_include(400.0, 100.0, 800.0)
    assert (lo, hi) == (100.0, 800.0), (
        "a range is never NARROWED to fit — that would hide other peaks"
    )


def test_a_very_low_peak_is_clamped_at_the_floor():
    lo, _ = expanded_to_include(0.5, 100.0, 800.0)
    assert lo == FLOOR_HZ, "never below 1 Hz — there is nothing to draw there"


def test_peak_exactly_at_the_boundary_changes_nothing():
    assert expanded_to_include(800.0, 100.0, 800.0)[1] == 800.0, "already visible"
    assert expanded_to_include(100.0, 100.0, 800.0)[0] == 100.0, "already visible"
