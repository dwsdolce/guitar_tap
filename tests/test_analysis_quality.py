# @parity test/analysis-quality
"""Lock the guitar tap-tone quality labels + colors (parity group dsp/analysis-quality).

Port of Swift's Float.decayQuality(for:) / decayQualityColor(for:) and
Float.tapToneRatioQuality / tapToneRatioQualityColor (Extensions.swift), plus
GuitarType.decayThresholds. The Python single source lives in
views/utilities/extensions.py (Python can't extend `float`, so these are module
functions), mirroring Swift's Float extensions. Colors are the SwiftUI system-color
hexes the semantic Swift colors resolve to; the live Qt panel and the PDF both
consume these strings.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_type import GuitarType
from guitar_tap.views.utilities.extensions import (
    decay_quality_color,
    decay_quality_label,
    tap_tone_ratio_quality_color,
    tap_tone_ratio_quality_label,
)


# ── Decay thresholds (data on GuitarType) ────────────────────────────────────

def test_classical_decay_thresholds():
    t = GuitarType.CLASSICAL.decay_thresholds
    assert (t.very_short, t.short, t.moderate, t.good) == (0.15, 0.35, 0.6, 1.0)


# ── Decay quality label ──────────────────────────────────────────────────────

def test_decay_labels_at_boundaries():
    g = GuitarType.CLASSICAL
    assert decay_quality_label(0.14, g) == "Very Short"
    assert decay_quality_label(0.15, g) == "Short"      # >= very_short
    assert decay_quality_label(0.35, g) == "Moderate"   # >= short
    assert decay_quality_label(0.6, g) == "Good"        # >= moderate
    assert decay_quality_label(1.0, g) == "Excellent"   # >= good


def test_decay_labels_are_type_specific():
    # 0.5 s: Good for flamenco (good=0.55) but Moderate for classical (moderate=0.6).
    assert decay_quality_label(0.5, GuitarType.FLAMENCO) == "Good"
    assert decay_quality_label(0.5, GuitarType.CLASSICAL) == "Moderate"


# ── Decay quality color ──────────────────────────────────────────────────────

def test_decay_colors():
    g = GuitarType.CLASSICAL
    assert decay_quality_color(0.10, g) == "#8E8E93"   # gray   — Very Short
    assert decay_quality_color(0.20, g) == "#FF9500"   # orange — Short
    assert decay_quality_color(0.50, g) == "#FFCC00"   # yellow — Moderate
    assert decay_quality_color(0.80, g) == "#34C759"   # green  — Good
    assert decay_quality_color(1.20, g) == "#007AFF"   # blue   — Excellent


# ── Tap-tone-ratio quality label (f_Top / f_Air; target 1.9–2.1) ─────────────

def test_ratio_labels_at_boundaries():
    assert tap_tone_ratio_quality_label(1.69) == "Low"
    assert tap_tone_ratio_quality_label(1.7) == "Below Target"   # >= 1.7
    assert tap_tone_ratio_quality_label(1.9) == "Ideal"          # >= 1.9 (inclusive)
    assert tap_tone_ratio_quality_label(2.0) == "Ideal"
    assert tap_tone_ratio_quality_label(2.1) == "Ideal"          # <= 2.1 (inclusive)
    assert tap_tone_ratio_quality_label(2.2) == "Above Target"   # > 2.1
    assert tap_tone_ratio_quality_label(2.3) == "High"           # >= 2.3


# ── Tap-tone-ratio quality color ─────────────────────────────────────────────

def test_ratio_colors():
    assert tap_tone_ratio_quality_color(1.5) == "#FF3B30"   # red    — Low
    assert tap_tone_ratio_quality_color(1.8) == "#FF9500"   # orange — Below Target
    assert tap_tone_ratio_quality_color(2.0) == "#34C759"   # green  — Ideal
    assert tap_tone_ratio_quality_color(2.2) == "#FF9500"   # orange — Above Target
    assert tap_tone_ratio_quality_color(2.5) == "#FF3B30"   # red    — High