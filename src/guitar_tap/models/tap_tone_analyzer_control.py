"""
TapToneAnalyzer+Control — lifecycle control, device management, calibration,
tap-sequence management, and parameter setters.

Mirrors Swift TapToneAnalyzer+Control.swift.
"""

from __future__ import annotations

import time as _time

from guitar_tap.utilities.logging import gt_log


class TapToneAnalyzerControlMixin:
    """Lifecycle control and parameter management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+Control.swift.
    """

    # ------------------------------------------------------------------ #
    # _set_status_message
    # ------------------------------------------------------------------ #

    def _set_status_message(self, message: str) -> None:
        """Assign status_message and notify the view via statusMessageChanged.

        All writes to status_message must go through this helper so that the
        status bar label is kept in sync.  Mirrors Swift @Published var
        statusMessage: String whose every write auto-fires objectWillChange on
        TapToneAnalyzer, causing SwiftUI to re-render the Text(tap.statusMessage)
        label in TapToneAnalysisView+Controls.swift.

        If the mic input is currently clipping, the displayed message is
        overridden with a remediation warning while the analyzer's intended
        message is preserved in _latest_real_status for restoration when the
        clip clears.  Mirrors Swift's identical override pattern.
        """
        self._latest_real_status = message
        if getattr(self, "is_clipping", False):
            self.status_message = "⚠ Input clipping — reduce mic gain"
        else:
            self.status_message = message
        self.statusMessageChanged.emit(self.status_message)

    # ---- Status derivation (mirrors the web state->string machine) ---- #

    def _tap_prompt(self) -> str:
        """The guitar resting prompt (post-warmup steady state) — the single source for the
        'Tap the guitar…' / 'Tap the guitar N times…' strings.  Mirrors Swift tapPrompt()."""
        return ("Tap the guitar..." if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times...")

    def _guitar_loop_status(self, capturing: bool) -> str:
        """Guitar detection-loop status derived from state — the analyzer's equivalent of the
        web setGuitarStatus(engineState).  capturing=False -> resting prompt (count 0) or the
        between-taps '…captured. Tap again…'; capturing=True -> 'Tap n/N capturing…' or, on the
        final tap, 'All taps captured. Processing…'.  (guitar mode keeps current_tap_count ==
        len(captured_taps), so the provisional +1 matches the old len(captured_taps) + 1.)
        Mirrors Swift guitarLoopStatus(capturing:)."""
        if capturing:
            prov = min(self.current_tap_count + 1, self.number_of_taps)
            return (f"Tap {prov}/{self.number_of_taps} capturing..." if prov < self.number_of_taps
                    else "All taps captured. Processing...")
        return (self._tap_prompt() if self.current_tap_count == 0
                else f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again...")

    def _set_clipping(self, clipping: bool) -> None:
        """Update the input-clipping state and re-render the status message.

        Called from a slot connected to the FFT thread's clippingChanged signal.
        On transition, swaps the displayed status between the clipping warning
        and the most recent analyzer-set message (preserved in
        _latest_real_status).  Mirrors Swift TapToneAnalyzer.setClipping(_:).
        """
        if clipping == getattr(self, "is_clipping", False):
            return
        self.is_clipping = clipping
        if clipping:
            self.status_message = "⚠ Input clipping — reduce mic gain"
        else:
            self.status_message = self._latest_real_status
        self.statusMessageChanged.emit(self.status_message)

    # ------------------------------------------------------------------ #
    # Hot-plug (mirrors FftCanvas._on_devices_refreshed)
    # ------------------------------------------------------------------ #

    def _on_devices_refreshed(self) -> None:
        """Handle a hot-plug event (always on main thread).

        Mirrors Swift loadAvailableInputDevicesMacOS() which:
        1. Re-enumerates the device list
        2. Auto-selects newly connected real devices (or falls back on disconnect)
        3. Calls setInputDevice(_:) if the selection changed

        Python adds an explicit PortAudio re-init step because sounddevice
        caches the device list at Pa_Initialize() time (Swift CoreAudio/
        AVAudioSession don't have this limitation).

        We call mic.load_available_input_devices() — the direct mirror of Swift's
        loadAvailableInputDevicesMacOS() — but temporarily suppress its
        _on_devices_changed callback to avoid recursing back into this method.

        Re-entrancy guard: on Windows, opening a new PortAudio stream triggers
        the CM_Register_Notification callback, which queues another
        _on_devices_refreshed call on the main thread while the current refresh
        is still running.  The re-entrancy guard (Guard 1) drops those duplicates.

        Post-completion cooldown: after the impl finishes, ignore additional calls
        for 1.0 s.  This stops the cascade of CM_Register_Notification events
        triggered by Pa_OpenStream (each stream open fires a CM notification that,
        after the 0.5 s sleep in _notify_devices_changed, arrives ~0.5-0.7 s after
        the previous impl completed).  Legitimate Windows device-settled
        notifications (e.g. Realtek WASAPI becoming available after UMIK unplug)
        arrive 1-2+ seconds after the initial event and are not suppressed.
        """
        now = _time.monotonic()
        # Guard 1: already inside a refresh — drop the duplicate.
        if getattr(self, '_devices_refresh_active', False):
            gt_log("🔄 _on_devices_refreshed: suppressed (already in progress)")
            return
        # Guard 2: completed a refresh too recently — drop rapid-fire cascade.
        # 1.0 s is long enough to swallow the CM notifications triggered by
        # Pa_OpenStream (the stream open fires a CM notification which, after the
        # 0.5 s sleep in _notify_devices_changed, arrives ~0.5-0.7 s after the
        # impl finishes).  Legitimate Windows device-settled notifications arrive
        # 1-2+ seconds after the initial unplug event, so they pass through.
        last = getattr(self, '_devices_refresh_last_t', 0.0)
        if now - last < 1.0:
            return
        self._devices_refresh_active = True
        try:
            self._on_devices_refreshed_impl()
        finally:
            self._devices_refresh_active = False
            self._devices_refresh_last_t = _time.monotonic()

    def _on_devices_refreshed_impl(self) -> None:
        """Inner implementation of _on_devices_refreshed (called with debounce guard held)."""
        import sounddevice as _sd
        previous_device = self.mic.selected_input_device

        # Close the active stream BEFORE terminating PortAudio. Calling
        # Pa_Terminate while a stream is open leaves the Python stream handle
        # dangling on a torn-down PortAudio instance; on Windows WMME this has
        # been observed to leave the next InputStream unable to deliver
        # samples even though it opens successfully.
        self.mic._close_stream_only()

        # Flush PortAudio's cached device list so query_devices() reflects
        # the current OS device state. Swift CoreAudio doesn't need this step.
        try:
            _sd._terminate()
            _sd._initialize()
        except Exception:
            pass

        # Re-enumerate and apply auto-selection (fingerprint-based diff,
        # aggregate filter, built-in fallback) — mirrors Swift
        # loadAvailableInputDevicesMacOS() auto-selection logic.
        # Suppress the _on_devices_changed callback to avoid re-entry.
        saved_cb = self.mic._on_devices_changed
        self.mic._on_devices_changed = None
        try:
            self.mic.load_available_input_devices()
        finally:
            self.mic._on_devices_changed = saved_cb

        # On Windows, PortAudio may not yet see a USB device that was present
        # before reinit — the OS needs a moment to re-register it.  If the
        # previously selected device is no longer in the list, wait briefly
        # and re-enumerate once before accepting a fallback device.
        import platform as _platform
        if _platform.system() == "Windows" and previous_device is not None:
            prev_fp = getattr(previous_device, "fingerprint", None)
            if prev_fp and not any(
                d.fingerprint == prev_fp for d in self.mic.available_input_devices
            ):
                import time as _time_mod
                _time_mod.sleep(1.0)
                self.mic._on_devices_changed = None
                try:
                    self.mic.load_available_input_devices()
                finally:
                    self.mic._on_devices_changed = saved_cb
        names: list[str] = sorted(d.name for d in self.mic.available_input_devices)
        self.devicesChanged.emit(names)

        # PortAudio was re-initialized, so the previous stream is dead — always
        # reopen on the currently-selected device (which may be the same one,
        # a newly-plugged device, or a fallback after disconnect).
        new_device = self.mic.selected_input_device
        if new_device is not None:
            self.set_device(new_device)
            self.handle_route_change_restart()

        # Notify the view if the previously active device disappeared.
        # Mirrors Swift's "disconnected" log path in loadAvailableInputDevicesMacOS().
        prev_name = getattr(previous_device, "name", None) or self._calibration_device_name
        if prev_name and prev_name not in names:
            self.currentDeviceLost.emit(prev_name)

    # ------------------------------------------------------------------ #
    # Calibration
    # ------------------------------------------------------------------ #

    def load_calibration(self, path: str) -> bool:
        """Load and interpolate a calibration file onto the FFT bin grid."""
        import os
        import models.microphone_calibration as _mc
        try:
            cal_data = _mc.parse_cal_file(path)
            self._calibration_corrections = _mc.interpolate_to_bins(cal_data, self.freq)
            # Try to build a MicrophoneCalibration profile for gated-FFT use.
            try:
                profile = _mc.MicrophoneCalibration.from_path(path)
            except Exception:
                profile = None
            self._calibration_profile = profile
            self.mic.set_calibration(self._calibration_corrections,
                                     profile=profile)
            # Track the calibration name (file stem) so it is saved with
            # measurements — mirrors load_calibration_from_profile().
            self._active_calibration_name = os.path.splitext(os.path.basename(path))[0] or None
            return True
        except Exception:
            return False

    def load_calibration_from_profile(self, cal) -> None:
        """Apply a pre-parsed MicrophoneCalibration profile to the FFT pipeline."""
        self._calibration_corrections = cal.interpolate_to_bins(self.freq)
        self._calibration_profile = cal
        self.mic.set_calibration(self._calibration_corrections,
                                 profile=cal)
        # Track the name so _on_export_pdf can report it — mirrors Swift activeCalibration?.name.
        self._active_calibration_name = getattr(cal, "name", None)

    def set_temporary_calibration(self, cal) -> None:
        """Apply calibration for file playback without persisting to storage.

        Unlike ``load_calibration_from_profile``, this does not save the
        calibration to ``CalibrationStorage`` or associate it with a device.
        Mirrors Swift ``RealtimeFFTAnalyzer.setTemporaryCalibration(_:)``.
        """
        if cal is not None:
            self._calibration_corrections = cal.interpolate_to_bins(self.freq)
            self._calibration_profile = cal
            self.mic.set_calibration(self._calibration_corrections, profile=cal)
            self._active_calibration_name = getattr(cal, "name", None)
        else:
            self._calibration_corrections = None
            self._calibration_profile = None
            self._active_calibration_name = None
            self.mic.set_calibration(None)

    def clear_calibration(self) -> None:
        """Remove the active calibration."""
        self._calibration_corrections = None
        self._calibration_profile = None
        self._active_calibration_name = None
        self.mic.set_calibration(None)

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self._calibration_device_name

    def set_device(self, device) -> None:
        """Switch to a different input device.

        Delegates to RealtimeFFTAnalyzer.set_device(), which owns the stream
        restart and calibration auto-load (via _on_mic_calibration_changed).
        _gated_sample_rate and _pre_roll_samples are computed properties that
        read self.mic.rate directly, so they automatically reflect the new
        device rate — mirrors Swift where preRollSamples and gatedCaptureSamples
        are computed vars that always read from mpmSampleRate.

        Mirrors Swift TapToneAnalyzer+Control.swift: setInputDevice is called
        on fftAnalyzer, then selectedInputDevice.didSet applies calibration —
        both now happen inside RealtimeFFTAnalyzer.set_device().
        """
        self._calibration_device_name = device.name
        self.mic.set_device(device)
        # Recompute self.freq from the new device's sample rate.
        # Mirrors Swift start() calling updateFrequencyBins() after the engine
        # restarts with the new device — ensures the frequency axis matches
        # the actual hardware sample rate.
        self._update_frequency_bins()

    def _on_mic_calibration_changed(self, cal) -> None:
        """Apply the calibration profile emitted by RealtimeFFTAnalyzer.set_device().

        Mirrors Swift setCalibrationWithoutSavingDeviceMapping(_:) called from
        selectedInputDevice.didSet.  Receives a MicrophoneCalibration profile
        (or None) and applies or clears it on the FFT pipeline.
        """
        if cal is not None:
            self.load_calibration_from_profile(cal)
        else:
            self.clear_calibration()

    def handle_route_change_restart(self) -> None:
        """Respond to an audio-engine restart triggered by a device or route change.

        Mirrors Swift TapToneAnalyzer.handleRouteChangeRestart():
        - If detection was active: temporarily disable, reset warmup timer,
          wait 3 s for the FFT buffer to refill (covering HALC startup transients),
          then restore is_detecting.
        - If is_measurement_complete (frozen result): leave it untouched.
        - If idle (not detecting): stay idle.
        - If the display was live: blank the spectrum and clear peak annotations
          during the settle period so the view shows nothing rather than stale data.

        The 3-second settle delay mirrors Swift's fftSettleTime constant (extended
        from 2 s to absorb HALC/CoreAudio startup transients at ~2.5 s).
        """
        import numpy as np
        from models.analysis_display_mode import AnalysisDisplayMode as _ADM
        from PySide6.QtCore import QTimer as _QTimer

        gt_log("🔄 TapToneAnalyzer: Handling route change restart - resetting detection state")

        was_detecting = self.is_detecting

        # Disable the is_ready_for_detection flag while reinitialising.
        # Mirrors Swift: isReadyForDetection = false / isDetecting = false.
        self.is_ready_for_detection = False
        self.is_detecting = False

        # Reset the warmup timer so the new engine session starts cleanly.
        # Mirrors Swift: analyzerStartTime = Date().
        self.warmup_start_audio_time = self._audio_now()

        # Pre-set is_above_threshold = True so the first FFT frame does not fire a
        # false rising edge.  The actual value is corrected after the settle delay.
        # Mirrors Swift: isAboveThreshold = true / tapDetected = false.
        self.is_above_threshold = True
        self.tap_detected = False

        # Freeze the display on a blank spectrum while the pipeline refills with
        # valid data from the new device.  Only freeze if we were in live mode —
        # don't disturb a frozen measurement result.
        # Mirrors Swift: wasLive / setFrozenSpectrum([], []) / displayMode = .frozen /
        #                currentPeaks = [] / identifiedModes = [].
        was_live = (self.display_mode == _ADM.LIVE)
        if was_live:
            self.set_frozen_spectrum(np.array([]), np.array([]))
            self.display_mode = _ADM.FROZEN
            self.all_peaks = []
            self.identified_modes = []
            self.peaksChanged.emit([])

        # Mirrors Swift: statusMessage = "Audio device changed - reinitializing...".
        self._set_status_message("Audio device changed - reinitializing...")

        # Wait for the FFT pipeline to fill with valid post-restart data
        # (~1.36 s for 65 536 samples at 48 kHz).  Use 3 s to absorb HALC/CoreAudio
        # startup transients that can arrive at ~2.5 s on the engine-recovery path.
        # Mirrors Swift: fftSettleTime = 3.0 / DispatchQueue.main.asyncAfter.
        self._main_async_after(
            3000,
            lambda: self._restore_detection_after_route_change(was_detecting, was_live),
        )

    def _restore_detection_after_route_change(self, was_detecting: bool, was_live: bool = False) -> None:
        """Re-anchor threshold and restore detection state after the settle delay.

        This method is the structural equivalent of the combined
        DispatchQueue.main.asyncAfter + $magnitudes.dropFirst().first() sink
        closure in Swift's handleRouteChangeRestart().  It is a named method
        rather than an inline lambda only because _main_async_after requires a
        callable — it should not be called from anywhere else.

        Mirrors Swift's inner sink:
        - Guards that the stream is still running.
        - Re-anchors is_above_threshold to the current FFT peak magnitude.
        - Calls setFrozenSpectrum([], []) then restores displayMode to .live.
        - Sets isReadyForDetection = true.
        - Restores is_detecting and status message.
        """
        import numpy as np
        from models.analysis_display_mode import AnalysisDisplayMode as _ADM

        # Guard: stream may have been stopped again before the timer fired.
        # Mirrors Swift: guard self.fftAnalyzer.isRunning else { return }.
        if self.mic.is_stopped:
            return

        # Re-anchor is_above_threshold to the current FFT peak magnitude.
        # Mirrors Swift: let currentPeakMag = fftAnalyzer.peakMagnitude /
        #                isAboveThreshold = (currentPeakMag > tapDetectionThreshold).
        current_level = self._current_peak_magnitude_db
        self.is_above_threshold = current_level > self.tap_detection_threshold

        # Unfreeze the display now that valid FFT data is available.
        # Mirrors Swift: setFrozenSpectrum([], []) / displayMode = .live.
        if was_live:
            self.set_frozen_spectrum(np.array([]), np.array([]))
            self.display_mode = _ADM.LIVE

        # Mirrors Swift: isReadyForDetection = true.
        self.is_ready_for_detection = True

        # Mirrors Swift: isDetecting / statusMessage restore block.
        if was_detecting:
            self.is_detecting = True
            self._set_status_message(self._tap_prompt())
        else:
            self._set_status_message("Ready")

        gt_log(f"🔄 TapToneAnalyzer: Detection re-enabled after route change "
               f"(current level: {current_level} dB, threshold: {self.tap_detection_threshold} dB, "
               f"above threshold: {self.is_above_threshold})")

    # ------------------------------------------------------------------ #
    # Tap detector control — all state lives directly on TapToneAnalyzer,
    # mirroring Swift where detectTap() and all tap state are on the class.
    # ------------------------------------------------------------------ #

    def set_tap_threshold(self, value: int) -> None:
        """Update tap-trigger threshold (0-100 scale → dBFS)."""
        self.tap_detection_threshold = float(value - 100)
        # Keep the audio-queue level-crossing threshold in sync.
        # Mirrors Swift tapDetectionThreshold.didSet updating fftAnalyzer.levelCrossingThreshold.
        if self.mic is not None:
            self.mic._level_crossing_threshold = self.tap_detection_threshold
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_tap_detection_threshold(self.tap_detection_threshold)
        # Mirrors Swift tapDetectionThreshold.didSet: clear warning if user deviates from loaded value.
        if (self.show_loaded_settings_warning
                and self.loaded_tap_detection_threshold is not None
                and self.tap_detection_threshold != self.loaded_tap_detection_threshold):
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)

    def pause_tap_detection(self) -> None:
        """Pause tap detection mid-sequence without losing the current tap count.

        No-op when not currently detecting or already paused.
        Mirrors Swift pauseTapDetection() guard: isDetecting && !isDetectionPaused.
        """
        if not self.is_detecting or self.is_detection_paused:
            return
        self.is_detecting = False
        self.is_detection_paused = True
        # Stop accumulating audio during pause — mirrors Swift pauseTapDetection.
        self._is_session_recording = False
        self._set_status_message("Detection paused – tap freely, then resume")
        self.tapDetectionPaused.emit(True)

    def resume_tap_detection(self) -> None:
        """Resume tap detection after a pause, continuing from the current tap count.

        No-op when not paused.
        Mirrors Swift resumeTapDetection() guard: isDetectionPaused.
        Resets the warm-up timer inline (mirrors Swift analyzerStartTime = Date();
        isAboveThreshold = false) without calling the full reset_tap_detector().
        """
        if not self.is_detection_paused:
            return
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        self.is_detection_paused = False

        # Reset warm-up timer to prevent an immediate false trigger on the first frame.
        # Mirrors Swift: analyzerStartTime = Date(); isAboveThreshold = false
        self.warmup_start_audio_time = self._audio_now()
        self.is_above_threshold = False

        # Resume accumulating audio after pause — mirrors Swift resumeTapDetection.
        self._is_session_recording = True
        self.is_detecting = True

        # Restore a context-appropriate prompt (mirrors Swift resumeTapDetection).
        resume_type = _tds.measurement_type()
        is_plate = (resume_type == _MT.PLATE)
        is_brace = (resume_type == _MT.BRACE)
        if is_plate or is_brace:
            from models.material_tap_phase import MaterialTapPhase as _MTP
            phase = getattr(self, "material_tap_phase", _MTP.NOT_STARTED)
            if phase == _MTP.CAPTURING_LONGITUDINAL:
                self._set_status_message("Ready for fL tap" if is_brace else "Ready for L tap")
            elif phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP):
                self._set_status_message("Ready for FLC tap")
            else:
                self._set_status_message("Ready for C tap")
        elif self.current_tap_count == 0:
            self._set_status_message(self._tap_prompt())
        else:
            self._set_status_message(
                f"Tap {self.current_tap_count}/{self.number_of_taps} captured. Tap again..."
            )

        self.tapDetectionPaused.emit(False)

    # ------------------------------------------------------------------ #
    # Tap sequence management
    # ------------------------------------------------------------------ #

    def start_from_file(self, path: str,
                        on_finished: "Callable[[], None] | None" = None) -> None:
        """Feed an audio file through the FFT pipeline instead of the microphone.

        Starts the file playback thread and recomputes the FFT frequency axis to
        match the file's sample rate.  Does NOT arm tap detection — the caller
        (view layer) is responsible for calling start_tap_sequence(skip_warmup=True)
        afterwards, exactly as Swift's openAudioFile(_:) does.

        Mirrors Swift RealtimeFFTAnalyzer.startFromFile(_:completion:):
          - mic.start_from_file  ↔  fft.startFromFile(url, completion:)
          - _update_frequency_bins  ↔  updateFrequencyBins() + updateMetrics()
          - on_finished callback  ↔  the completion: closure (releases security-scoped
            resource on iOS; here used to restore the freq axis and emit title changes).

        Args:
            path:        Filesystem path to the audio file.
            on_finished: Optional closure called from the playback thread after the
                         mic stream has been restarted.  Mirrors Swift's completion
                         parameter on startFromFile(_:completion:).
        """
        # Wire the completion callback.  Mirrors Swift's completion block that releases
        # security-scoped resource access after playback.  Python uses it to restore the
        # frequency axis; the view no longer passes a closure (on_finished=None).
        def _on_finished_wrapper() -> None:
            # Restore frequency axis to the mic's hardware rate now that the
            # mic stream has been restarted (mic.rate is back to hardware rate).
            # Mirrors Swift's start() → updateFrequencyBins() inside the asyncAfter block.
            # Must run on the main thread — _update_frequency_bins writes self.freq which
            # on_fft_frame reads on the main thread (no lock).
            self._main_async_after(0, self._update_frequency_bins)
            if on_finished is not None:
                on_finished()

        self.mic._on_playback_finished = _on_finished_wrapper

        # _on_pre_mic_restart is already wired by _wire_pipeline_signals()
        # (called from __init__ or start()), so any active gated capture is
        # zero-padded and completed before mic noise can fill the remaining
        # window.  Mirrors Swift preMicRestartHandler wired in setupSubscriptions().

        self.mic.start_from_file(path)

        # Pre-roll is cleared (not zero-filled) inside start_from_file via
        # the _on_post_engine_stop callback (wired by _wire_pipeline_signals),
        # matching Swift where postEngineStopHandler clears preRollBuffer
        # after the engine stops.  The buffer fills naturally with real
        # audio as file chunks arrive.

        # Recompute the frequency axis now that mic.rate reflects the file's sample rate.
        # Mirrors Swift updateFrequencyBins() called synchronously inside startFromFile
        # before the main-thread async block sets isPlayingFile / playingFileName.
        self._update_frequency_bins()

    # @parity state/tap-tone-analyzer
    def start_tap_sequence(self, skip_warmup: bool = False, initial_phase=None) -> None:
        """Begin a new tap detection sequence, resetting all per-sequence state.

        Mirrors Swift startTapSequence() including:
        - Seeds noise_floor_estimate from the current ambient level (fftAnalyzer.inputLevelDB).
        - Calls _reset_decay_tracking().
        - Calls _reset_material_phase_state() for plate/brace.
        - Sets is_detecting = True.
        - Sets context-appropriate status_message.
        - Clears previous peaks, spectra, and annotation offsets.
        """
        import numpy as np
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds

        from .analysis_display_mode import AnalysisDisplayMode as _ADM

        meas_type = _tds.measurement_type()
        is_plate = (meas_type == _MT.PLATE)
        is_brace = (meas_type == _MT.BRACE)

        gt_log(f"🎬 Analyzer started - warm-up period: {self.warmup_period}s")
        gt_log(f"🎬 Starting tap sequence: {self.number_of_taps} tap(s),"
               f" plate mode: {is_plate}, brace mode: {is_brace},"
               f" skip_warmup: {skip_warmup}")

        # Mirrors Swift startTapSequence() lines 140-143:
        #   self.comparisonSpectra = []
        #   self.displayMode = .live
        #   self.loadedMeasurementName = nil  (set below)
        #   self.isMeasurementComplete = false
        # Clear comparison state on the model, matching Swift's model-owned clear.
        self.clear_comparison()
        self._display_mode = _ADM.LIVE
        self.show_loaded_settings_warning = False
        self.showLoadedSettingsWarningChanged.emit(False)

        # Mirrors Swift: isMeasurementComplete = false (clears frozen state before new sequence).
        # Emitted here so the view transitions to live mode before audio starts.
        self.is_measurement_complete = False
        self.measurementComplete.emit(False)

        # Clear per-sequence accumulated data (mirrors Swift startTapSequence async block).
        self.captured_taps.clear()
        self.tap_entries = []
        self.showing_multi_tap_comparison = False
        self.current_tap_count = 0
        self.tap_progress = 0.0
        self.tap_detected = False
        self.is_detection_paused = False

        # Cancel any in-flight gated capture from a previous sequence and drop
        # the pre-roll ring buffer.  Without this, a gated capture that was
        # mid-fill when the new sequence starts will eventually complete and
        # append a stale entry into the now-cleared captured_taps list, and the
        # pre-roll buffer would carry stale audio from the previous run into
        # the next gated capture's leading window.
        #
        # Session recording: clear the buffer and begin recording.  The buffer
        # accumulates raw audio while detection is active, producing a single
        # WAV per measurement for replay.  Seed checkpoints with [0] so the
        # first phase has a truncation anchor — without it, redoing the first
        # phase (or the same phase repeatedly) would leave the rejected tap's
        # audio in the saved WAV.  See accept_current_phase / redo_current_phase.
        with self._gated_lock:
            self._gated_capture_active = False
            self._gated_accum = []
            self._pre_roll_buf = []
            # Clear the audio-queue fast-start markers so the first tap of this
            # sequence cannot mistake a stale "already handled" equality
            # (_gated_capture_id == _last_level_crossing_capture_id) for a real
            # fast-start capture.  A material (plate/brace) completion leaves
            # these two IDs equal — unlike the guitar re-enable paths, it never
            # resets them — so a material→guitar switch would otherwise make
            # start_guitar_gated_capture bail out (accum 0 samples) without
            # capturing or completing, stranding the analyzer with all tap
            # controls disabled.  Mirrors _on_post_engine_stop /
            # re_enable_detection_for_next_plate_tap.
            self._gated_capture_id = 0
            self._last_level_crossing_capture_id = -1
            self._session_recording_buffer = []
            self._session_checkpoints = [0]
            self._is_session_recording = True
            self._session_pre_roll_active = True  # bound the pre-first-tap audio to ~2 s (§6)
            self._session_recording_sample_rate = (
                self._mpm_sample_rate if self._mpm_sample_rate > 0 else 48000.0
            )

        # Seed the noise-floor estimate so the first relative-threshold
        # calculation has a reasonable baseline.  Seed from the current input level; the warm-up's EMA
        # then converges it, and the warm-up-exit re-anchor snaps it to the real floor.
        #
        # The -100 case now only arises when the warm-up is skipped, which -- since callers key
        # skip_warmup on the MEASUREMENT TYPE -- means GUITAR, where the estimate is never read (guitar
        # uses the absolute threshold).  It must not be reached for material: -100 makes
        #     headroom = max(threshold - (-100), 10) = threshold + 100
        #     rising   = -100 + headroom             = threshold
        # i.e. the relative rule collapses onto the absolute one, silently disabling the very model it
        # is meant to implement.  That is what used to happen on EVERY file playback, which is why the
        # relative detector was never exercised by any regression test on any platform.
        # See GuitarTapWeb/Development/OUT-4-DETECTION-SPEC.md.
        # Mirrors Swift TapToneAnalyzer+Control.swift noiseFloorEstimate.
        self.noise_floor_estimate = -100.0 if skip_warmup else self._current_input_level_db

        self.current_decay_time = None
        self.peak_magnitude_history = []
        self._reset_decay_tracking()

        # Initialise plate/brace phase state (mirrors Swift resetMaterialPhaseState(to: newPhase)).
        # If initial_phase is provided (used by playFileForTesting for phase-targeted
        # plate testing), use it instead of the default .capturingLongitudinal.
        if is_plate or is_brace:
            new_phase = initial_phase if initial_phase is not None else _MTP.CAPTURING_LONGITUDINAL
        else:
            new_phase = _MTP.NOT_STARTED
        self._reset_material_phase_state(to=new_phase)

        # Clear annotation offsets so dragged positions reset for the new measurement.
        self.reset_all_annotation_offsets()

        # Clear frozen spectrum so live FFT is shown while waiting for taps.
        self.set_frozen_spectrum(np.array([]), np.array([]))

        # For live mic: start with is_above_threshold = False so the first real tap
        # produces a genuine rising edge.  The warm-up period suppresses detections
        # for the first warmup_period seconds.
        #
        # For file playback (skip_warmup): start with is_above_threshold = True so
        # the detector requires a falling edge (signal drops below threshold) before
        # any rising edge can fire.  This prevents the file's opening audio — which
        # may be mid-decay from a prior tap and already above threshold — from
        # immediately triggering a false first tap that captures garbage.
        # The decay will naturally fall below threshold, then the real first tap
        # attack will produce the genuine rising edge.
        self.is_above_threshold = skip_warmup
        self.just_exited_warmup = False  # Will be set True as warm-up ends.

        # Reset the warm-up timer for this new sequence.
        # Mirrors Swift TapToneAnalyzer+Control.swift startTapSequence(skipWarmup:):
        # For file playback (skip_warmup=True) set the start time far enough in the
        # past that the warmup_period has already elapsed when the first audio buffer
        # arrives.  The audio source is deterministic, so no startup-noise suppression
        # is needed, and the tap transient may appear within the first 0.5 s of the file.
        if skip_warmup:
            # AUDIO clock — backdate so the window has already elapsed at the first chunk.
            self.warmup_start_audio_time = self._audio_now() - (self.warmup_period + 0.1)
        else:
            self.warmup_start_audio_time = self._audio_now()

        self.is_detecting = True

        # Set context-appropriate status message (mirrors Swift lines 184-196).
        if is_brace:
            self._set_status_message(
                f"Ready for fL tap (×{self.number_of_taps})"
                if self.number_of_taps > 1
                else "Ready for fL tap"
            )
        elif is_plate:
            measure_flc = _tds.measure_flc()
            if self.number_of_taps > 1:
                phases = "L, C, FLC" if measure_flc else "L, C"
                self._set_status_message(
                    f"Ready for L tap (×{self.number_of_taps} each for {phases})"
                )
            else:
                self._set_status_message("Ready for L tap")
        else:
            self._set_status_message(self._tap_prompt())

        # Clear previous results so the chart shows a clean slate while waiting.
        self.all_peaks = []
        self.identified_modes = []

        # Mirrors Swift startTapSequence: loadedMeasurementName = nil
        self.loaded_measurement_name = None
        self.source_measurement_timestamp = None
        self.loadedMeasurementNameChanged.emit(None)

        # Also clear the played-file name so the chart title reverts to "New"
        # when the user starts a fresh tap sequence (e.g. by changing
        # measurement type across the guitar/material boundary).  Without
        # this, chart_title — computed as
        #   fft.playing_file_name ?? tap.loaded_measurement_name ?? "New"
        # — keeps showing the previously-played filename even though the new
        # sequence is unrelated to that file.  For the file-playback path
        # (start_from_file) this is harmless because process_file_data
        # re-assigns playing_file_name immediately after start_tap_sequence
        # returns.
        if self.mic is not None and getattr(self.mic, "playing_file_name", None) is not None:
            self.mic.playing_file_name = None
            self.playingFileNameChanged.emit(None)

        self.tapCountChanged.emit(0, self.number_of_taps)

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing.

        Mirrors Swift numberOfTaps.didSet.

        NOTE: there is deliberately NO "reduce the count mid-sequence -> finalise with the taps
        already captured" branch.  The tap-count spinner is disabled the moment a sequence has a
        tap -- ``setEnabled(not (captured > 0 and not complete))``, matching Swift's
        ``.disabled(currentTapCount > 0 && !isMeasurementComplete)`` -- so the count simply cannot
        change mid-sequence; to change it you cancel first.  The branch that used to live here was
        therefore unreachable, and being unreachable it had silently drifted three ways: Swift
        deferred processing by ``captureWindow`` and averaged ALL captured taps, this method
        finalised synchronously and TRUNCATED to the new count, and the web never implemented it at
        all.  Removed rather than reconciled (OUT-5) -- reachable behaviour is unchanged.

        If a mid-sequence count change is ever wanted, unlock the spinner and define the semantics
        deliberately -- do not resurrect an implicit finalise.
        """
        self.number_of_taps = max(1, n)
        # Raising the count mid-sequence does NOT clear what was already captured (mirrors Swift,
        # which never clears capturedTaps here) -- though the spinner lock means this cannot be
        # reached from the UI either.
        # Mirrors Swift numberOfTaps.didSet: clear warning if user deviates from loaded value.
        if (self.show_loaded_settings_warning
                and self.loaded_number_of_taps is not None
                and self.number_of_taps != self.loaded_number_of_taps):
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)
        # Mirrors Swift numberOfTaps.didSet: update status message when waiting
        # for the first tap (isDetecting=True, currentTapCount=0).
        if self.is_detecting and len(self.captured_taps) == 0:
            self._set_status_message(self._tap_prompt())

    # ------------------------------------------------------------------ #
    # Cancel
    # ------------------------------------------------------------------ #

    def cancel_tap_sequence(self) -> None:
        """Cancel the current tap sequence by restarting it.

        Cancel is a **restart**: it returns to the exact state that New Tap
        produces — a fresh, re-armed sequence waiting for the first tap — rather
        than completing the measurement.  (Previously this set
        is_measurement_complete = True purely to re-enable the New Tap button;
        that button-gating hack is gone now that the button rule keys off
        is_measurement_complete.)  Cancel is only offered while a multi-step
        (multi-tap or multi-phase) sequence is in progress.  Mirrors Swift
        cancelTapSequence().
        """
        gt_log("❌ Tap sequence cancelled — restarting")
        # A pending capture-completion timer from the abandoned sequence must not
        # fire into the fresh one (mirrors Swift captureTimer?.invalidate()).
        self.capture_timer_active = False
        # Re-arm a fresh sequence — identical to pressing New Tap. start_tap_sequence
        # clears captured taps / counts / frozen spectrum, resets the material phase,
        # restarts session recording, sets is_detecting = True with the correct status,
        # and emits tapCountChanged / measurementComplete(False).
        self.start_tap_sequence()

    # ------------------------------------------------------------------ #
    # Phase Review — Accept / Redo
    # Mirrors Swift TapToneAnalyzer+Control acceptCurrentPhase() / redoCurrentPhase()
    # ------------------------------------------------------------------ #

    def accept_current_phase(self) -> None:
        """Advance from a reviewing phase to the next capture phase (or complete).

        Called when the user presses Accept after reviewing a frozen spectrum.
        Mirrors Swift TapToneAnalyzer+Control.acceptCurrentPhase().
        """
        import time as _time_mod

        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from models.tap_display_settings import TapDisplaySettings as _tds

        # Session recording: checkpoint the current buffer position so that
        # if a subsequent phase is redone, we can truncate back to here.
        # Mirrors Swift acceptCurrentPhase checkpoint append.
        with self._gated_lock:
            self._session_checkpoints.append(len(self._session_recording_buffer))

        phase = self.material_tap_phase

        if phase == _MTP.REVIEWING_LONGITUDINAL:
            # Advance to cross-grain capture.
            # Mirrors Swift: set phase first, then clear frozen spectrum.
            self._set_material_tap_phase(_MTP.CAPTURING_CROSS)
            self.set_frozen_spectrum(_np.array([]), _np.array([]))
            level = self._current_input_level_db
            falling = self.tap_detection_threshold - self.hysteresis_margin
            self.is_above_threshold = level > falling
            self.warmup_start_audio_time = self._audio_now()
            self.is_detecting = True
            self.tap_detected = False
            self._set_status_message("Rotate 90° and tap for C")

        elif phase == _MTP.REVIEWING_CROSS:
            if _tds.measure_flc():
                # Advance to FLC waiting then capturing.
                # Mirrors Swift: set WAITING_FOR_FLC_TAP and status message first,
                # then transition to CAPTURING_FLC and clear frozen spectrum inside
                # the asyncAfter closure (after the cooldown delay).
                self._set_material_tap_phase(_MTP.WAITING_FOR_FLC_TAP)
                self._set_status_message("Set up for FLC tap, then tap")
                cooldown = self.tap_cooldown
                self._main_async_after(int(cooldown * 1000), self._do_start_flc)
            else:
                # No FLC — finalise measurement now.
                self._finalise_plate_no_flc()

        elif phase == _MTP.REVIEWING_FLC:
            # Finalise measurement with all three phases.
            self._finalise_plate_with_flc()

        else:
            gt_log(f"⚠️ accept_current_phase called in unexpected phase: {phase}")

    def redo_current_phase(self) -> None:
        """Clear the current phase's data and re-arm detection to re-capture it.

        Called when the user presses Redo after reviewing a frozen spectrum.
        Only the current phase's data is cleared; earlier phases are preserved.
        Mirrors Swift TapToneAnalyzer+Control.redoCurrentPhase().
        """
        import time as _time_mod

        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP

        # Session recording: truncate back to the start of the current phase
        # so the rejected tap's audio is excluded from the saved WAV.
        # Peek (don't pop) — the anchor must remain in place so that a second
        # redo of the same phase truncates to the same position, not to the
        # start of the *previous* accepted phase.  Mirrors Swift redoCurrentPhase.
        with self._gated_lock:
            if self._session_checkpoints:
                phase_start = self._session_checkpoints[-1]
                if len(self._session_recording_buffer) > phase_start:
                    del self._session_recording_buffer[phase_start:]
                    # Redoing the FIRST phase empties the buffer back to the pre-first-tap state,
                    # so re-arm the bounded pre-roll (§6). Later phases keep the latch frozen.
                    if phase_start == 0:
                        self._session_pre_roll_active = True

        phase = self.material_tap_phase

        if phase == _MTP.REVIEWING_LONGITUDINAL:
            # Clear longitudinal data only.
            self.longitudinal_spectrum = None
            self.longitudinal_peaks = []
            self.auto_selected_longitudinal_peak_id = None
            self.selected_longitudinal_peak = None
            self.user_selected_longitudinal_peak_id = None
            self.captured_taps.clear()
            self.current_tap_count = 0
            self.tap_progress = 0.0
            capture_phase = _MTP.CAPTURING_LONGITUDINAL
            status_msg = "Ready for L tap — tap again"
            # longitudinalSpectrum = nil → materialSpectra returns [] → live curve restored.
            self.set_material_spectra([])

        elif phase == _MTP.REVIEWING_CROSS:
            # Clear cross data only — longitudinal stays.
            self.cross_spectrum = None
            self.cross_peaks = []
            self.auto_selected_cross_peak_id = None
            self.selected_cross_peak = None
            self.user_selected_cross_peak_id = None
            self.captured_taps.clear()
            # Mirrors Swift: lCount = (longitudinalSpectrum != nil) ? numberOfTaps : 0
            l_count = self.number_of_taps if self.longitudinal_spectrum is not None else 0
            self.current_tap_count = l_count
            self.tap_progress = float(l_count) / float(self.total_plate_taps)
            capture_phase = _MTP.CAPTURING_CROSS
            status_msg = "Ready for C tap — tap again"
            # crossSpectrum = nil → materialSpectra returns [L only] → show longitudinal overlay.
            spectra = []
            if self.longitudinal_spectrum:
                l_mags, l_freqs = self.longitudinal_spectrum
                spectra.append(("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)))
            self.set_material_spectra(spectra)

        elif phase == _MTP.REVIEWING_FLC:
            # Clear FLC data only — L and C stay.
            self.flc_spectrum = None
            self.flc_peaks = []
            self.auto_selected_flc_peak_id = None
            self.selected_flc_peak = None
            self.user_selected_flc_peak_id = None
            self.captured_taps.clear()
            # Mirrors Swift: lcCount = (longitudinalSpectrum != nil && crossSpectrum != nil) ? numberOfTaps * 2 : 0
            lc_count = (
                self.number_of_taps * 2
                if (self.longitudinal_spectrum is not None and self.cross_spectrum is not None)
                else 0
            )
            self.current_tap_count = lc_count
            self.tap_progress = float(lc_count) / float(self.total_plate_taps)
            capture_phase = _MTP.CAPTURING_FLC
            status_msg = "Ready for FLC tap — tap again"
            # flcSpectrum = nil → materialSpectra returns [L, C] → show both overlays.
            spectra = []
            if self.longitudinal_spectrum:
                l_mags, l_freqs = self.longitudinal_spectrum
                spectra.append(("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)))
            if self.cross_spectrum:
                c_mags, c_freqs = self.cross_spectrum
                spectra.append(("Cross-grain (C)", (255, 149, 0), list(c_freqs), list(c_mags)))
            self.set_material_spectra(spectra)

        else:
            gt_log(f"⚠️ redo_current_phase called in unexpected phase: {phase}")
            return

        # Clear frozen spectrum for the redo.
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        # Notify the view of the updated cumulative tap count so the spinner
        # lock and phase label reflect the correct state (mirrors Swift where
        # currentTapCount is @Published and the view re-renders automatically).
        self.tapCountChanged.emit(self.current_tap_count, self.number_of_taps)

        # Reset warm-up and re-arm detection.
        level = self._current_input_level_db
        falling = self.tap_detection_threshold - self.hysteresis_margin
        self.is_above_threshold = level > falling
        self.warmup_start_audio_time = self._audio_now()
        self.is_detecting = True
        self.tap_detected = False

        self._set_material_tap_phase(capture_phase)
        self._set_status_message(status_msg)

    def _finalise_plate_no_flc(self) -> None:
        """Complete a two-tap plate measurement (L + C, no FLC).

        Called from accept_current_phase when leaving REVIEWING_CROSS without FLC.
        Mirrors the no-FLC branch of Swift acceptCurrentPhase.
        """
        import numpy as _np

        sel = self._resolved_plate_peaks(
            cross_override=self.selected_cross_peak or (self.cross_peaks[0] if self.cross_peaks else None)
        )
        self.all_peaks = sel
        self.selected_peak_ids = {p.id for p in sel}
        self.selected_peak_frequencies = [p.frequency for p in sel]
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        from models.material_tap_phase import MaterialTapPhase as _MTP
        self._set_material_tap_phase(_MTP.COMPLETE)
        self.set_measurement_complete(True)
        # Save the session WAV — mirrors Swift finishSessionRecording(label: "Plate_LC").
        self.finish_session_recording(label="Plate_LC")
        # Mirrors Swift isMeasurementComplete.didSet: clear warning on successful new tap.
        if self.show_loaded_settings_warning:
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)
        self.tap_progress = 1.0

        fl_str = (
            f"{self.selected_longitudinal_peak.frequency:.1f}"
            if self.selected_longitudinal_peak else "?"
        )
        fc_str = (
            f"{self.selected_cross_peak.frequency:.1f}"
            if self.selected_cross_peak else "?"
        )
        self._set_status_message(
            f"Complete \u2014 fL: {fl_str} Hz, fC: {fc_str} Hz"
        )

        self._emit_peaks_array(self.current_peaks)

        l_mags, l_freqs = self.longitudinal_spectrum
        c_mags, c_freqs = self.cross_spectrum
        self.set_material_spectra([
            ("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)),
            ("Cross-grain (C)",  (255, 149, 0), list(c_freqs), list(c_mags)),
        ])

        fl = self.selected_longitudinal_peak.frequency if self.selected_longitudinal_peak else 0.0
        fc = self.selected_cross_peak.frequency if self.selected_cross_peak else 0.0
        self.plateAnalysisComplete.emit(fl, fc, 0.0)

    def _finalise_plate_with_flc(self) -> None:
        """Complete a three-tap plate measurement (L + C + FLC).

        Called from accept_current_phase when leaving REVIEWING_FLC.
        Mirrors the FLC branch of Swift acceptCurrentPhase.
        """
        import numpy as _np

        sel = self._resolved_plate_peaks(
            include_cross=True,
            include_flc=True,
            flc_override=self.selected_flc_peak or (self.flc_peaks[0] if self.flc_peaks else None),
        )
        self.all_peaks = sel
        self.selected_peak_ids = {p.id for p in sel}
        self.selected_peak_frequencies = [p.frequency for p in sel]
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        from models.material_tap_phase import MaterialTapPhase as _MTP
        self._set_material_tap_phase(_MTP.COMPLETE)
        self.set_measurement_complete(True)
        # Save the session WAV — mirrors Swift finishSessionRecording(label: "Plate_LCF").
        self.finish_session_recording(label="Plate_LCF")
        # Mirrors Swift isMeasurementComplete.didSet: clear warning on successful new tap.
        if self.show_loaded_settings_warning:
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)
        self.tap_progress = 1.0
        self._set_status_message("Complete - check Results")

        self._emit_peaks_array(self.current_peaks)

        l_mags, l_freqs = self.longitudinal_spectrum
        c_mags, c_freqs = self.cross_spectrum
        f_mags, f_freqs = self.flc_spectrum
        self.set_material_spectra([
            ("Longitudinal (L)", (0, 122, 255), list(l_freqs), list(l_mags)),
            ("Cross-grain (C)",  (255, 149, 0), list(c_freqs), list(c_mags)),
            ("FLC",              (175, 82, 222), list(f_freqs), list(f_mags)),
        ])

        l_freq = self.selected_longitudinal_peak.frequency if self.selected_longitudinal_peak else 0.0
        c_freq = self.selected_cross_peak.frequency if self.selected_cross_peak else 0.0
        f_freq = self.selected_flc_peak.frequency if self.selected_flc_peak else 0.0
        self.plateAnalysisComplete.emit(l_freq, c_freq, f_freq)

    # ------------------------------------------------------------------ #
    # Measurement type
    # ------------------------------------------------------------------ #

    def set_measurement_type(self, measurement_type) -> None:
        """Switch between Guitar / Plate / Brace analysis modes."""
        import models.measurement_type as _mt_mod
        if isinstance(measurement_type, str):
            measurement_type = _mt_mod.MeasurementType.from_combo_values(measurement_type, "")
        self._measurement_type = measurement_type

    # ------------------------------------------------------------------ #
    # Axis and parameter setters
    # ------------------------------------------------------------------ #

    def set_threshold(self, threshold: int) -> None:
        """Set the peak-detection threshold (0-100 scale, stored as dBFS)."""
        # Assigning peak_min_threshold re-projects (the property setter, mirroring Swift didSet).
        self.peak_min_threshold = float(threshold - 100)
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_peak_min_threshold(self.peak_min_threshold)
        # Notify the view the projection changed (current_peaks is a plain attr, not @Published).
        self.peaksChanged.emit(list(self.current_peaks))

    def set_fmin(self, fmin: int) -> None:
        self.update_axis(fmin, int(self.max_frequency))

    def set_fmax(self, fmax: int) -> None:
        self.update_axis(int(self.min_frequency), fmax)

    def update_axis(self, fmin: int, fmax: int, init: bool = False) -> None:
        """Update the frequency analysis range."""
        if fmin < fmax:
            self.min_frequency = float(fmin)
            self.max_frequency = float(fmax)
        if not init:
            self.recalculate_frozen_peaks_if_needed()

    def set_loaded_axis_range(
        self, min_freq: int, max_freq: int, min_db: float, max_db: float
    ) -> None:
        """Publish all four axis bounds atomically via loadedAxisRangeChanged.

        Mirrors Swift TapToneAnalyzer.setLoadedAxisRange(minFreq:maxFreq:minDB:maxDB:)
        which sets loadedAxisRange (a struct) in a single objectWillChange notification so
        the view applies all four bounds in one render pass.

        Also calls update_axis() to keep the model's peak-analysis frequency range in sync,
        matching Swift where minFrequency/maxFrequency track the displayed range.
        """
        self.update_axis(min_freq, max_freq)
        self.loadedAxisRangeChanged.emit(min_freq, max_freq, min_db, max_db)

    def set_auto_scale(self, enabled: bool) -> None:
        self._auto_scale_db = enabled

    # ------------------------------------------------------------------ #
    # Private Helpers
    # ------------------------------------------------------------------ #

    def _reset_material_phase_state(self, to) -> None:
        """Clear all plate/brace phase state and set material_tap_phase to the given value.

        Call with MaterialTapPhase.NOT_STARTED from reset() and with
        MaterialTapPhase.CAPTURING_LONGITUDINAL from start_tap_sequence() /
        cancel_tap_sequence() when in plate or brace mode.

        Mirrors Swift private func resetMaterialPhaseState(to phase: MaterialTapPhase).
        """
        self._set_material_tap_phase(to)

        # Clear all per-phase spectra and peak selections.
        self.longitudinal_spectrum = None
        self.cross_spectrum = None
        self.flc_spectrum = None
        self.longitudinal_peaks = []
        self.cross_peaks = []
        self.flc_peaks = []
        self.auto_selected_longitudinal_peak_id = None
        self.auto_selected_cross_peak_id = None
        self.auto_selected_flc_peak_id = None
        self.selected_longitudinal_peak = None
        self.selected_cross_peak = None
        self.selected_flc_peak = None
        self.user_selected_longitudinal_peak_id = None
        self.user_selected_cross_peak_id = None
        self.user_selected_flc_peak_id = None
        # All phase spectra cleared — mirrors Swift's @Published vars becoming nil,
        # which causes materialSpectra to return [] and SpectrumView to restore the live curve.
        self.set_material_spectra([])

        # Cancel any in-flight gated capture when resetting phase state.
        # Mirrors Swift which simply clears gatedCaptureActive in resetMaterialPhaseState.
        # Gated state now lives on self (TapToneAnalyzer), not on proc_thread.
        with self._gated_lock:
            self._gated_capture_active = False
            self._gated_accum = []

    # ------------------------------------------------------------------ #
    # Plate / brace tap sequence entry points
    # Mirrors Swift TapToneAnalyzer+Control.swift (startTapSequence / cancelTapSequence)
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

    def _reset_decay_tracking(self) -> None:
        """Stop any active decay tracking and clear the associated timer.

        Mirrors Swift private func resetDecayTracking() lines 342-346.
        """
        self.is_tracking_decay = False
        if self._decay_tracking_timer is not None:
            self._decay_tracking_timer.stop()
            self._decay_tracking_timer = None
