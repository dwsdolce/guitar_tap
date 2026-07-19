# @parity test/quality-colors
"""Lock WoodQuality.color hex against silent drift (parity group model/quality-colors).

Single source of truth (material_properties.py); the live view and the PDF both delegate to it.
Swift uses semantic SwiftUI Colors, the web a per-scheme hex table; Python pins its hex map here.
This is the exact bug the group guards: a copy drifts to a wrong hue with nothing to catch it.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.material_properties import WoodQuality


def test_per_quality_hex():
    assert WoodQuality.EXCELLENT.color == "#34C759"   # SwiftUI .green
    assert WoodQuality.VERY_GOOD.color == "#00C7BE"   # SwiftUI .mint
    assert WoodQuality.GOOD.color      == "#007AFF"   # SwiftUI .blue
    assert WoodQuality.FAIR.color      == "#FF9500"   # SwiftUI .orange
    assert WoodQuality.POOR.color      == "#FF3B30"   # SwiftUI .red


def test_labels():
    assert WoodQuality.EXCELLENT.value == "Excellent"
    assert WoodQuality.VERY_GOOD.value == "Very Good"
    assert WoodQuality.GOOD.value      == "Good"
    assert WoodQuality.FAIR.value      == "Fair"
    assert WoodQuality.POOR.value      == "Poor"