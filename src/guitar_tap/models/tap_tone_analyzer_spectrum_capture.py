"""
TapToneAnalyzer+SpectrumCapture — gated-FFT capture pipeline for plate/brace
measurements, dominant-peak selection, and spectrum averaging.

Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift.

## Gated FFT Architecture

The continuous FFT operates on a fixed long window (~400 ms at gatedCaptureDuration).
For guitar measurements this is fine because the tap-detection threshold ensures we
see the ring-out.  For plate and brace measurements the ring-out is much shorter and
the transient tap energy is spread across the full window, reducing the apparent peak
magnitude by up to ~15 dB.

The gated approach captures *raw PCM samples* starting just before the tap onset
(via the pre-roll buffer) and running until the window fills:

    ┌────────────────────────────────────┐
    │  200 ms pre-roll  │  400 ms gate   │
    │  (ring buffer)    │  (new samples) │
    └────────────────────────────────────┘
                  ↑ tap onset

## Dominant Peak Selection — HPS + Q filter

findDominantPeak uses a two-stage strategy:
1. Q filtering: candidates with Q < 3 are rejected as impact thuds.
2. Magnitude + HPS tie-breaking or lowest-significant selection for plate phases.

## Spectrum Averaging

Multiple taps are averaged in the linear power domain before peak detection.

Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift.
"""

from __future__ import annotations

import os

import numpy as np
import numpy.typing as npt
from PySide6 import QtCore
from PySide6.QtCore import Slot

from guitar_tap.utilities.logging import gt_log


class TapToneAnalyzerSpectrumCaptureMixin:
    """Gated-FFT capture pipeline and spectrum averaging for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift.

    Stored state (initialised in TapToneAnalyzer.__init__):
        self.material_tap_phase: MaterialTapPhase
        self.longitudinal_spectrum: tuple | None
        self.cross_spectrum: tuple | None
        self.flc_spectrum: tuple | None
        self.longitudinal_peaks: list[ResonantPeak]
        self.cross_peaks: list[ResonantPeak]
        self.flc_peaks: list[ResonantPeak]
        self.auto_selected_longitudinal_peak_id: str | None
        self.auto_selected_cross_peak_id: str | None
        self.auto_selected_flc_peak_id: str | None
        self.selected_longitudinal_peak: ResonantPeak | None
        self.selected_cross_peak: ResonantPeak | None
        self.selected_flc_peak: ResonantPeak | None
        self.captured_taps: list[tuple]
    """

    # Gated capture window duration in seconds.
    # Mirrors Swift TapToneAnalyzer.gatedCaptureDuration.
    GATED_CAPTURE_DURATION: float = 0.4  # 400 ms

    @property
    def _pre_roll_samples(self) -> int:
        """Number of pre-roll samples at the current hardware sample rate.

        Computed property — mirrors Swift:
            var preRollSamples: Int { Int(mpmSampleRate * TapToneAnalyzer.preRollDuration) }

        Uses _mpm_sample_rate (updated on every audio buffer) as the primary
        source, matching Swift's stored mpmSampleRate property.
        """
        return int(self._mpm_sample_rate * self._pre_roll_seconds)

    @property
    def _gated_sample_rate(self) -> float:
        """Current hardware sample rate in Hz.

        Mirrors Swift mpmSampleRate (a stored property updated on every audio buffer).
        _mpm_sample_rate is set at the top of _accumulate_gated_samples each call.
        Falls back to mic.rate if no audio buffer has been received yet.
        """
        rate = getattr(self, "_mpm_sample_rate", None)
        if rate:
            return float(rate)
        if self.mic is None:
            return 48000.0
        return float(self.mic.rate)

    # ------------------------------------------------------------------ #
    # WAV dump helper
    # ------------------------------------------------------------------ #

    def _dump_capture_wav(self, samples, sample_rate: float, label: str) -> None:
        """Write raw PCM samples to a mono 32-bit float WAV file.

        Saves to ~/Documents/GuitarTap/ (macOS/Linux) or
        Documents\\GuitarTap\\ (Windows) when the setting is enabled.
        Shared by guitar, plate, and brace capture paths.

        Mirrors Swift dumpCaptureWAV(samples:sampleRate:label:).
        """
        from models.tap_display_settings import TapDisplaySettings as _tds
        if not _tds.dump_capture_audio():
            return
        try:
            import struct
            import sys
            from datetime import datetime, timezone
            from pathlib import Path

            if sys.platform == "win32":
                docs = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
            else:
                docs = Path.home() / "Documents"
            dump_dir = docs / "GuitarTap"
            dump_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            name = f"python_{label}_{ts}.wav"
            path = dump_dir / name

            pcm = samples.astype(np.float32).tobytes()
            sr = int(sample_rate)
            n_samples = len(samples)
            bytes_per_sample = 4
            data_size = n_samples * bytes_per_sample

            with open(path, "wb") as f:
                f.write(b"RIFF")
                f.write(struct.pack("<I", 36 + data_size))
                f.write(b"WAVE")
                f.write(b"fmt ")
                f.write(struct.pack("<I", 16))
                f.write(struct.pack("<H", 3))             # IEEE float
                f.write(struct.pack("<H", 1))             # mono
                f.write(struct.pack("<I", sr))
                f.write(struct.pack("<I", sr * bytes_per_sample))
                f.write(struct.pack("<H", bytes_per_sample))
                f.write(struct.pack("<H", 32))
                f.write(b"data")
                f.write(struct.pack("<I", data_size))
                f.write(pcm)
            gt_log(f"📦 WAV dump: {path} ({n_samples} samples, {sr} Hz)")
        except Exception as e:
            gt_log(f"⚠️ WAV dump failed: {e}")

    # ------------------------------------------------------------------ #
    # _set_material_tap_phase
    # ------------------------------------------------------------------ #

    def _set_material_tap_phase(self, phase) -> None:
        """Assign material_tap_phase and notify the UI via plateStatusChanged.

        All writes to material_tap_phase must go through this helper so that
        the UI phase step indicator is kept in sync.  Mirrors Swift, where
        materialTapPhase is a @Published property and the view observes it
        directly; here we emit plateStatusChanged explicitly because plain
        Python attributes have no automatic Qt reactivity.
        """
        self.material_tap_phase = phase
        self.plateStatusChanged.emit(phase.value)

    # ------------------------------------------------------------------ #
    # _accumulate_gated_samples
    # Mirrors Swift TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:)
    # ------------------------------------------------------------------ #

    def _accumulate_gated_samples(self, chunk: "npt.NDArray[np.float32]", sample_rate: float) -> None:
        """Maintain the pre-roll ring buffer and accumulate a gated capture window.

        Called on every audio chunk by _FftProcessingThread.run() via
        mic.raw_sample_handler.  Runs on the audio processing background thread
        so all shared state is protected by self._gated_lock.

        Mirrors Swift TapToneAnalyzer.accumulateGatedSamples(_:sampleRate:):
          - Always updates the pre-roll ring buffer.
          - When gatedCaptureActive, appends to gatedAccumBuffer.
          - When the window fills, sets gatedCaptureActive = false and dispatches
            finishGatedFFTCapture to the main thread via gatedCaptureComplete signal.

        Args:
            chunk:       Raw PCM audio chunk (float32, mono, normalised ±1.0).
            sample_rate: Hardware sample rate in Hz.
        """
        import numpy as np

        # Mirrors Swift: mpmSampleRate = sampleRate (stored property updated each call).
        self._mpm_sample_rate = sample_rate

        samples = chunk.tolist()

        # Step 1 — hold lock, update pre-roll and accumulator, read count, release.
        # Mirrors Swift: mpmLock.lock() → append → let count = … → mpmLock.unlock()
        with self._gated_lock:
            # Maintain the pre-roll ring buffer — always, even when not capturing.
            # Mirrors Swift: preRollBuffer.append(contentsOf: samples)
            self._pre_roll_buf.extend(samples)
            if len(self._pre_roll_buf) > self._pre_roll_samples:
                self._pre_roll_buf = self._pre_roll_buf[-self._pre_roll_samples:]

            if not self._gated_capture_active:
                return

            self._gated_accum.extend(samples)
            count = len(self._gated_accum)
        # Lock released — mirrors Swift mpmLock.unlock() before count check.

        if count < self._gated_capture_samples:
            return

        # Step 2 — window is full; re-acquire lock to slice and clear accumulator.
        # Mirrors Swift: gatedCaptureActive = false; mpmLock.lock() → slice → mpmLock.unlock()
        with self._gated_lock:
            self._gated_capture_active = False
            captured = self._gated_accum[:self._gated_capture_samples]
            phase = self._gated_capture_phase
            self._gated_accum = []

        # DIAG: log capture completion details
        _diag_consumed = 0
        if self.mic is not None and hasattr(self.mic, "proc_thread"):
            _diag_consumed = getattr(self.mic.proc_thread, '_diag_total_samples', 0)
        _cap_arr = np.array(captured, dtype=np.float32)
        _diag_rms = float(np.sqrt(np.mean(_cap_arr ** 2))) if len(captured) > 0 else 0.0
        _diag_hash = float(np.sum(_cap_arr[:16])) if len(captured) >= 16 else 0.0
        from guitar_tap.utilities.logging import TAP_DEBUG as _td2
        _td2("gatedAccum",
             f"CAPTURE COMPLETE | samples={len(captured)} "
             f"fileSamplePos={_diag_consumed} "
             f"captureRMS={20*np.log10(max(_diag_rms,1e-10)):.2f}dB "
             f"first16hash={_diag_hash:.6f}")

        # Emit on background thread; Qt queued connection delivers on main thread.
        # gatedCaptureComplete signal is still on proc_thread as a delivery mechanism.
        if self.mic is not None and hasattr(self.mic, "proc_thread"):
            self.mic.proc_thread.gatedCaptureComplete.emit(
                _cap_arr,
                sample_rate,
                phase,
            )

    # ------------------------------------------------------------------ #
    # _flush_gated_capture_on_file_end
    # Mirrors Swift TapToneAnalyzer.flushGatedCaptureOnFileEnd()
    # ------------------------------------------------------------------ #

    def _flush_gated_capture_on_file_end(self) -> None:
        """Zero-pad and complete any active gated capture when file playback ends.

        Called from _playback_worker (via _on_pre_mic_restart) after the input
        buffer flush but BEFORE the mic stream restarts.  Without this, the mic
        restarts instantly and mic noise fills the remaining gated capture window,
        contaminating the last tap's spectrum.

        Mirrors Swift TapToneAnalyzer.flushGatedCaptureOnFileEnd() which is
        called from startFromFile's asyncAfter block.

        The pattern is the same as the safety timeout flush: take whatever
        samples have accumulated, zero-pad to the target window size, and
        emit gatedCaptureComplete so the FFT runs on a clean (partial +
        silence) buffer rather than partial + mic noise.
        """
        import numpy as np

        from guitar_tap.utilities.logging import TAP_DEBUG as _td_flush
        with self._gated_lock:
            _td_flush("file_playback", f"FLUSH_GATED_CHECK | active={self._gated_capture_active} accumLen={len(self._gated_accum)} phase={self._gated_capture_phase}")
            if not self._gated_capture_active:
                _td_flush("file_playback", "FLUSH_GATED_SKIP | not active")
                return
            self._gated_capture_active = False
            partial = list(self._gated_accum)
            target = self._gated_capture_samples
            phase = self._gated_capture_phase
            self._gated_accum = []

        if not partial:
            _td_flush("file_playback", "FLUSH_GATED_SKIP | empty partial")
            return

        sample_rate = self._mpm_sample_rate

        # Zero-pad to target window size so the FFT receives an exactly-sized
        # window.  The padded zeros lower the average level but don't distort
        # the ring-out peaks — the file signal is in the leading portion.
        if len(partial) < target:
            partial.extend([0.0] * (target - len(partial)))
        else:
            partial = partial[:target]

        gt_log(f"🎯 Gated capture flushed on file end — "
               f"{len(partial)} samples (zero-padded to {target})")

        # Emit on this thread (playback worker); Qt queued connection delivers
        # on the main thread.
        if self.mic is not None and hasattr(self.mic, "proc_thread"):
            self.mic.proc_thread.gatedCaptureComplete.emit(
                np.array(partial, dtype=np.float32),
                sample_rate,
                phase,
            )

    # ------------------------------------------------------------------ #
    # start_gated_capture
    # Mirrors Swift TapToneAnalyzer.startGatedCapture(phase:)
    # ------------------------------------------------------------------ #

    def start_gated_capture(self, phase) -> None:
        """Open a raw-PCM capture window for the current plate/brace phase.

        Seeds the gated accumulator with the pre-roll contents so the tap attack
        transient (which arrived before this call) is included in the captured window.
        Starts a 2-second safety timeout that flushes or prompts a re-tap.

        Mirrors Swift TapToneAnalyzer.startGatedCapture(phase:).

        Args:
            phase: MaterialTapPhase being captured.
        """
        rate = float(self._gated_sample_rate)
        target_samples = int(rate * self.GATED_CAPTURE_DURATION)
        window_ms = int(self.GATED_CAPTURE_DURATION * 1000)
        with self._gated_lock:
            # Bump capture identity — invalidates any pending safety-timeout
            # from a previous capture so it cannot flush this capture's
            # accumulator with a partial buffer.  See start_guitar_gated_capture
            # for the full explanation of the race this prevents.
            self._gated_capture_id += 1
            my_capture_id = self._gated_capture_id
            # Seed accumulator with pre-roll (mirrors Swift: gatedAccumBuffer = preRollBuffer).
            self._gated_accum = list(self._pre_roll_buf)
            self._gated_capture_samples = target_samples
            self._gated_capture_phase = phase
            self._gated_capture_active = True

        gt_log(
            f"🎯 Gated FFT capture started for phase {phase} — "
            f"{target_samples}-sample window ({window_ms} ms at {int(rate)} Hz)"
        )

        # Safety timeout: if the buffer still has audio after 2 s, flush it;
        # if empty, ask the user to tap again.
        # Mirrors Swift DispatchQueue.main.asyncAfter(deadline: .now() + 2.0).
        # QTimer.singleShot fires on the main thread.
        def _safety_timeout() -> None:
            with self._gated_lock:
                # Identity guard — see start_guitar_gated_capture.
                if self._gated_capture_id != my_capture_id:
                    return
                if not self._gated_capture_active:
                    return  # already completed normally
                self._gated_capture_active = False
                partial = list(self._gated_accum)
                self._gated_accum = []
            if partial:
                # Reuse the existing queued-connection delivery path: emit on the
                # background thread; Qt delivers finish_gated_fft_capture on main.
                if self.mic is not None and hasattr(self.mic, "proc_thread"):
                    self.mic.proc_thread.gatedCaptureComplete.emit(
                        np.array(partial, dtype=np.float32),
                        self._gated_sample_rate,
                        phase,
                    )
            else:
                # QTimer.singleShot(2000, ...) already fires on the main thread,
                # so call directly — mirrors Swift closure calling statusMessage and
                # reEnableDetectionForNextPlateTap() directly in the timeout closure.
                gt_log("⚠️ Gated capture timeout with no samples — tap again")
                self._set_status_message("No signal detected — tap again")
                self.re_enable_detection_for_next_plate_tap()

        QtCore.QTimer.singleShot(2000, _safety_timeout)

    # ------------------------------------------------------------------ #
    # start_guitar_gated_capture / finish_guitar_gated_capture
    # Guitar-mode raw-PCM capture aligned to the tap onset.  Reuses the
    # plate/brace pre-roll buffer + accumulator (single source of audio
    # samples) but captures fft_size samples and applies the same
    # rectangular window used by the live FFT, so the resulting spectrum
    # is interchangeable with what on_fft_frame would have produced for
    # a tap-aligned frame.  No Swift counterpart yet — this is the new
    # design path.
    # ------------------------------------------------------------------ #

    def start_guitar_gated_capture(self) -> None:
        """Open a raw-PCM capture window for guitar mode, aligned to tap onset.

        Two-layer architecture (mirrors Swift TapToneAnalyzer+SpectrumCapture):

        Layer 1 — Audio-queue fast-start (level-crossing handler):
          The level-crossing handler on the audio processing thread seeds
          the gated accumulator and sets _gated_capture_active = True the
          instant RMS crosses the detection threshold.  This eliminates the
          main-thread Qt dispatch delay, keeping the pre-roll buffer aligned
          with the tap attack transient.

        Layer 2 — Main-thread fallback (this method):
          Called from _handle_tap_detection on the main thread.  If the
          fast-start already activated the capture, this method just sets up
          the safety timeout and returns.  Otherwise (crossing handler missed
          or not wired), it falls back to the original pre-roll seed path.

        Capture window size = mic.fft_size (matches live FFT frequency
        resolution exactly).  When the window fills, _accumulate_gated_samples
        emits gatedCaptureComplete with phase=None so finish_gated_fft_capture
        routes the result through finish_guitar_gated_capture.
        """
        if self.mic is None:
            return
        rate = float(self._gated_sample_rate)
        target_samples = int(self.mic.fft_size)

        with self._gated_lock:
            already_active = self._gated_capture_active
            if already_active:
                # Fast-start already seeded the accumulator on the audio queue.
                # Just read the capture ID and current count for logging.
                my_capture_id = self._gated_capture_id
                current_count = len(self._gated_accum)
            else:
                # Fallback: seed from live pre-roll (crossing handler missed).
                self._gated_capture_id += 1
                my_capture_id = self._gated_capture_id
                self._gated_accum = list(self._pre_roll_buf)
                self._gated_capture_samples = target_samples
                self._gated_capture_phase = None  # None = guitar mode marker
                self._gated_capture_active = True
                current_count = len(self._gated_accum)

        target_ms = int((target_samples / max(rate, 1.0)) * 1000) + 500

        if already_active:
            gt_log(
                f"🎯 Guitar gated capture (audio-queue fast-start) — "
                f"{target_samples}-sample window "
                f"({target_ms - 500} ms at {int(rate)} Hz, "
                f"accum {current_count}/{target_samples}), "
                f"timeout {target_ms} ms"
            )
        else:
            gt_log(
                f"🎯 Guitar gated capture (main-thread fallback) — "
                f"{target_samples}-sample window "
                f"({target_ms - 500} ms at {int(rate)} Hz, "
                f"pre-roll {current_count} samples)"
            )

        # Safety timeout — if the file ends or the user stops before the
        # capture window fills, flush whatever we have so the partial
        # spectrum still gets appended.  Long enough to allow the full
        # post-trigger portion at all supported sample rates.
        def _safety_timeout() -> None:
            with self._gated_lock:
                # Identity guard: if a newer capture has started since this
                # timeout was scheduled, this closure is stale — do nothing.
                # (Without this, the stale timeout would steal the new
                # capture's accumulator and dispatch it as a partial.)
                if self._gated_capture_id != my_capture_id:
                    return
                if not self._gated_capture_active:
                    return
                self._gated_capture_active = False
                partial = list(self._gated_accum)
                self._gated_accum = []
            if not partial:
                gt_log("⚠️ Guitar gated capture timeout with no samples")
                self._guitar_gated_capture_failed()
                return
            if self.mic is not None and hasattr(self.mic, "proc_thread"):
                self.mic.proc_thread.gatedCaptureComplete.emit(
                    np.array(partial, dtype=np.float32),
                    self._gated_sample_rate,
                    None,
                )

        QtCore.QTimer.singleShot(target_ms, _safety_timeout)

    def _guitar_gated_capture_failed(self) -> None:
        """Re-arm detection without storing a tap when guitar capture fails."""
        self._set_status_message("No signal detected — tap again")
        cooldown_ms = int(self.tap_cooldown * 1000)
        QtCore.QTimer.singleShot(cooldown_ms, self._do_reenable_guitar)

    def finish_guitar_gated_capture(self, samples, sample_rate: float) -> None:
        """Compute FFT for a guitar gated capture and append to captured_taps.

        Uses the same fft_size and rectangular window as the live FFT, so the
        resulting (magnitudes, frequencies) tuple is shape-compatible with
        what the previous code path appended directly from on_fft_frame.

        After the spectrum is appended, advances the tap counter and either
        schedules _finish_capture (all taps done) or _do_reenable_guitar
        (next tap pending).
        """
        from .realtime_fft_analyzer_fft_processing import dft_anal as _dft_anal
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        if self.mic is None:
            return

        # Orphan-capture guard.  In brace/plate mode the level-crossing handler
        # may seed a phase=None (guitar) gated capture from a noise spike that
        # never produces a confirming rising-edge — when its 65536-sample
        # window fills (~1.36 s later) it lands here.  Without this guard we
        # would append a silent spectrum to captured_taps, advance the tap
        # counter, and overwrite the displayed frozen spectrum, masking the
        # real brace/plate phase capture that runs in parallel.  Mirrors the
        # equivalent guard in Swift TapToneAnalyzer+SpectrumCapture.swift
        # finishGuitarGatedCapture.
        if _tds.measurement_type() != _MT.GENERIC:
            from utilities.logging import TAP_DEBUG as _td_orphan
            _td_orphan(
                "guitar_gated_capture",
                f"ORPHAN — discarded (measurementType={_tds.measurement_type()}, "
                f"samples={len(samples)})",
            )
            return

        self._dump_capture_wav(samples, sample_rate, "guitar")

        fft_size = int(self.mic.fft_size)

        # Truncate or zero-pad to exactly fft_size.
        if len(samples) >= fft_size:
            chunk = samples[:fft_size].astype(np.float32)
        else:
            chunk = np.concatenate(
                [samples.astype(np.float32),
                 np.zeros(fft_size - len(samples), dtype=np.float32)]
            )

        window_fcn = self.mic.window_fcn  # rectangular (np.ones(fft_size))
        magnitudes_db, _ = _dft_anal(chunk, window_fcn, fft_size)

        # Apply per-bin calibration if present — mirrors what
        # _FftProcessingThread.run does on every live FFT frame.
        proc = self.mic.proc_thread
        cal = None
        if proc is not None:
            with proc._settings_lock:
                cal = proc._calibration
        if cal is not None and len(cal) == len(magnitudes_db):
            magnitudes_db = magnitudes_db + cal

        # Build the matching frequency axis.  Use the same self.freq array
        # the live path uses so downstream peak detection sees identical bins.
        freqs = list(self.freq) if self.freq is not None else (
            [i * float(sample_rate) / fft_size for i in range(fft_size // 2 + 1)]
        )

        import datetime as _dt
        self.captured_taps.append((list(magnitudes_db), freqs, _dt.datetime.now()))

        peak_db = float(np.max(magnitudes_db))
        # DIAG: spectrum fingerprint — sum of first 100 magnitude bins
        _diag_spec_hash = float(np.sum(magnitudes_db[:100]))
        _diag_sample_hash = float(np.sum(samples[:16].astype(np.float64))) if len(samples) >= 16 else 0.0
        from utilities.logging import TAP_DEBUG as _td
        _td("guitar_gated_capture",
            f"FINISHED | newCount={len(self.captured_taps)}/{self.number_of_taps} "
            f"capturedPeakMag={peak_db:.2f}dB samples={len(samples)} "
            f"specHash={_diag_spec_hash:.4f} sampleHash={_diag_sample_hash:.6f}"
        )

        self.current_tap_count = len(self.captured_taps)
        self.tap_progress = min(
            1.0, float(self.current_tap_count) / max(self.number_of_taps, 1)
        )
        self.tapCountChanged.emit(self.current_tap_count, self.number_of_taps)

        if self.current_tap_count < self.number_of_taps:
            self._set_status_message(
                f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again..."
            )
            cooldown_ms = int(self.tap_cooldown * 1000)
            QtCore.QTimer.singleShot(cooldown_ms, self._do_reenable_guitar)
        else:
            self._set_status_message("All taps captured. Processing...")
            self.capture_timer_active = False
            QtCore.QTimer.singleShot(int(self.capture_window * 1000), self._finish_capture)

    @Slot()
    def _do_start_flc(self) -> None:
        """Main-thread slot: arm detection for the FLC tap phase.

        Invoked via QTimer.singleShot from _handle_cross_gated_progress,
        so this always runs on the main thread.

        Mirrors Swift handleCrossGatedProgress() FLC-transition closure:
          self.isAboveThreshold = fftAnalyzer.inputLevelDB > fallingThreshold
          self.isDetecting = true
          self.materialTapPhase = .capturingFlc
        Does NOT reset analyzerStartTime — mirrors Swift reEnableDetectionForNextPlateTap
        doc comment: resetting would restart warm-up and destabilise isAboveThreshold.
        """
        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP
        # Guard: if the sequence was cancelled or reset while the cooldown timer was
        # running, the phase will no longer be WAITING_FOR_FLC_TAP.  Do not re-arm
        # detection — mirrors Swift's captureTimer?.invalidate() cancellation idiom.
        if self.material_tap_phase != _MTP.WAITING_FOR_FLC_TAP:
            return
        # Use instantaneous RMS level — mirrors Swift fftAnalyzer.inputLevelDB.
        level = self._current_input_level_db
        falling = self.tap_detection_threshold - self.hysteresis_margin
        self.is_above_threshold = level > falling
        self.is_detecting = True
        self.tap_detected = False
        self._set_material_tap_phase(_MTP.CAPTURING_FLC)
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

    # ------------------------------------------------------------------ #
    # finish_gated_fft_capture
    # Mirrors Swift TapToneAnalyzer.finishGatedFFTCapture(samples:sampleRate:phase:)
    # ------------------------------------------------------------------ #

    def finish_gated_fft_capture(self, samples, sample_rate: float, phase) -> None:
        """Process a captured PCM window and route to the appropriate phase handler.

        Dispatches first by phase: guitar-mode captures (phase is None) go
        through finish_guitar_gated_capture; plate/brace captures continue
        below to the original Hann-windowed gated-FFT pipeline.

        Runs computeGatedFFT to produce a magnitude spectrum, then calls
        findDominantPeak to identify the strongest material resonance.

        Rejects the capture and requests a re-tap if:
          - The FFT returns an empty spectrum.
          - No peak is found in the search window.
          - The dominant peak is below tapDetectionThreshold.

        Mirrors Swift TapToneAnalyzer.finishGatedFFTCapture(samples:sampleRate:phase:).

        Args:
            samples:     Captured PCM samples (pre-roll + gate window), float32.
            sample_rate: Hardware sample rate in Hz.
            phase:       MaterialTapPhase active at capture time.
        """
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        # Guitar-mode capture (phase is None) — uses a different FFT pipeline
        # (rectangular window, full fft_size, no HPS / dominant-peak gate).
        if phase is None:
            self.finish_guitar_gated_capture(samples, sample_rate)
            return

        self._dump_capture_wav(samples, sample_rate, phase.value.replace(" ", "_"))

        # Compute Hann-windowed gated FFT.
        magnitudes, frequencies = self.mic.proc_thread.compute_gated_fft(samples, sample_rate)

        if not magnitudes:
            gt_log("⚠️ Gated FFT returned empty spectrum — tap again")
            self._set_status_message("No signal detected — tap again")
            self.re_enable_detection_for_next_plate_tap()
            return

        # Determine the frequency search window for this phase.
        # Mirrors Swift finishGatedFFTCapture switch over mType / phase.
        meas_type = _tds.measurement_type()
        if meas_type == _MT.BRACE:
            hps_min_hz = 100.0
            hps_max_hz = 1200.0
        elif meas_type == _MT.PLATE:
            if phase == _MTP.CAPTURING_LONGITUDINAL:
                # fL: longitudinal bending mode of a free rectangular plate blank.
                # Gore course data: ~43-77 Hz across tonewoods (Gore & Gilet Vol.1 §4.5).
                # Note: fL and fLC ranges overlap (~43-77 Hz vs ~25-76 Hz); the tap
                # orientation physically selects the mode — fL is excited by a tap near
                # the centre of the long edge, not a corner tap.
                # Upper bound 100 Hz covers outliers; lower bound 20 Hz excludes DC/rumble.
                hps_min_hz = 20.0
                hps_max_hz = 100.0
            elif phase == _MTP.CAPTURING_CROSS:
                # fC: cross-grain bending mode of a free rectangular plate blank.
                # Gore course data: ~57-194 Hz across tonewoods (Gore & Gilet Vol.1 §4.5).
                # Upper bound 220 Hz covers outliers; lower bound 40 Hz excludes fL/fLC.
                hps_min_hz = 40.0
                hps_max_hz = 220.0
            elif phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP):
                # fLC: torsional (twist) mode of a free rectangular plate blank.
                # Gore course data: ~25-76 Hz across tonewoods (Gore & Gilet Vol.1 §4.5).
                # fLC is weak and overlaps fL in frequency; it is distinguished by tap
                # placement (corner tap) and the characteristic low-amplitude ring-out.
                # Upper bound 100 Hz covers outliers; lower bound 15 Hz is near the limit
                # of typical measurement microphones.
                hps_min_hz = 15.0
                hps_max_hz = 100.0
            else:
                hps_min_hz = 15.0
                hps_max_hz = 220.0
        else:
            hps_min_hz = 20.0
            hps_max_hz = 2000.0

        # For plate fL and fLC phases prefer the lowest significant peak.
        # For plate fC the strongest peak is correct — the cross-grain tap excites
        # fC as the dominant resonance; preferring the lowest would risk
        # re-selecting fL if it appears in the spectrum.
        # For brace mode, always use the strongest peak — there is only one
        # resonance of interest and it should dominate the spectrum.
        # Mirrors Swift: let preferLowest = mType != .brace && (phase == …)
        prefer_lowest = (
            meas_type != _MT.BRACE
            and (
                phase == _MTP.CAPTURING_LONGITUDINAL
                or phase == _MTP.CAPTURING_FLC
                or phase == _MTP.WAITING_FOR_FLC_TAP
            )
        )

        dominant_peak = self.find_dominant_peak(
            magnitudes=magnitudes,
            frequencies=frequencies,
            min_hz=hps_min_hz,
            max_hz=hps_max_hz,
            prefer_lowest_significant=prefer_lowest,
        )

        if dominant_peak is None:
            gt_log("⚠️ Gated FFT: no peak found — tap again")
            self._set_status_message("No resonance detected — tap again")
            self.re_enable_detection_for_next_plate_tap()
            return

        # Reject captures where the dominant peak is below the tap detection threshold.
        #
        # Exceptions (skip the magnitude gate):
        #   - fLC (torsional mode): inherently 20–30 dB weaker than fL/fC.
        #   - Brace mode: braces are small and stiff — their tap resonance is
        #     inherently much quieter than a guitar top or plate, producing
        #     dominant peaks that routinely fall below the plate/guitar threshold.
        # In both cases the rising-edge tap trigger already proved a real strike
        # occurred, so there is no benefit in applying an additional spectral gate.
        is_flc_phase = phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP)
        is_brace_mode = _tds.measurement_type() == _MT.BRACE
        if not is_flc_phase and not is_brace_mode and dominant_peak.magnitude < self.tap_detection_threshold:
            gt_log(
                f"⚠️ Gated FFT: dominant peak {dominant_peak.frequency:.1f} Hz @ "
                f"{dominant_peak.magnitude:.1f} dB is below tap detection threshold "
                f"({self.tap_detection_threshold:.0f} dB) — tap again"
            )
            self._set_status_message("Signal too quiet — tap harder")
            self.re_enable_detection_for_next_plate_tap()
            return

        gt_log(
            f"📊 Gated FFT complete: {len(magnitudes)} bins, "
            f"dominant peak {dominant_peak.frequency:.1f} Hz @ "
            f"{dominant_peak.magnitude:.1f} dB, phase {phase}"
        )

        # Store spectrum and advance tap counter.
        # Mirrors Swift: materialCapturedTaps.append(...); currentTapCount += 1; tapProgress = ...
        import datetime as _dt
        self.captured_taps.append((magnitudes, frequencies, _dt.datetime.now()))
        self.current_tap_count = len(self.captured_taps)
        self.tap_progress = min(1.0, float(self.current_tap_count) / float(self.total_plate_taps))

        # Mirrors Swift: currentTapCount (@Published) → drives tap progress label in view.
        # Swift SpectrumCapture.swift:292 increments currentTapCount and the @Published
        # property notifies the view automatically. Python emits tapCountChanged explicitly.
        self.tapCountChanged.emit(self.current_tap_count, self.number_of_taps)

        # Route to the phase-specific handler.
        # Mirrors Swift switch phase { case .capturingLongitudinal: … }
        if phase == _MTP.CAPTURING_LONGITUDINAL:
            self._handle_longitudinal_gated_progress(magnitudes, frequencies, dominant_peak)
        elif phase == _MTP.CAPTURING_CROSS:
            self._handle_cross_gated_progress(magnitudes, frequencies, dominant_peak)
        elif phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP):
            self._handle_flc_gated_progress(magnitudes, frequencies, dominant_peak)
        else:
            # Covers .notStarted, .complete, .reviewingLongitudinal, .reviewingCross, .reviewingFlc
            # — mirrors Swift's combined default case.
            gt_log(f"⚠️ Unexpected gated FFT capture in phase: {phase}")

    # ------------------------------------------------------------------ #
    # find_dominant_peak
    # Mirrors Swift TapToneAnalyzer.findDominantPeak(…)
    # ------------------------------------------------------------------ #

    def find_dominant_peak(
        self,
        magnitudes: "list[float]",
        frequencies: "list[float]",
        min_hz: float = 20.0,
        max_hz: float = 2000.0,
        prefer_lowest_significant: bool = False,
    ) -> "object | None":
        """Select the dominant resonance peak from a gated-FFT spectrum.

        Two-stage algorithm:
          Step 1 — Candidate collection: find all local maxima above the median
                   noise floor.  Compute Q and HPS score for each.
          Step 2 — Selection:
                   - Filter candidates with Q < 3 (impact thuds / broadband noise).
                   - If prefer_lowest_significant: pick the lowest-frequency candidate
                     within 15 dB of the strongest.
                   - Otherwise: strongest wins unless a lower-frequency candidate is
                     within 6 dB and has a comparable HPS score (within one order of
                     magnitude).

        Mirrors Swift TapToneAnalyzer.findDominantPeak(magnitudes:frequencies:…).

        Args:
            magnitudes:                dBFS magnitude spectrum from the gated FFT.
            frequencies:               Frequency axis matching magnitudes, in Hz.
            min_hz:                    Lower search bound in Hz.
            max_hz:                    Upper search bound in Hz.
            prefer_lowest_significant: When True, pick the lowest-frequency candidate
                                       within 15 dB of the peak.

        Returns:
            ResonantPeak or None if no candidates are found.
        """
        from typing import NamedTuple

        from models.resonant_peak import ResonantPeak

        class _Candidate(NamedTuple):
            index: int
            magnitude: float
            hps_score: float
            q_factor: float

        n = len(magnitudes)
        if n != len(frequencies) or n <= 10:
            return None

        start_idx = next((i for i, f in enumerate(frequencies) if f >= min_hz), 0)
        end_idx   = next((i for i, f in enumerate(frequencies) if f > max_hz), n)
        if start_idx >= end_idx:
            return None

        window_size = 5  # mirrors Swift windowSize = 5

        # Adaptive noise floor — median of the search range.
        # Mirrors Swift: sortedMags[sortedMags.count / 2]
        search_mags = magnitudes[start_idx:end_idx]
        sorted_mags = sorted(search_mags)
        noise_floor = sorted_mags[len(sorted_mags) // 2]

        # Pre-compute linear amplitudes for HPS scoring.
        # Mirrors Swift: let linear = magnitudes.map { pow(10.0, max($0, -160) / 20.0) }
        linear = [10.0 ** (max(m, -160.0) / 20.0) for m in magnitudes]

        candidates = []  # (index, magnitude, hps_score, q_factor)

        scan_start = start_idx + window_size
        scan_end   = end_idx   - window_size

        for i in range(scan_start, scan_end):
            mag = magnitudes[i]
            if mag <= noise_floor:
                continue

            # Local maximum check — mirrors Swift ±windowSize loop.
            # scan_start/scan_end guarantee i ± window_size stays within [0, n).
            is_local = True
            for offset in range(-window_size, window_size + 1):
                if offset == 0:
                    continue
                if magnitudes[i + offset] >= mag:
                    is_local = False
                    break
            if not is_local:
                continue

            # HPS score: linear[i] × linear[2i] × linear[3i] (order 3).
            # Mirrors Swift: for k in 2...3 { harmIdx = i*k; hpsScore *= linear[harmIdx] }
            hps_score = linear[i]
            for k in (2, 3):
                harm_idx = i * k
                if harm_idx < n:
                    hps_score *= linear[harm_idx]

            # Q factor — key discriminant between resonances (high-Q) and impact thuds (low-Q).
            q, _ = self._calculate_q_factor(magnitudes, frequencies, i, mag)

            candidates.append(_Candidate(index=i, magnitude=mag, hps_score=hps_score, q_factor=q))

        if not candidates:
            return None

        # Q filtering — mirrors Swift: let highQCandidates = candidates.filter { $0.qFactor >= minQ }
        min_q = 3.0
        high_q = [c for c in candidates if c.q_factor >= min_q]
        if len(high_q) < len(candidates):
            rejected = [c for c in candidates if c.q_factor < min_q]
            rej_str = ", ".join(
                f"{frequencies[c.index]:.0f} Hz (Q={c.q_factor:.1f})" for c in rejected
            )
            gt_log(f"🔇 Q-filtered out low-Q peaks: {rej_str}")
        pool = high_q if high_q else candidates

        by_magnitude = sorted(pool, key=lambda c: c.magnitude, reverse=True)
        strongest = by_magnitude[0]

        if prefer_lowest_significant:
            # Mirrors Swift: thresholdDB = strongest.magnitude - 15; pick lowest-index significant.
            threshold_db = strongest.magnitude - 15.0
            significant = [c for c in pool if c.magnitude >= threshold_db]
            best = min(significant, key=lambda c: c.index)
        else:
            # Default: strongest wins unless a lower-frequency candidate is within 6 dB
            # and has a comparable HPS score (within one order of magnitude).
            # Mirrors Swift: for candidate in byMagnitude.dropFirst() { … }
            current = strongest
            for candidate in by_magnitude[1:]:
                if candidate.index >= current.index:
                    continue  # not lower frequency
                mag_diff = current.magnitude - candidate.magnitude
                if mag_diff < 6.0 and candidate.hps_score >= current.hps_score * 0.1:
                    current = candidate
            best = current

        best_idx = best.index
        best_hps = best.hps_score
        best_q   = best.q_factor

        # Refine with parabolic interpolation — mirrors Swift parabolicInterpolate call.
        freq, mag = self._parabolic_interpolate(magnitudes, frequencies, best_idx)
        quality, bandwidth = self._calculate_q_factor(magnitudes, frequencies, best_idx, mag)

        # Pitch info — mirrors Swift pitchCalculator calls in findDominantPeak.
        pitch_note      = self.pitch_calculator.note(float(freq))
        pitch_cents     = self.pitch_calculator.cents(float(freq))
        pitch_frequency = self.pitch_calculator.freq0(float(freq))

        gt_log(
            f"🎯 Dominant peak: {freq:.1f} Hz @ {mag:.1f} dB "
            f"(Q: {best_q:.1f}, HPS score: {best_hps:.3e})"
        )
        return ResonantPeak(
            frequency=freq, magnitude=mag,
            quality=quality, bandwidth=bandwidth,
            pitch_note=pitch_note, pitch_cents=pitch_cents,
            pitch_frequency=pitch_frequency,
        )

    # ------------------------------------------------------------------ #
    # _handle_longitudinal_gated_progress
    # Mirrors Swift handleLongitudinalGatedProgress(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _handle_longitudinal_gated_progress(self, magnitudes, frequencies, dominant_peak) -> None:
        """Handle a longitudinal gated-FFT tap result.

        Mirrors Swift TapToneAnalyzer.handleLongitudinalGatedProgress(…).
        """
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        captured = len(self.captured_taps)
        total = self.number_of_taps
        gt_log(f"📊 Gated LONGITUDINAL tap {captured}/{total}: {dominant_peak.frequency:.1f} Hz")

        if captured < total:
            self._set_status_message(f"L tap {captured}/{total} captured. Tap again...")
            self.re_enable_detection_for_next_plate_tap()
            return

        # Average all captured spectra — mirrors Swift averageSpectra(from: materialCapturedTaps).
        avg_mags, avg_freqs = self.average_spectra(from_taps=self.captured_taps)
        self.longitudinal_spectrum = (avg_mags, avg_freqs)

        # Build the full peak list for display/manual override.
        self.longitudinal_peaks = self._build_all_peaks(avg_mags, avg_freqs, dominant_peak)
        self.auto_selected_longitudinal_peak_id = dominant_peak.id
        self.selected_longitudinal_peak = (
            next((p for p in self.longitudinal_peaks if p.id == dominant_peak.id), dominant_peak)
        )
        gt_log(f"🔵 Auto-selected longitudinal peak: {dominant_peak.frequency} Hz")

        self.current_peaks = self.longitudinal_peaks
        # Only the identified (auto-selected) peak is selected — others are informational.
        # Mirrors Swift: selectedPeakIDs = Set([dominantPeak.id])
        self.selected_peak_ids = {dominant_peak.id}
        self.captured_taps.clear()

        # Update displayed spectrum — mirrors Swift setFrozenSpectrum (empty for plate transitions).
        import numpy as _np
        self.set_frozen_spectrum(_np.array(avg_freqs), _np.array(avg_mags))

        is_brace = (_tds.measurement_type() == _MT.BRACE)
        if is_brace:
            # Brace: only longitudinal tap — measurement complete.
            sel_peak = next(
                (p for p in self.longitudinal_peaks if p.id == dominant_peak.id),
                dominant_peak
            )
            self.current_peaks = [sel_peak]
            self.set_frozen_spectrum(_np.array([]), _np.array([]))
            self._set_material_tap_phase(_MTP.COMPLETE)
            self.set_measurement_complete(True)
            # Mirrors Swift isMeasurementComplete.didSet: clear warning on successful new tap.
            if self.show_loaded_settings_warning:
                self.show_loaded_settings_warning = False
                self.showLoadedSettingsWarningChanged.emit(False)
            self.tap_progress = 1.0
            self._set_status_message("Complete - check Results")
            gt_log(f"✅ Brace measurement complete: fL={dominant_peak.frequency} Hz")
            # Emit final peaks.
            self._emit_peaks_array(self.current_peaks)
            # Emit the longitudinal spectrum for display — mirrors Swift's @Published
            # longitudinalSpectrum being set, which causes TapToneAnalysisView.materialSpectra
            # (a computed property) to return [("Longitudinal (L)", blue, ...)] and
            # SpectrumView to render the blue overlay waveform.
            l_mags, l_freqs = self.longitudinal_spectrum
            self.set_material_spectra([
                ("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)),
            ])
            self.plateAnalysisComplete.emit(dominant_peak.frequency, 0.0, 0.0)
        elif self.mic.is_playing_file:
            # File playback: auto-advance L → C without pausing at the review state.
            # The file audio flows continuously, so pausing detection would miss
            # the cross-grain taps that follow immediately.
            self._emit_peaks_array(self.current_peaks)
            self._set_material_tap_phase(_MTP.CAPTURING_CROSS)
            self.set_frozen_spectrum(_np.array([]), _np.array([]))
            self.is_above_threshold = False
            self.is_detecting = True
            self.tap_detected = False
            self._set_status_message("File: L complete, capturing C...")
            gt_log("📂 File playback: auto-advancing L → C")
            l_mags, l_freqs = self.longitudinal_spectrum
            self.set_material_spectra([
                ("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)),
            ])
        else:
            # Plate: pause at review state — user must press Accept to continue or Redo to re-tap.
            # Emit longitudinal peaks now — mirrors Swift's single currentPeaks assignment.
            self._emit_peaks_array(self.current_peaks)
            self._set_material_tap_phase(_MTP.REVIEWING_LONGITUDINAL)
            self.is_detecting = False
            self._set_status_message(
                f"fL: {dominant_peak.frequency:.1f} Hz \u2014 Accept to continue or Redo to re-tap"
            )
            # Show longitudinal overlay — mirrors Swift's @Published longitudinalSpectrum
            # causing materialSpectra to return [("Longitudinal (L)", .blue, ...)] which
            # SpectrumView renders instead of the primary curve (exclusive: no live curve shown).
            l_mags, l_freqs = self.longitudinal_spectrum
            self.set_material_spectra([
                ("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)),
            ])

        # Notify spectrum update (no peaksChanged here — each branch above emits exactly once).
        self.spectrumUpdated.emit(
            self.frozen_frequencies if len(self.frozen_frequencies) else self.freq,
            self.frozen_magnitudes  if len(self.frozen_magnitudes)  else self.freq * 0,
        )

    # ------------------------------------------------------------------ #
    # _resolved_plate_peaks
    # Mirrors Swift func resolvedPlatePeaks(…)
    # ------------------------------------------------------------------ #

    def _resolved_plate_peaks(
        self,
        include_cross: bool = True,
        cross_override=None,
        include_flc: bool = False,
        flc_override=None,
    ) -> "list":
        """Build the ordered peak list from whichever phase peaks are available.

        Mirrors Swift TapToneAnalyzer.resolvedPlatePeaks(…).
        """
        sel = []
        if self.selected_longitudinal_peak:
            sel.append(self.selected_longitudinal_peak)
        elif self.longitudinal_peaks:
            sel.append(self.longitudinal_peaks[0])

        if include_cross:
            cross = cross_override or self.selected_cross_peak or (self.cross_peaks[0] if self.cross_peaks else None)
            if cross:
                sel.append(cross)

        if include_flc:
            flc = flc_override or self.selected_flc_peak or (self.flc_peaks[0] if self.flc_peaks else None)
            if flc:
                sel.append(flc)

        return sel

    # ------------------------------------------------------------------ #
    # _handle_cross_gated_progress
    # Mirrors Swift handleCrossGatedProgress(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _handle_cross_gated_progress(self, magnitudes, frequencies, dominant_peak) -> None:
        """Handle a cross-grain gated-FFT tap result.

        Mirrors Swift TapToneAnalyzer.handleCrossGatedProgress(…).
        """
        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP

        captured = len(self.captured_taps)
        total = self.number_of_taps
        gt_log(f"📊 Gated CROSS-GRAIN tap {captured}/{total}: {dominant_peak.frequency:.1f} Hz")

        if captured < total:
            self._set_status_message(f"C tap {captured}/{total} captured. Tap again...")
            self.re_enable_detection_for_next_plate_tap()
            return

        avg_mags, avg_freqs = self.average_spectra(from_taps=self.captured_taps)
        self.cross_spectrum = (avg_mags, avg_freqs)
        self.cross_peaks = self._build_all_peaks(avg_mags, avg_freqs, dominant_peak)
        self.auto_selected_cross_peak_id = dominant_peak.id
        self.selected_cross_peak = (
            next((p for p in self.cross_peaks if p.id == dominant_peak.id), dominant_peak)
        )
        gt_log(f"🟠 Auto-selected cross-grain peak: {dominant_peak.frequency} Hz")
        self.captured_taps.clear()

        self.current_peaks = self.combine_plate_peaks()
        # Only the identified (auto-selected) L and C peaks are selected — others are informational.
        # Mirrors Swift: selectedPeakIDs = Set([autoSelectedLongitudinalPeakID, autoSelectedCrossPeakID].compactMap { $0 })
        self.selected_peak_ids = {
            pid for pid in (self.auto_selected_longitudinal_peak_id, self.auto_selected_cross_peak_id)
            if pid is not None
        }
        # Emit peaks BEFORE the phase transition so the view's peaks model has
        # up-to-date data when plateStatusChanged triggers refresh_annotations().
        self._emit_peaks_array(self.current_peaks)

        if self.mic.is_playing_file:
            # File playback: auto-advance past the review state.
            from models.tap_display_settings import TapDisplaySettings as _tds
            if _tds.measure_flc():
                # Skip reviewingCross AND tapCooldown — go straight to capturingFlc.
                # The cooldown exists for user repositioning; irrelevant for file audio.
                self._set_material_tap_phase(_MTP.CAPTURING_FLC)
                self.set_frozen_spectrum(_np.array([]), _np.array([]))
                self.is_above_threshold = False
                self.is_detecting = True
                self.tap_detected = False
                self._set_status_message("File: C complete, capturing FLC...")
                gt_log("📂 File playback: auto-advancing C → FLC")
            else:
                # No FLC: measurement complete. Reuse existing finalise helper.
                self._finalise_plate_no_flc()
                gt_log("📂 File playback: C complete, measurement done (no FLC)")
        else:
            # Pause at review state — user must press Accept to continue or Redo to re-tap.
            self.set_frozen_spectrum(_np.array(avg_freqs), _np.array(avg_mags))
            self._set_material_tap_phase(_MTP.REVIEWING_CROSS)
            self.is_detecting = False
            self._set_status_message(
                f"fC: {dominant_peak.frequency:.1f} Hz \u2014 Accept to continue or Redo to re-tap"
            )

        # Show longitudinal + cross overlays — mirrors Swift's @Published crossSpectrum
        # causing materialSpectra to return L + C series (SpectrumView replaces primary curve).
        spectra = []
        if self.longitudinal_spectrum:
            l_mags, l_freqs = self.longitudinal_spectrum
            spectra.append(("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)))
        if self.cross_spectrum:
            c_mags, c_freqs = self.cross_spectrum
            spectra.append(("Cross-grain (C)", (255, 149, 0), list(c_freqs), list(c_mags)))
        self.set_material_spectra(spectra)

    # ------------------------------------------------------------------ #
    # _handle_flc_gated_progress
    # Mirrors Swift handleFlcGatedProgress(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _handle_flc_gated_progress(self, magnitudes, frequencies, dominant_peak) -> None:
        """Handle an FLC (shear/diagonal) gated-FFT tap result.

        Mirrors Swift TapToneAnalyzer.handleFlcGatedProgress(…).
        """
        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP

        captured = len(self.captured_taps)
        total = self.number_of_taps
        gt_log(f"📊 Gated FLC tap {captured}/{total}: {dominant_peak.frequency:.1f} Hz")

        if captured < total:
            self._set_status_message(f"FLC tap {captured}/{total} captured. Tap again...")
            self.re_enable_detection_for_next_plate_tap()
            return

        avg_mags, avg_freqs = self.average_spectra(from_taps=self.captured_taps)
        self.flc_spectrum = (avg_mags, avg_freqs)
        self.flc_peaks = self._build_all_peaks(avg_mags, avg_freqs, dominant_peak)
        self.auto_selected_flc_peak_id = dominant_peak.id
        self.selected_flc_peak = (
            next((p for p in self.flc_peaks if p.id == dominant_peak.id), dominant_peak)
        )
        gt_log(f"🟣 Auto-selected FLC peak: {dominant_peak.frequency} Hz")
        self.captured_taps.clear()

        sel = self._resolved_plate_peaks(
            include_cross=True,
            include_flc=True,
            flc_override=self.selected_flc_peak or dominant_peak,
        )
        self.current_peaks = sel
        self.selected_peak_ids = {p.id for p in sel}
        # Emit peaks BEFORE the phase transition so the view's peaks model has
        # up-to-date data when plateStatusChanged triggers refresh_annotations().
        self._emit_peaks_array(self.current_peaks)

        if self.mic.is_playing_file:
            # File playback: auto-complete without pausing at the review state.
            # Reuse existing finalise helper which resolves peaks, emits signals,
            # sets .complete, and updates spectra overlays.
            self._finalise_plate_with_flc()
            gt_log("📂 File playback: FLC complete, measurement done")
        else:
            # Pause at review state — user must press Accept to complete or Redo to re-tap.
            self.set_frozen_spectrum(_np.array(avg_freqs), _np.array(avg_mags))
            self._set_material_tap_phase(_MTP.REVIEWING_FLC)
            self.is_detecting = False
            self._set_status_message(
                f"fLC: {dominant_peak.frequency:.1f} Hz \u2014 Accept to complete or Redo to re-tap"
            )
        # Show longitudinal + cross + FLC overlays — mirrors Swift's @Published flcSpectrum
        # causing materialSpectra to return L + C + FLC series (replaces primary curve).
        spectra = []
        if self.longitudinal_spectrum:
            l_mags, l_freqs = self.longitudinal_spectrum
            spectra.append(("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)))
        if self.cross_spectrum:
            c_mags, c_freqs = self.cross_spectrum
            spectra.append(("Cross-grain (C)", (255, 149, 0), list(c_freqs), list(c_mags)))
        f_mags, f_freqs = self.flc_spectrum
        spectra.append(("FLC", (175, 82, 222), list(f_freqs), list(f_mags)))
        self.set_material_spectra(spectra)
        # Mirrors Swift handleFlcGatedProgress terminal log:
        # gtLog("📊 FLC review: L=… C=… FLC=… Hz")
        gt_log(
            f"📊 FLC review: "
            f"L={self.longitudinal_peaks[0].frequency if self.longitudinal_peaks else 0} "
            f"C={self.cross_peaks[0].frequency if self.cross_peaks else 0} "
            f"FLC={dominant_peak.frequency} Hz"
        )

    # ------------------------------------------------------------------ #
    # _build_all_peaks
    # Mirrors Swift func buildAllPeaks(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _build_all_peaks(self, magnitudes, frequencies, dominant_peak) -> "list":
        """Build a display-ready peak list ensuring dominantPeak is always present.

        Runs findPeaks with no range restrictions, then replaces or prepends
        dominantPeak so its UUID identity is preserved for ID-based lookups.

        For plate/brace, uses the median of the full spectrum as an adaptive
        noise-floor threshold instead of the guitar-mode peak_min_threshold.
        Mirrors Swift TapToneAnalyzer.buildAllPeaks(magnitudes:frequencies:dominantPeak:).
        """
        sorted_mags = sorted(magnitudes)
        median_threshold = sorted_mags[len(sorted_mags) // 2]
        peaks = self.find_peaks(magnitudes, frequencies, peak_min_override=median_threshold)
        prox = self.PEAK_PROXIMITY_HZ

        idx = next(
            (i for i, p in enumerate(peaks) if abs(p.frequency - dominant_peak.frequency) < prox),
            None,
        )
        if idx is not None:
            peaks[idx] = dominant_peak
        else:
            peaks.insert(0, dominant_peak)
        return peaks

    # ------------------------------------------------------------------ #
    # average_spectra
    # Mirrors Swift func averageSpectra(from:)
    # ------------------------------------------------------------------ #

    def average_spectra(self, from_taps: "list[tuple]") -> "tuple[list[float], list[float]]":
        """Average multiple tap spectra using frequency-domain power averaging.

        Mirrors Swift TapToneAnalyzer.averageSpectra(from:).

        Each entry in from_taps is a (magnitudes, frequencies, captureTime) tuple
        as stored by finish_gated_fft_capture.

        Args:
            from_taps: List of (magnitudes, frequencies, captureTime) tuples.

        Returns:
            (magnitudes, frequencies) of the averaged spectrum.
            Returns ([], []) if from_taps is empty, returns the single tap's
            data unchanged if len == 1, returns first tap's data if lengths differ.
        """
        import math

        if not from_taps:
            return [], []
        if len(from_taps) == 1:
            return list(from_taps[0][0]), list(from_taps[0][1])

        mags0, freqs0, _ = from_taps[0]
        n_bins = len(mags0)
        if not all(len(t[0]) == n_bins for t in from_taps):
            gt_log("⚠️ Warning: Spectrum lengths don't match, using first tap only")
            return list(mags0), list(freqs0)

        power_sum = [0.0] * n_bins
        for mags, _, _ in from_taps:
            for b in range(n_bins):
                power_sum[b] += 10.0 ** (mags[b] / 10.0)

        n_taps = len(from_taps)
        avg = [10.0 * math.log10(power_sum[b] / n_taps) for b in range(n_bins)]
        gt_log(f"📊 Averaged {n_taps} spectra: {n_bins} bins each")
        return avg, list(freqs0)

    # ------------------------------------------------------------------ #
    # finish_capture
    # Mirrors Swift TapToneAnalyzer.finishCapture()
    # ------------------------------------------------------------------ #

    def finish_capture(self) -> None:
        """Invalidate the guitar-mode capture timer after the ring-out window closes.

        Mirrors Swift TapToneAnalyzer.finishCapture(), which calls
        captureTimer?.invalidate() and sets captureTimer = nil.

        In Python, the capture timer is a QTimer.singleShot closure that holds
        no persistent reference, so there is no timer object to invalidate.
        This method exists to maintain structural parity with Swift.
        """
        # No persistent captureTimer reference in Python — QTimer.singleShot
        # fires once and discards itself. Nothing to clean up.
        pass

    # ------------------------------------------------------------------ #
    # process_multiple_taps
    # Mirrors Swift TapToneAnalyzer.processMultipleTaps()
    # ------------------------------------------------------------------ #

    def process_multiple_taps(self) -> None:
        """Average all captured guitar taps and freeze the result.

        Called after all required taps have been captured (currentTapCount >= numberOfTaps).
        Mirrors Swift TapToneAnalyzer.processMultipleTaps().
        """
        import numpy as _np

        if not self.captured_taps:
            return

        gt_log(f"🔬 Processing {len(self.captured_taps)} taps for averaging...")

        # captured_taps stores (magnitudes, frequencies, captureTime) tuples —
        # mirrors Swift capturedTaps which uses the same named-tuple structure.
        # Pass directly to average_spectra; no wrapping needed.
        tap_tuples = self.captured_taps
        avg_mags, avg_freqs = self.average_spectra(from_taps=tap_tuples)
        avg_db = _np.array(avg_mags)

        self.set_frozen_spectrum(_np.array(avg_freqs), avg_db)
        # Set is_measurement_complete early (mirrors Swift isMeasurementComplete = true
        # at the same point) but defer the signal emit until after peaks, modes, and
        # selected IDs are fully populated — mirrors loadMeasurement() which also sets
        # the flag early and emits last. Swift @Published batches all state in one render
        # cycle; Python signals fire immediately, so the emit must come after all state
        # is ready to avoid the view seeing an incomplete snapshot.
        self.is_measurement_complete = True
        # Mirrors Swift isMeasurementComplete.didSet: clear warning on successful new tap.
        if self.show_loaded_settings_warning:
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)
        gt_log(f"📸 Guitar spectrum captured from {len(self.captured_taps)} averaged taps")

        peaks = self.find_peaks(avg_mags, avg_freqs)

        # Mirrors Swift processMultipleTaps() property-assignment sequence (lines 817-824):
        #   currentPeaks = peaks
        #   selectedPeakIDs = guitarModeSelectedPeakIDs(from: peaks)
        #   userHasModifiedPeakSelection = false
        #   loadedMeasurementPeaks = nil
        #   selectedPeakFrequencies = []
        #   identifiedModes = …
        self.current_peaks = peaks
        self.selected_peak_ids = self.guitar_mode_selected_peak_ids(peaks)
        self.user_has_modified_peak_selection = False
        self.loaded_measurement_peaks = None
        self.selected_peak_frequencies = []

        from models.tap_display_settings import TapDisplaySettings as _tds_sc

        from .guitar_mode import GuitarMode as _GM
        _mode_map = _GM.classify_all(peaks, _tds_sc.guitar_type())
        self.identified_modes = [
            {"peak": p, "mode": _mode_map.get(p.id, _GM.UNKNOWN)}
            for p in peaks
        ]

        tap_count = len(self.captured_taps)
        self._set_status_message(
            f"Analysis complete! {len(peaks)} peaks identified "
            f"(from {tap_count} averaged taps)."
        )
        self.tap_progress = 1.0
        gt_log(f"✅ Found {len(peaks)} peaks in averaged spectrum from {tap_count} taps")

        # ── Build per-tap entries for multi-tap comparison ─────────────────
        # Mirrors Swift processMultipleTaps() per-tap block.
        # Only built when there are 2+ taps (single-tap has nothing to compare).
        if tap_count > 1:
            import uuid as _uuid2

            from .spectrum_snapshot import SpectrumSnapshot
            from .tap_display_settings import TapDisplaySettings as _tds2
            from .tap_tone_measurement import TapEntry

            _mt_str2 = _tds2.measurement_type().value
            _gt_str2 = _tds2.guitar_type().value
            _show_unk2 = _tds2.show_unknown_modes()
            _min_f2 = _tds2.min_frequency()
            _max_f2 = _tds2.max_frequency()
            _min_db2 = _tds2.min_magnitude()

            tap_entries_built = []
            for idx, tap_mags in enumerate(tap_tuples):
                t_mags, t_freqs, _ = tap_mags
                t_peaks = self.find_peaks(t_mags, t_freqs)
                t_sel_ids = self.guitar_mode_selected_peak_ids(t_peaks)
                snap = SpectrumSnapshot(
                    frequencies=list(t_freqs),
                    magnitudes=list(t_mags),
                    min_freq=_min_f2,
                    max_freq=_max_f2,
                    min_db=_min_db2,
                    max_db=0.0,
                    is_logarithmic=False,
                    show_unknown_modes=_show_unk2,
                    guitar_type=_gt_str2,
                    measurement_type=_mt_str2,
                    max_peaks=self.max_peaks,
                )
                tap_entries_built.append(TapEntry(
                    id=str(_uuid2.uuid4()),
                    tap_index=idx + 1,
                    snapshot=snap,
                    peaks=t_peaks,
                    selected_peak_ids=list(t_sel_ids),
                ))
            self.tap_entries = tap_entries_built
            gt_log(f"📋 Built {len(tap_entries_built)} tap entries for multi-tap comparison")
        else:
            self.tap_entries = []

        # Emit measurementComplete before peaksChanged so that the view's
        # _is_measurement_complete flag is True when _on_peaks_changed_results runs.
        # This is required for the selection guard in _on_peaks_changed_results to
        # propagate selected_peak_frequencies, enabling peak annotations to appear.
        # tap_entries is already fully built above, so the Taps button check works too.
        self.measurementComplete.emit(True)

        # Now emit peaksChanged with _is_measurement_complete already True in the view.
        self.peaksChanged.emit(peaks)

        # Do NOT clear captured_taps here — mirrors Swift processMultipleTaps() which
        # leaves capturedTaps intact until resetForNewSequence()/reset() clears them.
        # tap_entries now holds all per-tap data; captured_taps is only needed until reset.

    # ------------------------------------------------------------------ #
    # _emit_peaks_array — helper (no Swift equivalent)
    # ------------------------------------------------------------------ #

    def _emit_peaks_array(self, peaks: "list") -> None:
        """Emit peaksChanged with the list[ResonantPeak] — objects all the way through.

        Called after gated-FFT phase handlers update current_peaks, so the
        spectrum view can annotate the live display.

        This mirrors the store+emit block at the end of find_peaks but for
        the gated path which bypasses find_peaks for current_peaks assignment.
        """
        self.current_peaks = peaks
        self.peaksChanged.emit(peaks)  # list[ResonantPeak] — mirrors Swift currentPeaks

