"""
TapToneAnalyzer+Control — lifecycle control, device management, calibration,
tap-sequence management, and parameter setters.

Mirrors Swift TapToneAnalyzer+Control.swift.
"""

from __future__ import annotations

import time as _time

from guitar_tap.utilities.logging import gt_log
from guitar_tap.views.utilities import palette

from . import field_precision as fp
from .detection_state import DetectionState

# The plate/brace phase colours, by role.
_FL = palette.Role.MATERIAL_LONGITUDINAL
_FC = palette.Role.MATERIAL_CROSS
_FLC = palette.Role.MATERIAL_FLC


class TapToneAnalyzerControlMixin:
    """Lifecycle control and parameter management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+Control.swift.
    """

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
        # Guard 2 exists because cfgmgr32 device-interface events cascade: Pa_OpenStream
        # itself fires one. MMDevice endpoint events do not — opening a shared-mode stream
        # neither adds, removes nor activates an endpoint — so with that monitor the
        # cooldown has nothing to suppress and is skipped: it would drop the endpoint
        # notification that finds a newly plugged microphone. Guard 1 still covers overlap,
        # without a clock.
        if getattr(self.mic, "_hotplug_kind", None) != "mmdevice":
            last = getattr(self, '_devices_refresh_last_t', 0.0)
            if now - last < 1.0:
                gt_log("🔄 _on_devices_refreshed: suppressed (within 1 s of the last refresh)")
                return
        self._devices_refresh_active = True
        try:
            self._on_devices_refreshed_impl()
        finally:
            self._devices_refresh_active = False
            self._devices_refresh_last_t = _time.monotonic()

    def _on_devices_refreshed_impl(self) -> None:
        """Inner implementation of _on_devices_refreshed (called with debounce guard held)."""
        previous_device = self.mic.selected_input_device

        # Close the active stream BEFORE terminating PortAudio. Calling
        # Pa_Terminate while a stream is open leaves the Python stream handle
        # dangling on a torn-down PortAudio instance; on Windows WMME this has
        # been observed to leave the next InputStream unable to deliver
        # samples even though it opens successfully.
        self.mic._close_stream_only()

        # Flush PortAudio's cached device list so query_devices() reflects
        # the current OS device state (not while a stream close is still pending — see
        # terminate_and_reinitialize_portaudio). Swift CoreAudio doesn't need this step.
        self.mic.terminate_and_reinitialize_portaudio()

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
        if new_device is not None and self.mic._is_recovering:
            # A watchdog restart is pending: it opens whichever device is selected, so the refresh
            # only updates the selection. Mirrors Swift, where a device switch while the engine is
            # stopped for a recovery does not restart it.
            gt_log("🔄 Device refresh during a pending watchdog restart — the restart opens "
                   f"'{new_device.name}'")
        elif new_device is not None:
            from guitar_tap.models.realtime_fft_analyzer_device_management import (
                InputDeviceOpenError,
            )
            try:
                self.set_device(new_device)
            except InputDeviceOpenError as exc:
                self._keep_previous_after_failed_open(previous_device, exc)
            self.handle_route_change_restart()

        # Notify the view if the previously active device disappeared.
        # Mirrors Swift's "disconnected" log path in loadAvailableInputDevicesMacOS().
        prev_name = getattr(previous_device, "name", None) or self._calibration_device_name
        if prev_name and prev_name not in names:
            self.currentDeviceLost.emit(prev_name)

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self._calibration_device_name

    def _on_stream_reopened(self) -> None:
        """The watchdog's restart reopened the stream — on the selected device, which a refresh during
        the pending restart may have changed: re-read its name and rate. Mirrors Swift start()
        updating actualSampleRate and the frequency bins."""
        current = self.mic.selected_input_device
        self._calibration_device_name = current.name if current is not None else ""
        self._update_frequency_bins()

    def _keep_previous_after_failed_open(self, previous_device, error) -> None:
        """A device the list selected (plugged in, or a fallback) could not be opened: select and
        open the previous device again if it is still listed, and report the failure for the view's
        alert. Mirrors Swift revertFailedInputSwitch(from:to:)."""
        from guitar_tap.models.realtime_fft_analyzer_device_management import (
            InputDeviceOpenError,
        )
        if previous_device is not None:
            fresh = next((d for d in self.mic.available_input_devices
                          if d.fingerprint == previous_device.fingerprint), None)
            if fresh is not None:
                try:
                    self.set_device(fresh)
                except InputDeviceOpenError:
                    pass
        self.inputDeviceOpenFailed.emit(str(error))

    def set_device(self, device) -> None:
        """Switch to a different input device.

        Delegates to RealtimeFFTAnalyzer.set_device(), which owns the stream
        restart and the device's calibration (set_calibration_without_saving_device_mapping).
        _gated_sample_rate and _pre_roll_samples are computed properties that
        read self.mic.rate directly, so they automatically reflect the new
        device rate — mirrors Swift where preRollSamples and gatedCaptureSamples
        are computed vars that always read from mpmSampleRate.

        Mirrors Swift TapToneAnalyzer+Control.swift: setInputDevice is called
        on fftAnalyzer, then selectedInputDevice.didSet applies calibration —
        both now happen inside RealtimeFFTAnalyzer.set_device().
        """
        try:
            self.mic.set_device(device)
        finally:
            # The device now selected — the new one, or the previous one if the new one could not
            # be opened (mic.set_device then raises InputDeviceOpenError).
            current = self.mic.selected_input_device
            self._calibration_device_name = current.name if current is not None else ""
            # Recompute self.freq from the device's sample rate.
            # Mirrors Swift start() calling updateFrequencyBins() after the engine
            # restarts with the new device — ensures the frequency axis matches
            # the actual hardware sample rate.
            self._update_frequency_bins()

    # ------------------------------------------------------------------ #
    # Tap detector control — all state lives directly on TapToneAnalyzer,
    # mirroring Swift where detectTap() and all tap state are on the class.
    # ------------------------------------------------------------------ #

    def set_tap_threshold(self, value: int) -> None:
        """Update tap-trigger threshold (0-100 scale → dBFS). The property setter saves it and ends the
        loaded-settings warning (Swift's didSet)."""
        self.tap_detection_threshold = float(value - 100)

    def pause_tap_detection(self) -> None:
        """Pause tap detection mid-sequence without losing the current tap count.

        No-op when not currently listening.
        Mirrors Swift pauseTapDetection() guard: detectionState == .listening.
        """
        if self.detection_state is not DetectionState.LISTENING:
            return
        self.detection_state = DetectionState.PAUSED
        # Stop accumulating audio during pause — mirrors Swift pauseTapDetection.
        self._is_session_recording = False
        self._set_status_message("Detection paused – tap freely, then resume")
        self.tapDetectionPaused.emit(True)

    def resume_tap_detection(self) -> None:
        """Resume tap detection after a pause, continuing from the current tap count.

        No-op when not paused.
        Mirrors Swift resumeTapDetection() guard: detectionState == .paused.
        Resets the warm-up timer (mirrors Swift warmupStartAudioTime = fftAnalyzer.audioElapsed;
        isAboveThreshold = false).
        """
        if self.detection_state is not DetectionState.PAUSED:
            return
        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        # Reset warm-up timer to prevent an immediate false trigger on the first frame.
        # Mirrors Swift: warmupStartAudioTime = fftAnalyzer.audioElapsed; isAboveThreshold = false
        self.warmup_start_audio_time = self._audio_now()
        self.is_above_threshold = False
        # The tap confirmation restarts: a chunk counted before the pause must not help confirm a tap
        # after it, or a single loud chunk could fire one. The web behaves the same.
        self.detect_tap_consecutive_above = 0

        # Resume accumulating audio after pause — the saved recording, or the pre-roll before the
        # first tap. Mirrors Swift resumeTapDetection.
        self._is_session_recording = (
            self._is_session_recording_enabled or self._session_pre_roll_active
        )
        self.detection_state = DetectionState.LISTENING

        # Restore a context-appropriate prompt. The same derivation the device-change settle uses.
        self._set_status_message(self._armed_prompt())

        self.tapDetectionPaused.emit(False)

    # ------------------------------------------------------------------ #
    # Tap sequence management
    # ------------------------------------------------------------------ #

    def play_file(self, path: str, calibration_path: "str | None" = None,
                  on_finished: "Callable[[], None] | None" = None) -> None:
        """Play an audio file through the live pipeline — the Play File action.

        Plays with the calibration file given for it, or with no calibration (never the live input's),
        arms a fresh tap sequence, then starts the file; the calibration in effect before is restored
        when playback ends. The view
        calls this; so do the file-playback regressions, which therefore run the path users take.
        Mirrors Swift ``TapToneAnalyzer.playFile(url:calibrationURL:completion:)``.

        The warm-up is decided by the MEASUREMENT TYPE, not by "is this a file". Guitar skips it: an
        externally recorded file may put the tap inside the first 0.5 s, and guitar uses the absolute
        threshold, never the noise floor. Material (plate/brace) runs it: it is the only mode on the
        relative noise-floor detector, and the warm-up is what establishes that floor — skipping it
        collapses ``rising`` onto ``tap_detection_threshold``. A saved session WAV always contains its
        warm-up.

        ``start_tap_sequence`` runs BEFORE ``start_from_file``, as in Swift: ``start_from_file`` tears the
        engine down (stops the stream, drains the processing queue, clears the input buffer) before any
        file audio flows, so the armed detector cannot fire on stale mic audio.

        Args:
            path:             Filesystem path to the audio file.
            calibration_path: The calibration of the microphone the file was recorded with, or None to
                              play uncalibrated. A file that cannot be parsed is logged and the
                              playback is uncalibrated.
            on_finished:      Called after playback has ended and the calibration is restored.
        Raises:
            Exception: If the audio file cannot be read.
        """
        from guitar_tap.models import microphone_calibration as _mc
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        # The playback uses the file's calibration, or none. The microphone the file was recorded with is
        # unknown, so the live input's calibration never applies to it.
        previous = self.mic.active_calibration
        playback_calibration = None
        if calibration_path:
            try:
                playback_calibration = _mc.MicrophoneCalibration.from_path(calibration_path)
            except Exception as exc:  # noqa: BLE001 — an unreadable calibration file must not stop playback
                gt_log(f"⚠️ Could not parse calibration file: {exc}")
        self.mic.set_temporary_calibration(playback_calibration)

        def _restore_calibration() -> None:
            self.mic.set_temporary_calibration(previous)

        def _finished() -> None:
            _restore_calibration()
            if on_finished is not None:
                on_finished()

        self.start_tap_sequence(skip_warmup=_tds.measurement_type().is_guitar)
        try:
            self.start_from_file(path, on_finished=_finished)
            # The result comes from the file: its calibration, its sample rate, an unknown microphone.
            from .tap_tone_analyzer import ResultProvenance
            self.result_provenance = ResultProvenance(
                microphone_name=None, microphone_uid=None,
                calibration_name=getattr(playback_calibration, "name", None) or None,
                sample_rate=float(self.mic.rate),
            )
        except Exception:
            _restore_calibration()
            raise

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
    def request_start_tap_sequence(self) -> bool:
        """User-initiated arming (New Tap, settings-apply re-arm, launch auto-arm). A file that is
        playing is stopped first: a new sequence — for a changed measurement type, say — must not be
        fed the rest of the file. If Dump Capture Audio is on and its folder can't be reached, emits
        ``dumpFolderUnreachable`` so the view prompts the user (Change Location / Turn Off Saving /
        Cancel) and does **not** arm — the prompt's actions retry. File-playback setup calls
        ``start_tap_sequence`` directly, bypassing this check. Returns whether it armed.
        Mirrors Swift ``requestStartTapSequence()``.
        """
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        from guitar_tap.models.wav_dump_folder import WavDumpFolder

        self.mic.stop_file_playback()
        if _tds.dump_capture_audio() and not WavDumpFolder.is_reachable():
            self.dumpFolderUnreachable.emit()
            return False
        self.start_tap_sequence()
        return True

    # @parity state/tap-tone-analyzer
    def start_tap_sequence(self, skip_warmup: bool = False) -> None:
        """Begin a new tap detection sequence, resetting all per-sequence state.

        Mirrors Swift startTapSequence() including:
        - Seeds noise_floor_estimate from the current ambient level (fftAnalyzer.inputLevelDB).
        - Clears the last ring-out (current_decay_time).
        - Calls _reset_material_phase_state() for plate/brace.
        - Sets is_detecting = True.
        - Sets context-appropriate status_message.
        - Clears previous peaks, spectra, and annotation offsets.
        """
        import numpy as np

        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
        from guitar_tap.models.measurement_type import MeasurementType as _MT
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

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

        # Clear per-sequence accumulated data, as Swift's startTapSequence does (the captured taps
        # go with the capture, below).
        self.tap_entries = []
        self.showing_multi_tap_comparison = False
        self.current_tap_count = 0
        self.tap_progress = 0.0
        # No pause-clear here: DetectionState.LISTENING further down leaves PAUSED on its
        # own. Mirrors Swift startTapSequence.

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
        # Cancel any in-flight gated capture from a previous sequence and reset the pre-roll, as Swift's
        # startTapSequence.
        self.abandon_capture()
        # Session recording: clear the buffer and begin recording. With Dump Capture Audio off
        # only the bounded pre-roll is kept, and it is dropped at the first tap unless the
        # setting has been turned on by then.
        self._session_recording_buffer = []
        self._session_checkpoints = [0]
        self._is_session_recording_enabled = _tds.dump_capture_audio()
        self._is_session_recording = True
        self._session_pre_roll_active = True  # bound the pre-first-tap audio to ~2 s
        self._session_recording_sample_rate = (
            self._mpm_sample_rate if self._mpm_sample_rate > 0 else 48000.0
        )
        from . import capture_probe
        capture_probe.begin_live_session(_tds.dump_capture_audio())  # diagnostic

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
        # Mirrors Swift TapToneAnalyzer+Control.swift noiseFloorEstimate.
        self.noise_floor_estimate = -100.0 if skip_warmup else self._current_input_level_db

        self.current_decay_time = None

        # Reset material phase state: a material sequence starts at its first phase (mirrors Swift
        # resetMaterialPhaseState(to:)).
        self._reset_material_phase_state(
            to=_MTP.CAPTURING_LONGITUDINAL if (is_plate or is_brace) else _MTP.NOT_STARTED
        )

        # Clear annotation offsets so dragged positions reset for the new measurement.
        self.reset_all_annotation_offsets()

        # Clear ALL per-peak state from the PREVIOUS measurement. These are keyed by the old
        # peaks' UUIDs, so once the peaks are replaced they are invisible on screen — but they would
        # otherwise be written verbatim into the NEXT measurement's saved file. A new sequence starts
        # with no selection, no manual labels and no dragged offsets. Mirrors Swift startTapSequence.
        self.selected_peak_ids = set()
        self.selected_peak_frequencies = []
        self.user_has_modified_peak_selection = False
        self.peak_mode_overrides = {}

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
        # A new sequence starts its tap confirmation from zero: a chunk counted before it cannot help
        # confirm its first tap. The web behaves the same.
        self.detect_tap_consecutive_above = 0
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

        self.detection_state = DetectionState.LISTENING

        # Set context-appropriate status message (mirrors Swift startTapSequence).
        # The material phase was set above, so the prompt is READ from it rather than rebuilt here
        # -- one source for these strings.  A phase-targeted start (file playback)
        # consequently announces the phase it actually begins in instead of always announcing fL.
        if is_brace or is_plate:
            self._set_status_message(self._material_arm_prompt())
        else:
            self._set_status_message(self._tap_prompt())

        # Clear previous results so the chart shows a clean slate while waiting.
        self.all_peaks = []
        self.identified_modes = []
        # Notify the view so the scatter clears now (Swift gets this free via @Published
        # currentPeaks = []; mirrors the device-change path above). Without it the previous
        # measurement's dots linger until the first tap of the new sequence — e.g. leftover
        # guitar dots after switching to a plate measurement via Settings.
        self.peaks.peaksChanged.emit([])

        # Mirrors Swift startTapSequence: loadedMeasurementName = nil; loadedNotes = nil
        self.loaded_measurement_name = None
        self.loaded_notes = None
        self.source_measurement_timestamp = None
        self.loadedMeasurementNameChanged.emit(None)
        self.dismiss_capture_audio_saved()
        self.material_peaks_from_load = False

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
        # A new sequence listens to the input until play_file says otherwise.
        self.result_provenance = None

        self.tapCountChanged.emit(0, self.number_of_taps)

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing.

        Mirrors Swift numberOfTaps.didSet.

        NOTE: there is deliberately NO "reduce the count mid-sequence -> finalise with the taps
        already captured" branch.  The tap-count spinner is disabled the moment a sequence has a
        tap -- ``setEnabled(not (captured > 0 and not complete))``, matching Swift's
        ``.disabled(currentTapCount > 0 && !isMeasurementComplete)`` -- so the count simply cannot
        change mid-sequence; to change it you cancel first.  Such a branch would be unreachable,
        and an unreachable branch drifts between editions unnoticed.

        If a mid-sequence count change is ever wanted, unlock the spinner and define the semantics
        deliberately -- do not resurrect an implicit finalise.
        """
        self.number_of_taps = max(1, n)
        # Raising the count mid-sequence does NOT clear what was already captured (mirrors Swift,
        # which never clears capturedTaps here) -- though the spinner lock means this cannot be
        # reached from the UI either.
        # Mirrors Swift numberOfTaps.didSet: update status message when waiting
        # for the first tap (isDetecting=True, currentTapCount=0).
        #
        # `current_tap_count`, not `len(captured_taps)`: the latter is the WITHIN-PHASE buffer,
        # cleared at every material phase completion, so it read zero at the start of every plate
        # phase rather than only at the start of the measurement.  current_tap_count is the
        # cumulative count -- the same field the spinner lock reads, so the guard and the lock
        # agree.  And `_armed_prompt()`, not `_tap_prompt()`: the latter is the GUITAR prompt, and
        # changing Taps at the start of a plate or brace sequence must keep the material prompt
        # ("Ready for fL tap (×3 each for L, C)").
        if self.is_detecting and self.current_tap_count == 0:
            self._set_status_message(self._armed_prompt())

    # ------------------------------------------------------------------ #
    # Cancel
    # ------------------------------------------------------------------ #

    def cancel_tap_sequence(self) -> None:
        """Cancel the current tap sequence by restarting it.

        Cancel is a **restart**: it returns to the exact state that New Tap
        produces — a fresh, re-armed sequence waiting for the first tap — rather
        than completing the measurement.  Cancel is offered while a multi-step
        (multi-tap or multi-phase) sequence is in progress, and throughout a file
        playback. During a playback it stops the file first, so the fresh sequence
        listens to the microphone and the partial result is discarded.  Mirrors Swift
        cancelTapSequence().
        """
        gt_log("❌ Tap sequence cancelled — restarting")
        # A pending capture-completion timer from the abandoned sequence must not
        # fire into the fresh one (mirrors Swift captureTimer?.invalidate()).
        self.capture_timer_active = False
        if self.mic is not None:
            self.mic.stop_file_playback()
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

        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds

        # Session recording: checkpoint the current buffer position so that
        # if a subsequent phase is redone, we can truncate back to here.
        # Mirrors Swift acceptCurrentPhase checkpoint append.
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
            self.detection_state = DetectionState.LISTENING
            # Phase is CAPTURING_CROSS -- one source for the string.
            self._set_status_message(self._material_arm_prompt())

        elif phase == _MTP.REVIEWING_CROSS:
            if _tds.measure_flc():
                # Advance to FLC waiting then capturing.
                # Mirrors Swift: set WAITING_FOR_FLC_TAP and status message first,
                # then transition to CAPTURING_FLC and clear frozen spectrum inside
                # the hold's closure (tap_cooldown of AUDIO).
                self._set_material_tap_phase(_MTP.WAITING_FOR_FLC_TAP)
                # Phase is WAITING_FOR_FLC_TAP -- one source for the string.
                self._set_status_message(self._material_arm_prompt())
                self.after_audio(self.tap_cooldown, self._do_start_flc)
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

        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP

        # Session recording: truncate back to the start of the current phase
        # so the rejected tap's audio is excluded from the saved WAV.
        # Peek (don't pop) — the anchor must remain in place so that a second
        # redo of the same phase truncates to the same position, not to the
        # start of the *previous* accepted phase.  Mirrors Swift redoCurrentPhase.
        if self._session_checkpoints:
            phase_start = self._session_checkpoints[-1]
            if len(self._session_recording_buffer) > phase_start:
                del self._session_recording_buffer[phase_start:]
                # Redoing the FIRST phase empties the buffer back to the pre-first-tap state,
                # so re-arm the bounded pre-roll. Later phases keep the latch frozen.
                if phase_start == 0:
                    self._session_pre_roll_active = True

        phase = self.material_tap_phase

        if phase == _MTP.REVIEWING_LONGITUDINAL:
            # Clear longitudinal data only.
            self.longitudinal_spectrum = None
            self.selected_longitudinal_peak = None
            self.captured_taps.clear()
            self.current_tap_count = 0
            self.tap_progress = 0.0
            capture_phase = _MTP.CAPTURING_LONGITUDINAL
            status_msg = "Ready for fL tap — tap again"
            # longitudinalSpectrum = nil → materialSpectra returns [] → live curve restored.
            self.set_material_spectra([])

        elif phase == _MTP.REVIEWING_CROSS:
            # Clear cross data only — longitudinal stays.
            self.cross_spectrum = None
            self.selected_cross_peak = None
            self.captured_taps.clear()
            # Mirrors Swift: lCount = (longitudinalSpectrum != nil) ? numberOfTaps : 0
            l_count = self.number_of_taps if self.longitudinal_spectrum is not None else 0
            self.current_tap_count = l_count
            self.tap_progress = float(l_count) / float(self.total_plate_taps)
            capture_phase = _MTP.CAPTURING_CROSS
            status_msg = "Ready for fC tap — tap again"
            # crossSpectrum = nil → materialSpectra returns [L only] → show longitudinal overlay.
            spectra = []
            if self.longitudinal_spectrum:
                l_mags, l_freqs = self.longitudinal_spectrum
                spectra.append(("Longitudinal (fL)", _FL, list(l_freqs), list(l_mags)))
            self.set_material_spectra(spectra)

        elif phase == _MTP.REVIEWING_FLC:
            # Clear FLC data only — L and C stay.
            self.flc_spectrum = None
            self.selected_flc_peak = None
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
            status_msg = "Ready for fLC tap — tap again"
            # flcSpectrum = nil → materialSpectra returns [L, C] → show both overlays.
            spectra = []
            if self.longitudinal_spectrum:
                l_mags, l_freqs = self.longitudinal_spectrum
                spectra.append(("Longitudinal (fL)", _FL, list(l_freqs), list(l_mags)))
            if self.cross_spectrum:
                c_mags, c_freqs = self.cross_spectrum
                spectra.append(("Cross-grain (fC)", _FC, list(c_freqs), list(c_mags)))
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
        # The redone phase's identified peak is gone: tell the view, so its dot and label go now
        # (Swift's view re-reads materialIdentifiedPeaks on the change).
        self._emit_peaks_array(self.peaks_above_peak_min)

        # Reset warm-up and re-arm detection.
        level = self._current_input_level_db
        falling = self.tap_detection_threshold - self.hysteresis_margin
        self.is_above_threshold = level > falling
        self.warmup_start_audio_time = self._audio_now()
        self.detection_state = DetectionState.LISTENING

        self._set_material_tap_phase(capture_phase)
        self._set_status_message(status_msg)

    def _finalise_plate_no_flc(self) -> None:
        """Complete a two-tap plate measurement (L + C, no FLC).

        Called from accept_current_phase when leaving REVIEWING_CROSS without FLC.
        Mirrors the no-FLC branch of Swift acceptCurrentPhase.
        """
        import numpy as _np

        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
        self._set_material_tap_phase(_MTP.COMPLETE)
        self.set_measurement_complete(True)
        # Save the session WAV — mirrors Swift finishSessionRecording(label: "Plate_LC").
        self.finish_session_recording(label="Plate_LC")

        fl_str = (
            f"{fp.string(self.selected_longitudinal_peak.frequency, fp.PEAK_FREQUENCY_HZ)}"
            if self.selected_longitudinal_peak else "?"
        )
        fc_str = (
            f"{fp.string(self.selected_cross_peak.frequency, fp.PEAK_FREQUENCY_HZ)}"
            if self.selected_cross_peak else "?"
        )
        self._set_status_message(
            f"Complete \u2014 fL: {fl_str} Hz, fC: {fc_str} Hz"
        )

        self._emit_peaks_array(self.peaks_above_peak_min)

        l_mags, l_freqs = self.longitudinal_spectrum
        c_mags, c_freqs = self.cross_spectrum
        self.set_material_spectra([
            ("Longitudinal (fL)", _FL, list(l_freqs), list(l_mags)),
            ("Cross-grain (fC)",  _FC, list(c_freqs), list(c_mags)),
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

        self.set_frozen_spectrum(_np.array([]), _np.array([]))

        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
        self._set_material_tap_phase(_MTP.COMPLETE)
        self.set_measurement_complete(True)
        # Save the session WAV — mirrors Swift finishSessionRecording(label: "Plate_LCF").
        self.finish_session_recording(label="Plate_LCF")
        self._set_status_message("Complete - check Results")

        self._emit_peaks_array(self.peaks_above_peak_min)

        l_mags, l_freqs = self.longitudinal_spectrum
        c_mags, c_freqs = self.cross_spectrum
        f_mags, f_freqs = self.flc_spectrum
        self.set_material_spectra([
            ("Longitudinal (fL)", _FL, list(l_freqs), list(l_mags)),
            ("Cross-grain (fC)",  _FC, list(c_freqs), list(c_mags)),
            ("Diagonal (fLC)",              _FLC, list(f_freqs), list(f_mags)),
        ])

        l_freq = self.selected_longitudinal_peak.frequency if self.selected_longitudinal_peak else 0.0
        c_freq = self.selected_cross_peak.frequency if self.selected_cross_peak else 0.0
        f_freq = self.selected_flc_peak.frequency if self.selected_flc_peak else 0.0
        self.plateAnalysisComplete.emit(l_freq, c_freq, f_freq)

    # ------------------------------------------------------------------ #
    # Measurement type
    # ------------------------------------------------------------------ #

    def set_measurement_type(self, measurement_type) -> None:
        """Switch between Guitar / Plate / Brace analysis modes — sets the saved measurement type,
        which the analyzer reads (``_measurement_type``)."""
        import guitar_tap.models.measurement_type as _mt_mod
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        if isinstance(measurement_type, str):
            measurement_type = _mt_mod.MeasurementType.from_combo_values(measurement_type, "")
        _tds.set_measurement_type(measurement_type)

    # ------------------------------------------------------------------ #
    # Axis and parameter setters
    # ------------------------------------------------------------------ #

    def set_threshold(self, threshold: int) -> None:
        """Set the peak-detection threshold (0-100 scale, stored as dBFS)."""
        # Assigning peak_min_threshold saves and re-projects (the property setter, Swift's didSet).
        self.peak_min_threshold = float(threshold - 100)
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        # Notify the view the projection changed (peaks_above_peak_min is a plain attr, not @Published).
        # The measurement's peaks: the projection (guitar) or the identified L/C/FLC (material).
        self.peaks.peaksChanged.emit(list(
            self.peaks_above_peak_min if _tds.measurement_type().is_guitar else self.material_identified_peaks
        ))

    def set_loaded_axis_range(
        self, min_freq: float, max_freq: float, min_db: float, max_db: float
    ) -> None:
        """Publish all four axis bounds atomically via loadedAxisRangeChanged.

        Mirrors Swift TapToneAnalyzer.setLoadedAxisRange(minFreq:maxFreq:minDB:maxDB:)
        which sets loadedAxisRange (a struct) in a single objectWillChange notification so
        the view applies all four bounds in one render pass. A display range only: the analysis
        range (min_frequency / max_frequency, the fixed 30–2000 Hz find_peaks searches) is not touched.
        """
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
        self.selected_longitudinal_peak = None
        self.selected_cross_peak = None
        self.selected_flc_peak = None
        # All phase spectra cleared — mirrors Swift's @Published vars becoming nil,
        # which causes materialSpectra to return [] and SpectrumView to restore the live curve.
        self.set_material_spectra([])

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
