""" Calculate the dft, find the peaks, and then interpolate the peaks """
import numpy as np
import numpy.typing as npt
from scipy.fftpack import fft

def is_power2(num):
    """
	Check if num is power of two
	"""
    return ((num & (num - 1)) == 0) and num > 0

def dft_anal(chunk: npt.NDArray[np.float32],
             window_function,
             n_freq_samples: int
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
    window_function = window_function / sum(window_function)
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

def peak_detection(magnitude: npt.NDArray[np.float32],
                   threshold: int
                  ) -> npt.NDArray[np.signedinteger]:
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

def peak_interp(magnitude: npt.NDArray[np.float32],
                ploc: npt.NDArray[np.int64]
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

"""
***********************************************************************
Name            : yin.py
Description     : Fundamental frequency estimation. Based on the YIN alorgorithm [1]: De Cheveigné, A., & Kawahara, H. (2002). YIN, a fundamental frequency estimator for speech and music. The Journal of the Acoustical Society of America, 111(4), 1917-1930.
Author          : Patrice Guyot. Previous works on the implementation of the YIN algorithm have been made thanks to Robin Larvor, Maxime Le Coz and Lionel Koenig.
***********************************************************************
"""

def differenceFunction(x, N, tau_max):
    """
    Compute difference function of data x. This corresponds to equation (6) in [1]

    Fastest implementation.
    This solution is implemented directly with Numpy fft.


    :param x: audio data
    :param N: length of data
    :param tau_max: integration window size
    :return: difference function
    :rtype: list
    """

    x = np.array(x, np.float64)
    w = x.size
    tau_max = min(tau_max, w)
    x_cumsum = np.concatenate((np.array([0.]), (x * x).cumsum()))
    size = w + tau_max
    p2 = (size // 32).bit_length()
    nice_numbers = (16, 18, 20, 24, 25, 27, 30, 32)
    size_pad = min(x * 2 ** p2 for x in nice_numbers if x * 2 ** p2 >= size)
    fc = np.fft.rfft(x, size_pad)
    conv = np.fft.irfft(fc * fc.conjugate())[:tau_max]
    return x_cumsum[w:w - tau_max:-1] + x_cumsum[w] - x_cumsum[:tau_max] - 2 * conv

def cumulativeMeanNormalizedDifferenceFunction(df, N):
    """
    Compute cumulative mean normalized difference function (CMND).

    This corresponds to equation (8) in [1]

    :param df: Difference function
    :param N: length of data
    :return: cumulative mean normalized difference function
    :rtype: list
    """

    cmndf = df[1:] * range(1, N) / np.cumsum(df[1:]).astype(float) #scipy method
    return np.insert(cmndf, 0, 1)

def getPitch(cmdf, tau_min, tau_max, harmo_th=0.1):
    """
    Return fundamental period of a frame based on CMND function.

    :param cmdf: Cumulative Mean Normalized Difference function
    :param tau_min: minimum period for speech
    :param tau_max: maximum period for speech
    :param harmo_th: harmonicity threshold to determine if it is necessary to compute pitch frequency
    :return: fundamental period if there is values under threshold, 0 otherwise
    :rtype: float
    """
    tau = tau_min
    while tau < tau_max:
        if cmdf[tau] < harmo_th:
            while tau + 1 < tau_max and cmdf[tau + 1] < cmdf[tau]:
                tau += 1
            return tau
        tau += 1

    return 0    # if unvoiced

def compute_yin(sig, sr, w_len=512, w_step=256, f0_min=100, f0_max=500, harmo_thresh=0.1):
    """

    Compute the Yin Algorithm. Return fundamental frequency and harmonic rate.

    :param sig: Audio signal (list of float)
    :param sr: sampling rate (int)
    :param w_len: size of the analysis window (samples)
    :param w_step: size of the lag between two consecutives windows (samples)
    :param f0_min: Minimum fundamental frequency that can be detected (hertz)
    :param f0_max: Maximum fundamental frequency that can be detected (hertz)
    :param harmo_tresh: Threshold of detection. The yalgorithmù return the first minimum of the CMND fubction below this treshold.

    :returns:

        * pitches: list of fundamental frequencies,
        * harmonic_rates: list of harmonic rate values for each fundamental frequency value (= confidence value)
        * argmins: minimums of the Cumulative Mean Normalized DifferenceFunction
        * times: list of time of each estimation
    :rtype: tuple
    """

    print('Yin: compute yin algorithm')
    tau_min = int(sr / f0_max)
    tau_max = int(sr / f0_min)

    timeScale = range(0, len(sig) - w_len, w_step)  # time values for each analysis window
    times = [t/float(sr) for t in timeScale]
    frames = [sig[t:t + w_len] for t in timeScale]

    pitches = [0.0] * len(timeScale)
    harmonic_rates = [0.0] * len(timeScale)
    argmins = [0.0] * len(timeScale)

    for i, frame in enumerate(frames):

        #Compute YIN
        df = differenceFunction(frame, w_len, tau_max)
        cmdf = cumulativeMeanNormalizedDifferenceFunction(df, tau_max)
        p = getPitch(cmdf, tau_min, tau_max, harmo_thresh)

        #Get results
        if np.argmin(cmdf)>tau_min:
            argmins[i] = float(sr / np.argmin(cmdf))
        if p != 0: # A pitch was found
            pitches[i] = float(sr / p)
            harmonic_rates[i] = cmdf[p]
        else: # No pitch, but we compute a value of the harmonic rate
            harmonic_rates[i] = min(cmdf)

    return pitches, harmonic_rates, argmins, times