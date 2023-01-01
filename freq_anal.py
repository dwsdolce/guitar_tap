""" Calculate the dft, find the peaks, and then interpolate the peaks """

import numpy as np
from scipy.fftpack import fft

PHASE_TOL = 1e-14  # threshold used to compute phase

def is_power2(num):
    """
	Check if num is power of two
	"""
    return ((num & (num - 1)) == 0) and num > 0

def dft_anal(chunk, window_function, n_freq_samples):
    """
	Analysis of a signal using the discrete Fourier transform
	x: input signal, w: analysis window, N: FFT size
	returns magnitude, phase: magnitude and phase spectrum
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
    window_function = window_function / sum(window_function)
    windowed_chunk = chunk * window_function  # window the input sound
    # zero-phase window in fftbuffer
    fftbuffer[:half_time_samples_1] = windowed_chunk[half_time_samples_2:]
    fftbuffer[-half_time_samples_2:] = windowed_chunk[:half_time_samples_2]
    complex_fft = fft(fftbuffer)  # compute FFT
    # compute ansolute value of positive side
    abs_fft = abs(complex_fft[:half_n_freq_samples])
    # if zeros add epsilon to handle log
    abs_fft[abs_fft < np.finfo(float).eps] = np.finfo(float).eps
    # magnitude spectrum of positive frequencies in dB
    magnitude = 20 * np.log10(abs_fft)
    # for phase calculation set to 0 the small values
    complex_fft[:half_n_freq_samples].real[
            np.abs(complex_fft[:half_n_freq_samples].real) < PHASE_TOL] = 0.0
    complex_fft[:half_n_freq_samples].imag[
            np.abs(complex_fft[:half_n_freq_samples].imag) < PHASE_TOL] = 0.0
    # unwrapped phase spectrum of positive frequencie
    phase = np.unwrap(np.angle(complex_fft[:half_n_freq_samples]))
    return magnitude, phase

def peak_detection(magnitude, threshold):
    """
	Detect spectral peak locations
	magnitude: magnitude spectrum, t: threshold
	returns ploc: peak locations
	"""

    # locations above threshold
    thresh_values = np.where(
            np.greater(magnitude[1:-1], threshold), magnitude[1:-1], 0)
    # locations higher than the next one
    next_minor = np.where(magnitude[1:-1] > magnitude[2:], magnitude[1:-1], 0)
    # locations higher than the previous one
    prev_minor = np.where(magnitude[1:-1] > magnitude[:-2], magnitude[1:-1], 0)
    # locations fulfilling the three criteria
    ploc = thresh_values * next_minor * prev_minor
    ploc = ploc.nonzero()[0] + 1  # add 1 to compensate for previous steps
    return ploc

def peak_interp(magnitude, phase, ploc):
    """
	Interpolate peak values using parabolic interpolation
	magnitude, phase: magnitude and phase spectrum, ploc: locations of
        peaks returns iploc, ipmag, ipphase: interpolated peak location,
        magnitude and phase values
	"""

    val = magnitude[ploc]  # magnitude of peak bin
    lval = magnitude[ploc - 1]  # magnitude of bin at left
    rval = magnitude[ploc + 1]  # magnitude of bin at right
    # center of parabola
    iploc = ploc + 0.5 * (lval - rval) / (lval - 2 * val + rval)
    ipmag = val - 0.25 * (lval - rval) * (iploc - ploc)  # magnitude of peaks
    # phase of peaks by linear interpolation
    ipphase = np.interp(iploc, np.arange(0, phase.size), phase)
    return iploc, ipmag, ipphase
