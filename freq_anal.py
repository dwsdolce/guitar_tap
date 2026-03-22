""" Calculate the dft, find the peaks, and then interpolate the peaks """

import numpy as np
import numpy.typing as npt
from scipy.fft import fft

Float64_1D = npt.NDArray[np.float64]

def is_power2(num: int) -> bool:
    """
    Check if num is power of two
    """
    return ((num & (num - 1)) == 0) and num > 0


def dft_anal(
    chunk: npt.NDArray[np.float32], window_function: Float64_1D, n_freq_samples: int
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """
    Analysis of a signal using the discrete Fourier transform
    x: input signal, w: analysis window, N: FFT size
    returns magnitude
    """

    # raise error if N not a power of two
    if not is_power2(n_freq_samples):
        raise ValueError("FFT size (N) is not a power of 2")

    # raise error if window size bigger than fft size
    if window_function.size > n_freq_samples:
        raise ValueError("Window size (M) is bigger than FFT size")

    # size of positive spectrum, it includes sample 0
    half_n_freq_samples = (n_freq_samples // 2) + 1

    # half analysis window size by rounding
    half_time_samples_1 = (window_function.size + 1) // 2

    # half analysis window size by floor
    half_time_samples_2 = window_function.size // 2

    # initialize buffer for FFT
    fftbuffer = np.zeros(n_freq_samples)

    # normalize analysis window
    # print(f"Shape of window function: {window_function.shape}")

    window_function = window_function / sum(window_function)
    # print(f"value and Shape of window function sum: {sum(window_function)} {sum(window_function).shape}")
    # print(f"Shape of window function/ sum: {window_function.shape}")
    # print(f"Type and Shape of chunk: {type(chunk)} {chunk.shape}")
    windowed_chunk = chunk * window_function  # window the input sound

    # zero-phase window in fftbuffer
    fftbuffer[:half_time_samples_1] = windowed_chunk[half_time_samples_2:]
    fftbuffer[-half_time_samples_2:] = windowed_chunk[:half_time_samples_2]
    complex_fft = fft(fftbuffer)  # compute FFT

    # compute absolute value of positive side
    abs_fft = abs(complex_fft[:half_n_freq_samples])

    # if zeros add epsilon to handle log
    abs_fft[abs_fft < np.finfo(float).eps] = np.finfo(float).eps

    # magnitude spectrum of positive frequencies in dB
    magnitude = 20 * np.log10(abs_fft)
    return magnitude, abs_fft


def peak_detection(
    magnitude: npt.NDArray[np.float32], threshold: int
) -> npt.NDArray[np.signedinteger]:
    """
    Detect spectral peak locations
    magnitude: magnitude spectrum, t: threshold
    returns ploc: peak locations
    """

    # locations above threshold
    thresh_values = np.where(np.greater(magnitude[1:-1], threshold), magnitude[1:-1], 0)
    # locations higher than the next one
    next_minor = np.where(magnitude[1:-1] > magnitude[2:], magnitude[1:-1], 0)
    # locations higher than the previous one
    prev_minor = np.where(magnitude[1:-1] > magnitude[:-2], magnitude[1:-1], 0)
    # locations fulfilling the three criteria
    ploc = thresh_values * next_minor * prev_minor
    ploc = ploc.nonzero()[0] + 1  # add 1 to compensate for previous steps
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
    """
    Interpolate peak values using parabolic interpolation
    magnitude: magnitude spectrum, ploc: locations of
    peaks returns iploc, ipmag: interpolated peak location,
    magnitude
    """

    val = magnitude[ploc]  # magnitude of peak bin
    lval = magnitude[ploc - 1]  # magnitude of bin at left
    rval = magnitude[ploc + 1]  # magnitude of bin at right
    # center of parabola
    iploc = ploc + 0.5 * (lval - rval) / (lval - 2 * val + rval)
    ipmag = val - 0.25 * (lval - rval) * (iploc - ploc)  # magnitude of peaks
    return iploc, ipmag
