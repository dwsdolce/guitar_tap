# @parity test/settings-store
"""The per-measurement-type display frequency range store.

Each type has its own default and its own stored minimum and maximum, a bound never stored reads
the default, a stored bound keeps its exact value at Swift's Float precision (Save Current View
comes back as saved; an untouched Settings field never rounds it), and an entered range is
validated before it is stored. Mirrors Swift SettingsStoreTests / web settings-store.test.ts.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from PySide6 import QtWidgets

from guitar_tap.models.measurement_type import MeasurementType as MT
from guitar_tap.models.tap_display_settings import TapDisplaySettings as tds


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


@pytest.fixture
def restore_plate_and_brace():
    saved = {(t, b): f(t) for t in (MT.PLATE, MT.BRACE)
             for b, f in (("min", tds.min_frequency_for), ("max", tds.max_frequency_for))}
    yield
    for (t, b), v in saved.items():
        (tds.set_min_frequency_for if b == "min" else tds.set_max_frequency_for)(v, t)


def test_per_type_defaults_match_canonical():
    for t in (MT.GENERIC, MT.ACOUSTIC, MT.CLASSICAL, MT.FLAMENCO):
        assert tds.default_min_frequency(t) == 75.0
        assert tds.default_max_frequency(t) == 350.0
    assert tds.default_min_frequency(MT.PLATE) == 20.0
    assert tds.default_max_frequency(MT.PLATE) == 200.0
    assert tds.default_min_frequency(MT.BRACE) == 30.0
    assert tds.default_max_frequency(MT.BRACE) == 1000.0


def test_a_type_with_nothing_stored_reads_its_default():
    assert tds.min_frequency_for(MT.FLAMENCO) == 75.0
    assert tds.max_frequency_for(MT.FLAMENCO) == 350.0


def test_a_stored_range_reads_back(restore_plate_and_brace):
    tds.set_min_frequency_for(15.0, MT.PLATE)
    tds.set_max_frequency_for(180.0, MT.PLATE)
    assert tds.min_frequency_for(MT.PLATE) == 15.0
    assert tds.max_frequency_for(MT.PLATE) == 180.0


def test_storing_one_type_does_not_change_another(restore_plate_and_brace):
    tds.set_min_frequency_for(18.0, MT.PLATE)
    tds.set_min_frequency_for(40.0, MT.BRACE)
    assert tds.min_frequency_for(MT.PLATE) == 18.0
    assert tds.min_frequency_for(MT.BRACE) == 40.0


def test_storing_one_bound_leaves_the_other(restore_plate_and_brace):
    tds.set_min_frequency_for(15.0, MT.PLATE)
    tds.set_max_frequency_for(250.0, MT.PLATE)
    assert tds.min_frequency_for(MT.PLATE) == 15.0
    assert tds.max_frequency_for(MT.PLATE) == 250.0


def test_a_stored_range_keeps_its_exact_value(restore_plate_and_brace):
    import numpy as np
    tds.set_min_frequency_for(15.37, MT.PLATE)
    tds.set_max_frequency_for(180.43, MT.PLATE)
    # Exactly, at Swift's Float precision.
    assert tds.min_frequency_for(MT.PLATE) == float(np.float32(15.37))
    assert tds.max_frequency_for(MT.PLATE) == float(np.float32(180.43))


# A Settings range field: untouched keeps the exact stored value.

def test_entered_value_untouched_field_keeps_the_exact_stored_value():
    from guitar_tap.models import field_precision as fp
    from guitar_tap.models.display_range import entered_value
    shown = fp.string(23.37, fp.FREQUENCY_HZ)   # "23"
    assert entered_value(shown, 23.37, fp.FREQUENCY_HZ) == 23.37


def test_entered_value_edited_field_is_the_number_typed():
    from guitar_tap.models import field_precision as fp
    from guitar_tap.models.display_range import entered_value
    assert entered_value("30", 23.37, fp.FREQUENCY_HZ) == 30.0


def test_entered_value_not_a_number_is_none():
    from guitar_tap.models import field_precision as fp
    from guitar_tap.models.display_range import entered_value
    assert entered_value("abc", 23.37, fp.FREQUENCY_HZ) is None


# Settings validates an entered range: each bound clamped, and the two at least 10 apart; otherwise
# the saved range.

@pytest.fixture
def restore_saved_range():
    saved = (tds.min_frequency(), tds.max_frequency(), tds.min_magnitude(), tds.max_magnitude())
    yield
    tds.set_min_frequency(saved[0])
    tds.set_max_frequency(saved[1])
    tds.set_min_magnitude(saved[2])
    tds.set_max_magnitude(saved[3])


def test_frequency_range_valid_is_unchanged():
    assert tds.validate_frequency_range(200.0, 3000.0) == pytest.approx((200.0, 3000.0))


def test_frequency_range_below_1_hz_is_clamped():
    assert tds.validate_frequency_range(0.0, 3000.0) == pytest.approx((1.0, 3000.0))


def test_frequency_range_above_5_khz_is_clamped():
    assert tds.validate_frequency_range(200.0, 6000.0) == pytest.approx((200.0, 5000.0))


def test_frequency_range_inverted_reads_the_saved_range(restore_saved_range):
    tds.set_min_frequency(100.0)
    tds.set_max_frequency(8000.0)
    assert tds.validate_frequency_range(5000.0, 200.0) == pytest.approx((100.0, 8000.0))


def test_frequency_range_too_narrow_reads_the_saved_range(restore_saved_range):
    tds.set_min_frequency(100.0)
    tds.set_max_frequency(8000.0)
    assert tds.validate_frequency_range(1000.0, 1005.0) == pytest.approx((100.0, 8000.0))


def test_frequency_range_exactly_10_hz_apart_is_accepted():
    assert tds.validate_frequency_range(100.0, 110.0) == pytest.approx((100.0, 110.0))


def test_magnitude_range_valid_is_unchanged():
    assert tds.validate_magnitude_range(-80.0, -20.0) == pytest.approx((-80.0, -20.0))


def test_magnitude_range_below_minus_120_db_is_clamped():
    assert tds.validate_magnitude_range(-150.0, -20.0) == pytest.approx((-120.0, -20.0))


def test_magnitude_range_above_20_db_is_clamped():
    assert tds.validate_magnitude_range(-80.0, 50.0) == pytest.approx((-80.0, 20.0))


def test_magnitude_range_inverted_reads_the_saved_range(restore_saved_range):
    tds.set_min_magnitude(-100.0)
    tds.set_max_magnitude(-10.0)
    assert tds.validate_magnitude_range(-20.0, -80.0) == pytest.approx((-100.0, -10.0))


def test_magnitude_range_too_narrow_reads_the_saved_range(restore_saved_range):
    tds.set_min_magnitude(-100.0)
    tds.set_max_magnitude(-10.0)
    assert tds.validate_magnitude_range(-50.0, -45.0) == pytest.approx((-100.0, -10.0))


def test_magnitude_range_exactly_10_db_apart_is_accepted():
    assert tds.validate_magnitude_range(-60.0, -50.0) == pytest.approx((-60.0, -50.0))

