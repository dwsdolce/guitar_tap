# @parity test/quality-colors
"""Lock WoodQuality.color hex against silent drift (parity group model/quality-colors).

Single source of truth (material_properties.py); the live view and the PDF both delegate to it.
This is the exact bug the group guards: a copy drifts to a wrong hue with nothing to catch it.

The values are ABSOLUTE hex, in all three editions, not OS-supplied semantic colours
(SwiftUI's .green, .blue, ...), whose hue changes when the OS revises its palette. A test of a
semantic identity (`color == .green`) stays true whatever hue the OS hands back, so Swift pins
`WoodQuality.hex` and these values are what all three editions compare. Mirrors Swift
QualityColorsTests and web quality-colors.test.ts.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.material_properties import WoodQuality


def test_per_quality_hex():
    """The canonical table. Swift's WoodQuality.hex and web's WOOD_QUALITY_COLOR.light match."""
    assert WoodQuality.EXCELLENT.color == "#34C759"
    assert WoodQuality.VERY_GOOD.color == "#00C7BE"
    assert WoodQuality.GOOD.color      == "#007AFF"
    assert WoodQuality.FAIR.color      == "#FF9500"
    assert WoodQuality.POOR.color      == "#FF3B30"


def test_every_grade_has_its_own_colour():
    """Five grades must be five distinguishable colours — the only thing the hue has to do."""
    hexes = [q.color for q in WoodQuality]
    assert len(set(hexes)) == len(hexes), f"each grade needs its own colour, got {hexes}"


def test_labels():
    assert WoodQuality.EXCELLENT.value == "Excellent"
    assert WoodQuality.VERY_GOOD.value == "Very Good"
    assert WoodQuality.GOOD.value      == "Good"
    assert WoodQuality.FAIR.value      == "Fair"
    assert WoodQuality.POOR.value      == "Poor"
