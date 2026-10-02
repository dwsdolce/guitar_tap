# @parity test/display-range
"""Every load publishes the range the chart shows.

The view remembers it as the loaded range, so a new measurement can return to the saved view: a
measurement's snapshot range, exactly, or the saved range when it has none. A load never moves the
analysis range — the fixed 30–2000 Hz peak detection searches. Mirrors Swift LoadedRangeTests.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from PySide6 import QtWidgets


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _plate(min_freq, max_freq, min_db, max_db):
    from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    snap = SpectrumSnapshot(frequencies=[100.0, 200.0], magnitudes=[-10.0, -20.0],
                            min_freq=min_freq, max_freq=max_freq, min_db=min_db, max_db=max_db,
                            measurement_type="Material (Plate)")
    return TapToneMeasurement.create(measurement_type="Material (Plate)", guitar_type=None,
                                     peaks=[], longitudinal_snapshot=snap, number_of_taps=1)


def _published(sut):
    seen: list = []
    sut.loadedAxisRangeChanged.connect(lambda *r: seen.append(r))
    return seen


def test_loading_a_plate_publishes_its_snapshot_range_exactly():
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer.for_testing()
    seen = _published(sut)
    sut.load_measurement(_plate(24.37, 46.81, -75.5, -61.25))
    assert seen[-1] == pytest.approx((24.37, 46.81, -75.5, -61.25))


def test_loading_without_a_snapshot_publishes_the_saved_range():
    from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    sut = TapToneAnalyzer.for_testing()
    seen = _published(sut)
    sut.load_measurement(TapToneMeasurement.create(measurement_type="Classical Guitar",
                                                   guitar_type=None, peaks=[], number_of_taps=1))
    assert seen[-1] == pytest.approx((TDS.min_frequency(), TDS.max_frequency(),
                                      TDS.min_magnitude(), TDS.max_magnitude()))


def test_a_load_leaves_the_analysis_range():
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer.for_testing()
    sut.load_measurement(_plate(24.0, 46.0, -75.0, -61.0))
    assert (sut.min_frequency, sut.max_frequency) == (30.0, 2000.0)
