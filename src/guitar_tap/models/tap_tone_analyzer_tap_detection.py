# @parity state/tap-detection tests=test/tap-decisions,test/status-message
"""
TapToneAnalyzerTapDetectionHandlerMixin — detectTap, handleTapDetection,
and all tap-detection stored state.

Mirrors Swift TapToneAnalyzer+TapDetection.swift.  There is no separate
TapDetector class in Swift; all state and logic lives directly on
TapToneAnalyzer.  This mixin puts all of that state and every method on the
Python TapToneAnalyzer exactly the same way.

Guitar mode  — absolute threshold on the per-chunk RMS input level.
    risingThreshold  = tapDetectionThreshold
    fallingThreshold = tapDetectionThreshold − hysteresisMargin

Plate/Brace mode — EMA-relative threshold on the RMS input level.
    noiseFloor = α × level + (1 − α) × noiseFloor   (α = 0.05, τ ≈ 190 ms at 10 Hz)
    headroom   = max(tapDetectionThreshold − noiseFloor, 10 dB)
    risingThreshold  = noiseFloor + headroom
    fallingThreshold = noiseFloor + max(headroom − hysteresisMargin, 4 dB)

Warmup is measured on the AUDIO clock (seconds of audio processed), not the wall clock, so it always
covers the first `warmup_period` of AUDIO however long the setup before the first chunk took, and
behaves identically whether playback is real-time paced or not.  So are the lifecycle's delays — the
rests before re-arming, the FLC hold, the capture window (after_audio, #19).
"""

from __future__ import annotations

import time

from PySide6 import QtCore
from PySide6.QtCore import Slot

from guitar_tap.utilities.logging import TAP_DEBUG, gt_log

from .analysis_display_mode import AnalysisDisplayMode
from .detection_state import DetectionState
from .realtime_fft_analyzer import RealtimeFFTAnalyzer


class TapToneAnalyzerTapDetectionHandlerMixin:
    """Tap detection state machine and capture coordinator for TapToneAnalyzer.

    All state and logic that Swift places directly on TapToneAnalyzer.
    Mirrors Swift TapToneAnalyzer+TapDetection.swift.

    Stored properties initialised in TapToneAnalyzer.__init__:
        self.is_above_threshold: bool
        self.just_exited_warmup: bool
        self.warmup_start_audio_time: float | None   (AUDIO clock, not wall clock)
        self.last_audio_time: float              (AUDIO clock seen by detection — #19)
        self.last_chunk_level_db: float          (level of that chunk)
        self.noise_floor_estimate: float          (dBFS)
        self.noise_floor_alpha: float             (EMA coefficient = 0.05)
        self.warmup_period: float                 (seconds = 0.5)
        self.tap_cooldown: float                  (seconds = 0.5)
        self.tap_peak_level: float                (dBFS at moment of tap)
        self.is_detecting: bool                   (via Published)
        self.is_detection_paused: bool            (via Published)
        self.current_tap_count: int               (via Published)
        self.tap_progress: float                  (via Published)
        self.status_message: str                  (via Published)
        self.tap_detection_level: float           (via Published)
    """

    # ------------------------------------------------------------------ #
    # detect_tap — mirrors Swift detectTap(level:audioTime:magnitudes:frequencies:)
    # ------------------------------------------------------------------ #

    def _audio_now(self) -> float:
        """Current value of the engine's AUDIO clock (seconds of audio processed).

        0.0 when there is no engine (unit tests that drive detect_tap directly).  Mirrors Swift
        `fftAnalyzer.audioElapsed`.
        """
        mic = getattr(self, "mic", None)
        return float(getattr(mic, "audio_elapsed", 0.0)) if mic is not None else 0.0

    def detect_tap(self, level: float, audio_time: float, mag_y_db, freq) -> None:
        """Evaluate the current signal level and fire a tap on a rising edge.

        Mirrors Swift TapToneAnalyzer.detectTap(level:magnitudes:frequencies:).

        Called from _on_rms_level_changed() on the main thread for all modes,
        mirroring Swift's Combine subscription to fftAnalyzer.$inputLevelDB
        (~43 Hz per-chunk RMS).

        Args:
            level: Current RMS input level in dBFS
                            (fftAnalyzer.inputLevelDB, ~43 Hz).

                            This was previously named ``peak_magnitude``, which was wrong and actively
                            misleading: it is the broadband RMS chunk level, never an FFT peak-bin
                            magnitude.  (A genuine FFT peak does exist -- see ``on_fft_frame`` /
                            ``analyze_magnitudes`` -- but it drives peak ANALYSIS, not tap detection.)
                            The old name cost real time during the OUT-4 investigation: it looked as
                            though Swift and the web were detecting on entirely different signals.
                            They are not -- all three platforms detect on the per-chunk RMS level.
            audio_time:     The AUDIO clock value for THIS chunk (mic.audio_elapsed at the moment
                            the chunk was processed).  It travels WITH the sample rather than being
                            read here: the handler can be delivered across a thread hop and the audio
                            side races ahead, so reading mic.audio_elapsed here would give a LATER
                            time than this chunk's — which silently skips the warm-up.  Mirrors Swift
                            detectTap(audioTime:).
            mag_y_db:       Current FFT magnitude spectrum (ndarray, dBFS).
            freq:           Frequency axis matching mag_y_db, in Hz.
        """
        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        meas_type = _tds.measurement_type()
        use_relative = (meas_type == _MT.PLATE or meas_type == _MT.BRACE)

        # Update noise-floor EMA only while below threshold (mirrors Swift).
        # Updated during warm-up too — the most valuable time to build an
        # accurate noise floor since no taps have occurred yet.
        if use_relative and not self.is_above_threshold:
            self.noise_floor_estimate = (
                self.noise_floor_alpha * level
                + (1.0 - self.noise_floor_alpha) * self.noise_floor_estimate
            )

        # Compute effective thresholds.
        # NOTE: Per-chunk log lines restored for file playback only to diagnose
        # intermittent gated-capture failures.
        _is_file = self.mic and getattr(self.mic, 'is_playing_file', False)
        if use_relative:
            headroom = max(self.tap_detection_threshold - self.noise_floor_estimate, 10.0)
            effective_rising  = self.noise_floor_estimate + headroom
            effective_falling = self.noise_floor_estimate + max(headroom - self.hysteresis_margin, 4.0)
            if _is_file:
                TAP_DEBUG("detectTap",
                    f"FILE_CHUNK | peakMag={level:.2f} "
                    f"noiseFloor={self.noise_floor_estimate:.2f} "
                    f"headroom={headroom:.1f} "
                    f"risingThresh={effective_rising:.2f} "
                    f"isAbove={self.is_above_threshold}"
                )
        else:
            effective_rising  = self.tap_detection_threshold
            effective_falling = self.tap_detection_threshold - self.hysteresis_margin
            if _is_file:
                TAP_DEBUG("detectTap",
                    f"FILE_CHUNK | peakMag={level:.2f} "
                    f"absThresh={effective_rising:.2f} "
                    f"isAbove={self.is_above_threshold}"
                )

        # Warmup period — suppress detection (mirrors Swift warmupPeriod check).
        # Measured on the AUDIO clock, against THIS chunk's timestamp (see `audio_time`).
        if self.warmup_start_audio_time is not None:
            elapsed = audio_time - self.warmup_start_audio_time
            if elapsed < self.warmup_period:
                # SILENT warm-up: suppress detection but never write status_message, so the
                # prompt set at the transition (arm/accept/redo/resume) survives — mirrors the
                # web's counter-based warm-up. (Was: overwrote status with "Initializing… (Xs)".)
                self.just_exited_warmup = True
                return

        # First frame after warmup — re-anchor state (mirrors Swift justExitedWarmup).
        if self.just_exited_warmup:
            self.just_exited_warmup = False
            if use_relative:
                self.noise_floor_estimate = level
                h = max(self.tap_detection_threshold - self.noise_floor_estimate, 10.0)
                rising_anchored = self.noise_floor_estimate + h
                self.is_above_threshold = level > rising_anchored
                TAP_DEBUG("detectTap",
                    f"WARMUP EXIT (relative) | peakMag={level:.2f} "
                    f"noiseFloorAnchored={self.noise_floor_estimate:.2f} "
                    f"risingAnchored={rising_anchored:.2f} "
                    f"isAboveThreshold={self.is_above_threshold}"
                )
            else:
                self.is_above_threshold = level > effective_rising
                TAP_DEBUG("detectTap",
                    f"WARMUP EXIT (absolute) | peakMag={level:.2f} "
                    f"risingThresh={effective_rising:.2f} "
                    f"isAboveThreshold={self.is_above_threshold}"
                )
            # (The noise-floor re-anchor above stays; only the status write is gone — silent warm-up.)
            return

        # No cooldown gate here. There used to be one — a crossing within tap_cooldown of the last tap,
        # measured on the WALL clock, was ignored. In file playback a plate phase auto-advances and
        # arms the next at once, so this edition, whose test harness processes audio inline, reached
        # it and rejected the tail of the ring-out, while Swift, whose audio runs ahead of its main
        # thread, reached the same audio after the gate had closed — the same audio decided two ways
        # (#19). The auto-advance's own latch (is_above_threshold = True) already makes a ring-out fall
        # before anything counts, so the gate was removed in all three editions.


        # Update detection-level indicator (mirrors Swift tapDetectionLevel).
        self.tap_detection_level = effective_rising

        # Hysteresis: rising edge ALSO requires N consecutive chunks above
        # the rising threshold to confirm — mirrors the audio-queue level
        # crossing detector in RealtimeFFTAnalyzer.  Without confirmation
        # here, a brief noise bump that the audio-queue rejected can still
        # fire the main-thread rising-edge detector and start a bogus
        # gated capture (see test failure on
        # plate-umik-1-swift-mac-1778816330 where the FLC bump at
        # -46.78 dB was rejected by the audio queue but caught here,
        # capturing 26.4 Hz @ -78.9 dB instead of the real 35.4 Hz FLC
        # tap that arrived a few seconds later).
        confirm_target = RealtimeFFTAnalyzer.LEVEL_CROSSING_CONFIRMATION_CHUNKS
        is_file_playback = (
            self.mic is not None and getattr(self.mic, "is_playing_file", False)
        )

        if self.is_above_threshold:
            # Currently latched above — apply falling-threshold hysteresis.
            if level <= effective_falling:
                # Falling edge.
                if (
                    self.current_tap_count > 0
                    and self.current_tap_count < self.number_of_taps
                ):
                    TAP_DEBUG("detectTap",
                        f"SIGNAL SETTLED | tap {self.current_tap_count}/{self.number_of_taps}"
                        f" — signal dropped below falling threshold"
                    )
                    self._set_status_message(self._guitar_loop_status(capturing=False))
                TAP_DEBUG("detectTap",
                    f"FALLING EDGE | peakMag={level:.2f} "
                    f"fallingThresh={effective_falling:.2f} — signal settled, ready for next tap"
                )
                self.is_above_threshold = False
                self.detect_tap_consecutive_above = 0
        else:
            # Currently latched below — apply rising-threshold gate with
            # N-chunk confirmation.
            if level > effective_rising:
                self.detect_tap_consecutive_above += 1
                if self.detect_tap_consecutive_above >= confirm_target:
                    # Confirmed rising edge — fire the tap-detection event.
                    TAP_DEBUG("detectTap",
                        f"RISING EDGE FIRED | peakMag={level:.2f} "
                        f"risingThresh={effective_rising:.2f} "
                        f"tapCount={self.current_tap_count + 1}/{self.number_of_taps} "
                        f"confirmedBy={confirm_target}"
                    )
                    self.is_above_threshold = True
                    self.detect_tap_consecutive_above = 0
                    # Capture the recent peak input level for decay tracking
                    # reference.  Mirrors Swift TapToneAnalyzer+TapDetection.swift:
                    #   tapPeakLevel = fftAnalyzer.recentPeakLevelDB
                    # (2.0 s peak-hold).  This is the CORRECT intentional use
                    # of recentPeakLevelDB: at tap-fire time the peak-hold
                    # captures the actual tap transient even though FFT
                    # detection lags by up to one FFT frame.  Fall back to
                    # level when mic is None (tests, no audio hardware).
                    if self.mic is not None and hasattr(self.mic, "recent_peak_level_db"):
                        self.tap_peak_level = self.mic.recent_peak_level_db
                    else:
                        self.tap_peak_level = level
                    self._handle_tap_detection(mag_y_db, freq, audio_time)
                else:
                    # Pending — waiting for more above-threshold chunks.
                    if is_file_playback and self.detect_tap_consecutive_above == 1:
                        TAP_DEBUG("detectTap",
                            f"RISING EDGE PENDING | peakMag={level:.2f} "
                            f"risingThresh={effective_rising:.2f} "
                            f"need={confirm_target - 1} more"
                        )
            else:
                # Below rising threshold.
                if self.detect_tap_consecutive_above > 0 and is_file_playback:
                    TAP_DEBUG("detectTap",
                        f"RISING EDGE CANCELED | peakMag={level:.2f} "
                        f"(signal fell below after "
                        f"{self.detect_tap_consecutive_above}/{confirm_target} chunks)"
                    )
                self.detect_tap_consecutive_above = 0

    # ------------------------------------------------------------------ #
    # _handle_tap_detection — mirrors Swift handleTapDetection(magnitudes:frequencies:time:)
    # ------------------------------------------------------------------ #

    def _handle_tap_detection(self, mag_y_db, freq, audio_time: float) -> None:
        """Dispatch a confirmed tap to the appropriate capture handler.

        Mirrors Swift handleTapDetection(magnitudes:frequencies:time:audioTime:). audio_time (the
        tap's audio-clock time) seeds ring-out decay tracking so it is measured in audio time.
        Guitar mode: accumulates spectra, starts decay tracking, starts capture-window timer.
        Plate/brace mode: delegates to handle_plate_tap_detection().
        """
        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        # Stop detection temporarily while handling this tap (mirrors Swift line 247).
        self.detection_state = DetectionState.IDLE

        meas_type = _tds.measurement_type()
        is_plate = (meas_type == _MT.PLATE)
        is_brace = (meas_type == _MT.BRACE)

        TAP_DEBUG("handleTapDetection",
            f"ENTERED | measurementType={meas_type} "
            f"isPlate={is_plate} isBrace={is_brace} "
            f"currentTapCount={self.current_tap_count} "
            f"numberOfTaps={self.number_of_taps}"
        )

        if is_plate or is_brace:
            TAP_DEBUG("handleTapDetection",
                f"Routing to handle_plate_tap_detection | phase={self.material_tap_phase}"
            )
            self.handle_plate_tap_detection(mag_y_db, freq)
            return

        # Guitar mode — start a gated raw-PCM capture aligned to the tap onset.
        # Detection uses RMS-based edge (~23 ms resolution); the captured window
        # is one full fft_size buffer that begins ~pre_roll_ms before the trigger.
        # The FFT is computed inside finish_guitar_gated_capture once the window
        # fills, then appended to captured_taps. This eliminates the variability
        # caused by where a tap happens to fall within the live FFT framing.
        TAP_DEBUG("handleTapDetection",
            f"GUITAR — starting gated capture "
            f"capturedTaps={len(self.captured_taps)}/{self.number_of_taps}"
        )

        # Start decay tracking immediately (still uses RMS level, independent of
        # spectrum capture). Mirrors Swift startDecayTracking(tapAudioTime:) at tap-fire time.
        self.start_decay_tracking(tap_audio_time=audio_time)

        # Provisional status update — final status is emitted after gated capture
        # completes and the captured_taps list grows.  (current_tap_count == len(captured_taps)
        # here, so _guitar_loop_status's provisional +1 == the old len(captured_taps) + 1.)
        self._set_status_message(self._guitar_loop_status(capturing=True))

        # capture_timer_active flag — leave True so analyze_magnitudes keeps
        # rendering the live spectrum during the ring-out window.
        self.capture_timer_active = True

        # Open the guitar gated capture. _accumulate_gated_samples will fill the
        # accumulator over the next fft_size samples and emit gatedCaptureComplete,
        # which routes to finish_guitar_gated_capture (in spectrum_capture mixin).
        self.start_guitar_gated_capture()

    # ------------------------------------------------------------------ #
    # _finish_capture — mirrors Swift finishCapture() + processMultipleTaps()
    # ------------------------------------------------------------------ #

    @Slot()
    def _finish_capture(self) -> None:
        """Average all captured tap spectra, build tap_entries, and freeze the result.

        Called after captureWindow seconds from the final tap.
        Invoked via QTimer.singleShot from _handle_tap_detection, so this
        always runs on the main thread.

        Mirrors Swift's combined finishCapture() + processMultipleTaps() flow:
          finishCapture()      → invalidates captureTimer (captureTimer = nil)
          processMultipleTaps() → averages spectra, builds tapEntries, freezes result
        Delegates to process_multiple_taps() so that tap_entries is always built
        for multi-tap guitar measurements, enabling the Taps toggle button.
        """
        # Mirrors Swift finishCapture(): captureTimer?.invalidate(); captureTimer = nil
        self.capture_timer_active = False
        self.process_multiple_taps()

    @Slot()
    def _do_reenable_guitar(self) -> None:
        """Main-thread slot: re-arm detection after guitar tap cooldown.

        Invoked via QMetaObject.invokeMethod(QueuedConnection) from the
        _reenable closure in _handle_tap_detection, so this always runs on
        the main thread.
        Mirrors Swift handleTapDetection re-enable closure dispatched with
        DispatchQueue.main.asyncAfter.
        Uses _current_input_level_db (per-chunk RMS, ~43 Hz) — guitar
        detection now runs on RMS, so the seed for is_above_threshold must
        come from the same source the rising-edge detector reads.
        """
        # Re-anchor the latch from the current level and listen again — and nothing else. The status
        # message was set when the tap was captured (the loop prompt) and stays as it is: Swift's
        # scheduleGuitarReEnable and the web's touch only the latch and the detection state. This
        # used to rewrite it here, and to show "Tap N/M captured. Waiting for settle..." while the
        # level was still high — text neither other edition has (#17 F45).
        self._re_arm_from_current_chunk()
        with self._gated_lock:
            self._last_level_crossing_capture_id = -1

    # ------------------------------------------------------------------ #
    # totalPlateTaps — mirrors Swift var totalPlateTaps: Int
    # ------------------------------------------------------------------ #

    @property
    def total_plate_taps(self) -> int:
        """Total number of individual taps expected across all plate/brace phases.

        - Brace mode: numberOfTaps (longitudinal phase only).
        - Plate without FLC: numberOfTaps × 2 (L + C phases).
        - Plate with FLC: numberOfTaps × 3 (L + C + FLC phases).

        Used to compute tapProgress (0.0–1.0) across the full multi-phase sequence.
        Mirrors Swift var totalPlateTaps: Int.
        """
        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        meas_type = _tds.measurement_type()
        if meas_type == _MT.BRACE:
            return self.number_of_taps
        return self.number_of_taps * (3 if _tds.measure_flc() else 2)

    # ------------------------------------------------------------------ #
    # handle_plate_tap_detection
    # Mirrors Swift handlePlateTapDetection(magnitudes:frequencies:time:)
    # ------------------------------------------------------------------ #

    def handle_plate_tap_detection(self, mag_y_db, freq) -> None:
        """Route a plate/brace tap event to the active gated-FFT capture window.

        Mirrors Swift handlePlateTapDetection(magnitudes:frequencies:time:).
        Switches over materialTapPhase directly (mirroring Swift's
        `let phase = materialTapPhase` switch) and calls start_gated_capture()
        to trigger raw-PCM gated FFT capture for active capture phases.

        is_detecting is already False (set by _handle_tap_detection caller).
        """
        from .material_tap_phase import MaterialTapPhase as _MTP

        phase = self.material_tap_phase
        TAP_DEBUG("handlePlateTapDetection",
            f"ENTERED | phase={phase} "
            f"materialCapturedTaps.count={len(self.captured_taps)} "
            f"numberOfTaps={self.number_of_taps}"
        )

        if phase in (
            _MTP.CAPTURING_LONGITUDINAL,
            _MTP.CAPTURING_CROSS,
            _MTP.CAPTURING_FLC,
            _MTP.WAITING_FOR_FLC_TAP,
        ):
            TAP_DEBUG("handlePlateTapDetection", f"Starting gated capture for phase={phase}")
            # Mirrors Swift startGatedCapture(phase:): seeds the pre-roll PCM buffer
            # into the gated accumulator and collects raw samples until the window fills,
            # then calls finishGatedFFTCapture via the gatedCaptureComplete signal.
            self.start_gated_capture(phase)
        else:
            # Covers .notStarted, .complete, .reviewingLongitudinal, .reviewingCross,
            # .reviewingFlc — mirrors Swift's combined default case.
            TAP_DEBUG("handlePlateTapDetection",
                f"UNEXPECTED TAP | phase={phase} — tap ignored"
            )
            gt_log(f"⚠️ Unexpected tap in plate phase: {phase}")

    # ------------------------------------------------------------------ #
    # re_enable_detection_for_next_plate_tap
    # Mirrors Swift reEnableDetectionForNextPlateTap()
    # ------------------------------------------------------------------ #

    def re_enable_detection_for_next_plate_tap(self) -> None:
        """Re-enable tap detection after a brief cooldown between plate/brace taps.

        Waits tap_cooldown seconds, then checks the current input level to
        seed is_above_threshold correctly so the hysteresis logic starts from
        an accurate state.

        Mirrors Swift reEnableDetectionForNextPlateTap().
        Does NOT reset warmup_start_audio_time — doing so would restart warmup and
        destabilise is_above_threshold via the just_exited_warmup sync path.
        """
        TAP_DEBUG(
            "reEnableDetectionForNextPlateTap",
            f"Scheduling re-enable after cooldown={self.tap_cooldown}s"
        )

        # tap_cooldown of AUDIO (#19).
        self.after_audio(self.tap_cooldown, self._do_reenable_detection)

    @Slot()
    def _do_reenable_detection(self) -> None:
        """Main-thread slot that applies the re-enable state after cooldown.

        Called via QMetaObject.invokeMethod(QueuedConnection) from _reenable,
        so this always runs on the main thread.
        Mirrors Swift: DispatchQueue.main.asyncAfter { ... } in reEnableDetectionForNextPlateTap().
        """
        # Re-anchored from the chunk that made the rest due — its level, not a peak-hold: the
        # 2.0 s peak-hold stays elevated after a tap and would latch is_above_threshold True.
        self._re_arm_from_current_chunk()
        # Clear stale fast-start marker so the next tap's main-thread
        # start_gated_capture correctly falls back to pre-roll seeding
        # if the audio-queue level crossing doesn't fire in time.
        with self._gated_lock:
            self._last_level_crossing_capture_id = -1
        TAP_DEBUG(
            "reEnableDetectionForNextPlateTap",
            f"Re-enabled | chunkLevel={self.last_chunk_level_db:.2f} "
            f"isAboveThreshold={self.is_above_threshold} "
            f"isDetecting={self.is_detecting}"
        )

    # ------------------------------------------------------------------ #
    # combine_plate_peaks — mirrors Swift func combinePlatePeaks() -> [ResonantPeak]
    # ------------------------------------------------------------------ #

    def combine_plate_peaks(self) -> list:
        """Merge longitudinal, cross-grain, and FLC peak arrays for combined display.

        Cross and FLC peaks are deduplicated against previously added peaks using
        a 5 Hz frequency tolerance, except that the auto-selected peak from each
        phase is always included regardless of proximity to another peak.

        Returns the merged peak list sorted by frequency (ascending).
        Mirrors Swift func combinePlatePeaks() -> [ResonantPeak].
        """
        FREQUENCY_TOLERANCE: float = 5.0  # Hz

        combined: list = list(self.longitudinal_peaks)

        # Add cross-grain peaks, avoiding duplicates; always include the auto-selected one.
        for cross_peak in self.cross_peaks:
            is_auto = (cross_peak.id == self.auto_selected_cross_peak_id)
            is_duplicate = any(
                abs(existing.frequency - cross_peak.frequency) < FREQUENCY_TOLERANCE
                for existing in combined
            )
            if is_auto or not is_duplicate:
                combined.append(cross_peak)

        # Add FLC peaks with the same deduplication logic.
        for flc_peak in self.flc_peaks:
            is_auto = (flc_peak.id == self.auto_selected_flc_peak_id)
            is_duplicate = any(
                abs(existing.frequency - flc_peak.frequency) < FREQUENCY_TOLERANCE
                for existing in combined
            )
            if is_auto or not is_duplicate:
                combined.append(flc_peak)

        return sorted(combined, key=lambda p: p.frequency)

    # ------------------------------------------------------------------ #
    # on_fft_frame — main-thread FFT frame receiver
    # ------------------------------------------------------------------ #

    def on_fft_frame(
        self,
        mag_y_db,
        mag_y,
        peak_db: float,
        fps: float,
        sample_dt: float,
        processing_dt: float,
    ) -> None:
        """Receive a processed FFT frame (main thread slot).

        Mirrors Swift setupSubscriptions() Combine sinks on fftAnalyzer.$magnitudes
        (guitar tap detection + peak analysis) and fftAnalyzer.$inputLevelDB
        (plate/brace tap detection + decay tracking).

        The processing thread no longer runs detect_tap(); it only delivers
        raw FFT and level data.  detect_tap() is called here on the main thread,
        exactly as Swift's Combine subscriptions do.

        Args:
            mag_y_db:     FFT magnitude spectrum in dBFS (ndarray).
            mag_y:        FFT linear magnitude spectrum (ndarray).
            peak_db:      The spectrum's peak in dBFS, as a float (Swift ``peakMagnitude``).
            fps, sample_dt, processing_dt: Diagnostics.
        """
        import numpy as np

        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        self._current_mag_y = mag_y
        self._current_mag_y_db = mag_y_db

        # Cache instantaneous FFT peak magnitude — mirrors Swift fftAnalyzer.peakMagnitude.
        # Updated here at the FFT frame rate (~2.7 Hz).  Used by guitar-mode _reenable()
        # to seed is_above_threshold, exactly as Swift handleTapDetection() does.
        # Distinct from _current_input_level_db (fftAnalyzer.inputLevelDB / RMS, ~43 Hz).
        self._current_peak_magnitude_db = peak_db

        # NOTE: decay tracking is NOT driven here. on_fft_frame fires at the FFT frame rate (~2.7 Hz),
        # far too coarse for ring-out timing. It now runs in _on_rms_level_changed at the per-chunk
        # RMS rate (~43 Hz), matching Swift fftAnalyzer.$inputLevelDB → trackDecayFast(inputLevel:).

        # Tap detection for ALL modes is now driven by _on_rms_level_changed
        # (~43 Hz, per-chunk RMS).  Earlier the guitar path detected via FFT
        # peak here (~2.7 Hz), but that resolution was coarser than the
        # inter-tap interval for closely-spaced taps and produced unreliable
        # rising/falling edges. Spectrum capture is now triggered by RMS edges
        # and the captured window is a full fft_size buffer aligned to the
        # tap onset (see start_guitar_gated_capture).

        # Emit spectrum for the view to draw.
        # A device/route change is settling: show nothing rather than the new device's
        # not-yet-valid audio. This used to fall out of the settle writing display_mode = FROZEN
        # with blank frozen arrays; the settle now says so directly and leaves the frozen arrays
        # (a completed or loaded measurement's data) alone (#17 F35).
        if self.is_settling:
            self.spectrumUpdated.emit(np.array([]), np.array([]))
        elif self._display_mode == AnalysisDisplayMode.LIVE:
            if self.is_measurement_complete:
                self.spectrumUpdated.emit(self.frozen_frequencies, self.frozen_magnitudes)
            else:
                # Delegate to analyze_magnitudes — mirrors Swift setupSubscriptions()
                # Combine sink at TapToneAnalyzer.swift:876 which calls
                # self?.analyzeMagnitudes(magnitudes, frequencies:, peakMagnitude:).
                # analyze_magnitudes updates peaks_above_peak_min, selected_peak_ids,
                # identified_modes, and emits peaksChanged via its internal logic.
                self.analyze_magnitudes(list(mag_y_db), list(self.freq), peak_db)
                self.spectrumUpdated.emit(self.freq, mag_y_db)
        # COMPARISON: skip spectrum update — only overlay curves shown.
        # There was a FROZEN branch here emitting the frozen arrays; it was redundant with the
        # is_measurement_complete check above (a loaded or completed measurement is complete) and
        # unreachable once the settle stopped writing FROZEN (#17 F35).

        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))
        peak_idx = int(np.argmax(mag_y_db))
        if peak_idx < len(self.freq):
            peak_freq = float(self.freq[peak_idx])
            self.peakInfoChanged.emit(peak_freq, float(mag_y_db[peak_idx]))

    # ------------------------------------------------------------------ #
    # _on_rms_level_changed — tap detection for all modes at ~43 Hz
    # ------------------------------------------------------------------ #

    def _on_rms_level_changed(self, level_db: float, audio_time: float) -> None:
        """Tap-detection driver for ALL modes at ~43 Hz from per-chunk RMS.

        Mirrors Swift's Combine sink on fftAnalyzer.$inputLevelDB which fires
        every 1024 samples (~43 Hz).  Guitar mode now detects from RMS too —
        previously it ran inside on_fft_frame at ~2.7 Hz which was coarser
        than the inter-tap interval for files with closely-spaced taps.

        For guitar mode the detected rising edge starts a gated raw-PCM
        capture (start_guitar_gated_capture) that retroactively assembles
        an fft_size-aligned spectrum starting just before the tap onset.

        Args:
            level_db:   Per-chunk RMS level in dBFS, exact (Swift ``levelDB``; −100 on true silence).
            audio_time: The AUDIO clock value for THIS chunk (see detect_tap).

        Called ONCE per chunk, directly by process_raw_samples on the processing thread — Swift's
        rmsLevelHandler on the audio queue. It used to be called twice (direct, plus the queued Qt
        signal) and deduplicated by the mic's CURRENT sample count, which a late queued copy could
        slip past — and it received the level truncated to whole dB (#17 F44).
        """

        # Cache instantaneous level — mirrors Swift fftAnalyzer.inputLevelDB.
        self._current_input_level_db = level_db

        # Advance the analyzer's audio clock and run any lifecycle action this chunk makes due —
        # before the guards, since a re-arm is what turns detection back on (#19). A chunk that made
        # an action due is not also detected on: a re-arm has just re-anchored the latch from it.
        # Mirrors Swift onRmsLevelChanged.
        self.last_audio_time = audio_time
        self.last_chunk_level_db = level_db
        self.last_chunk_wall_time = time.monotonic()
        ran_actions = self._run_due_audio_actions()

        # Fast path: decay tracking at the per-chunk RMS rate (~43 Hz), run regardless of detection
        # state (its own is_tracking_decay guard gates it, and the post-tap window must keep updating
        # even once the measurement is complete). Stamped with THIS chunk's audio_time so the ring-out
        # is measured in audio time (load-invariant). Mirrors Swift rmsLevelHandler -> trackDecayFast.
        self.track_decay_fast(self._current_input_level_db, audio_time)
        if ran_actions:
            return

        if self.mic and getattr(self.mic, 'is_playing_file', False):
            TAP_DEBUG("onRmsLevel",
                f"FILE | levelDB={self._current_input_level_db:.2f} "
                f"isDetecting={self.is_detecting} "
                f"isPaused={self.is_detection_paused} "
                f"isComplete={self.is_measurement_complete}"
            )
        if not self.is_detecting or self.is_detection_paused or self.is_measurement_complete:
            return
        level = self._current_input_level_db
        self.detect_tap(level, audio_time, self._current_mag_y_db, self.freq)

    # ------------------------------------------------------------------ #
    # Audio-clock lifecycle timers (#19) — mirrors Swift afterAudio / runDueAudioActions
    # ------------------------------------------------------------------ #

    def after_audio(self, delay: float, action, released_at_file_end: bool = False) -> None:
        """Schedule *action* to run once the audio clock has advanced *delay* seconds past last_audio_time.

        The tap lifecycle's delays — the rest before re-arming, the FLC hold, the capture window — run
        on this clock, never the wall clock: file playback advances audio at "real time + processing
        time", so a wall-clock delay covered a different stretch of audio on a slower run and late
        captures in a sequence moved (#19). The action runs on the main thread from
        _on_rms_level_changed, on the first chunk whose audio time reaches the due time. Like the
        _main_async_after it replaces, it cannot be cancelled; each action guards itself.

        Args:
            delay:                Seconds of AUDIO to wait.
            action:               Zero-argument callable.
            released_at_file_end: Run it at once when file playback ends, if still pending. With no
                                  more audio the clock stops, and an action that must happen — the
                                  capture window's processing — would otherwise never run. A re-arm is
                                  not released: with no audio there is nothing to detect.
        """
        self._pending_audio_actions.append((self.last_audio_time + delay, released_at_file_end, action))

    def _run_due_audio_actions(self) -> bool:
        """Run, in scheduling order, every pending action whose due time last_audio_time has reached.

        Returns True if any ran on this chunk.
        """
        due = [a for a in self._pending_audio_actions if a[0] <= self.last_audio_time]
        if not due:
            return False
        self._pending_audio_actions = [a for a in self._pending_audio_actions if a[0] > self.last_audio_time]
        for _, _, action in due:
            action()
        return True

    def release_audio_actions_at_file_end(self) -> None:
        """File playback has ended: run every pending action marked released_at_file_end now, because
        the audio clock will not advance again to make it due. Called from the file-end flush."""
        released = [a for a in self._pending_audio_actions if a[1]]
        self._pending_audio_actions = [a for a in self._pending_audio_actions if not a[1]]
        for _, _, action in released:
            action()

    def after_audio_stall(self, interval: float, relevant, action) -> None:
        """Run *action* once NO audio has arrived for *interval* seconds of WALL time — the gated
        capture's safety timeout (T6).

        It exists for when the audio STOPS (the file ends, the user stops, the device drops), and then
        the audio clock stops too, so it cannot run on that clock. But it must not fire while audio is
        merely slow: measured from the capture's START it did, when paced playback ran slower than real
        time — which macOS timer throttling (App Nap) made 2–4× in this edition's test process — and
        closed captures early (#19). Measured from the LAST chunk, it fires only when the audio has
        really stopped. Stops checking once *relevant()* is false. Mirrors Swift afterAudioStall.
        """
        def check() -> None:
            if not relevant():
                return
            quiet = time.monotonic() - self.last_chunk_wall_time
            if quiet >= interval:
                action()
            else:
                self.after_audio_stall(interval - quiet, relevant, action)
        self._main_async_after(int(interval * 1000), check)

    def _re_arm_from_current_chunk(self) -> None:
        """Re-arm detection from the chunk that made a rest due: re-anchor the hysteresis latch from THAT
        chunk's level, so the next rising edge is judged against the audio actually present, then
        listen. Shared by the guitar and plate/brace rests. Mirrors Swift reArmFromCurrentChunk."""
        falling_threshold = self.tap_detection_threshold - self.hysteresis_margin
        self.is_above_threshold = self.last_chunk_level_db > falling_threshold
        self.detection_state = DetectionState.LISTENING

    # ------------------------------------------------------------------ #
    # reset_tap_detector — mirrors Swift analyzerStartTime = Date() reset
    # ------------------------------------------------------------------ #

    def reset_tap_detector(self) -> None:
        """Restart warmup — mirrors Swift analyzerStartTime = Date().

        Called after device change, new tap sequence, resume, cancel.
        Equivalent to the Swift pattern of setting analyzerStartTime = Date()
        to restart the warmup window from now.
        """
        self.is_above_threshold = False
        self.just_exited_warmup = True
        self.warmup_start_audio_time = self._audio_now()
        TAP_DEBUG("reset_tap_detector", "reset_tap_detector called — warmup restarted")
