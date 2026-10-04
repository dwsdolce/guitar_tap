# @parity dsp/guitar-fft
# @parity dsp/fft
"""
FFT processing — mirrors Swift RealtimeFFTAnalyzer+FFTProcessing.swift.

RealtimeFFTAnalyzerFFTProcessingMixin holds the live (continuous) FFT path as methods on the
analyzer, as Swift's extension does:

  compute_fft   ↔  computeFFT(on:) — the side-effect-free DSP core: the rectangular window, the
                   FFT, the one-sided dB spectrum.
  perform_fft   ↔  performFFT(on:) — compute_fft, then calibration and the live peak
                   (peak_frequency / peak_magnitude).

The gated plate/brace capture path, Swift's computeGatedFFT, is
RealtimeFFTAnalyzer.compute_gated_fft in realtime_fft_analyzer.py.

Swift uses vDSP_DFT_zrop (Accelerate) on deinterleaved split-complex input; Python uses
numpy.fft.fft on a zero-phase-rotated buffer. Both apply the rectangular window of fft_size
samples with no zero-padding, and both give the one-sided spectrum with the interior bins doubled.
Swift normalises with scale = 1/fftSize; Python divides the window by its sum, which is the same.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def _is_power2(num: int) -> bool:
    """Whether ``num`` is a power of two. Swift lets vDSP validate the size at setup time."""
    return ((num & (num - 1)) == 0) and num > 0


class RealtimeFFTAnalyzerFFTProcessingMixin:
    """The live FFT path. Mirrors Swift ``RealtimeFFTAnalyzer+FFTProcessing.swift``."""

    def compute_fft(self, samples: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
        """Magnitude spectrum of ``samples`` in dBFS, with the analyzer's rectangular window and FFT size.

        The deterministic DSP core shared by ``perform_fft`` and the guitar gated capture. It reads
        ``window_fcn`` and ``fft_size`` and writes nothing.

        - Parameter samples: ``fft_size`` time-domain samples.
        - Returns: The one-sided magnitude spectrum in dBFS, ``fft_size / 2`` bins (DC up to the last
          bin below Nyquist, as Swift's).

        A bin with no energy is -inf, which is what Swift's vDSP_vdbcon produces: -inf means
        "nothing at all", and it has to stay distinguishable from -100 dB, a REAL level a live
        UMIK-1 reaches in a quiet room (and the dead-input watchdog's threshold). A clamp would put
        "-313.0 dB" on screen for the absence of a signal.

        Mirrors Swift ``RealtimeFFTAnalyzer.computeFFT(on:)``.
        """
        # numpy.fft.fft is numerically identical to scipy.fft.fft for power-of-2 sizes (both use
        # pocketfft) and avoids the ~8 s scipy cold-import cost on Windows.
        from numpy.fft import fft

        n_freq_samples = self.fft_size
        window_function = self.window_fcn
        if not _is_power2(n_freq_samples):
            raise ValueError("FFT size (N) is not a power of 2")
        if window_function.size > n_freq_samples:
            raise ValueError("Window size (M) is bigger than FFT size")

        half_n_freq_samples = n_freq_samples // 2
        half_time_samples_1 = (window_function.size + 1) // 2
        half_time_samples_2 = window_function.size // 2

        # Zero-phase rotation into fftbuffer (equivalent to fftshift). Swift achieves the same by
        # deinterleaving into split-complex format before vDSP_DFT_Execute.
        fftbuffer = np.zeros(n_freq_samples)
        window_function = window_function / sum(window_function)
        windowed_chunk = samples * window_function
        fftbuffer[:half_time_samples_1] = windowed_chunk[half_time_samples_2:]
        fftbuffer[-half_time_samples_2:] = windowed_chunk[:half_time_samples_2]

        complex_fft = fft(fftbuffer)
        # One-sided spectrum: bins 0 … N/2 − 1, as Swift's. The interior bins are doubled to restore the
        # discarded mirror half — the factor Swift's vDSP_DFT_zrop output already carries. DC has no
        # mirror, so it is not doubled.
        abs_fft = abs(complex_fft[:half_n_freq_samples])
        abs_fft[1:] *= 2.0
        # errstate only silences numpy's divide-by-zero warning — the -inf is the intended result.
        with np.errstate(divide="ignore"):
            return 20 * np.log10(abs_fft)

    def perform_fft(self, samples: npt.NDArray[np.float32]) -> tuple[npt.NDArray[np.float64], float]:
        """Run the live FFT on ``samples``: ``compute_fft``, then the input's calibration, then the
        spectrum's peak.

        Sets ``peak_frequency`` / ``peak_magnitude`` — the first maximum on ties, as Swift's
        ``max(by:)``, so a silent input is -inf dB at bin 0 (0 Hz) — and ``display_level_db``
        (Swift: ``displayLevelDB = readoutLevelDB``, at the graph's rate).

        - Parameter samples: ``fft_size`` time-domain samples.
        - Returns: ``(magnitudes_db, peak_db)`` — the calibrated dB spectrum and its peak.

        Mirrors Swift ``RealtimeFFTAnalyzer.performFFT(on:)``.
        """
        # Snapshot the calibration under the settings lock. Mirrors Swift reading
        # calibrationCorrections inside performFFT.
        with self._settings_lock:
            calibration = self._calibration

        magnitudes_db = self.compute_fft(samples)
        if calibration is not None:
            magnitudes_db = magnitudes_db + calibration

        peak_bin = int(np.argmax(magnitudes_db))  # first maximum on ties, as Swift's max(by:)
        peak_db = float(magnitudes_db[peak_bin])
        self.peak_frequency = peak_bin * float(self.rate) / self.fft_size
        self.peak_magnitude = peak_db
        self.display_level_db = self.readout_level_db
        return magnitudes_db, peak_db
