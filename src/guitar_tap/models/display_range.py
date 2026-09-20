"""The rule for widening the chart's frequency axis so a newly identified peak is visible.

Mirrors Swift ``DisplayRange`` (Models/DisplayRange.swift).

# @parity presentation/display-range
"""

from __future__ import annotations

# Ten percent of the peak's frequency, so the peak is not flush against the axis edge.
PADDING_FRACTION: float = 0.10

# The lowest frequency the axis may show. Below 1 Hz there is nothing to draw.
FLOOR_HZ: float = 1.0


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
        hi = frequency + padding
    if frequency < lo:
        lo = max(FLOOR_HZ, frequency - padding)
    return lo, hi
