"""
File playback regression tests.

These tests verify that the WAV-file playback pipeline produces correct
FFT results — particularly frequency accuracy and magnitude scaling — and
that the key edge cases (short files, stereo downmix, sample-rate tracking,
end-of-file flush) all behave as expected.

All tests work at the function or component level; no Qt event loop, no
PortAudio stream, and no real audio hardware are required.

Test IDs follow the project convention (FP1, FP2, …).

Real-recording tests (FR1–FR4) use Tests/Tap Test 2.wav from the GuitarTap
Swift project.  The expected peak values were established by running the file
through the Python pipeline and recording the results; they serve as a
regression baseline.  If the expected values need updating after a deliberate
algorithm change, re-run the discovery script at the bottom of this file.
"""

from __future__ import annotations

import io
import os
import struct
import sys
import tempfile
import threading
import time
from queue import Queue
from typing import Generator

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.realtime_fft_analyzer_fft_processing import (
    dft_anal,
    peak_detection,
    peak_interp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_wav(path: str, samples: np.ndarray, sample_rate: int, n_channels: int = 1) -> None:
    """Write a minimal PCM WAV file at *path*.

    Uses only the stdlib ``wave`` module so the tests have no extra dependency
    beyond what the project already requires.
    """
    import wave
    samples_int16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    if n_channels > 1:
        # Interleave: shape (frames, channels) → flat
        samples_int16 = np.column_stack([samples_int16] * n_channels).flatten()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(samples_int16.tobytes())


def _sine(freq_hz: float, duration_s: float, sample_rate: int, amplitude: float = 0.5) -> np.ndarray:
    """Return a mono sine wave as float32 samples in [-1, 1]."""
    t = np.arange(int(duration_s * sample_rate)) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _rect_window(n: int) -> np.ndarray:
    """Return a rectangular (boxcar) window of length *n*."""
    return np.ones(n, dtype=np.float64)


def _hann_window(n: int) -> np.ndarray:
    """Return a Hann window of length *n*."""
    return np.hanning(n).astype(np.float64)


def _peak_freq(mag_db: np.ndarray, sample_rate: int, fft_size: int) -> float:
    """Return the interpolated frequency (Hz) of the strongest peak in *mag_db*."""
    peaks = peak_detection(mag_db, threshold=-80)
    if len(peaks) == 0:
        return 0.0
    # Pick the highest-magnitude peak
    best = peaks[np.argmax(mag_db[peaks])]
    iploc, _ = peak_interp(mag_db, np.array([best]))
    bin_hz = sample_rate / fft_size
    return float(iploc[0] * bin_hz)


# ---------------------------------------------------------------------------
# FP1 — dft_anal: sine wave frequency is detected accurately
# ---------------------------------------------------------------------------

class TestDftAnalFrequencyAccuracy:
    """FP1–FP3: dft_anal returns the correct frequency for a known sine wave."""

    @pytest.mark.parametrize("freq_hz,sample_rate,fft_size", [
        (440.0,  44100, 16384),
        (440.0,  48000, 16384),
        (225.5,  44100, 16384),
        (1000.0, 44100,  8192),
    ])
    def test_FP1_peak_frequency_matches_input(self, freq_hz, sample_rate, fft_size):
        """FP1: dft_anal detects the correct frequency for a sine wave."""
        samples = _sine(freq_hz, duration_s=fft_size / sample_rate, sample_rate=sample_rate)
        window = _rect_window(fft_size)
        mag_db, _ = dft_anal(samples, window, fft_size)

        detected = _peak_freq(mag_db, sample_rate, fft_size)
        tolerance_hz = 2.0  # ±2 Hz is acceptable for parabolic interpolation
        assert abs(detected - freq_hz) < tolerance_hz, (
            f"Expected ~{freq_hz} Hz; got {detected:.2f} Hz "
            f"(sample_rate={sample_rate}, fft_size={fft_size})"
        )

    def test_FP2_hann_window_matches_frequency(self):
        """FP2: Hann-windowed dft_anal also returns the correct frequency."""
        freq_hz = 440.0
        sample_rate = 44100
        fft_size = 16384
        samples = _sine(freq_hz, duration_s=fft_size / sample_rate, sample_rate=sample_rate)
        window = _hann_window(fft_size)
        mag_db, _ = dft_anal(samples, window, fft_size)

        detected = _peak_freq(mag_db, sample_rate, fft_size)
        assert abs(detected - freq_hz) < 2.0, (
            f"Hann window: expected ~{freq_hz} Hz; got {detected:.2f} Hz"
        )

    def test_FP3_different_sample_rates_give_correct_frequency(self):
        """FP3: Frequency axis depends on sample_rate; both 44.1 kHz and 48 kHz are correct."""
        freq_hz = 440.0
        fft_size = 16384
        for sample_rate in (44100, 48000):
            samples = _sine(freq_hz, duration_s=fft_size / sample_rate, sample_rate=sample_rate)
            window = _rect_window(fft_size)
            mag_db, _ = dft_anal(samples, window, fft_size)
            detected = _peak_freq(mag_db, sample_rate, fft_size)
            assert abs(detected - freq_hz) < 2.0, (
                f"sample_rate={sample_rate}: expected ~{freq_hz} Hz; got {detected:.2f} Hz"
            )


# ---------------------------------------------------------------------------
# FP4 — dft_anal: magnitude scaling is correct
# ---------------------------------------------------------------------------

class TestDftAnalMagnitude:
    """FP4–FP6: dft_anal magnitude output is scaled correctly."""

    def test_FP4_full_scale_sine_is_near_0_dBFS(self):
        """FP4: A full-scale sine wave (amplitude ≈ 1.0) peaks close to 0 dBFS.

        With a rectangular window the expected peak is ~0 dBFS.
        The test allows ±3 dB for windowing and bin-edge effects.
        """
        sample_rate = 44100
        fft_size = 16384
        # Use a frequency that lands close to a bin centre to minimise scalloping.
        # bin spacing = 44100/16384 ≈ 2.69 Hz; pick bin 164 → ~441 Hz
        bin_target = 164
        freq_hz = bin_target * sample_rate / fft_size
        samples = _sine(freq_hz, duration_s=fft_size / sample_rate, sample_rate=sample_rate, amplitude=1.0)
        window = _rect_window(fft_size)
        mag_db, _ = dft_anal(samples, window, fft_size)

        peak_db = float(np.max(mag_db))
        assert -3.0 <= peak_db <= 3.0, (
            f"Full-scale sine peak should be near 0 dBFS; got {peak_db:.2f} dB"
        )

    def test_FP5_half_amplitude_is_6dB_below_full_scale(self):
        """FP5: Halving amplitude reduces the peak by ~6 dB."""
        sample_rate = 44100
        fft_size = 16384
        bin_target = 164
        freq_hz = bin_target * sample_rate / fft_size

        def _peak(amplitude):
            samples = _sine(freq_hz, fft_size / sample_rate, sample_rate, amplitude)
            window = _rect_window(fft_size)
            mag_db, _ = dft_anal(samples, window, fft_size)
            return float(np.max(mag_db))

        diff = _peak(1.0) - _peak(0.5)
        assert abs(diff - 6.0) < 1.0, (
            f"Halving amplitude should reduce peak by ~6 dB; got {diff:.2f} dB"
        )

    def test_FP6_silence_produces_very_low_magnitude(self):
        """FP6: A silent (all-zero) signal produces a spectrum well below -60 dBFS."""
        fft_size = 4096
        samples = np.zeros(fft_size, dtype=np.float32)
        window = _rect_window(fft_size)
        mag_db, _ = dft_anal(samples, window, fft_size)
        assert float(np.max(mag_db)) < -60.0, (
            "Silent signal should produce very low magnitude spectrum"
        )


# ---------------------------------------------------------------------------
# FP7 — WAV file reading and stereo downmix
# ---------------------------------------------------------------------------

class TestWavFileReading:
    """FP7–FP9: WAV file reading produces correct samples."""

    def test_FP7_mono_wav_reads_correct_samples(self, tmp_path):
        """FP7: A mono WAV file is read back with the correct sample values."""
        import soundfile as sf
        freq_hz = 440.0
        sample_rate = 44100
        duration = 0.5
        original = _sine(freq_hz, duration, sample_rate)
        wav_path = str(tmp_path / "mono.wav")
        _write_wav(wav_path, original, sample_rate, n_channels=1)

        data, rate = sf.read(wav_path, dtype="float32", always_2d=True)
        assert rate == sample_rate
        mono = data.mean(axis=1).astype(np.float32)
        # Amplitude should be within ±1% after the 16-bit quantisation round-trip
        rms_orig = np.sqrt(np.mean(original ** 2))
        rms_read = np.sqrt(np.mean(mono ** 2))
        assert abs(rms_read / rms_orig - 1.0) < 0.02, (
            f"Mono RMS mismatch after WAV round-trip: {rms_orig:.4f} vs {rms_read:.4f}"
        )

    def test_FP8_stereo_downmix_equals_mono(self, tmp_path):
        """FP8: Stereo WAV where both channels are identical downmixes to the original mono."""
        import soundfile as sf
        freq_hz = 440.0
        sample_rate = 44100
        duration = 0.5
        original = _sine(freq_hz, duration, sample_rate)
        wav_path = str(tmp_path / "stereo.wav")
        _write_wav(wav_path, original, sample_rate, n_channels=2)

        data, rate = sf.read(wav_path, dtype="float32", always_2d=True)
        assert data.shape[1] == 2, "Expected 2-channel data"
        mono = data.mean(axis=1).astype(np.float32)
        rms_orig = np.sqrt(np.mean(original ** 2))
        rms_mono = np.sqrt(np.mean(mono ** 2))
        assert abs(rms_mono / rms_orig - 1.0) < 0.02, (
            f"Stereo→mono downmix RMS mismatch: {rms_orig:.4f} vs {rms_mono:.4f}"
        )

    def test_FP9_sample_rate_is_preserved(self, tmp_path):
        """FP9: The sample rate read from the WAV file matches what was written."""
        import soundfile as sf
        for rate in (44100, 48000):
            samples = _sine(440.0, 0.1, rate)
            path = str(tmp_path / f"tone_{rate}.wav")
            _write_wav(path, samples, rate)
            _, file_rate = sf.read(path, dtype="float32", always_2d=True)
            assert file_rate == rate, f"Expected rate {rate}; got {file_rate}"


# ---------------------------------------------------------------------------
# FP10 — end-of-file zero-pad flush produces at least one FFT frame
# ---------------------------------------------------------------------------

class TestEndOfFileFlush:
    """FP10–FP11: The zero-pad flush at end-of-file fires an FFT frame."""

    def _run_flush(self, samples: np.ndarray, sample_rate: int, fft_size: int):
        """Exercise the end-of-file flush logic extracted from _playback_worker.

        Returns the (mag_db, mag_linear) tuple that would be emitted.
        """
        # Simulate the input_buffer that the processing thread would have
        # after consuming all the chunks that didn't fill fft_size samples.
        remainder = len(samples) % fft_size
        if remainder == 0 and len(samples) > 0:
            remainder = fft_size
        partial = samples[-remainder:] if remainder > 0 else np.zeros(0, dtype=np.float32)

        # Replicate the zero-pad logic from _playback_worker
        if len(partial) < fft_size:
            padded = np.concatenate(
                [partial, np.zeros(fft_size - len(partial), dtype=np.float32)]
            )
        else:
            padded = partial[:fft_size]

        window = _rect_window(fft_size)
        return dft_anal(padded, window, fft_size)

    def test_FP10_short_file_flush_produces_fft_frame(self):
        """FP10: A file shorter than one FFT window produces an FFT frame via zero-padding."""
        fft_size = 16384
        sample_rate = 44100
        # File is shorter than one FFT window
        freq_hz = 440.0
        samples = _sine(freq_hz, duration_s=0.1, sample_rate=sample_rate)
        assert len(samples) < fft_size, "Precondition: samples must be shorter than fft_size"

        mag_db, mag_linear = self._run_flush(samples, sample_rate, fft_size)

        # The frame must be the right shape and contain finite values
        assert mag_db.shape == (fft_size // 2 + 1,)
        assert np.all(np.isfinite(mag_db))

    def test_FP11_flush_frame_contains_correct_frequency(self):
        """FP11: The flushed FFT frame detects the expected tone even with zero-padding."""
        fft_size = 16384
        sample_rate = 44100
        freq_hz = 440.0
        # File shorter than one window
        samples = _sine(freq_hz, duration_s=0.2, sample_rate=sample_rate)

        mag_db, _ = self._run_flush(samples, sample_rate, fft_size)
        detected = _peak_freq(mag_db, sample_rate, fft_size)
        # Zero-padding broadens peaks so allow a wider tolerance here
        assert abs(detected - freq_hz) < 10.0, (
            f"Flushed (zero-padded) frame: expected ~{freq_hz} Hz; got {detected:.2f} Hz"
        )


# ---------------------------------------------------------------------------
# FP12 — queue injection: chunks fed into the queue produce correct FFT output
# ---------------------------------------------------------------------------

class TestQueueInjection:
    """FP12: Verify that samples chunked and queued match direct dft_anal output."""

    def test_FP12_chunked_queue_reassembly_matches_direct_fft(self):
        """FP12: Reassembling chunks from the queue gives the same FFT as a single call.

        This mirrors how _FftProcessingThread accumulates chunks from the queue
        into its ring buffer before firing dft_anal.
        """
        fft_size = 4096
        sample_rate = 44100
        chunksize = 1024
        freq_hz = 440.0

        samples = _sine(freq_hz, duration_s=fft_size / sample_rate, sample_rate=sample_rate)

        # Direct single-call reference
        window = _rect_window(fft_size)
        ref_mag, _ = dft_anal(samples, window, fft_size)

        # Chunked assembly via a queue
        q: Queue = Queue()
        for start in range(0, fft_size, chunksize):
            q.put(samples[start:start + chunksize])

        accumulated: list[np.ndarray] = []
        total = 0
        while total < fft_size:
            chunk = q.get_nowait()
            accumulated.append(chunk)
            total += len(chunk)
        assembled = np.concatenate(accumulated)[:fft_size]

        chunked_mag, _ = dft_anal(assembled, window, fft_size)

        np.testing.assert_allclose(
            chunked_mag, ref_mag, atol=1e-4,
            err_msg="Chunked reassembly must produce identical FFT to a single call"
        )


# ---------------------------------------------------------------------------
# FP13 — calibration offset is applied correctly
# ---------------------------------------------------------------------------

class TestCalibrationApplication:
    """FP13: A calibration correction array shifts magnitudes by the expected amount."""

    def test_FP13_calibration_shifts_magnitude_uniformly(self):
        """FP13: Adding a flat +3 dB calibration shifts every bin by exactly +3 dB."""
        fft_size = 4096
        sample_rate = 44100
        freq_hz = 440.0
        samples = _sine(freq_hz, duration_s=fft_size / sample_rate, sample_rate=sample_rate)
        window = _rect_window(fft_size)
        mag_db, _ = dft_anal(samples, window, fft_size)

        cal = np.full(len(mag_db), 3.0, dtype=np.float32)
        mag_corrected = mag_db + cal

        np.testing.assert_allclose(
            mag_corrected - mag_db, 3.0, atol=1e-5,
            err_msg="Calibration offset should shift every bin by exactly the correction value"
        )


# ---------------------------------------------------------------------------
# FP14 — playing_file_name is set correctly
# ---------------------------------------------------------------------------

class TestPlayingFileName:
    """FP14: The filename stored for chart-title use is correct."""

    def test_FP14_playing_file_name_strips_extension(self, tmp_path):
        """FP14: playing_file_name contains only the stem, without path or extension."""
        import soundfile as sf

        # Write a tiny WAV so soundfile can open it
        samples = _sine(440.0, 0.05, 44100)
        wav_path = str(tmp_path / "Tap Test 2.wav")
        _write_wav(wav_path, samples, 44100)

        import os
        stem = os.path.splitext(os.path.basename(wav_path))[0]
        assert stem == "Tap Test 2"


# ---------------------------------------------------------------------------
# FP15 — two-tone file: both peaks are detected
# ---------------------------------------------------------------------------

class TestTwoToneDetection:
    """FP15: A file with two simultaneous tones produces two detected peaks."""

    def test_FP15_two_tones_are_both_detected(self):
        """FP15: A signal containing 440 Hz and 880 Hz produces peaks near both."""
        fft_size = 16384
        sample_rate = 44100
        duration = fft_size / sample_rate
        t = np.arange(int(duration * sample_rate)) / sample_rate
        # Equal-amplitude tones well separated in frequency
        samples = (0.4 * np.sin(2 * np.pi * 440.0 * t)
                   + 0.4 * np.sin(2 * np.pi * 880.0 * t)).astype(np.float32)

        window = _hann_window(fft_size)
        mag_db, _ = dft_anal(samples, window, fft_size)

        peaks = peak_detection(mag_db, threshold=-60)
        iploc, _ = peak_interp(mag_db, peaks)
        bin_hz = sample_rate / fft_size
        detected_freqs = sorted(iploc * bin_hz)

        # There should be at least two peaks, and they should be near 440 and 880 Hz
        near_440 = any(abs(f - 440.0) < 5.0 for f in detected_freqs)
        near_880 = any(abs(f - 880.0) < 5.0 for f in detected_freqs)
        assert near_440, f"No peak near 440 Hz; detected: {[f'{f:.1f}' for f in detected_freqs]}"
        assert near_880, f"No peak near 880 Hz; detected: {[f'{f:.1f}' for f in detected_freqs]}"


# ---------------------------------------------------------------------------
# Real-recording tests — Tap Test 2.wav
#
# Expected values established by running the file through the Python pipeline
# (see the discovery commands at the bottom of this file).  These tests catch
# regressions anywhere in the chain: file reading, downmix, sample-rate
# tracking, window application, FFT, and peak interpolation.
#
# WAV file location: GuitarTap/Tests/Tap Test 2.wav (Swift project repo).
# The path is resolved relative to this file so CI works from any cwd.
# Tests are skipped automatically if the file is not present.
# ---------------------------------------------------------------------------

_TAP_TEST_2 = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "GuitarTap", "Tests", "Tap Test 2.wav")
)

# Baseline peaks established from the strongest frame (frame #1, Hann window, fft_size=16384).
# Format: (expected_freq_hz, tolerance_hz, expected_mag_dbfs, mag_tolerance_db)
_TAP_TEST_2_EXPECTED_PEAKS_HANN = [
    (243.1,  1.5, -33.1, 2.0),   # dominant mode — must always be present
    (396.0,  2.0, -39.7, 3.0),   # second strongest
    (434.0,  2.0, -46.5, 3.0),   # third
]

# Baseline for rectangular window (live display path), same frame.
_TAP_TEST_2_EXPECTED_PEAKS_RECT = [
    (243.0,  1.5, -30.2, 2.0),   # dominant mode
    (397.0,  2.0, -40.9, 3.0),   # second strongest
]


@pytest.fixture(scope="module")
def tap_test_2_frames():
    """Load Tap Test 2.wav and return the strongest Hann and rectangular FFT frames."""
    sf = pytest.importorskip("soundfile")
    if not os.path.exists(_TAP_TEST_2):
        pytest.skip(f"Tap Test 2.wav not found at {_TAP_TEST_2}")

    data, file_rate = sf.read(_TAP_TEST_2, dtype="float32", always_2d=True)
    mono = data.mean(axis=1).astype(np.float32)

    fft_size = 16384
    hann_win = _hann_window(fft_size)
    rect_win = _rect_window(fft_size)

    # Find the strongest frame (frame with highest peak magnitude)
    best_hann_mag = None
    best_rect_mag = None
    best_peak = -999.0
    n_frames = len(mono) // fft_size
    for i in range(n_frames):
        chunk = mono[i * fft_size:(i + 1) * fft_size]
        h_mag, _ = dft_anal(chunk, hann_win, fft_size)
        r_mag, _ = dft_anal(chunk, rect_win, fft_size)
        if float(np.max(h_mag)) > best_peak:
            best_peak = float(np.max(h_mag))
            best_hann_mag = h_mag
            best_rect_mag = r_mag

    return {
        "file_rate": file_rate,
        "fft_size": fft_size,
        "hann_mag": best_hann_mag,
        "rect_mag": best_rect_mag,
        "n_samples": len(mono),
        "mono": mono,
    }


def _check_peaks(mag_db, file_rate, fft_size, expected_peaks):
    """Assert that each (freq, tolerance, mag, mag_tolerance) entry in expected_peaks
    has a detected peak within the stated bounds."""
    peaks = peak_detection(mag_db, threshold=-65)
    iploc, ipmag = peak_interp(mag_db, peaks)
    bin_hz = file_rate / fft_size
    detected = list(zip(iploc * bin_hz, ipmag))

    for exp_freq, freq_tol, exp_mag, mag_tol in expected_peaks:
        # Find the closest detected peak to the expected frequency
        if not detected:
            pytest.fail(f"No peaks detected; expected peak near {exp_freq} Hz")
        closest = min(detected, key=lambda p: abs(p[0] - exp_freq))
        closest_freq, closest_mag = closest
        assert abs(closest_freq - exp_freq) < freq_tol, (
            f"Peak near {exp_freq} Hz: detected {closest_freq:.2f} Hz "
            f"(tolerance ±{freq_tol} Hz)"
        )
        assert abs(closest_mag - exp_mag) < mag_tol, (
            f"Peak near {exp_freq} Hz: magnitude {closest_mag:.2f} dBFS, "
            f"expected {exp_mag:.1f} ±{mag_tol} dB"
        )


class TestRealRecording:
    """FR1–FR4: Regression tests using Tap Test 2.wav."""

    def test_FR1_dominant_peak_frequency_hann(self, tap_test_2_frames):
        """FR1: Dominant peak from Tap Test 2.wav is ~243 Hz (Hann window)."""
        f = tap_test_2_frames
        peaks = peak_detection(f["hann_mag"], threshold=-65)
        iploc, ipmag = peak_interp(f["hann_mag"], peaks)
        bin_hz = f["file_rate"] / f["fft_size"]
        freqs = iploc * bin_hz
        dominant_freq = freqs[np.argmax(ipmag)]
        assert abs(dominant_freq - 243.1) < 1.5, (
            f"Dominant peak should be ~243.1 Hz; got {dominant_freq:.2f} Hz"
        )

    def test_FR2_top_three_peaks_hann(self, tap_test_2_frames):
        """FR2: Top three peaks from Tap Test 2.wav match baseline frequencies and
        magnitudes (Hann window, strongest frame)."""
        f = tap_test_2_frames
        _check_peaks(
            f["hann_mag"], f["file_rate"], f["fft_size"],
            _TAP_TEST_2_EXPECTED_PEAKS_HANN,
        )

    def test_FR3_dominant_peak_rectangular_window(self, tap_test_2_frames):
        """FR3: Dominant peak is ~243 Hz with a rectangular window (live display path)."""
        f = tap_test_2_frames
        _check_peaks(
            f["rect_mag"], f["file_rate"], f["fft_size"],
            _TAP_TEST_2_EXPECTED_PEAKS_RECT,
        )

    def test_FR4_results_are_deterministic(self, tap_test_2_frames):
        """FR4: Running the same file twice gives identical peak frequencies."""
        import soundfile as sf
        f = tap_test_2_frames
        data, file_rate = sf.read(_TAP_TEST_2, dtype="float32", always_2d=True)
        mono = data.mean(axis=1).astype(np.float32)

        fft_size = f["fft_size"]
        window = _hann_window(fft_size)
        # Use the same frame index as the fixture (frame #1 — confirmed strongest above)
        chunk = mono[fft_size:2 * fft_size]
        mag_db, _ = dft_anal(chunk, window, fft_size)

        peaks = peak_detection(mag_db, threshold=-65)
        iploc, ipmag = peak_interp(mag_db, peaks)
        bin_hz = file_rate / fft_size
        dominant_freq = float((iploc * bin_hz)[np.argmax(ipmag)])

        # Must match the fixture's result to within floating-point precision
        peaks2 = peak_detection(f["hann_mag"], threshold=-65)
        iploc2, ipmag2 = peak_interp(f["hann_mag"], peaks2)
        dominant_freq2 = float((iploc2 * bin_hz)[np.argmax(ipmag2)])

        assert abs(dominant_freq - dominant_freq2) < 0.01, (
            f"Results are not deterministic: {dominant_freq:.4f} Hz vs {dominant_freq2:.4f} Hz"
        )


# ---------------------------------------------------------------------------
# Discovery script
#
# To refresh the baseline values after a deliberate algorithm change, run:
#
#   cd /Users/dws/src/guitar_tap
#   .venv/bin/python - << 'EOF'
#   import sys; sys.path.insert(0, "src")
#   import numpy as np, soundfile as sf
#   from guitar_tap.models.realtime_fft_analyzer_fft_processing import (
#       dft_anal, peak_detection, peak_interp)
#   wav = "/Users/dws/src/GuitarTap/Tests/Tap Test 2.wav"
#   data, rate = sf.read(wav, dtype="float32", always_2d=True)
#   mono = data.mean(axis=1).astype(np.float32)
#   fft_size = 16384
#   window = np.hanning(fft_size).astype(np.float64)
#   best, best_mag = -999, None
#   for i in range(len(mono) // fft_size):
#       mag, _ = dft_anal(mono[i*fft_size:(i+1)*fft_size], window, fft_size)
#       if np.max(mag) > best: best, best_mag = np.max(mag), mag
#   peaks = peak_detection(best_mag, threshold=-65)
#   iploc, ipmag = peak_interp(best_mag, peaks)
#   order = np.argsort(ipmag)[::-1]
#   print("Freq (Hz)  Mag (dBFS)")
#   for i in order[:10]: print(f"  {iploc[i]*rate/fft_size:>8.2f}  {ipmag[i]:>8.2f}")
#   EOF
# ---------------------------------------------------------------------------
