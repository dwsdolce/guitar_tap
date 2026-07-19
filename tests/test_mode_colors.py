# @parity test/mode-colors
"""Lock GuitarMode.color RGB against silent drift (parity group model/mode-colors).

Swift uses semantic SwiftUI Colors and the web brightened hexes; Python pins its own RGB map here.
This is the class of bug that hit the material quality colors — a copy drifts and nothing catches it.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode


def test_per_mode_rgb():
    assert GuitarMode.AIR.color == (0, 183, 235)
    assert GuitarMode.TOP.color == (40, 160, 40)
    assert GuitarMode.BACK.color == (220, 120, 40)
    assert GuitarMode.DIPOLE.color == (210, 50, 50)
    assert GuitarMode.RING_MODE.color == (130, 60, 200)
    assert GuitarMode.UPPER_MODES.color == (130, 130, 130)
    assert GuitarMode.UNKNOWN.color == (130, 130, 130)