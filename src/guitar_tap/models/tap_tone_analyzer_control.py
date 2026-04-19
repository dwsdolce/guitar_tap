"""
TapToneAnalyzer+Control — lifecycle control, device management, calibration,
tap-sequence management, and parameter setters.

Mirrors Swift TapToneAnalyzer+Control.swift.
"""

from __future__ import annotations

import time as _time


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
        """Handle a hot-plug event (always on main thread)."""
        self.mic.reinitialize_portaudio()
        try:
            names: list = sorted(
                str(d["name"]) for d in self._sd.query_devices() if d["max_input_channels"] > 0
            )
        except Exception:
            names = []
        self.devicesChanged.emit(names)
        if (
            self._calibration_device_name
            and self._calibration_device_name not in names
        ):
            self.currentDeviceLost.emit(self._calibration_device_name)

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
        This method only syncs the Python-layer fft_data sample rate after the
        switch, which has no Swift equivalent (Swift derives sample rate from
        the running AVAudioEngine directly).

        Mirrors Swift TapToneAnalyzer+Control.swift: setInputDevice is called
        on fftAnalyzer, then selectedInputDevice.didSet applies calibration —
        both now happen inside RealtimeFFTAnalyzer.set_device().
        """
        self._calibration_device_name = device.name
        self.mic.set_device(device)
        # Sync fft_data sample rate to the new device's native rate so the
        # frequency axis stays correct.  Python-only — Swift reads actualSampleRate
        # from the running AVAudioEngine.
        if self.mic.rate != self.fft_data.sample_freq:
            self.fft_data.sample_freq = self.mic.rate

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

    # ------------------------------------------------------------------ #
    # Tap detector control — all state lives directly on TapToneAnalyzer,
    # mirroring Swift where detectTap() and all tap state are on the class.
    # ------------------------------------------------------------------ #

    def set_tap_threshold(self, value: int) -> None:
        """Update tap-trigger threshold (0-100 scale → dBFS)."""
        self.tap_detection_threshold = float(value - 100)
        from models.tap_display_settings import TapDisplaySettings as _tds
        _tds.set_tap_detection_threshold(self.tap_detection_threshold)
        # mirrors tapDetectionThreshold.didSet in Swift

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

    def start_tap_sequence(self) -> None:
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

        meas_type = _tds.measurement_type()
        is_plate = (meas_type == _MT.PLATE)
        is_brace = (meas_type == _MT.BRACE)

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

        # Reset the warm-up timer for this new sequence (mirrors Swift analyzerStartTime = Date()).
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
            print(f"⚠️ accept_current_phase called in unexpected phase: {phase}")

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
            print(f"⚠️ redo_current_phase called in unexpected phase: {phase}")
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
        self.is_measurement_complete = True
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
        self.is_measurement_complete = True
        self.tap_progress = 1.0
        self._set_status_message("Complete \u2014 check Results")

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
            # n_fmin / n_fmax are now computed properties — no assignment needed.
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
            self._decay_tracking_timer.cancel()
            self._decay_tracking_timer = None
