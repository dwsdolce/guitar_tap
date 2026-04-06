"""
TapToneAnalyzerTapDetectionHandlerMixin — detectTap, handleTapDetection,
and all tap-detection stored state.

Mirrors Swift TapToneAnalyzer+TapDetection.swift.  There is no separate
TapDetector class in Swift; all state and logic lives directly on
TapToneAnalyzer.  This mixin puts all of that state and every method on the
Python TapToneAnalyzer exactly the same way.

Guitar mode  — absolute threshold on the FFT peak magnitude.
    risingThreshold  = tapDetectionThreshold
    fallingThreshold = tapDetectionThreshold − hysteresisMargin

Plate/Brace mode — EMA-relative threshold on the RMS input level.
    noiseFloor = α × level + (1 − α) × noiseFloor   (α = 0.05, τ ≈ 190 ms at 10 Hz)
    headroom   = max(tapDetectionThreshold − noiseFloor, 10 dB)
    risingThreshold  = noiseFloor + headroom
    fallingThreshold = noiseFloor + max(headroom − hysteresisMargin, 4 dB)

Warmup and cooldown are measured in real time (seconds) so that
behaviour is independent of the audio block size or call rate.
"""

from __future__ import annotations

import threading
import time as _time

from utilities.logging import TAP_DEBUG

from .analysis_display_mode import AnalysisDisplayMode


class TapToneAnalyzerTapDetectionHandlerMixin:
    """Tap detection state machine and capture coordinator for TapToneAnalyzer.

    All state and logic that Swift places directly on TapToneAnalyzer.
    Mirrors Swift TapToneAnalyzer+TapDetection.swift.

    Stored properties initialised in TapToneAnalyzer.__init__:
        self.is_above_threshold: bool
        self.just_exited_warmup: bool
        self.analyzer_start_time: float | None   (monotonic clock, not Date)
        self.last_tap_time: float | None          (monotonic clock)
        self.noise_floor_estimate: float          (dBFS)
        self.noise_floor_alpha: float             (EMA coefficient = 0.05)
        self.warmup_period: float                 (seconds = 0.5)
        self.tap_cooldown: float                  (seconds = 0.5)
        self.tap_peak_level: float                (dBFS at moment of tap)
        self.is_detecting: bool                   (via Published)
        self.is_detection_paused: bool            (via Published)
        self.tap_detected: bool                   (via Published)
        self.current_tap_count: int               (via Published)
        self.tap_progress: float                  (via Published)
        self.status_message: str                  (via Published)
        self.tap_detection_level: float           (via Published)
    """

    # ------------------------------------------------------------------ #
    # detect_tap — mirrors Swift detectTap(peakMagnitude:magnitudes:frequencies:)
    # ------------------------------------------------------------------ #

    def detect_tap(self, peak_magnitude: float, mag_y_db, freq) -> None:
        """Evaluate the current signal level and fire a tap on a rising edge.

        Mirrors Swift TapToneAnalyzer.detectTap(peakMagnitude:magnitudes:frequencies:).

        Called from on_fft_frame() on the main thread, mirroring Swift's Combine
        subscription to fftAnalyzer.$magnitudes (guitar, ~1 Hz) and
        fftAnalyzer.$inputLevelDB (plate/brace, ~10 Hz).

        Args:
            peak_magnitude: Current peak dBFS level.  FFT peak for guitar;
                            RMS inputLevelDB for plate/brace.
            mag_y_db:       Current FFT magnitude spectrum (ndarray, dBFS).
            freq:           Frequency axis matching mag_y_db, in Hz.
        """
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        now = _time.monotonic()

        meas_type = _tds.measurement_type()
        use_relative = (meas_type == _MT.PLATE or meas_type == _MT.BRACE)

        # Update noise-floor EMA only while below threshold (mirrors Swift).
        # Updated during warm-up too — the most valuable time to build an
        # accurate noise floor since no taps have occurred yet.
        if use_relative and not self.is_above_threshold:
            self.noise_floor_estimate = (
                self.noise_floor_alpha * peak_magnitude
                + (1.0 - self.noise_floor_alpha) * self.noise_floor_estimate
            )

        # Compute effective thresholds.
        if use_relative:
            headroom = max(self.tap_detection_threshold - self.noise_floor_estimate, 10.0)
            effective_rising  = self.noise_floor_estimate + headroom
            effective_falling = self.noise_floor_estimate + max(headroom - self.hysteresis_margin, 4.0)
            TAP_DEBUG("detectTap",
                f"RELATIVE mode | peakMag={peak_magnitude:.2f} "
                f"noiseFloor={self.noise_floor_estimate:.2f} "
                f"headroom={headroom:.2f} "
                f"risingThresh={effective_rising:.2f} "
                f"fallingThresh={effective_falling:.2f} "
                f"isAboveThreshold={self.is_above_threshold}"
            )
        else:
            effective_rising  = self.tap_detection_threshold
            effective_falling = self.tap_detection_threshold - self.hysteresis_margin
            TAP_DEBUG("detectTap",
                f"ABSOLUTE mode | peakMag={peak_magnitude:.2f} "
                f"risingThresh={effective_rising:.2f} "
                f"fallingThresh={effective_falling:.2f} "
                f"isAboveThreshold={self.is_above_threshold}"
            )

        # Warmup period — suppress detection (mirrors Swift warmupPeriod check).
        if self.analyzer_start_time is not None:
            elapsed = now - self.analyzer_start_time
            if elapsed < self.warmup_period:
                remaining = self.warmup_period - elapsed
                TAP_DEBUG("detectTap",
                    f"WARMUP in progress | remaining={remaining:.2f}s "
                    f"peakMag={peak_magnitude:.2f}"
                )
                self.tap_detected = False
                # Mirrors Swift: statusMessage = "Initializing... (Xs)"
                self.status_message = f"Initializing... ({remaining:.1f}s)"
                self.just_exited_warmup = True
                return

        # First frame after warmup — re-anchor state (mirrors Swift justExitedWarmup).
        if self.just_exited_warmup:
            self.just_exited_warmup = False
            if use_relative:
                self.noise_floor_estimate = peak_magnitude
                h = max(self.tap_detection_threshold - self.noise_floor_estimate, 10.0)
                rising_anchored = self.noise_floor_estimate + h
                self.is_above_threshold = peak_magnitude > rising_anchored
                TAP_DEBUG("detectTap",
                    f"WARMUP EXIT (relative) | peakMag={peak_magnitude:.2f} "
                    f"noiseFloorAnchored={self.noise_floor_estimate:.2f} "
                    f"risingAnchored={rising_anchored:.2f} "
                    f"isAboveThreshold={self.is_above_threshold}"
                )
            else:
                self.is_above_threshold = peak_magnitude > effective_rising
                TAP_DEBUG("detectTap",
                    f"WARMUP EXIT (absolute) | peakMag={peak_magnitude:.2f} "
                    f"risingThresh={effective_rising:.2f} "
                    f"isAboveThreshold={self.is_above_threshold}"
                )
            self.tap_detected = False
            # Mirrors Swift: statusMessage = "Tap the guitar..." / "Tap N times..."
            self.status_message = (
                "Tap the guitar..."
                if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times..."
            )
            return

        # Cooldown check (mirrors Swift tapCooldown).
        if self.last_tap_time is not None:
            cooldown_remaining = self.tap_cooldown - (now - self.last_tap_time)
            if cooldown_remaining > 0:
                TAP_DEBUG("detectTap",
                    f"COOLDOWN active | remaining={cooldown_remaining:.3f}s "
                    f"peakMag={peak_magnitude:.2f}"
                )
                self.tap_detected = False
                return

        # Update status when ready and waiting for the first tap (mirrors Swift).
        if self.current_tap_count == 0 and "Initializing" in self.status_message:
            self.status_message = (
                "Tap the guitar..."
                if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times..."
            )

        # Update detection-level indicator (mirrors Swift tapDetectionLevel).
        self.tap_detection_level = effective_rising

        # Hysteresis evaluation (mirrors Swift currentlyAboveThreshold logic).
        currently_above = (
            peak_magnitude > effective_falling
            if self.is_above_threshold
            else peak_magnitude > effective_rising
        )

        TAP_DEBUG("detectTap",
            f"HYSTERESIS eval | peakMag={peak_magnitude:.2f} "
            f"wasAbove={self.is_above_threshold} nowAbove={currently_above} "
            f"risingThresh={effective_rising:.2f} fallingThresh={effective_falling:.2f} "
            f"isDetecting={self.is_detecting} currentTapCount={self.current_tap_count}"
        )

        # Update status message when signal settles after a tap in multi-tap mode
        # (mirrors Swift detectTap lines 196-200).
        if currently_above != self.is_above_threshold:
            if (
                not currently_above and self.is_above_threshold
                and self.current_tap_count > 0
                and self.current_tap_count < self.number_of_taps
            ):
                TAP_DEBUG("detectTap",
                    f"SIGNAL SETTLED | tap {self.current_tap_count}/{self.number_of_taps}"
                    f" — signal dropped below falling threshold"
                )
                self.status_message = (
                    f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again..."
                )

        if currently_above and not self.is_above_threshold:
            # Rising edge (mirrors Swift: tapDetected = true; handleTapDetection).
            TAP_DEBUG("detectTap",
                f"RISING EDGE FIRED | peakMag={peak_magnitude:.2f} "
                f"risingThresh={effective_rising:.2f} "
                f"tapCount={self.current_tap_count + 1}/{self.number_of_taps}"
            )
            self.tap_detected = True
            self.last_tap_time = now
            # Capture the recent peak input level for decay tracking reference.
            # Use _proc_thread.recent_peak_level_db which holds the max level over the
            # last 0.5 s, ensuring we get the actual tap peak even though FFT detection
            # is delayed (mirrors Swift: tapPeakLevel = fftAnalyzer.recentPeakLevelDB).
            # Fall back to peak_magnitude when mic is None (tests, no audio hardware).
            if self.mic is not None and hasattr(self.mic, "proc_thread"):
                self.tap_peak_level = self.mic.proc_thread.recent_peak_level_db
            else:
                self.tap_peak_level = peak_magnitude
            self._handle_tap_detection(mag_y_db, freq)
        elif not currently_above and self.is_above_threshold:
            TAP_DEBUG("detectTap",
                f"FALLING EDGE | peakMag={peak_magnitude:.2f} "
                f"fallingThresh={effective_falling:.2f} — signal settled, ready for next tap"
            )
            self.tap_detected = False
        else:
            self.tap_detected = False

        # Update hysteresis state for next frame (mirrors Swift isAboveThreshold = currentlyAboveThreshold).
        self.is_above_threshold = currently_above

    # ------------------------------------------------------------------ #
    # _handle_tap_detection — mirrors Swift handleTapDetection(magnitudes:frequencies:time:)
    # ------------------------------------------------------------------ #

    def _handle_tap_detection(self, mag_y_db, freq) -> None:
        """Dispatch a confirmed tap to the appropriate capture handler.

        Mirrors Swift handleTapDetection(magnitudes:frequencies:time:).
        Guitar mode: accumulates spectra, starts decay tracking, starts capture-window timer.
        Plate/brace mode: delegates to handle_plate_tap_detection().
        """
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        # Stop detection temporarily while handling this tap (mirrors Swift line 247).
        self.is_detecting = False

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

        # Guitar mode — store spectrum, start decay tracking, schedule finish.
        self.captured_taps.append(mag_y_db.copy())
        self.current_tap_count = len(self.captured_taps)
        self.tap_progress = min(1.0, float(self.current_tap_count) / max(self.number_of_taps, 1))

        TAP_DEBUG("handleTapDetection",
            f"GUITAR TAP STORED | "
            f"currentTapCount={self.current_tap_count} numberOfTaps={self.number_of_taps} "
            f"tapProgress={self.tap_progress:.2f}"
        )

        self.tapCountChanged.emit(self.current_tap_count, self.number_of_taps)

        # Start decay tracking for ring-out time measurement
        # (mirrors Swift startDecayTracking() call in handleTapDetection).
        self.start_decay_tracking()

        # Status message (mirrors Swift lines 282-286).
        if self.current_tap_count < self.number_of_taps:
            self.status_message = (
                f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again..."
            )
        else:
            self.status_message = "All taps captured. Processing..."

        # If all taps collected: schedule processMultipleTaps after captureWindow.
        # (mirrors Swift: captureTimer fires finishCapture(), then processMultipleTaps().)
        # Python equivalent: wait captureWindow, then call _finish_capture() which averages.
        if self.current_tap_count >= self.number_of_taps:
            t = threading.Timer(self.capture_window, self._finish_capture)
            t.daemon = True
            t.start()
        else:
            # Re-enable detection after cooldown for next tap
            # (mirrors Swift lines 294-322).
            cooldown = self.tap_cooldown

            def _reenable() -> None:
                if self.mic is not None and hasattr(self.mic, "proc_thread"):
                    current_level = self.mic.proc_thread.recent_peak_level_db
                else:
                    current_level = self.tap_peak_level
                falling_threshold = self.tap_detection_threshold - self.hysteresis_margin
                if current_level <= falling_threshold:
                    self.is_above_threshold = False
                    self.is_detecting = True
                    self.tap_detected = False
                    self.status_message = (
                        f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again..."
                    )
                else:
                    self.is_above_threshold = True
                    self.is_detecting = True
                    self.tap_detected = False
                    self.status_message = (
                        f"Tap {self.current_tap_count}/{self.number_of_taps} captured."
                        " Waiting for settle..."
                    )

            t = threading.Timer(cooldown, _reenable)
            t.daemon = True
            t.start()

    # ------------------------------------------------------------------ #
    # _finish_capture — mirrors Swift finishCapture() + processMultipleTaps()
    # ------------------------------------------------------------------ #

    def _finish_capture(self) -> None:
        """Average all captured tap spectra and freeze the result.

        Called after captureWindow seconds from the final tap.
        Mirrors Swift finishCapture() which calls processMultipleTaps().
        """
        import numpy as np

        if not self.captured_taps:
            return
        stacked = np.stack(self.captured_taps)
        avg_db = 10.0 * np.log10(np.mean(np.power(10.0, stacked / 10.0), axis=0))
        self.frozen_magnitudes = avg_db
        self.frozen_frequencies = self.freq
        self.find_peaks(list(avg_db), list(self.freq))
        self.captured_taps.clear()
        self.tapDetectedSignal.emit()

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
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

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
            _MTP.WAITING_FOR_CROSS_TAP,
            _MTP.CAPTURING_FLC,
            _MTP.WAITING_FOR_FLC_TAP,
        ):
            TAP_DEBUG("handlePlateTapDetection", f"Starting gated capture for phase={phase}")
            # Mirrors Swift startGatedCapture(phase:): seeds the pre-roll PCM buffer
            # into the gated accumulator and collects raw samples until the window fills,
            # then calls finishGatedFFTCapture via the gatedCaptureComplete signal.
            self.start_gated_capture(phase)
        else:
            TAP_DEBUG("handlePlateTapDetection",
                f"UNEXPECTED TAP | phase={phase} — tap ignored"
            )

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
        Does NOT reset analyzer_start_time — doing so would restart warmup and
        destabilise is_above_threshold via the just_exited_warmup sync path.
        """
        TAP_DEBUG(
            "reEnableDetectionForNextPlateTap",
            f"Scheduling re-enable after cooldown={self.tap_cooldown}s"
        )

        cooldown = self.tap_cooldown

        def _reenable() -> None:
            # Use recent_peak_level_db as the proxy for current input level.
            # (Swift uses fftAnalyzer.inputLevelDB directly.)
            current_level = self.mic.proc_thread.recent_peak_level_db
            falling_threshold = self.tap_detection_threshold - self.hysteresis_margin
            self.is_above_threshold = current_level > falling_threshold
            self.is_detecting = True
            self.tap_detected = False
            TAP_DEBUG(
                "reEnableDetectionForNextPlateTap",
                f"Re-enabled | currentLevel={current_level:.2f} "
                f"fallingThreshold={falling_threshold:.2f} "
                f"isAboveThreshold={self.is_above_threshold} "
                f"isDetecting={self.is_detecting}"
            )

        t = threading.Timer(cooldown, _reenable)
        t.daemon = True
        t.start()

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
        fft_peak_amp: int,
        rms_amp: int,
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
            fft_peak_amp: FFT peak level on 0-100 scale (dBFS + 100).
            rms_amp:      Per-chunk RMS level on 0-100 scale (dBFS + 100).
            fps, sample_dt, processing_dt: Diagnostics.
        """
        import numpy as np
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        self._current_mag_y = mag_y

        # Fast path: decay tracking uses per-buffer RMS level at ~10 Hz.
        # Mirrors Swift fftAnalyzer.$inputLevelDB → trackDecayFast(inputLevel:).
        level_db = float(rms_amp) - 100.0
        self.track_decay_fast(level_db)

        # Tap detection — mirrors Swift Combine subscription routing:
        #   guitar:       fftAnalyzer.$magnitudes → detectTap with FFT peak level
        #   plate/brace:  fftAnalyzer.$inputLevelDB → detectTap with RMS level
        if self.is_detecting and not self.is_detection_paused and not self.is_measurement_complete:
            meas_type = _tds.measurement_type()
            use_relative = (meas_type == _MT.PLATE or meas_type == _MT.BRACE)
            peak_mag = (float(rms_amp) - 100.0) if use_relative else (float(fft_peak_amp) - 100.0)
            self.detect_tap(peak_mag, mag_y_db, self.freq)

        # Emit spectrum for the view to draw.
        if self._display_mode == AnalysisDisplayMode.LIVE:
            if self.is_measurement_complete:
                self.spectrumUpdated.emit(self.frozen_frequencies, self.frozen_magnitudes)
            else:
                self.find_peaks(list(mag_y_db), list(self.freq))
                self.spectrumUpdated.emit(self.freq, mag_y_db)
        elif self._display_mode == AnalysisDisplayMode.FROZEN:
            self.spectrumUpdated.emit(self.frozen_frequencies, self.frozen_magnitudes)
        # COMPARISON: skip spectrum update — only overlay curves shown

        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))
        self.levelChanged.emit(fft_peak_amp)
        peak_idx = int(np.argmax(mag_y_db))
        if peak_idx < len(self.freq):
            self.peakInfoChanged.emit(float(self.freq[peak_idx]), float(mag_y_db[peak_idx]))

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
        self.analyzer_start_time = _time.monotonic()
        self.last_tap_time = None
        TAP_DEBUG("reset_tap_detector", "reset_tap_detector called — warmup restarted")
