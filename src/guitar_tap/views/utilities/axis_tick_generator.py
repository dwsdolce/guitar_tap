"""
Axis tick calculation helpers.

Mirrors Swift's AxisTickGenerator.swift.

In Swift, AxisTickGenerator produces custom tick values and labels for the
frequency (x) and magnitude (y/dB) axes of the spectrum chart.  In Python,
pyqtgraph handles tick generation automatically; this module provides the
helper functions that map between FFT bin indices and Hz/dB values, which are
used by FftCanvas.update_axis() and _refresh_peaks_for_viewport().
"""

from __future__ import annotations


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
