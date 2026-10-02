# @parity test/display-range
"""Each change to a material peak is announced.

The chart widens onto a newly identified plate / brace peak by observing the analyzer's three
material peaks. These pin that each write of a peak is announced to observers: a load announces the
measurement's peaks, and a redo announces the cleared one. The widening decision itself is in
test_display_range_expansion.py. Mirrors Swift MaterialPeakAnnouncementTests.
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


def _plate(l_peak, c_peak, flc_peak):
    from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    snap = SpectrumSnapshot(frequencies=[100.0, 200.0], magnitudes=[-10.0, -20.0],
                            measurement_type="Material (Plate)")
    return TapToneMeasurement.create(
        measurement_type="Material (Plate)", guitar_type=None, peaks=[l_peak, c_peak, flc_peak],
        selected_longitudinal_peak_id=l_peak.id, selected_cross_peak_id=c_peak.id,
        selected_flc_peak_id=flc_peak.id, longitudinal_snapshot=snap, number_of_taps=1)


def _listen(sut):
    heard = {"l": [], "c": [], "f": []}
    sut.selectedLongitudinalPeakChanged.connect(lambda p: heard["l"].append(p and p.frequency))
    sut.selectedCrossPeakChanged.connect(lambda p: heard["c"].append(p and p.frequency))
    sut.selectedFlcPeakChanged.connect(lambda p: heard["f"].append(p and p.frequency))
    return heard


def test_loading_a_plate_announces_each_of_its_peaks():
    from guitar_tap.models.resonant_peak import ResonantPeak
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer.for_testing()
    heard = _listen(sut)
    sut.load_measurement(_plate(ResonantPeak(frequency=1500.0, magnitude=-20.0),
                                ResonantPeak(frequency=180.0, magnitude=-25.0),
                                ResonantPeak(frequency=410.0, magnitude=-30.0)))
    assert heard["l"][-1] == 1500.0
    assert heard["c"][-1] == 180.0
    assert heard["f"][-1] == 410.0



def test_loaded_peaks_are_marked_as_from_a_load_until_a_new_sequence():
    from guitar_tap.models.resonant_peak import ResonantPeak
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer.for_testing()
    sut.load_measurement(_plate(ResonantPeak(frequency=1500.0, magnitude=-20.0),
                                ResonantPeak(frequency=180.0, magnitude=-25.0),
                                ResonantPeak(frequency=410.0, magnitude=-30.0)))
    assert sut.material_peaks_from_load is True
    sut.start_tap_sequence()
    assert sut.material_peaks_from_load is False

def test_redoing_a_phase_announces_its_peak_cleared():
    from guitar_tap.models.material_tap_phase import MaterialTapPhase
    from guitar_tap.models.resonant_peak import ResonantPeak
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer.for_testing()
    sut.selected_longitudinal_peak = ResonantPeak(frequency=1500.0, magnitude=-20.0)
    sut.material_tap_phase = MaterialTapPhase.REVIEWING_LONGITUDINAL
    heard = _listen(sut)
    sut.redo_current_phase()
    assert heard["l"] == [None]
