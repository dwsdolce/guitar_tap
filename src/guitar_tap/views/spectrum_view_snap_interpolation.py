# @parity view/spectrum-chart tests=test/snap-interpolation
"""
The crosshair's snap to a curve. Mirrors Swift's SpectrumView+SnapInterpolation.swift.

When a result is held, or plate / brace phases or a comparison are shown, the crosshair reads a curve rather than
the pointer: the curve's magnitude at the pointer's frequency, interpolated between the two bins either side
(``snap_to_waveform``). With several curves it follows the one nearest the pointer on screen, and keeps it until
another is at least ``CURVE_GRAVITY_PX`` nearer (``locked_series``), so it does not flicker between curves close
together.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

# How much nearer on screen another curve must be before the crosshair leaves the one it follows. Swift's
# curveGravityThreshold, in points; here in the scene's logical pixels.
CURVE_GRAVITY_PX = 12.0


def snap_to_waveform(target_hz: float, magnitudes: Sequence[float],
                     frequencies: Sequence[float]) -> tuple[float, float] | None:
    """The point on a curve at ``target_hz``: frequency and magnitude interpolated linearly between the two bins
    either side of it (past an end, along the last two bins). ``frequencies`` ascending; None when the arrays are
    empty or of different lengths. Mirrors Swift ``snapToWaveform(targetHz:magnitudes:frequencies:)``."""
    n = len(frequencies)
    if n == 0 or len(magnitudes) != n:
        return None
    freqs = np.asarray(frequencies, dtype=np.float64)
    # The first bin at or above the target, then the nearer of it and the bin before.
    lo = int(np.searchsorted(freqs, target_hz, side="left"))
    lo = min(lo, n - 1)
    if lo > 0 and abs(freqs[lo - 1] - target_hz) < abs(freqs[lo] - target_hz):
        near = lo - 1
    else:
        near = lo
    # The bins either side of the target.
    if near < n - 1 and freqs[near] <= target_hz:
        left, right = near, near + 1
    elif near > 0:
        left, right = near - 1, near
    else:
        return float(freqs[near]), float(magnitudes[near])
    span = freqs[right] - freqs[left]
    if not span > 0:
        return float(freqs[near]), float(magnitudes[near])
    t = (target_hz - freqs[left]) / span
    return (float(freqs[left] + t * span),
            float(magnitudes[left] + t * (magnitudes[right] - magnitudes[left])))


def locked_series(candidates: Sequence[tuple[int, float]], locked_index: int) -> int:
    """The curve the crosshair follows, from each curve's ``(index, screen distance)`` to the pointer: the nearest,
    unless the one it follows (``locked_index``) is within ``CURVE_GRAVITY_PX`` of it. The first of equally near
    curves. Mirrors Swift ``lockedSeries(candidates:lockedIndex:)``."""
    if not candidates:
        return locked_index
    best_index, best_dist = min(candidates, key=lambda c: c[1])
    if best_index == locked_index:
        return locked_index
    locked_dist = next((d for i, d in candidates if i == locked_index), None)
    if locked_dist is not None and locked_dist - best_dist < CURVE_GRAVITY_PX:
        return locked_index
    return best_index


def nearest_series_index(target_hz: float, cursor_y: float, screen_y: Callable[[float], float],
                         series: Sequence[tuple[Sequence[float], Sequence[float]]], locked_index: int) -> int:
    """The curve to follow among ``series`` (each ``(magnitudes, frequencies)``): each curve's snapped point at
    ``target_hz`` is placed on screen by ``screen_y(magnitude)`` and measured from ``cursor_y``; then
    ``locked_series``. ``-1`` when there are no curves. Mirrors Swift ``nearestSeriesIndex``."""
    if not series:
        return -1
    candidates = []
    for i, (magnitudes, frequencies) in enumerate(series):
        snapped = snap_to_waveform(target_hz, magnitudes, frequencies)
        if snapped is not None:
            candidates.append((i, abs(screen_y(snapped[1]) - cursor_y)))
    return locked_series(candidates, locked_index)
