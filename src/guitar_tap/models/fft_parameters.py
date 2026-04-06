"""
FftParameters — FFT configuration parameters for audio analysis.

Python-only — no Swift counterpart.

In Swift, the FFT configuration values are already consolidated on
RealtimeFFTAnalyzer: fftSize, targetSampleRate, and window.
TapToneAnalyzer.mpmSampleRate is not a configuration parameter — it is a
runtime measurement of the hardware sample rate updated from audio buffers.

Python uses FftParameters as a construction-time helper: FftCanvas creates one
to compute axis values (freq array, n_fmin/n_fmax) before the analyzer and mic
objects exist.  It is passed to TapToneAnalyzer.__init__, which forwards
fft_size to RealtimeFFTAnalyzer — the object that then owns those values at
runtime, matching Swift's architecture.

Previously lived in views/fft_canvas.py as ``FftData``.  Moved here so
business-layer configuration lives in the model layer, not the view layer.
"""

from __future__ import annotations

from scipy.signal import get_window


class FftParameters:
    """FFT configuration parameters derived from a sample rate and FFT size.

    Owns the window function array and the pre-computed FFT-size fields
    (n_f, h_n_f) so callers do not have to recompute them.

    Previously ``FftData`` in views/fft_canvas.py.

    Python-only — Swift's equivalent values (fftSize, targetSampleRate, window)
    are already consolidated on RealtimeFFTAnalyzer.

    The window function is of length n_f (the FFT size), matching Swift's
    performFFT which applies a rectangular window of exactly fftSize samples
    with no zero-padding.
    """

    # MARK: - Initialization

    def __init__(self, sample_freq: int = 44100, n_f: int = 16384) -> None:
        """
        Args:
            sample_freq: Hardware sample rate in Hz (e.g. 44100 or 48000).
                         Updated after device selection to match the native rate.
            n_f:         FFT size in samples (must be a power of 2).
                         Mirrors Swift RealtimeFFTAnalyzer.fftSize.
        """
        # MARK: - Stored Properties

        # Hardware sample rate in Hz.
        # May be updated after construction to match the selected device's native rate.
        self.sample_freq: int = sample_freq

        # FFT size — must be a power of 2.
        # Mirrors Swift RealtimeFFTAnalyzer.fftSize.
        self.n_f: int = n_f

        # Ring-buffer / window length in samples — equals n_f, matching Swift's
        # inputBuffer which accumulates exactly fftSize samples before each FFT.
        self.m_t: int = n_f

        # Window function applied to the ring buffer before the FFT.
        # Using a rectangular (boxcar) window of n_f samples — matching Swift's
        # performFFT which applies a rectangular window of exactly fftSize samples
        # with no zero-padding.
        # See realtime_fft_analyzer_fft_processing.py for why rectangular is preferred.
        self.window_fcn = get_window("boxcar", self.n_f)

        # Half FFT size — number of positive-frequency bins (DC to Nyquist inclusive).
        self.h_n_f: int = self.n_f // 2

    # MARK: - Convenience

    def __repr__(self) -> str:
        return (
            f"FftParameters(sample_freq={self.sample_freq}, "
            f"n_f={self.n_f})"
        )
