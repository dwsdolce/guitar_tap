"""
Reusable Qt widget helpers and free-function utilities. Mirrors Swift's Extensions.swift — extension
methods and small helper functions used across several view files.
"""

# @parity dsp/analysis-quality tests=test/analysis-quality
# @parity view/frequency-format tests=test/frequency-format
# @parity view/dimming tests=test/dimming

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from guitar_tap.models import field_precision as fp
from guitar_tap.views.utilities import palette

if TYPE_CHECKING:
    from guitar_tap.models.guitar_type import GuitarType


# ── Analysis-quality helpers ─────────────────────────────────────────────────
# The guitar tap-tone quality labels and colours. Mirrors Swift's Float.decayQuality(for:) /
# decayQualityColor(for:) / tapToneRatioQuality / tapToneRatioQualityColor (Extensions.swift); Python
# cannot extend ``float``, so these are functions taking the value first. The thresholds are
# GuitarType.decay_thresholds. A colour is a ``palette.ColorPair``; the caller takes the value for its
# background (``on(widget)`` on screen, ``light`` in a PDF). A negative or NaN value is in no band:
# "Unknown", grey.

def disabled_dimmed(widget: QtWidgets.QWidget, disabled: bool) -> None:
    """Disable a control AND show that it is disabled — the whole group (label, control and value) at the
    shared ``control.dimmed`` opacity. Qt's own disabled look does not reach a sibling label, and a label's
    colour comes from its role, so disabling alone leaves the group looking available. Mirrors Swift
    ``View.disabledDimmed(_:)``."""
    _dim(widget, disabled, palette.Opacity.CONTROL_DIMMED)


def not_applicable_dimmed(widget: QtWidgets.QWidget, not_applicable: bool) -> None:
    """Disable a control that has no meaning here (Peak Min for a plate or brace, or in a comparison) AND
    show it, more faintly than one that cannot act now — the whole group at ``control.notApplicable``.
    Mirrors Swift ``View.notApplicableDimmed(_:)``."""
    _dim(widget, not_applicable, palette.Opacity.CONTROL_NOT_APPLICABLE)


def _dim(widget: QtWidgets.QWidget, on: bool, which: "palette.Opacity") -> None:
    widget.setEnabled(not on)
    effect = widget.graphicsEffect()
    if not isinstance(effect, QtWidgets.QGraphicsOpacityEffect):
        effect = QtWidgets.QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(palette.opacity(which))
    effect.setEnabled(on)


def decay_quality_label(decay_time: float, guitar_type: "GuitarType") -> str:
    """Ring-out label for a decay time (s). Mirrors Swift Float.decayQuality(for:)."""
    t = guitar_type.decay_thresholds
    if not decay_time >= 0:
        return "Unknown"
    if decay_time < t.very_short:
        return "Very Short"
    if decay_time < t.short:
        return "Short"
    if decay_time < t.moderate:
        return "Moderate"
    if decay_time < t.good:
        return "Good"
    return "Excellent"


def decay_quality_color(decay_time: float, guitar_type: "GuitarType") -> palette.ColorPair:
    """Colour for the ring-out quality, grey → orange → yellow → green → blue. Mirrors Swift
    decayQualityColor(for:)."""
    t = guitar_type.decay_thresholds
    if not decay_time >= 0:
        return palette.GRAY
    if decay_time < t.very_short:
        return palette.GRAY
    if decay_time < t.short:
        return palette.ORANGE
    if decay_time < t.moderate:
        return palette.YELLOW
    if decay_time < t.good:
        return palette.GREEN
    return palette.BLUE


def tap_tone_ratio_quality_label(ratio: float) -> str:
    """Tap-tone-ratio (f_Top / f_Air) label, target 1.9–2.1. Mirrors Swift Float.tapToneRatioQuality."""
    if not ratio >= 0:
        return "Unknown"
    if ratio < 1.7:
        return "Low"
    if ratio < 1.9:
        return "Below Target"
    if ratio <= 2.1:
        return "Ideal"
    if ratio < 2.3:
        return "Above Target"
    return "High"


def tap_tone_ratio_quality_color(ratio: float) -> palette.ColorPair:
    """Colour for the tap-tone-ratio quality: green ideal, orange near, red out of range. Mirrors Swift
    tapToneRatioQualityColor."""
    if not ratio >= 0:
        return palette.GRAY
    if ratio < 1.7:
        return palette.RED
    if ratio < 1.9:
        return palette.ORANGE
    if ratio <= 2.1:
        return palette.GREEN
    if ratio < 2.3:
        return palette.ORANGE
    return palette.RED


def formatted_as_frequency(hz: float) -> str:
    """A frequency for display: in kHz from 1000 Hz, with ``PEAK_FREQUENCY_HZ``'s decimals ("440.0 Hz",
    "2.5 kHz"). Mirrors Swift Float.formattedAsFrequency()."""
    if hz >= 1000:
        return f"{fp.string(hz / 1000, fp.PEAK_FREQUENCY_HZ)} kHz"
    return f"{fp.string(hz, fp.PEAK_FREQUENCY_HZ)} Hz"


def display_range_label(min_freq: float, max_freq: float) -> str:
    """The line above the guitar peak list: the chart's frequency range, each bound as
    ``formatted_as_frequency`` (e.g. ``"Showing 25.0 Hz - 45.0 Hz"``). Mirrors Swift
    displayRangeLabel(minFreq:maxFreq:)."""
    return f"Showing {formatted_as_frequency(min_freq)} - {formatted_as_frequency(max_freq)}"


def formatted_as_whole_hertz(hz: float, locale: "QtCore.QLocale | None" = None) -> str:
    """A sample rate or bandwidth for display: whole hertz, grouped by the locale's separator
    ("48,000 Hz"; "48.000 Hz" in German). Mirrors Swift formattedAsWholeHertz(_:locale:)."""
    return f"{(locale or QtCore.QLocale()).toString(int(fp.rounded(hz, 0)))} Hz"


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
