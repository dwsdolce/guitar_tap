"""
FFT computation functions — mirrors Swift RealtimeFFTAnalyzer+FFTProcessing.swift.

Contains the module-level FFT analysis functions that correspond to methods on
Swift's RealtimeFFTAnalyzer extension in +FFTProcessing.swift.

Python ↔ Swift correspondence:
  dft_anal        ↔  performFFT (rectangular window, live display) /
                      computeGatedFFT (Hann window, plate/brace capture)
  peak_detection  ↔  findPeaks — threshold + local-maximum filter
  peak_interp     ↔  findPeaks — parabolic sub-bin interpolation
  peak_q_factor   ↔  findPeaks — −3 dB bandwidth Q calculation
  hps_peak_freq   ↔  HPS dominant-peak selection inside computeGatedFFT
  is_power2       ↔  (utility; implicit in Swift vDSP_DFT_zrop_CreateSetup)

Python-only functions (no direct Swift equivalent):
  is_power2       — explicit check; Swift lets vDSP validate the size at setup time

Swift-only functions (no Python equivalent):
  updateFrequencyBins()      — publishes @Published frequencies on main thread
  updateCalibrationCorrections() — pre-computes calibration offsets per bin
  updateMetrics()            — publishes frequencyResolution, bandwidth, frameRate
  processAudioBuffer(_:)     — AVAudioEngine tap handler (buffer accumulation + resampling)
  resample(_:from:to:)       — linear-interpolation resampler for hardware ↔ target rate
  nextPowerOfTwo(_:)         — helper for computeGatedFFT zero-padding size

These functions are re-exported by realtime_fft_analyzer.py for backward
compatibility — callers that do `import models.realtime_fft_analyzer as f_a`
and call `f_a.dft_anal(...)` continue to work unchanged.

NOTE — Python vs Swift implementation differences:
  Swift uses vDSP_DFT_zrop (Accelerate framework) via deinterleaved split-complex format;
  Python uses scipy.fft.fft on a zero-phase-shifted buffer (fftbuffer rotation trick).
  Both implementations apply the same window choice:
    - Rectangular (all ones) for the live display path (performFFT / the rect-window
      branch of dft_anal) to favour flat amplitude response over sidelobe suppression.
    - Hann window for the gated tap-capture path (computeGatedFFT / the Hann-window
      branch of dft_anal) to suppress spectral sidelobes by ~31 dB for accurate
      frequency and Q measurements used in material property calculations.
  Swift normalises with scale = 1/fftSize before calling vDSP_zvabs;
  Python normalises implicitly via window_function / sum(window_function) in dft_anal.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from scipy.fft import fft

Float64_1D = npt.NDArray[np.float64]


# MARK: - Utilities

def is_power2(num: int) -> bool:
    """Return True when *num* is a power of two and greater than zero.

    Python-only utility — Swift passes the FFT size directly to
    vDSP_DFT_zrop_CreateSetup, which validates the size implicitly.
    """
    return ((num & (num - 1)) == 0) and num > 0


# MARK: - FFT Analysis

def dft_anal(
    chunk: npt.NDArray[np.float32], window_function: Float64_1D, n_freq_samples: int
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Analyse a signal using the Discrete Fourier Transform.

    Applies *window_function* to *chunk*, zero-phase-rotates the result into
    *fftbuffer*, computes the FFT, and returns both the dB-scale magnitude
    spectrum and the linear-scale magnitude spectrum.

    Args:
        chunk:           Input signal (time-domain samples).
        window_function: Analysis window (e.g. rectangular for live display, Hann
                         for gated plate/brace capture).  Normalised internally by
                         dividing by its sum.
        n_freq_samples:  FFT size N (must be a power of 2 and ≥ window_function.size).

    Returns:
        (magnitude_db, abs_fft) — dB-scale magnitude and linear-scale magnitude,
        each of length N/2 + 1 (the one-sided spectrum).

    Mirrors Swift performFFT(on:) (rectangular-window continuous path) and
    computeGatedFFT(samples:sampleRate:) (Hann-window plate/brace capture path).

    Design note — window choice:
      Rectangular (all ones) is used for the live display path: flat amplitude
      response is preferred over sidelobe suppression because the result is only
      used visually.  Hann is used for the gated path: it suppresses sidelobes
      by ~31 dB compared to rectangular, giving sharper, cleaner peaks and
      therefore more accurate frequency and Q readings that feed material property
      calculations.  Mirrors Swift's identical choice documented in performFFT and
      computeGatedFFT.
    """
    if not is_power2(n_freq_samples):
        raise ValueError("FFT size (N) is not a power of 2")

    if window_function.size > n_freq_samples:
        raise ValueError("Window size (M) is bigger than FFT size")

    half_n_freq_samples = (n_freq_samples // 2) + 1
    half_time_samples_1 = (window_function.size + 1) // 2
    half_time_samples_2 = window_function.size // 2

    # Zero-phase rotation into fftbuffer (equivalent to fftshift).
    # Swift achieves the same via deinterleaving into split-complex format
    # before calling vDSP_DFT_Execute.
    fftbuffer = np.zeros(n_freq_samples)
    window_function = window_function / sum(window_function)
    windowed_chunk = chunk * window_function
    fftbuffer[:half_time_samples_1] = windowed_chunk[half_time_samples_2:]
    fftbuffer[-half_time_samples_2:] = windowed_chunk[:half_time_samples_2]

    complex_fft = fft(fftbuffer)

    # One-sided spectrum: bins 0 … N/2 inclusive
    abs_fft = abs(complex_fft[:half_n_freq_samples])
    abs_fft[abs_fft < np.finfo(float).eps] = np.finfo(float).eps  # guard against log(0)

    magnitude = 20 * np.log10(abs_fft)
    return magnitude, abs_fft


# MARK: - Peak Detection (mirrors findPeaks in +FFTProcessing.swift)

def peak_detection(
    magnitude: npt.NDArray[np.float32], threshold: int, window_size: int = 5
) -> npt.NDArray[np.signedinteger]:
    """Detect spectral peak locations using a threshold and local-maximum filter.

    Args:
        magnitude:   dB-scale magnitude spectrum (one-sided).
        threshold:   Minimum magnitude in dB to qualify as a peak.
        window_size: Half-width of the local-maximum neighbourhood (bins on each side).
                     Default 5 mirrors Swift's ``windowSize = 5`` in findPeaks.

    Returns:
        ploc: Array of bin indices where local maxima exceed *threshold*.

    Mirrors Swift findPeaks — threshold + local-maximum filter section.
    The Swift implementation checks ±windowSize (= 5) bins; the original Python
    implementation only checked ±1 bin, which is why it found far more peaks than
    Swift.  The default window_size=5 now matches Swift exactly.
    """
    from scipy.signal import argrelmax
    # Find all local maxima over the ±window_size neighbourhood
    (local_max_indices,) = argrelmax(magnitude, order=window_size)
    # Keep only those above the threshold
    ploc = local_max_indices[magnitude[local_max_indices] > threshold]
    return ploc


def peak_interp(
    magnitude: npt.NDArray[np.float32], ploc: npt.NDArray[np.int64]
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Parabolic sub-bin interpolation for peak location and magnitude.

    Args:
        magnitude: dB-scale magnitude spectrum (one-sided).
        ploc:      Integer bin indices of detected peaks.

    Returns:
        (iploc, ipmag) — interpolated peak location (fractional bin) and
        interpolated peak magnitude (dB).

    Mirrors Swift findPeaks parabolic sub-bin interpolation section.
    The parabola is fitted through (ploc−1, ploc, ploc+1); the correction
    gives sub-bin accuracy roughly 10× finer than the raw bin spacing.
    """
    val = magnitude[ploc]
    lval = magnitude[ploc - 1]
    rval = magnitude[ploc + 1]
    iploc = ploc + 0.5 * (lval - rval) / (lval - 2 * val + rval)
    ipmag = val - 0.25 * (lval - rval) * (iploc - ploc)
    return iploc, ipmag


def peak_q_factor(
    magnitude: Float64_1D,
    ploc: npt.NDArray[np.signedinteger],
    iploc: Float64_1D,
    ipmag: Float64_1D,
    sample_freq: int,
    n_f: int,
) -> Float64_1D:
    """Compute Q = f₀ / bandwidth for each peak using the −3 dB method.

    Walks left and right from each integer peak bin until the magnitude spectrum
    drops below peak_mag − 3 dB, then computes Q = f₀ / (f_hi − f_lo).
    Returns 0 for peaks where the −3 dB boundary cannot be found within the spectrum.

    Args:
        magnitude:   dB-scale magnitude spectrum (one-sided).
        ploc:        Integer bin indices of detected peaks (from peak_detection).
        iploc:       Interpolated (fractional) bin positions (from peak_interp).
        ipmag:       Interpolated peak magnitudes in dB (from peak_interp).
        sample_freq: Audio sample rate in Hz.
        n_f:         FFT size.

    Returns:
        q_values: Q factor for each peak; 0.0 if boundary not found.

    Mirrors Swift findPeaks Q-factor calculation section in +FFTProcessing.swift.
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


# MARK: - HPS Dominant-Peak Selection (mirrors computeGatedFFT HPS section)

def hps_peak_freq(
    mag_linear: npt.NDArray[np.float32],
    sample_freq: float,
    n_f: int,
    f_min: float = 50.0,
    f_max: float = 2000.0,
    harmonics: int = 4,
) -> float:
    """Harmonic Product Spectrum (HPS) dominant-frequency estimator.

    Multiplies the linear magnitude spectrum by progressively downsampled copies
    of itself to reinforce the fundamental and suppress harmonics.  Returns the
    bin-centre frequency (Hz) of the dominant peak within [f_min, f_max], or
    0.0 if no valid peak is found.

    Args:
        mag_linear:  Linear (not dB) magnitude spectrum — the abs_fft returned
                     by dft_anal.  Must cover at least ``harmonics`` octaves above
                     ``f_min`` to give meaningful results.
        sample_freq: Audio sample rate in Hz.
        n_f:         FFT size (total, not one-sided).
        f_min:       Lower frequency search limit in Hz (default 50).
        f_max:       Upper frequency search limit in Hz (default 2000).
        harmonics:   Number of harmonics to fold in (2 through *harmonics*).
                     Typical values: 2–4.  Mirrors Swift's harmonic loop count.

    Returns:
        Dominant fundamental frequency in Hz, or 0.0 if not found.

    Mirrors Swift HPS dominant-peak selection used inside computeGatedFFT
    (+FFTProcessing.swift) for plate/brace material measurements.
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
