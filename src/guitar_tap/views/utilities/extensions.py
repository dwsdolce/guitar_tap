"""
Reusable Qt widget helpers and free-function utilities.

Mirrors Swift's Extensions.swift — extension methods and small helper
functions that are used across multiple view files.

These helpers are extracted from guitar_tap.py so that the mixin files
can import them without importing the entire MainWindow module.
"""

# @parity dsp/analysis-quality tests=test/analysis-quality

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtWidgets

if TYPE_CHECKING:
    from models.guitar_type import GuitarType


# ── Analysis-quality helpers ─────────────────────────────────────────────────
# Single Python source for the guitar tap-tone quality labels + colors, mirroring
# Swift's Float.decayQuality(for:) / decayQualityColor(for:) / tapToneRatioQuality /
# tapToneRatioQualityColor (Extensions.swift). Python can't extend `float`, so these
# are module functions taking the value as the first arg (the same shape the web port
# uses). Decay thresholds come from GuitarType.decay_thresholds — the one place they
# are defined. Colors are the SwiftUI system-color hexes (what the semantic Swift
# colors resolve to); the on-screen panel and the PDF both consume these strings.

def decay_quality_label(decay_time: float, guitar_type: "GuitarType") -> str:
    """Ring-out label for a decay time (s). Mirrors Swift Float.decayQuality(for:)."""
    t = guitar_type.decay_thresholds
    if decay_time < t.very_short:
        return "Very Short"
    if decay_time < t.short:
        return "Short"
    if decay_time < t.moderate:
        return "Moderate"
    if decay_time < t.good:
        return "Good"
    return "Excellent"


def decay_quality_color(decay_time: float, guitar_type: "GuitarType") -> str:
    """Hex color for the ring-out quality. Mirrors Swift decayQualityColor(for:)
    (.gray/.orange/.yellow/.green/.blue → SwiftUI system hexes)."""
    t = guitar_type.decay_thresholds
    if decay_time < t.very_short:
        return "#8E8E93"   # .gray
    if decay_time < t.short:
        return "#FF9500"   # .orange
    if decay_time < t.moderate:
        return "#FFCC00"   # .yellow
    if decay_time < t.good:
        return "#34C759"   # .green
    return "#007AFF"       # .blue


def tap_tone_ratio_quality_label(ratio: float) -> str:
    """Tap-tone-ratio (f_Top / f_Air) label. Mirrors Swift Float.tapToneRatioQuality.
    Target range 1.9–2.1."""
    if ratio < 1.7:
        return "Low"
    if ratio < 1.9:
        return "Below Target"
    if ratio <= 2.1:
        return "Ideal"
    if ratio < 2.3:
        return "Above Target"
    return "High"


def tap_tone_ratio_quality_color(ratio: float) -> str:
    """Hex color for the tap-tone-ratio quality. Mirrors Swift tapToneRatioQualityColor
    (.red/.orange/.green → SwiftUI system hexes)."""
    if ratio < 1.7:
        return "#FF3B30"   # .red
    if ratio < 1.9:
        return "#FF9500"   # .orange
    if ratio <= 2.1:
        return "#34C759"   # .green
    if ratio < 2.3:
        return "#FF9500"   # .orange
    return "#FF3B30"       # .red


def vsep() -> QtWidgets.QFrame:
    """Thin vertical separator for use inside horizontal toolbars."""
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return sep


def hsep() -> QtWidgets.QFrame:
    """Thin horizontal separator for use between vertical sections."""
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return sep
