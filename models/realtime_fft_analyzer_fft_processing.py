"""
FFT computation functions — mirrors Swift RealtimeFFTAnalyzer+FFTProcessing.swift.

Contains the module-level FFT analysis functions that correspond to Swift's
performFFT, computeGatedFFT, findPeaks, and HPS methods on RealtimeFFTAnalyzer.

  dft_anal        ↔  performFFT / computeGatedFFT (rectangular or Hann window)
  peak_detection  ↔  findPeaks — threshold + local-maximum filter
  peak_interp     ↔  findPeaks — parabolic sub-bin interpolation
  peak_q_factor   ↔  findPeaks — −3 dB bandwidth Q calculation
  hps_peak_freq   ↔  HPS dominant peak selection (plate/brace gated FFT)
  is_power2       ↔  (utility; implicit in Swift vDSP calls)

These functions are re-exported by realtime_fft_analyzer.py for backward
compatibility — callers that do `import models.realtime_fft_analyzer as f_a`
and call `f_a.dft_anal(...)` continue to work unchanged.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.fft import fft

Float64_1D = npt.NDArray[np.float64]


def is_power2(num: int) -> bool:
    """Check if num is power of two."""
    return ((num & (num - 1)) == 0) and num > 0


def dft_anal(
    chunk: npt.NDArray[np.float32], window_function: Float64_1D, n_freq_samples: int
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Analysis of a signal using the discrete Fourier transform.

    x: input signal, w: analysis window, N: FFT size.
    Returns (magnitude_dB, abs_fft).

    Mirrors Swift performFFT (continuous rectangular-window path) and
    computeGatedFFT (Hann-window path for plate/brace measurements).
    """

    if not is_power2(n_freq_samples):
        raise ValueError("FFT size (N) is not a power of 2")

    if window_function.size > n_freq_samples:
        raise ValueError("Window size (M) is bigger than FFT size")

    half_n_freq_samples = (n_freq_samples // 2) + 1
    half_time_samples_1 = (window_function.size + 1) // 2
    half_time_samples_2 = window_function.size // 2

    fftbuffer = np.zeros(n_freq_samples)

    window_function = window_function / sum(window_function)
    windowed_chunk = chunk * window_function

    fftbuffer[:half_time_samples_1] = windowed_chunk[half_time_samples_2:]
    fftbuffer[-half_time_samples_2:] = windowed_chunk[:half_time_samples_2]
    complex_fft = fft(fftbuffer)

    abs_fft = abs(complex_fft[:half_n_freq_samples])
    abs_fft[abs_fft < np.finfo(float).eps] = np.finfo(float).eps

    magnitude = 20 * np.log10(abs_fft)
    return magnitude, abs_fft


def peak_detection(
    magnitude: npt.NDArray[np.float32], threshold: int, window_size: int = 5
) -> npt.NDArray[np.signedinteger]:
    """Detect spectral peak locations.

    magnitude:   magnitude spectrum (dB).
    threshold:   minimum magnitude to qualify as a peak.
    window_size: half-width of the local-maximum window (bins on each side).
                 Default 5 mirrors Swift's ``windowSize = 5`` in findPeaks.

    Returns ploc: peak locations (bin indices).

    Mirrors Swift findPeaks — threshold + local-maximum filter.
    The Swift implementation checks ±5 bins (windowSize = 5); the original
    Python implementation only checked ±1 bin, which is why it found far more
    peaks than Swift.  The default window_size=5 now matches Swift exactly.
    """
    from scipy.signal import argrelmax
    # Find all local maxima over the ±window_size neighbourhood
    (local_max_indices,) = argrelmax(magnitude, order=window_size)
    # Keep only those above the threshold
    ploc = local_max_indices[magnitude[local_max_indices] > threshold]
    return ploc


def peak_q_factor(
    magnitude: Float64_1D,
    ploc: npt.NDArray[np.signedinteger],
    iploc: Float64_1D,
    ipmag: Float64_1D,
    sample_freq: int,
    n_f: int,
) -> Float64_1D:
    """Compute Q = f0 / bandwidth for each peak using the −3 dB method.

    Walks left and right from each integer peak bin until the spectrum
    drops below peak_mag − 3 dB, then Q = f0 / (f_hi − f_lo).
    Returns 0 for peaks where the boundary is not found within the spectrum.

    Mirrors Swift findPeaks Q-factor calculation.
    """
    hz_per_bin = sample_freq / n_f
    q_values = np.zeros(len(ploc), dtype=np.float64)

    for i, peak_bin in enumerate(ploc):
        half_power = ipmag[i] - 3.0

        bin_lo = int(peak_bin) - 1
        while bin_lo > 0 and magnitude[bin_lo] > half_power:
            bin_lo -= 1

        bin_hi = int(peak_bin) + 1
        while bin_hi < len(magnitude) - 1 and magnitude[bin_hi] > half_power:
            bin_hi += 1

        bandwidth = (bin_hi - bin_lo) * hz_per_bin
        if bandwidth > 0:
            q_values[i] = (iploc[i] * hz_per_bin) / bandwidth

    return q_values


def hps_peak_freq(
    mag_linear: npt.NDArray[np.float32],
    sample_freq: float,
    n_f: int,
    f_min: float = 50.0,
    f_max: float = 2000.0,
    harmonics: int = 4,
) -> float:
    """Harmonic Product Spectrum peak-frequency estimator.

    Multiplies the spectrum by progressively downsampled copies of itself to
    reinforce the fundamental and suppress harmonics.  Returns the dominant
    fundamental frequency (Hz) within [f_min, f_max], or 0.0 if no peak is
    found.

    Mirrors Swift HPS dominant-peak selection used by computeGatedFFT.

    Args:
        mag_linear:  Linear (not dB) magnitude spectrum — the abs_fft returned
                     by dft_anal.
        sample_freq: Audio sample rate (Hz).
        n_f:         FFT size (number of samples).
        f_min:       Lower frequency search limit (Hz).
        f_max:       Upper frequency search limit (Hz).
        harmonics:   Number of harmonics to include (2 → 4 is typical).
    """
    hps = mag_linear.astype(np.float64).copy()

    for h in range(2, harmonics + 1):
        downsampled = mag_linear[::h]
        n = min(len(hps), len(downsampled))
        hps[:n] *= downsampled[:n]

    bin_min = max(1, int(f_min * n_f / sample_freq))
    bin_max = min(len(hps) - 1, int(f_max * n_f / sample_freq))

    if bin_max <= bin_min:
        return 0.0

    peak_bin = int(np.argmax(hps[bin_min : bin_max + 1])) + bin_min
    return float(peak_bin * sample_freq / n_f)


def peak_interp(
    magnitude: npt.NDArray[np.float32], ploc: npt.NDArray[np.int64]
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Interpolate peak values using parabolic interpolation.

    magnitude: magnitude spectrum, ploc: locations of peaks.
    Returns iploc, ipmag: interpolated peak location, magnitude.

    Mirrors Swift findPeaks parabolic sub-bin interpolation.
    """
    val = magnitude[ploc]
    lval = magnitude[ploc - 1]
    rval = magnitude[ploc + 1]
    iploc = ploc + 0.5 * (lval - rval) / (lval - 2 * val + rval)
    ipmag = val - 0.25 * (lval - rval) * (iploc - ploc)
    return iploc, ipmag
