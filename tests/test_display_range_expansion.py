# @parity test/display-range
"""The chart widens its frequency axis onto a newly identified material peak.

A plate or brace scans a wide band (brace: 100-1200 Hz) and the display range is
per-measurement-type and persisted, so the fL / fC / fFLC a measurement just produced can land off
the edge of the chart. The chart's range widens to show it; a guitar's does not. The view only
applies widened_onto to its range, so the whole decision is tested here; the analyzer's announcing
each peak is tested in test_material_peak_announcement.py.

Mirrors Swift DisplayRangeExpansionTests / web display-range.test.ts.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.display_range import (
    FLOOR_HZ,
    ChartRange,
    expanded_to_include,
    loaded_after_widening,
    on_new_measurement,
    on_settings_done,
    widened_onto,
)
from guitar_tap.models.measurement_type import MeasurementType


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


def test_a_peak_above_the_charts_limit_widens_only_to_the_limit():
    from guitar_tap.models.display_range import MAX_FREQUENCY_HZ
    assert expanded_to_include(4900.0, 100.0, 800.0)[1] == MAX_FREQUENCY_HZ, "never beyond 5 kHz"


# The decision: plate and brace widen, guitar does not.

def test_material_peak_outside_the_range_widens_it():
    for t in (MeasurementType.PLATE, MeasurementType.BRACE):
        assert widened_onto(1000.0, t, False, 100.0, 800.0) == (100.0, 1100.0), t


def test_material_peak_inside_the_range_leaves_it_alone():
    assert widened_onto(400.0, MeasurementType.PLATE, False, 100.0, 800.0) == (100.0, 800.0)


def test_guitar_peak_outside_the_range_leaves_it_alone():
    for t in (MeasurementType.GENERIC, MeasurementType.ACOUSTIC, MeasurementType.CLASSICAL,
              MeasurementType.FLAMENCO):
        assert widened_onto(1000.0, t, False, 100.0, 800.0) == (100.0, 800.0), (
            f"{t}: a guitar's range is the user's analysis window"
        )



def test_material_peak_restored_by_a_load_leaves_the_range():
    assert widened_onto(1000.0, MeasurementType.PLATE, True, 100.0, 800.0) == (100.0, 800.0), (
        "a load shows the range it was saved with"
    )

# When the chart's range moves.

SAVED = ChartRange(20.0, 200.0, -100.0, 0.0)
LOADED = ChartRange(50.0, 300.0, -90.0, -10.0)
ZOOMED = ChartRange(60.0, 120.0, -90.0, -10.0)


def test_settings_done_with_nothing_changed_leaves_the_chart():
    assert on_settings_done(SAVED, SAVED, False) is None


def test_settings_done_with_a_changed_frequency_range_moves_to_it():
    assert on_settings_done(SAVED, SAVED._replace(max_freq=250.0), False) == SAVED


def test_settings_done_with_a_changed_magnitude_range_moves_to_it():
    assert on_settings_done(SAVED, SAVED._replace(min_db=-80.0), False) == SAVED


def test_settings_done_with_a_changed_type_moves_to_its_saved_view():
    assert on_settings_done(SAVED, SAVED, True) == SAVED


def test_new_measurement_with_no_load_leaves_the_chart():
    assert on_new_measurement(ZOOMED, None, SAVED) is None


def test_new_measurement_while_showing_the_load_returns_to_the_saved_view():
    assert on_new_measurement(LOADED, LOADED, SAVED) == SAVED


def test_new_measurement_after_the_user_moved_the_chart_leaves_it():
    assert on_new_measurement(ZOOMED, LOADED, SAVED) is None


def test_widening_while_showing_the_load_remembers_the_widened_range():
    widened = LOADED._replace(max_freq=1100.0)
    assert loaded_after_widening(LOADED, LOADED, widened) == widened


def test_widening_after_the_user_moved_the_chart_keeps_the_loaded_range():
    widened = ZOOMED._replace(max_freq=1100.0)
    assert loaded_after_widening(LOADED, ZOOMED, widened) == LOADED
