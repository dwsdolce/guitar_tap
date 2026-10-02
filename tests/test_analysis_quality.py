# @parity test/analysis-quality
"""The guitar tap-tone quality helpers: the per-type ring-out (decay) thresholds and their labels and
colours, the tap-tone-ratio bands, values outside every band, and the pinned palette the colours come
from (views/utilities/extensions.py, GuitarType.decay_thresholds, views/utilities/palette.py). Mirrors
Swift AnalysisQualityTests; the web suite has the same cases.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_type import GuitarType
from guitar_tap.views.utilities import palette
from guitar_tap.views.utilities.extensions import (
    decay_quality_color,
    decay_quality_label,
    tap_tone_ratio_quality_color,
    tap_tone_ratio_quality_label,
)


# ── Thresholds ───────────────────────────────────────────────────────────────

def test_decay_thresholds_every_type():
    expected = {
        GuitarType.CLASSICAL: (0.15, 0.35, 0.60, 1.0),
        GuitarType.FLAMENCO: (0.08, 0.20, 0.35, 0.55),
        GuitarType.ACOUSTIC: (0.10, 0.25, 0.45, 0.75),
        GuitarType.GENERIC: (0.10, 0.25, 0.45, 0.75),
    }
    for gt, values in expected.items():
        t = gt.decay_thresholds
        assert (t.very_short, t.short, t.moderate, t.good) == values, gt


# ── Decay labels ─────────────────────────────────────────────────────────────

def test_decay_labels_classical_at_every_boundary():
    cases = [
        (0, "Very Short"), (0.14, "Very Short"), (0.15, "Short"), (0.34, "Short"), (0.35, "Moderate"),
        (0.59, "Moderate"), (0.6, "Good"), (0.99, "Good"), (1.0, "Excellent"), (2.0, "Excellent"),
    ]
    for value, label in cases:
        assert decay_quality_label(value, GuitarType.CLASSICAL) == label, value


def test_decay_labels_each_type_at_its_thresholds():
    labels = ["Short", "Moderate", "Good", "Excellent"]
    for gt in (GuitarType.FLAMENCO, GuitarType.ACOUSTIC, GuitarType.GENERIC):
        t = gt.decay_thresholds
        for threshold, label in zip((t.very_short, t.short, t.moderate, t.good), labels):
            assert decay_quality_label(threshold, gt) == label, (gt, threshold)
        assert decay_quality_label(0, gt) == "Very Short", gt


# ── Decay colours ────────────────────────────────────────────────────────────

def test_decay_colors_every_band():
    cases = [
        (0.10, palette.GRAY), (0.20, palette.ORANGE), (0.50, palette.YELLOW),
        (0.80, palette.GREEN), (1.20, palette.BLUE),
    ]
    for value, color in cases:
        assert decay_quality_color(value, GuitarType.CLASSICAL) == color, value


# ── Ratio ────────────────────────────────────────────────────────────────────

def test_ratio_labels_at_every_boundary():
    cases = [
        (0, "Low"), (1.69, "Low"), (1.7, "Below Target"), (1.89, "Below Target"), (1.9, "Ideal"),
        (2.0, "Ideal"), (2.1, "Ideal"), (2.2, "Above Target"), (2.29, "Above Target"), (2.3, "High"),
        (3.0, "High"),
    ]
    for value, label in cases:
        assert tap_tone_ratio_quality_label(value) == label, value


def test_ratio_colors_every_band():
    cases = [
        (1.6, palette.RED), (1.8, palette.ORANGE), (2.0, palette.GREEN), (2.2, palette.ORANGE), (2.4, palette.RED),
    ]
    for value, color in cases:
        assert tap_tone_ratio_quality_color(value) == color, value


# ── Outside every band ───────────────────────────────────────────────────────

def test_negative_or_nan_is_unknown_and_gray():
    for value in (-0.1, math.nan):
        assert decay_quality_label(value, GuitarType.CLASSICAL) == "Unknown", value
        assert decay_quality_color(value, GuitarType.CLASSICAL) == palette.GRAY, value
        assert tap_tone_ratio_quality_label(value) == "Unknown", value
        assert tap_tone_ratio_quality_color(value) == palette.GRAY, value


# ── Palette ──────────────────────────────────────────────────────────────────

def test_palette_light_and_dark_values():
    expected = [
        (palette.GRAY, "#8E8E93", "#8E8E93"),
        (palette.ORANGE, "#FF9500", "#FF9F0A"),
        (palette.YELLOW, "#FFCC00", "#FFD60A"),
        (palette.GREEN, "#34C759", "#30D158"),
        (palette.BLUE, "#007AFF", "#0A84FF"),
        (palette.RED, "#FF3B30", "#FF453A"),
    ]
    for pair, light, dark in expected:
        assert (pair.light, pair.dark) == (light, dark)
