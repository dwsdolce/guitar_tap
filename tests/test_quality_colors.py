# @parity test/quality-colors
"""Lock WoodQuality.color hex against silent drift (parity group model/quality-colors).

Single source of truth (material_properties.py); the live view and the PDF both delegate to it.
This is the exact bug the group guards: a copy drifts to a wrong hue with nothing to catch it.

The values are ABSOLUTE, in all three editions, as of the #17 sweep. Swift used to resolve these
from SwiftUI's semantic colours (.green, .mint, .blue, .orange, .red), which the OS supplies — so
what Swift drew changed when Apple revised the palette, and macOS 26 did revise it: Swift moved to
.blue = #0088FF and .orange = #FF8D28 while Python and the web went on pinning #007AFF and #FF9500.
Three editions that all claimed to agree rendered two visibly different blues and oranges on the
same white surface (the macOS app, this app, and the PDF report the web generates).

Nothing caught it, because Swift's test asserted `color == .green` — a semantic identity that stays
true whatever hue the OS hands back. Swift now pins `WoodQuality.hex` and these values are what all
three editions compare. Mirrors Swift QualityColorsTests and web quality-colors.test.ts.
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
