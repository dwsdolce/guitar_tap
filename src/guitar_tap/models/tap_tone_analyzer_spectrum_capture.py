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

import numpy as np
import numpy.typing as npt
from PySide6 import QtCore
from PySide6.QtCore import Slot


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

        samples = chunk.tolist()
        with self._gated_lock:
            # Maintain the pre-roll ring buffer — always, even when not capturing.
            # Mirrors Swift: preRollBuffer.append(contentsOf: samples)
            self._pre_roll_buf.extend(samples)
            if len(self._pre_roll_buf) > self._pre_roll_samples:
                self._pre_roll_buf = self._pre_roll_buf[-self._pre_roll_samples:]

            if not self._gated_capture_active:
                return

            self._gated_accum.extend(samples)
            if len(self._gated_accum) < self._gated_capture_samples:
                return

            # Window is full — close capture and dispatch to main thread.
            # Mirrors Swift: gatedCaptureActive = false; DispatchQueue.main.async
            self._gated_capture_active = False
            captured = self._gated_accum[:self._gated_capture_samples]
            phase = self._gated_capture_phase
            self._gated_accum = []

        # Emit on background thread; Qt queued connection delivers on main thread.
        # gatedCaptureComplete signal is still on proc_thread as a delivery mechanism.
        if self.mic is not None and hasattr(self.mic, "proc_thread"):
            self.mic.proc_thread.gatedCaptureComplete.emit(
                np.array(captured, dtype=np.float32),
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
        if self.mic is None:
            print("⚠️ start_gated_capture called with no mic — ignoring")
            return

        rate = float(self._gated_sample_rate)
        target_samples = int(rate * self.GATED_CAPTURE_DURATION)
        window_ms = int(self.GATED_CAPTURE_DURATION * 1000)
        print(
            f"🎯 Gated FFT capture started for phase {phase} — "
            f"{target_samples}-sample window ({window_ms} ms at {int(rate)} Hz)"
        )
        with self._gated_lock:
            # Seed accumulator with pre-roll (mirrors Swift: gatedAccumBuffer = preRollBuffer).
            self._gated_accum = list(self._pre_roll_buf)
            self._gated_capture_samples = target_samples
            self._gated_capture_phase = phase
            self._gated_capture_active = True

        # Safety timeout: if the buffer still has audio after 2 s, flush it;
        # if empty, ask the user to tap again.
        # Mirrors Swift DispatchQueue.main.asyncAfter(deadline: .now() + 2.0).
        # QTimer.singleShot fires on the main thread.
        def _safety_timeout() -> None:
            with self._gated_lock:
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
                print("⚠️ Gated capture timeout with no samples — tap again")
                QtCore.QTimer.singleShot(0, self._on_safety_timeout_no_samples)

        QtCore.QTimer.singleShot(2000, _safety_timeout)

    @Slot()
    def _on_safety_timeout_no_samples(self) -> None:
        """Main-thread slot called by the safety timeout when no samples were captured.

        Invoked via QTimer.singleShot, so this always runs on the main thread.
        """
        self._set_status_message("No signal detected — tap again")
        self.re_enable_detection_for_next_plate_tap()

    @Slot()
    def _do_start_cross(self) -> None:
        """Main-thread slot: arm detection for the cross-grain tap phase.

        Invoked via QTimer.singleShot from _handle_longitudinal_gated_progress,
        so this always runs on the main thread.

        Mirrors Swift handleLongitudinalGatedProgress() cross-transition closure:
          self.isAboveThreshold = fftAnalyzer.inputLevelDB > fallingThreshold
          self.isDetecting = true
          self.materialTapPhase = .capturingCross
        Does NOT reset analyzerStartTime — mirrors Swift reEnableDetectionForNextPlateTap
        doc comment: resetting would restart warm-up and destabilise isAboveThreshold.
        """
        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP
        # Use instantaneous RMS level — mirrors Swift fftAnalyzer.inputLevelDB.
        level = self._current_input_level_db
        falling = self.tap_detection_threshold - self.hysteresis_margin
        self.is_above_threshold = level > falling
        self.is_detecting = True
        self.tap_detected = False
        self._set_material_tap_phase(_MTP.CAPTURING_CROSS)
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

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
        from models.tap_display_settings import TapDisplaySettings as _tds
        from models.measurement_type import MeasurementType as _MT
        from models.material_tap_phase import MaterialTapPhase as _MTP

        # Compute Hann-windowed gated FFT.
        magnitudes, frequencies = self.mic.proc_thread.compute_gated_fft(samples, sample_rate)

        if not magnitudes:
            print("⚠️ Gated FFT returned empty spectrum — tap again")
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
                hps_min_hz = 50.0
                hps_max_hz = 500.0
            elif phase == _MTP.CAPTURING_CROSS:
                hps_min_hz = 20.0
                hps_max_hz = 250.0
            elif phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP):
                hps_min_hz = 20.0
                hps_max_hz = 200.0
            else:
                hps_min_hz = 20.0
                hps_max_hz = 600.0
        else:
            hps_min_hz = 20.0
            hps_max_hz = 2000.0

        # For all three plate phases prefer the lowest significant peak.
        # Mirrors Swift: let preferLowest = (mType == .plate || phase == .capturingLongitudinal …)
        prefer_lowest = (
            meas_type == _MT.PLATE
            or phase == _MTP.CAPTURING_LONGITUDINAL
            or phase == _MTP.CAPTURING_CROSS
        )

        dominant_peak = self.find_dominant_peak(
            magnitudes=magnitudes,
            frequencies=frequencies,
            min_hz=hps_min_hz,
            max_hz=hps_max_hz,
            prefer_lowest_significant=prefer_lowest,
        )

        if dominant_peak is None:
            print("⚠️ Gated FFT: no peak found — tap again")
            self._set_status_message("No resonance detected — tap again")
            self.re_enable_detection_for_next_plate_tap()
            return

        # Reject captures where the dominant peak is below the tap detection threshold.
        if dominant_peak.magnitude < self.tap_detection_threshold:
            print(
                f"⚠️ Gated FFT: dominant peak {dominant_peak.frequency:.1f} Hz @ "
                f"{dominant_peak.magnitude:.1f} dB is below tap detection threshold "
                f"({self.tap_detection_threshold:.0f} dB) — tap again"
            )
            self._set_status_message("Signal too quiet — tap harder")
            self.re_enable_detection_for_next_plate_tap()
            return

        print(
            f"📊 Gated FFT complete: {len(magnitudes)} bins, "
            f"dominant peak {dominant_peak.frequency:.1f} Hz @ "
            f"{dominant_peak.magnitude:.1f} dB, phase {phase}"
        )

        # Store spectrum and advance tap counter.
        # Mirrors Swift: materialCapturedTaps.append(...); currentTapCount += 1; tapProgress = ...
        import datetime as _dt
        self.captured_taps.append((magnitudes, frequencies, _dt.datetime.now()))
        self.current_tap_count = len(self.captured_taps)
        total = self.total_plate_taps
        self.tap_progress = min(1.0, float(self.current_tap_count) / max(total, 1))

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
            print(f"⚠️ Unexpected gated FFT capture in phase: {phase}")

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
        from models.resonant_peak import ResonantPeak

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
            is_local = True
            for offset in range(-window_size, window_size + 1):
                if offset == 0:
                    continue
                j = i + offset
                if 0 <= j < n and magnitudes[j] >= mag:
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

            candidates.append((i, mag, hps_score, q))

        if not candidates:
            return None

        # Q filtering — mirrors Swift: let highQCandidates = candidates.filter { $0.qFactor >= minQ }
        min_q = 3.0
        high_q = [c for c in candidates if c[3] >= min_q]
        if len(high_q) < len(candidates):
            rejected = [c for c in candidates if c[3] < min_q]
            rej_str = ", ".join(
                f"{frequencies[c[0]]:.0f} Hz (Q={c[3]:.1f})" for c in rejected
            )
            print(f"🔇 Q-filtered out low-Q peaks: {rej_str}")
        pool = high_q if high_q else candidates

        by_magnitude = sorted(pool, key=lambda c: c[1], reverse=True)
        strongest = by_magnitude[0]

        if prefer_lowest_significant:
            # Mirrors Swift: thresholdDB = strongest.magnitude - 15; pick lowest-index significant.
            threshold_db = strongest[1] - 15.0
            significant = [c for c in pool if c[1] >= threshold_db]
            best = min(significant, key=lambda c: c[0])
        else:
            # Default: strongest wins unless a lower-frequency candidate is within 6 dB
            # and has a comparable HPS score (within one order of magnitude).
            # Mirrors Swift: for candidate in byMagnitude.dropFirst() { … }
            current = strongest
            for candidate in by_magnitude[1:]:
                if candidate[0] >= current[0]:
                    continue  # not lower frequency
                mag_diff = current[1] - candidate[1]
                if mag_diff < 6.0 and candidate[2] >= current[2] * 0.1:
                    current = candidate
            best = current

        best_idx, best_mag, best_hps, best_q = best

        # Refine with parabolic interpolation — mirrors Swift parabolicInterpolate call.
        freq, mag = self._parabolic_interpolate(magnitudes, frequencies, best_idx)
        quality, bandwidth = self._calculate_q_factor(magnitudes, frequencies, best_idx, mag)

        # Pitch info — mirrors Swift pitchCalculator calls in findDominantPeak.
        pitch_note = None
        pitch_cents = None
        pitch_frequency = None
        if hasattr(self, "pitch_calculator") and self.pitch_calculator is not None:
            try:
                pitch_note      = self.pitch_calculator.note(float(freq))
                pitch_cents     = self.pitch_calculator.cents(float(freq))
                pitch_frequency = self.pitch_calculator.freq0(float(freq))
            except Exception:
                pass

        print(
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
        from models.tap_display_settings import TapDisplaySettings as _tds
        from models.measurement_type import MeasurementType as _MT
        from models.material_tap_phase import MaterialTapPhase as _MTP
        import time as _t

        captured = len(self.captured_taps)
        total = self.number_of_taps
        print(f"📊 Gated LONGITUDINAL tap {captured}/{total}: {dominant_peak.frequency:.1f} Hz")

        if captured < total:
            self._set_status_message(f"L tap {captured}/{total} captured. Tap again...")
            self.re_enable_detection_for_next_plate_tap()
            return

        # Average all captured spectra — mirrors Swift averageSpectra(from: materialCapturedTaps).
        avg_mags, avg_freqs = self._average_captured_taps()
        self.longitudinal_spectrum = (avg_mags, avg_freqs)

        # Build the full peak list for display/manual override.
        self.longitudinal_peaks = self._build_all_peaks(avg_mags, avg_freqs, dominant_peak)
        self.auto_selected_longitudinal_peak_id = dominant_peak.id
        self.selected_longitudinal_peak = (
            next((p for p in self.longitudinal_peaks if p.id == dominant_peak.id), dominant_peak)
        )
        print(f"🔵 Auto-selected longitudinal peak: {dominant_peak.frequency} Hz")

        self.current_peaks = self.longitudinal_peaks
        self.selected_peak_ids = {p.id for p in self.longitudinal_peaks}
        # Mirrors Swift TapToneAnalyzer+SpectrumCapture: selectedPeakIDs = Set(longitudinalPeaks.map { $0.id })
        # selected_peak_frequencies must be set here (not only in _apply_frozen_peak_state) so
        # that _on_peaks_changed_results → peak_widget.model.selected_frequencies is correct
        # for live plate/brace measurements that never go through recalculate_frozen_peaks_if_needed.
        self.selected_peak_frequencies = [p.frequency for p in self.longitudinal_peaks]
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
            self.is_measurement_complete = True
            self.tap_progress = 1.0
            self._set_status_message("Complete - check Results")
            print(f"✅ Brace measurement complete: fL={dominant_peak.frequency} Hz")
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
        else:
            # Plate: pause at review state — user must press Accept to continue or Redo to re-tap.
            # Emit longitudinal peaks now — mirrors Swift's single currentPeaks assignment.
            self._emit_peaks_array(self.current_peaks)
            self._set_material_tap_phase(_MTP.REVIEWING_LONGITUDINAL)
            self.is_detecting = False
            self._set_status_message(
                f"fL: {dominant_peak.frequency:.1f} Hz \u2014 Accept to continue or Redo to re-tap"
            )

        # Notify spectrum update (no peaksChanged here — each branch above emits exactly once).
        self.spectrumUpdated.emit(
            self.frozen_frequencies if len(self.frozen_frequencies) else self.freq,
            self.frozen_magnitudes  if len(self.frozen_magnitudes)  else self.freq * 0,
        )

    # ------------------------------------------------------------------ #
    # _handle_cross_gated_progress
    # Mirrors Swift handleCrossGatedProgress(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _handle_cross_gated_progress(self, magnitudes, frequencies, dominant_peak) -> None:
        """Handle a cross-grain gated-FFT tap result.

        Mirrors Swift TapToneAnalyzer.handleCrossGatedProgress(…).
        """
        from models.tap_display_settings import TapDisplaySettings as _tds
        from models.material_tap_phase import MaterialTapPhase as _MTP
        import time as _t
        import numpy as _np

        captured = len(self.captured_taps)
        total = self.number_of_taps
        print(f"📊 Gated CROSS-GRAIN tap {captured}/{total}: {dominant_peak.frequency:.1f} Hz")

        if captured < total:
            self._set_status_message(f"C tap {captured}/{total} captured. Tap again...")
            self.re_enable_detection_for_next_plate_tap()
            return

        avg_mags, avg_freqs = self._average_captured_taps()
        self.cross_spectrum = (avg_mags, avg_freqs)
        self.cross_peaks = self._build_all_peaks(avg_mags, avg_freqs, dominant_peak)
        self.auto_selected_cross_peak_id = dominant_peak.id
        self.selected_cross_peak = (
            next((p for p in self.cross_peaks if p.id == dominant_peak.id), dominant_peak)
        )
        print(f"🟠 Auto-selected cross-grain peak: {dominant_peak.frequency} Hz")
        self.captured_taps.clear()

        # Pause at review state regardless of whether FLC is needed.
        # accept_current_phase() will check measure_flc and route accordingly.
        self.current_peaks = self.combine_plate_peaks()
        self.set_frozen_spectrum(_np.array(avg_freqs), _np.array(avg_mags))
        self._set_material_tap_phase(_MTP.REVIEWING_CROSS)
        self.is_detecting = False
        self._set_status_message(
            f"fC: {dominant_peak.frequency:.1f} Hz \u2014 Accept to continue or Redo to re-tap"
        )
        self._emit_peaks_array(self.current_peaks)

    # ------------------------------------------------------------------ #
    # _handle_flc_gated_progress
    # Mirrors Swift handleFlcGatedProgress(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _handle_flc_gated_progress(self, magnitudes, frequencies, dominant_peak) -> None:
        """Handle an FLC (shear/diagonal) gated-FFT tap result.

        Mirrors Swift TapToneAnalyzer.handleFlcGatedProgress(…).
        """
        from models.material_tap_phase import MaterialTapPhase as _MTP
        import numpy as _np

        captured = len(self.captured_taps)
        total = self.number_of_taps
        print(f"📊 Gated FLC tap {captured}/{total}: {dominant_peak.frequency:.1f} Hz")

        if captured < total:
            self._set_status_message(f"FLC tap {captured}/{total} captured. Tap again...")
            self.re_enable_detection_for_next_plate_tap()
            return

        avg_mags, avg_freqs = self._average_captured_taps()
        self.flc_spectrum = (avg_mags, avg_freqs)
        self.flc_peaks = self._build_all_peaks(avg_mags, avg_freqs, dominant_peak)
        self.auto_selected_flc_peak_id = dominant_peak.id
        self.selected_flc_peak = (
            next((p for p in self.flc_peaks if p.id == dominant_peak.id), dominant_peak)
        )
        print(f"🟣 Auto-selected FLC peak: {dominant_peak.frequency} Hz")
        self.captured_taps.clear()

        # Pause at review state — mirrors Swift: currentPeaks = resolvedPlatePeaks(includeCross:true,
        # includeFlc:true, flcOverride: selectedFlcPeak ?? dominantPeak) before freezing.
        sel = self._resolved_plate_peaks(
            include_cross=True,
            include_flc=True,
            flc_override=self.selected_flc_peak or dominant_peak,
        )
        self.current_peaks = sel
        self.selected_peak_ids = {p.id for p in sel}
        self.set_frozen_spectrum(_np.array(avg_freqs), _np.array(avg_mags))
        self._set_material_tap_phase(_MTP.REVIEWING_FLC)
        self.is_detecting = False
        self._set_status_message(
            f"fLC: {dominant_peak.frequency:.1f} Hz \u2014 Accept to complete or Redo to re-tap"
        )
        self._emit_peaks_array(self.current_peaks)

    # ------------------------------------------------------------------ #
    # _resolved_plate_peaks
    # Mirrors Swift private func resolvedPlatePeaks(…)
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
    # _build_all_peaks
    # Mirrors Swift func buildAllPeaks(magnitudes:frequencies:dominantPeak:)
    # ------------------------------------------------------------------ #

    def _build_all_peaks(self, magnitudes, frequencies, dominant_peak) -> "list":
        """Build a display-ready peak list ensuring dominantPeak is always present.

        Runs findPeaks with no range restrictions, then replaces or prepends
        dominantPeak so its UUID identity is preserved for ID-based lookups.

        Mirrors Swift TapToneAnalyzer.buildAllPeaks(magnitudes:frequencies:dominantPeak:).
        """
        peaks = self.find_peaks(magnitudes, frequencies)
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
    # _average_captured_taps
    # Mirrors Swift func averageSpectra(from:) — used for multi-tap phases
    # ------------------------------------------------------------------ #

    def _average_captured_taps(self) -> "tuple[list[float], list[float]]":
        """Average the captured_taps spectra in the linear power domain.

        Each entry in captured_taps is a (magnitudes, frequencies, captureTime) tuple
        as stored by finish_gated_fft_capture.

        Mirrors Swift TapToneAnalyzer.averageSpectra(from:) for material taps.

        Returns:
            (avg_magnitudes, frequencies) — both as list[float].
        """
        import math

        taps = self.captured_taps
        if not taps:
            return [], []
        if len(taps) == 1:
            return list(taps[0][0]), list(taps[0][1])

        mags0, freqs0, _ = taps[0]
        n_bins = len(mags0)
        if not all(len(t[0]) == n_bins for t in taps):
            print("⚠️ Spectrum lengths don't match, using first tap only")
            return list(mags0), list(freqs0)

        power_sum = [0.0] * n_bins
        for mags, _, _ in taps:
            for b in range(n_bins):
                power_sum[b] += 10.0 ** (mags[b] / 10.0)

        n_taps = len(taps)
        avg = [10.0 * math.log10(max(power_sum[b] / n_taps, 1e-30)) for b in range(n_bins)]
        print(f"📊 Averaged {n_taps} spectra: {n_bins} bins each")
        return avg, list(freqs0)

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

        print(f"🔬 Processing {len(self.captured_taps)} taps for averaging...")

        # captured_taps for guitar mode stores raw mag_y_db arrays (not tuples).
        # Use the existing averaging path that works on plain arrays.
        stacked = _np.stack(self.captured_taps)
        avg_db = 10.0 * _np.log10(_np.mean(_np.power(10.0, stacked / 10.0), axis=0))

        self.set_frozen_spectrum(self.freq, avg_db)
        self.is_measurement_complete = True
        print(f"📸 Guitar spectrum captured from {len(self.captured_taps)} averaged taps")

        peaks = self.find_peaks(list(avg_db), list(self.freq))
        self.current_peaks = peaks
        self.peaksChanged.emit(peaks)
        self.loaded_measurement_peaks = None
        self.selected_peak_ids = set()

        self._set_status_message(
            f"Analysis complete! {len(peaks)} peaks identified "
            f"(from {len(self.captured_taps)} averaged taps)."
        )
        self.tap_progress = 1.0
        print(f"✅ Found {len(peaks)} peaks in averaged spectrum from {len(self.captured_taps)} taps")

        self.captured_taps.clear()
        self.tapDetectedSignal.emit()

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

    # ------------------------------------------------------------------ #
    # Plate / brace tap sequence entry points
    # Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift
    # ------------------------------------------------------------------ #

    def start_plate_analysis(self) -> None:
        """Start a new plate/brace tap sequence via the gated-FFT pipeline.

        The gated pipeline arms itself via start_tap_sequence(), which transitions
        material_tap_phase to CAPTURING_LONGITUDINAL automatically.
        Mirrors Swift's equivalent call that triggers the first capture phase.
        """
        self.start_tap_sequence()

    def reset_plate_analysis(self) -> None:
        """Abort the current plate/brace tap sequence and return to idle."""
        self.cancel_tap_sequence()

    # ------------------------------------------------------------------ #
    # process_averages
    # Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift processMultipleTaps()
    # ------------------------------------------------------------------ #

    def process_averages(self, mag_y) -> None:
        """Accumulate and average FFT linear magnitudes.

        Mirrors Swift TapToneAnalyzer+SpectrumCapture averageSpectra / processMultipleTaps.
        Emits newSample, averagesChanged, spectrumUpdated on each triggered frame.
        """
        import numpy as np

        if self.num_averages < self.max_average_count:
            if self.num_averages > 0:
                mag_y_sum = self.mag_y_sum + mag_y
            else:
                mag_y_sum = mag_y
            num_averages = self.num_averages + 1

            avg_mag_y = mag_y_sum / num_averages
            avg_mag_y[avg_mag_y < np.finfo(float).eps] = np.finfo(float).eps
            avg_mag_y_db = 20 * np.log10(avg_mag_y)

            avg_amplitude = np.max(avg_mag_y_db) + 100
            if avg_amplitude > (self.peak_threshold + 100):
                avg_peaks = self.find_peaks(list(avg_mag_y_db), list(self.freq))
                if avg_peaks:
                    self.current_peaks = avg_peaks
                    self.peaksChanged.emit(avg_peaks)
                triggered = len(avg_peaks) > 0
                if triggered:
                    self.newSample.emit(self.is_measurement_complete)
                    self.mag_y_sum = mag_y_sum
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))
                    self.frozen_magnitudes = avg_mag_y_db
                    self.spectrumUpdated.emit(self.freq, avg_mag_y_db)

        self.spectrumUpdated.emit(self.freq, self.frozen_magnitudes)
