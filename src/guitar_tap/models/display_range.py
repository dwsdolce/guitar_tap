"""The rule for widening the chart's frequency axis so a newly identified peak is visible.

Mirrors Swift ``DisplayRange`` (Models/DisplayRange.swift).

# @parity presentation/display-range
"""

from __future__ import annotations

from typing import NamedTuple

# Ten percent of the peak's frequency, so the peak is not flush against the axis edge.
PADDING_FRACTION: float = 0.10

# The chart's limits — one set for Settings, zoom, pan and widening. Mirrors Swift DisplayRange.
# The frequencies the chart may show; above 5 kHz there is no useful tap-tone data.
MIN_FREQUENCY_HZ: float = 1.0
MAX_FREQUENCY_HZ: float = 5000.0
# The magnitudes the chart may show (dB).
MIN_MAGNITUDE_DB: float = -120.0
MAX_MAGNITUDE_DB: float = 20.0
# The narrowest range the chart may show; a range exactly this wide is allowed.
MIN_FREQUENCY_SPAN_HZ: float = 10.0
MIN_MAGNITUDE_SPAN_DB: float = 10.0

# The lowest frequency the axis may show.
FLOOR_HZ: float = MIN_FREQUENCY_HZ


def expanded_to_include(
    frequency: float, min_freq: float, max_freq: float
) -> "tuple[float, float]":
    """``(min_freq, max_freq)`` widened so *frequency* is inside it, or unchanged if it already was.

    Only ever widens. A peak near the middle of the range leaves it alone, and a range is never
    narrowed to fit, because that would hide peaks the user is already looking at.

    Mirrors Swift ``DisplayRange.expanded(toInclude:min:max:)``.
    """
    padding = frequency * PADDING_FRACTION
    lo, hi = min_freq, max_freq
    if frequency > hi:
        hi = min(MAX_FREQUENCY_HZ, frequency + padding)
    if frequency < lo:
        lo = max(FLOOR_HZ, frequency - padding)
    return lo, hi


def widened_onto(
    frequency: float, meas_type, from_load: bool, min_freq: float, max_freq: float
) -> "tuple[float, float]":
    """The chart range to show once a peak at *frequency* is identified: for a plate or brace,
    widened onto it (``expanded_to_include``); unchanged for a guitar — a guitar's range is the
    user's analysis window and is not widened for them — and for a peak restored by a load, which
    shows the range it was saved with.

    Mirrors Swift ``DisplayRange.widened(onto:for:fromLoad:min:max:)``.
    """
    if meas_type.is_guitar or from_load:
        return min_freq, max_freq
    return expanded_to_include(frequency, min_freq, max_freq)


# When the chart's range moves.
#
# The chart's range is each measurement type's saved view to start with, and moves only when the
# user moves it, when the app must show something (a loaded measurement's range; a newly identified
# plate or brace peak), or on a measurement-type switch. These are the decisions the view applies.


class ChartRange(NamedTuple):
    """The chart's four bounds. Mirrors Swift ``DisplayRange.ChartRange``."""

    min_freq: float
    max_freq: float
    min_db: float
    max_db: float


def on_settings_done(
    saved: ChartRange, previously_saved: ChartRange, type_changed: bool
) -> "ChartRange | None":
    """The chart range when Settings is closed with Done: the saved range if it changed, or if the
    measurement type changed (the chart moves to that type's saved view); None — the chart stays
    where it is — otherwise. Mirrors Swift ``DisplayRange.onSettingsDone``."""
    return saved if type_changed or saved != previously_saved else None


def on_new_measurement(
    current: ChartRange, loaded: "ChartRange | None", saved: ChartRange
) -> "ChartRange | None":
    """The chart range when a new measurement starts (New Tap, Play File): the saved range if the
    chart is still showing a loaded measurement's range (*loaded*, as widened) — the user has not
    moved it since the load; None — the chart stays where it is — otherwise. Mirrors Swift
    ``DisplayRange.onNewMeasurement``."""
    return saved if loaded is not None and current == loaded else None


def loaded_after_widening(
    loaded: "ChartRange | None", before: ChartRange, after: ChartRange
) -> "ChartRange | None":
    """The loaded range to remember after the chart widens onto a peak: the widened range if the
    chart was showing the loaded range (widening is the app, not the user); unchanged otherwise.
    Mirrors Swift ``DisplayRange.loadedAfterWidening``."""
    return after if loaded is not None and before == loaded else loaded


def entered_value(text: str, stored: float, decimals: int) -> "float | None":
    """The value of a Settings range field when Done is pressed: the stored value, exactly, if the
    field still shows it (*text* is its display at *decimals*) — an untouched field never rounds
    what was saved; otherwise the number typed, or None if it is not a number. Mirrors Swift
    ``DisplayRange.enteredValue``."""
    from guitar_tap.models import field_precision as fp  # noqa: PLC0415
    if text == fp.string(stored, decimals):
        return stored
    try:
        return float(text)
    except ValueError:
        return None

