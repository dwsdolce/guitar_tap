# @parity test/frequency-format
"""A frequency for display (one decimal, kHz from 1000 Hz) and the range line above the guitar peak
list built from it, and a sample rate or bandwidth in whole hertz grouped by the locale. Mirrors Swift
FrequencyFormatTests.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtCore

from guitar_tap.views.utilities.extensions import (
    display_range_label,
    formatted_as_frequency,
    formatted_as_whole_hertz,
)


def test_below_one_kilohertz_is_hertz_with_one_decimal():
    assert formatted_as_frequency(440) == "440.0 Hz"
    assert formatted_as_frequency(25.37) == "25.4 Hz"
    assert formatted_as_frequency(999.9) == "999.9 Hz"


def test_from_one_kilohertz_is_kilohertz_with_one_decimal():
    assert formatted_as_frequency(1000) == "1.0 kHz"
    assert formatted_as_frequency(2500) == "2.5 kHz"


def test_range_label_shows_both_bounds():
    assert display_range_label(25, 45) == "Showing 25.0 Hz - 45.0 Hz"


def test_range_label_keeps_a_zoomed_ranges_fraction():
    assert display_range_label(25.37, 44.81) == "Showing 25.4 Hz - 44.8 Hz"


def test_range_label_crossing_one_kilohertz_mixes_units():
    assert display_range_label(800, 1200) == "Showing 800.0 Hz - 1.2 kHz"


def test_whole_hertz_groups_by_the_locale():
    us = QtCore.QLocale("en_US")
    assert formatted_as_whole_hertz(48000, us) == "48,000 Hz"
    assert formatted_as_whole_hertz(22050, us) == "22,050 Hz"
    assert formatted_as_whole_hertz(48000, QtCore.QLocale("de_DE")) == "48.000 Hz"


def test_whole_hertz_rounds_to_the_nearest_hertz():
    assert formatted_as_whole_hertz(44100.4, QtCore.QLocale("en_US")) == "44,100 Hz"
