# @parity dsp/guitar-fft
# @parity dsp/fft
"""
FFT computation functions — mirrors Swift RealtimeFFTAnalyzer+FFTProcessing.swift.

Contains the module-level FFT analysis functions that correspond to methods on
Swift's RealtimeFFTAnalyzer extension in +FFTProcessing.swift.

Python ↔ Swift correspondence:
  dft_anal        ↔  computeFFT(on:) — pure DSP core (rectangular window, live display
                      path).  Swift's performFFT(on:) is now a thin wrapper that calls
                      computeFFT and dispatches its results to @Published properties;
                      dft_anal is the direct counterpart of computeFFT because both
                      are the side-effect-free computation layer used by the test suite.
  (computeGatedFFT, the Hann-window plate/brace capture path, is not here: it is
   RealtimeFFTAnalyzer.compute_gated_fft() in realtime_fft_analyzer.py)
  hps_peak_freq   ↔  HPS dominant-peak selection inside computeGatedFFT
  is_power2       ↔  (utility; implicit in Swift vDSP_DFT_zrop_CreateSetup)

Python-only functions (no direct Swift equivalent):
  is_power2       — explicit check; Swift lets vDSP validate the size at setup time

Swift-only functions (no Python equivalent):
  performFFT(on:)            — thin wrapper around computeFFT; publishes to @Published
                               on main thread.  Python equivalent: _FftProcessingThread.run()
                               calls dft_anal and emits fftFrameReady.
  updateFrequencyBins()      — publishes @Published frequencies on main thread
  updateCalibrationCorrections() — pre-computes calibration offsets per bin
  updateMetrics()            — publishes frequencyResolution, bandwidth, frameRate
  processAudioBuffer(_:)     — AVAudioEngine tap handler (buffer accumulation + FFT dispatch)
  nextPowerOfTwo(_:)         — helper for computeGatedFFT zero-padding size

These functions are re-exported by realtime_fft_analyzer.py for backward
compatibility — callers that do `import models.realtime_fft_analyzer as f_a`
and call `f_a.dft_anal(...)` continue to work unchanged.

NOTE — Python vs Swift implementation differences:
  Swift uses vDSP_DFT_zrop (Accelerate framework) via deinterleaved split-complex format;
  Python uses numpy.fft.fft on a zero-phase-shifted buffer (fftbuffer rotation trick).
  Both implementations apply the same window choice and the same window size (fft_size /
  fftSize), so neither implementation uses zero-padding in the continuous path:
    - Rectangular (all ones) window of fftSize samples for the live display path
      (performFFT / dft_anal with boxcar window) — flat amplitude response preferred
      over sidelobe suppression since the result is only used visually.
    - A periodic Hann window for the gated tap-capture path (computeGatedFFT /
      RealtimeFFTAnalyzer.compute_gated_fft), whose result feeds the material property
      calculations.  This path zero-pads to the next power-of-two, capped at 32768
      samples, and the window spans that padded length — see compute_gated_fft for what
      that does and does not suppress.
  Swift normalises with scale = 1/fftSize before calling vDSP_zvabs;
  Python normalises implicitly via window_function / sum(window_function) in dft_anal.
"""

from __future__ import annotations


import numpy as np
import numpy.typing as npt

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

    Mirrors Swift computeFFT(on:) (the rectangular-window continuous path). The
    Hann-window plate/brace capture path is RealtimeFFTAnalyzer.compute_gated_fft.

    Design note — window choice:
      Rectangular (all ones) is used for the live display path: flat amplitude
      response is preferred over sidelobe suppression because the result is only
      used visually.  Mirrors Swift's choice documented in performFFT.
    """
    # numpy.fft.fft is numerically identical to scipy.fft.fft for power-of-2 sizes
    # (both use pocketfft since NumPy 1.17) and avoids the ~8 s scipy cold-import
    # cost on Windows.
    from numpy.fft import fft
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

    # One-sided spectrum: bins 0 … N/2 inclusive.
    abs_fft = abs(complex_fft[:half_n_freq_samples])

    # Apply one-sided spectrum amplitude correction.
    #
    # scipy/numpy fft() returns the full two-sided DFT.  When we take only
    # the positive-frequency half (bins 0 … N/2) we discard the mirror
    # image, so the interior bins each hold only half the total signal power.
    # Multiplying by 2 restores the correct amplitude — matching the factor
    # already present in Swift's vDSP_DFT_zrop output, which folds the
    # two-sided spectrum into the one-sided form before returning.
    # DC (bin 0) and Nyquist (bin N/2) have no mirror, so they are not doubled.
    abs_fft[1:-1] *= 2.0

    # NO epsilon clamp. A bin with no energy is -inf, which is what Swift's vDSP_vdbcon produces
    # and what the Peak readout must say: -inf means "nothing at all", and it has to stay
    # distinguishable from -100 dB, a REAL level a live UMIK-1 reaches in a quiet room (it is also
    # the dead-input watchdog's own threshold). The clamp put "-313.0 dB" on screen for the absence
    # of a signal — a precise-looking number for nothing (#17, run-review).
    #
    # This is the LIVE per-frame path, the one the Peak readout reads; compute_gated_fft carried the
    # identical clamp and is fixed with it. errstate only silences numpy's per-frame divide-by-zero
    # warning — the -inf is the intended result.
    with np.errstate(divide="ignore"):
        magnitude = 20 * np.log10(abs_fft)
    return magnitude, abs_fft


# MARK: - perform_fft (mirrors Swift performFFT(on:) post-FFT block)

def perform_fft(analyzer, samples: "npt.NDArray[np.float32]", fft_size: int):
    """Run an FFT on *samples* and apply the per-frame post-processing.

    Mirrors Swift ``RealtimeFFTAnalyzer.performFFT(on:)`` in
    ``RealtimeFFTAnalyzer+FFTProcessing.swift`` — wraps the pure ``dft_anal``
    DSP step with:
      - per-bin calibration application (mirrors Swift's vDSP_vadd of
        calibrationCorrections)
      - the spectrum's peak, in dB, as a float — Swift's ``peakMagnitude``. It used to be
        int-encoded as ``max(dB) + 100`` for the Qt signal and decoded back at every consumer,
        which rounded the peak to whole dB for no reason any platform required (#17 F44).
    (Per-frame counters and any debug tracing live in the caller,
    _FftProcessingThread.run(), not here.)

    Lives in this file (rather than as a method on RealtimeFFTAnalyzer in
    realtime_fft_analyzer.py) so the file split matches Swift, where
    ``performFFT`` lives in ``RealtimeFFTAnalyzer+FFTProcessing.swift``.

    Args:
        analyzer:  The ``RealtimeFFTAnalyzer`` instance — supplies FFT
                   configuration and the calibration snapshot.
        samples:   Exactly ``fft_size`` time-domain samples (float32).
        fft_size:  FFT size, snapshot at call time.

    Returns:
        ``(mag_y_db, mag_y, peak_db)`` — the dB and linear magnitude spectra
        (calibration-applied) and the spectrum's peak in dB (``-inf`` on a silent input).
    """
    # Snapshot calibration under the analyzer's settings lock.  Mirrors Swift
    # where calibrationCorrections is read inside performFFT.
    with analyzer._settings_lock:
        calibration = analyzer._calibration

    mag_y_db, mag_y = dft_anal(samples, analyzer.window_fcn, fft_size)
    if calibration is not None:
        mag_y_db = mag_y_db + calibration

    _peak_bin = int(np.argmax(mag_y_db))  # first maximum on ties, as Swift's max(by:)
    _peak_db = float(mag_y_db[_peak_bin])

    # The live peak, owned here as Swift's RealtimeFFTAnalyzer owns peakFrequency/peakMagnitude.
    # A silent input is -inf dB at bin 0 (0 Hz), exactly as Swift reports it.
    analyzer.peak_frequency = _peak_bin * float(analyzer.rate) / fft_size
    analyzer.peak_magnitude = _peak_db
    # Swift: displayLevelDB = readoutLevelDB, at the same rate as the graph.
    analyzer.display_level_db = analyzer.readout_level_db

    return mag_y_db, mag_y, _peak_db


# MARK: - Peak detection, interpolation and Q — REMOVED 2026-09-20 (#17)
#
# peak_detection, peak_interp and peak_q_factor lived here: NumPy ports of the peak-finding
# section of Swift's findPeaks. Nothing in the application ever called them. The app uses the
# scalar pair on TapToneAnalyzer instead — _parabolic_interpolate and _calculate_q_factor in
# tap_tone_analyzer_peak_analysis.py — which are the direct counterparts of Swift's
# TapToneAnalyzer.parabolicInterpolate / calculateQFactor and are what the capture and
# peak-analysis paths run.
#
# So this module carried a second implementation of two rules, and test/dsp's ten tests
# exercised THAT one, in an edition where the app runs the other. Swift and the web each have
# exactly one implementation; the duplicate was Python-only.
#
# The same defect was found in test/peaks on 2026-07-19 and fixed by relocating those tests to
# test_fft_peak_detection.py rather than repointing them, which left this copy alive and its
# sibling slug untouched. test/dsp now tests the live pair in all three editions, and
# test_fft_peak_detection.py is gone with peak_detection. See SLUG-SWEEP.md F14.

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
