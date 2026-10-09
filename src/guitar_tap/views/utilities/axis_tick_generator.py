# @parity view/axis-ticks tests=test/axis-ticks
"""
Axis tick calculation helpers.

Mirrors Swift's AxisTickGenerator.swift: the tick values and labels of the spectrum chart's
frequency and magnitude axes, which are also its grid lines (one per tick, no minor lines);
plus the helpers that map between FFT bin indices and Hz, used by FftCanvas.update_axis() and
_refresh_peaks_for_viewport().
"""

from __future__ import annotations

import math


def generate_ticks(min_: float, max_: float, max_ticks: int = 10) -> list[float]:
    """Tick positions for [min_, max_] by the nice-number algorithm: the spacing is the rough
    spacing range / (max_ticks - 1) rounded up to {1, 2, 5} × 10ⁿ, and the bounds are extended
    outward to multiples of it. Mirrors Swift ``AxisTickGenerator.generateTicks``."""
    if not min_ < max_:
        return [min_]
    spacing = _nice_number((max_ - min_) / (max_ticks - 1), round_=False)
    nice_min = math.floor(min_ / spacing) * spacing
    nice_max = math.ceil(max_ / spacing) * spacing
    ticks: list[float] = []
    tick = nice_min
    while tick <= nice_max + spacing * 0.01:
        ticks.append(tick)
        tick += spacing
    return ticks


def _nice_number(x: float, round_: bool) -> float:
    exponent = math.floor(math.log10(x))
    fraction = x / math.pow(10, exponent)
    if round_:
        nice = 1 if fraction < 1.5 else 2 if fraction < 3 else 5 if fraction < 7 else 10
    else:
        nice = 1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10
    return nice * math.pow(10, exponent)


def format_tick_labels(values: list[float]) -> dict[float, str]:
    """The frequency ticks' labels — the same on screen and in the exported image: whole hertz below
    1 kHz and thousands with a k above (``1.2k``), the axis title carrying the unit; with more
    decimals until every label is different. Mirrors Swift
    ``AxisTickGenerator.formatTickLabels``."""
    if not values:
        return {}
    for extra in range(4):
        labels = {v: _frequency_label(v, 1 + extra) for v in values}
        if len(set(labels.values())) == len(labels):
            return labels
    return {v: "%.1f" % v for v in values}


def _frequency_label(value: float, thousands_decimals: int) -> str:
    if value >= 1000:
        return "%.*fk" % (thousands_decimals, value / 1000)
    return "%.0f" % value


def magnitude_stride(range_: float) -> float:
    """The screen's magnitude tick spacing (dB) for a visible range of ``range_`` dB: the smallest
    of 1, 2, 5, 10, 20 and 50 giving at most 8 ticks. Mirrors Swift
    ``AxisTickGenerator.magnitudeStride``."""
    for stride in (1.0, 2.0, 5.0, 10.0, 20.0, 50.0):
        if range_ / stride <= 8:
            return stride
    return 50.0


def freq_bin_range(
    n_f: int, sample_freq: int, fmin: int, fmax: int
) -> tuple[int, int]:
    """Convert a Hz range to FFT bin indices.

    Args:
        n_f: Total FFT size (power-of-two).
        sample_freq: Audio sample rate in Hz.
        fmin: Lower bound of the displayed frequency range (Hz).
        fmax: Upper bound of the displayed frequency range (Hz).

    Returns:
        (n_fmin, n_fmax) — half-spectrum bin indices corresponding to fmin/fmax.
    """
    n_fmin = (n_f * fmin) // sample_freq
    n_fmax = (n_f * fmax) // sample_freq
    return n_fmin, n_fmax


def clamp_freq_range(fmin: int, fmax: int) -> tuple[int, int]:
    """Ensure fmin < fmax; returns (fmin, fmax) unchanged if valid, else swaps."""
    if fmin < fmax:
        return fmin, fmax
    return fmax, fmin
