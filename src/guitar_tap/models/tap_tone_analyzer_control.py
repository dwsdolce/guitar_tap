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
        """
        self.status_message = message
        self.statusMessageChanged.emit(message)

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

        Debounce: on Windows, opening a new PortAudio stream triggers the
        CM_Register_Notification callback, which queues another _on_devices_refreshed
        call on the main thread — causing a cascade of 10+ restarts for a single
        plug/unplug event.  We suppress re-entrant calls and any calls that arrive
        within 3 s of the previous refresh completing.
        """
        now = _time.monotonic()
        # Guard 1: already inside a refresh — drop the duplicate.
        if getattr(self, '_devices_refresh_active', False):
            gt_log("🔄 _on_devices_refreshed: suppressed (already in progress)")
            return
        # Guard 2: completed a refresh less than 3 s ago — drop the duplicate.
        last = getattr(self, '_devices_refresh_last_t', 0.0)
        if now - last < 3.0:
            gt_log(f"🔄 _on_devices_refreshed: suppressed (last refresh {now - last:.1f} s ago)")
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
        import models.microphone_calibration as _mc
        try:
            cal_data = _mc.parse_cal_file(path)
            self._calibration_corrections = _mc.interpolate_to_bins(cal_data, self.freq)
            if self.mic.proc_thread is not None:
                self.mic.proc_thread.set_calibration(self._calibration_corrections)
            return True
        except Exception:
            return False

    def load_calibration_from_profile(self, cal) -> None:
        """Apply a pre-parsed MicrophoneCalibration profile to the FFT pipeline."""
        self._calibration_corrections = cal.interpolate_to_bins(self.freq)
        if self.mic.proc_thread is not None:
            self.mic.proc_thread.set_calibration(self._calibration_corrections)
        # Track the name so _on_export_pdf can report it — mirrors Swift activeCalibration?.name.
        self._active_calibration_name = getattr(cal, "name", None)

    def clear_calibration(self) -> None:
        """Remove the active calibration."""
        self._calibration_corrections = None
        self._active_calibration_name = None
        if self.mic.proc_thread is not None:
            self.mic.proc_thread.set_calibration(None)

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

    def _on_mic_sample_rate_changed(self) -> None:
        """Handle a sample-rate change on the current input device.

        Called by the platform sample-rate listener (CoreAudio on macOS, polling
        on Windows/Linux) after a 0.3 s delay.  Restarts the audio stream by
        re-calling set_device() with the currently selected device, which closes
        the old stream, opens a new one at the updated rate, and auto-loads
        calibration.

        Mirrors Swift's registerSampleRateListener block which calls stop() then,
        after a 0.3 s DispatchQueue.main.asyncAfter, calls try self.start() and
        increments routeChangeRestartCount.

        The 0.3 s delay is already applied by the listener before this method is
        invoked, so no additional delay is needed here.
        """
        import platform as _platform
        import sounddevice as _sd
        from PySide6.QtCore import QTimer as _QTimer

        device = self.mic.selected_input_device
        if device is None:
            return

        # On Windows, validate that the device we're about to restart on is still
        # present as a non-WDM-KS device.  After a USB unplug the sample-rate
        # poller may have fired before it detected the device-name change; by the
        # time we reach here the PortAudio table may have been renumbered so that
        # device.index now points to a WDM-KS device.  Opening it would produce a
        # stream that delivers silence (-313 dB) with no error.
        #
        # Resolution strategy: look up the device by name in the *current*
        # PortAudio device list and verify its host API is not WDM-KS.  If the
        # device is absent or WDM-KS, suppress the restart silently — the
        # CM_Register_Notification hot-plug path (_on_devices_refreshed) will
        # handle recovery once PortAudio is re-initialized.
        if _platform.system() == "Windows":
            try:
                apis = _sd.query_hostapis()
                wdm_ks_indices = {i for i, a in enumerate(apis) if a["name"] == "Windows WDM-KS"}
                all_devs = list(_sd.query_devices())
                # Find the device by name in the live list
                live = next(
                    (d for d in all_devs
                     if int(d["max_input_channels"]) > 0
                     and str(d["name"]) == device.name),
                    None,
                )
                if live is None or int(live["hostapi"]) in wdm_ks_indices:
                    # Device gone or now on WDM-KS — skip the restart
                    return
            except Exception:
                pass

        # Dispatch back onto the main thread (the listener fires on a daemon thread).
        # Also call handle_route_change_restart() to mirror Swift incrementing
        # routeChangeRestartCount after start(), which triggers handleRouteChangeRestart().
        _QTimer.singleShot(0, lambda: (self.set_device(device), self.handle_route_change_restart()))

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
        from PySide6.QtCore import QTimer as _QTimer
        from models.analysis_display_mode import AnalysisDisplayMode as _ADM

        gt_log("🔄 TapToneAnalyzer: Handling route change restart - resetting detection state")

        was_detecting = self.is_detecting

        # Disable the is_ready_for_detection flag while reinitialising.
        # Mirrors Swift: isReadyForDetection = false / isDetecting = false.
        self.is_ready_for_detection = False
        self.is_detecting = False

        # Reset the warmup timer so the new engine session starts cleanly.
        # Mirrors Swift: analyzerStartTime = Date().
        self.analyzer_start_time = _time.monotonic()

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
            self.current_peaks = []
            self.identified_modes = []
            self.peaksChanged.emit([])

        # Mirrors Swift: statusMessage = "Audio device changed - reinitializing...".
        self._set_status_message("Audio device changed - reinitializing...")

        # Wait for the FFT pipeline to fill with valid post-restart data
        # (~1.36 s for 65 536 samples at 48 kHz).  Use 3 s to absorb HALC/CoreAudio
        # startup transients that can arrive at ~2.5 s on the engine-recovery path.
        # Mirrors Swift: fftSettleTime = 3.0 / DispatchQueue.main.asyncAfter.
        _QTimer.singleShot(
            3000,
            lambda: self._restore_detection_after_route_change(was_detecting, was_live),
        )

    def _restore_detection_after_route_change(self, was_detecting: bool, was_live: bool = False) -> None:
        """Re-anchor threshold and restore detection state after the settle delay.

        This method is the structural equivalent of the combined
        DispatchQueue.main.asyncAfter + $magnitudes.dropFirst().first() sink
        closure in Swift's handleRouteChangeRestart().  It is a named method
        rather than an inline lambda only because QTimer.singleShot requires a
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
            self._set_status_message(
                "Tap the guitar..." if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times..."
            )
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
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_tap_detection_threshold(self.tap_detection_threshold)
        # Mirrors Swift tapDetectionThreshold.didSet: clear warning if user deviates from loaded value.
        if (self.show_loaded_settings_warning
                and self.loaded_tap_detection_threshold is not None
                and self.tap_detection_threshold != self.loaded_tap_detection_threshold):
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)

    def set_hysteresis_margin(self, value: float) -> None:
        """Update the hysteresis margin (dB)."""
        self.hysteresis_margin = float(value)
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_hysteresis_margin(self.hysteresis_margin)
        # mirrors hysteresisMargin.didSet in Swift

    def pause_tap_detection(self) -> None:
        """Pause tap detection mid-sequence without losing the current tap count.

        No-op when not currently detecting or already paused.
        Mirrors Swift pauseTapDetection() guard: isDetecting && !isDetectionPaused.
        """
        if not self.is_detecting or self.is_detection_paused:
            return
        self.is_detecting = False
        self.is_detection_paused = True
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
        self.analyzer_start_time = _time.monotonic()
        self.is_above_threshold = False

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
            self._set_status_message(
                "Tap the guitar..."
                if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times..."
            )
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
            self._update_frequency_bins()
            if on_finished is not None:
                on_finished()

        self.mic._on_playback_finished = _on_finished_wrapper

        self.mic.start_from_file(path)

        # Recompute the frequency axis now that mic.rate reflects the file's sample rate.
        # Mirrors Swift updateFrequencyBins() called synchronously inside startFromFile
        # before the main-thread async block sets isPlayingFile / playingFileName.
        self._update_frequency_bins()

    def start_tap_sequence(self, skip_warmup: bool = False) -> None:
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
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from .analysis_display_mode import AnalysisDisplayMode as _ADM

        meas_type = _tds.measurement_type()
        is_plate = (meas_type == _MT.PLATE)
        is_brace = (meas_type == _MT.BRACE)

        # Mirrors Swift startTapSequence() lines 140-143:
        #   self.comparisonSpectra = []  (handled by view's clear_comparison())
        #   self.displayMode = .live
        #   self.loadedMeasurementName = nil  (set below)
        #   self.isMeasurementComplete = false
        self._display_mode = _ADM.LIVE
        self.show_loaded_settings_warning = False
        self.showLoadedSettingsWarningChanged.emit(False)

        # Mirrors Swift: isMeasurementComplete = false (clears frozen state before new sequence).
        # Emitted here so the view transitions to live mode before audio starts.
        self.is_measurement_complete = False
        self.measurementComplete.emit(False)

        # Clear per-sequence accumulated data (mirrors Swift startTapSequence async block).
        self.captured_taps.clear()
        self.current_tap_count = 0
        self.tap_progress = 0.0
        self.tap_detected = False
        self.is_detection_paused = False

        # Seed the noise-floor estimate from the current ambient level so the first
        # relative-threshold calculation is accurate immediately.
        # Mirrors Swift TapToneAnalyzer+Control.swift:
        #   self.noiseFloorEstimate = self.fftAnalyzer.inputLevelDB  (instantaneous RMS)
        # Use _current_input_level_db which caches fftAnalyzer.inputLevelDB at ~43 Hz
        # via _on_rms_level_changed — NOT recent_peak_level_db (0.5 s peak-hold /
        # fftAnalyzer.recentPeakLevelDB), which would inflate the initial noise estimate.
        self.noise_floor_estimate = self._current_input_level_db

        self.current_decay_time = None
        self.peak_magnitude_history = []
        self._reset_decay_tracking()

        # Initialise plate/brace phase state (mirrors Swift resetMaterialPhaseState(to: newPhase)).
        new_phase = _MTP.CAPTURING_LONGITUDINAL if (is_plate or is_brace) else _MTP.NOT_STARTED
        self._reset_material_phase_state(to=new_phase)

        # Clear annotation offsets so dragged positions reset for the new measurement.
        self.reset_all_annotation_offsets()

        # Clear frozen spectrum so live FFT is shown while waiting for taps.
        self.set_frozen_spectrum(np.array([]), np.array([]))

        # Always start with is_above_threshold = False so the first real tap produces
        # a genuine rising edge.  The warm-up period suppresses detections for the
        # first warmup_period seconds.
        self.is_above_threshold = False
        self.just_exited_warmup = False  # Will be set True as warm-up ends.

        # Reset the warm-up timer for this new sequence.
        # Mirrors Swift TapToneAnalyzer+Control.swift startTapSequence(skipWarmup:):
        # For file playback (skip_warmup=True) set the start time far enough in the
        # past that the warmup_period has already elapsed when the first audio buffer
        # arrives.  The audio source is deterministic, so no startup-noise suppression
        # is needed, and the tap transient may appear within the first 0.5 s of the file.
        if skip_warmup:
            self.analyzer_start_time = _time.monotonic() - (self.warmup_period + 0.1)
        else:
            self.analyzer_start_time = _time.monotonic()

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
            self._set_status_message(
                "Tap the guitar..."
                if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times..."
            )

        # Clear previous results so the chart shows a clean slate while waiting.
        self.current_peaks = []
        self.identified_modes = []

        # Mirrors Swift startTapSequence: loadedMeasurementName = nil
        self.loaded_measurement_name = None
        self.source_measurement_timestamp = None
        self.loadedMeasurementNameChanged.emit(None)

        self.tapCountChanged.emit(0, self.number_of_taps)

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing.

        Mirrors Swift numberOfTaps.didSet: if the user reduces the tap count
        to at or below what has already been captured mid-sequence, process
        immediately rather than waiting for more taps.

        Note: the "process immediately" path only applies to guitar mode.  In
        plate/brace mode captured_taps holds (magnitudes, frequencies, timestamp)
        tuples (not homogeneous numpy arrays), and the tap count spinner is
        disabled once any tap is captured, so this branch is unreachable in that
        mode during normal use.
        """
        import numpy as np
        new_num = max(1, n)
        captured = len(self.captured_taps)
        is_guitar = getattr(self._measurement_type, "is_guitar", True)
        if is_guitar and captured >= new_num and captured > 0:
            # Already have enough — process now (mirrors Swift numberOfTaps.didSet)
            self.number_of_taps = new_num
            stacked = np.stack(self.captured_taps[:new_num])
            avg_db = 10.0 * np.log10(np.mean(np.power(10.0, stacked / 10.0), axis=0))
            self.set_frozen_spectrum(self.freq, avg_db)
            peaks = self.find_peaks(list(avg_db), list(self.freq))
            self.current_peaks = peaks
            self.peaksChanged.emit(peaks)
            self.captured_taps.clear()
            self.tapDetectedSignal.emit()
        else:
            self.number_of_taps = new_num
            # Don't clear spectra when count is raised mid-sequence — keep what
            # was already captured (mirrors Swift which never clears capturedTaps here).
        # Mirrors Swift numberOfTaps.didSet: clear warning if user deviates from loaded value.
        if (self.show_loaded_settings_warning
                and self.loaded_number_of_taps is not None
                and self.number_of_taps != self.loaded_number_of_taps):
            self.show_loaded_settings_warning = False
            self.showLoadedSettingsWarningChanged.emit(False)

    # ------------------------------------------------------------------ #
    # Cancel
    # ------------------------------------------------------------------ #

    def cancel_tap_sequence(self) -> None:
        """Cancel the current tap sequence and immediately restart detection from scratch.

        Unlike reset(), cancel keeps detection active so the user can start a new
        tap without pressing Start again.  Mirrors Swift cancelTapSequence().
        """
        import numpy as np
        from models.measurement_type import MeasurementType as _MT
        from models.tap_display_settings import TapDisplaySettings as _tds
        from models.material_tap_phase import MaterialTapPhase as _MTP

        meas_type = _tds.measurement_type()
        is_plate = (meas_type == _MT.PLATE)
        is_brace = (meas_type == _MT.BRACE)

        self.captured_taps.clear()
        self.current_tap_count = 0
        self.tap_progress = 0.0
        self.tap_detected = False
        self.is_detection_paused = False
        self.is_detecting = True  # mirrors Swift cancelTapSequence line 280

        # Reset plate/brace state back to the start of the sequence
        # (mirrors Swift resetMaterialPhaseState(to: newPhase)).
        new_phase = _MTP.CAPTURING_LONGITUDINAL if (is_plate or is_brace) else _MTP.NOT_STARTED
        self._reset_material_phase_state(to=new_phase)

        self._reset_decay_tracking()

        # Clear frozen spectrum (mirrors Swift setFrozenSpectrum(frequencies: [], magnitudes: [])).
        self.set_frozen_spectrum(np.array([]), np.array([]))

        # Reset the warm-up timer for the restarted sequence (mirrors Swift lines 292-293).
        self.analyzer_start_time = _time.monotonic()
        self.is_above_threshold = False

        # Show an appropriate ready prompt (mirrors Swift cancelTapSequence lines 299-305).
        if is_brace:
            self._set_status_message("Ready for fL tap")
        elif is_plate:
            self._set_status_message("Ready for L tap")
        else:
            self._set_status_message(
                "Tap the guitar..."
                if self.number_of_taps == 1
                else f"Tap the guitar {self.number_of_taps} times..."
            )

        self.tapCountChanged.emit(0, self.number_of_taps)

    def reset(self) -> None:
        """Clear all analyzer state and stop detection.

        Mirrors Swift TapToneAnalyzer+Control.reset().  Unlike cancel_tap_sequence(),
        this leaves isDetecting = False so the user must explicitly start a new sequence.

        State cleared:
        - currentPeaks, identifiedModes, currentDecayTime
        - sourceMeasurementTimestamp, loadedMeasurementName
        - peakMagnitudeHistory, tapDetected, isDetecting, capturedTaps
        - isAboveThreshold, analyzerStartTime (warm-up timer)
        - frozenSpectrum (unfrozen), isMeasurementComplete = False
        - peakAnnotationOffsets
        - materialTapPhase → .notStarted
        - displayMode → .live
        - showLoadedSettingsWarning = False
        - statusMessage → "Tap the guitar to begin"
        """
        import numpy as np
        from .analysis_display_mode import AnalysisDisplayMode
        from .material_tap_phase import MaterialTapPhase as _MTP

        self.current_peaks = []
        self.identified_modes = []
        self.current_decay_time = None

        # Mirrors Swift: sourceMeasurementTimestamp = nil; loadedMeasurementName = nil
        self.source_measurement_timestamp = None
        self.loaded_measurement_name = None
        self.loadedMeasurementNameChanged.emit(None)

        self.peak_magnitude_history = []
        self.tap_detected = False
        self.is_detecting = False
        self.current_tap_count = 0
        self.tap_progress = 0.0
        self.captured_taps.clear()

        # Always start fresh so the first new tap is detected on a rising edge.
        self.is_above_threshold = False
        self.analyzer_start_time = _time.monotonic()

        self._reset_decay_tracking()

        # Clear frozen spectrum (mirrors Swift setFrozenSpectrum(frequencies: [], magnitudes: [])).
        self.set_frozen_spectrum(np.array([]), np.array([]))
        self.is_measurement_complete = False
        self.measurementComplete.emit(False)

        # Clear annotation label offsets (mirrors Swift peakAnnotationOffsets = [:]).
        self.reset_all_annotation_offsets()

        # Reset all plate/brace phase state to notStarted (mirrors Swift line 110).
        self._reset_material_phase_state(to=_MTP.NOT_STARTED)

        self._display_mode = AnalysisDisplayMode.LIVE
        self.show_loaded_settings_warning = False
        self.showLoadedSettingsWarningChanged.emit(False)
        self._set_status_message("Tap the guitar to begin")

    # ------------------------------------------------------------------ #
    # Phase Review — Accept / Redo
    # Mirrors Swift TapToneAnalyzer+Control acceptCurrentPhase() / redoCurrentPhase()
    # ------------------------------------------------------------------ #

    def accept_current_phase(self) -> None:
        """Advance from a reviewing phase to the next capture phase (or complete).

        Called when the user presses Accept after reviewing a frozen spectrum.
        Mirrors Swift TapToneAnalyzer+Control.acceptCurrentPhase().
        """
        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP
        from models.tap_display_settings import TapDisplaySettings as _tds
        import time as _time_mod

        phase = self.material_tap_phase

        if phase == _MTP.REVIEWING_LONGITUDINAL:
            # Advance to cross-grain capture.
            # Mirrors Swift: set phase first, then clear frozen spectrum.
            self._set_material_tap_phase(_MTP.CAPTURING_CROSS)
            self.set_frozen_spectrum(_np.array([]), _np.array([]))
            level = self._current_input_level_db
            falling = self.tap_detection_threshold - self.hysteresis_margin
            self.is_above_threshold = level > falling
            self.analyzer_start_time = _time_mod.monotonic()
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
                from PySide6 import QtCore
                QtCore.QTimer.singleShot(int(cooldown * 1000), self._do_start_flc)
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
        import numpy as _np
        from models.material_tap_phase import MaterialTapPhase as _MTP
        import time as _time_mod

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
        self.analyzer_start_time = _time_mod.monotonic()
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
        self.current_peaks = sel
        self.selected_peak_ids = {p.id for p in sel}
        self.selected_peak_frequencies = [p.frequency for p in sel]
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        from models.material_tap_phase import MaterialTapPhase as _MTP
        self._set_material_tap_phase(_MTP.COMPLETE)
        self.set_measurement_complete(True)
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
        self.current_peaks = sel
        self.selected_peak_ids = {p.id for p in sel}
        self.selected_peak_frequencies = [p.frequency for p in sel]
        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        from models.material_tap_phase import MaterialTapPhase as _MTP
        self._set_material_tap_phase(_MTP.COMPLETE)
        self.set_measurement_complete(True)
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
        self.peak_threshold = float(threshold - 100)
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_peak_threshold(self.peak_threshold)
        # mirrors peakThreshold.didSet in Swift
        self.recalculate_frozen_peaks_if_needed()

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

    def set_max_average_count(self, max_average_count: int) -> None:
        self.max_average_count = max_average_count

    def reset_averaging(self) -> None:
        self.num_averages = 0

    def set_avg_enable(self, avg_enable: bool) -> None:
        self.avg_enable = avg_enable

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

    def _reset_decay_tracking(self) -> None:
        """Stop any active decay tracking and clear the associated timer.

        Mirrors Swift private func resetDecayTracking() lines 342-346.
        """
        self.is_tracking_decay = False
        if self._decay_tracking_timer is not None:
            self._decay_tracking_timer.stop()
            self._decay_tracking_timer = None
