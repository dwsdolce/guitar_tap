"""
TapToneAnalyzer+Control — lifecycle control, device management, calibration,
tap-sequence management, and parameter setters.

Mirrors Swift TapToneAnalyzer+Control.swift.
"""

from __future__ import annotations


class TapToneAnalyzerControlMixin:
    """Lifecycle control and parameter management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+Control.swift.
    """

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
            if self._proc_thread is not None:
                self._proc_thread.set_calibration(self._calibration_corrections)
            return True
        except Exception:
            return False

    def load_calibration_from_profile(self, cal) -> None:
        """Apply a pre-parsed MicrophoneCalibration profile to the FFT pipeline."""
        self._calibration_corrections = cal.interpolate_to_bins(self.freq)
        if self._proc_thread is not None:
            self._proc_thread.set_calibration(self._calibration_corrections)

    def clear_calibration(self) -> None:
        """Remove the active calibration."""
        self._calibration_corrections = None
        if self._proc_thread is not None:
            self._proc_thread.set_calibration(None)

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self._calibration_device_name

    def set_device(self, device) -> None:
        """Switch to a different input device and auto-load its calibration.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:) + selectedInputDevice.didSet.

        Args:
            device: AudioDevice to switch to.
        """
        import math as _math
        from models.microphone_calibration import CalibrationStorage as _CS
        self.mic.set_device(device)
        # Sync fft_data sample rate to the new device's native rate so the
        # frequency axis stays correct.
        if self.mic.rate != self.fft_data.sample_freq:
            self.fft_data.sample_freq = self.mic.rate
            self.fft_data.n_f = int(2 ** _math.ceil(_math.log2(self.fft_data.m_t)))
            self.fft_data.h_n_f = self.fft_data.n_f // 2
        self._calibration_device_name = device.name
        # Auto-load the device-specific calibration (mirrors selectedInputDevice.didSet).
        # Try fingerprint key first, then fall back to name-only key for measurements
        # saved before fingerprints were introduced.
        cal = _CS.calibration_for_device(device.fingerprint)
        if cal is None:
            cal = _CS.calibration_for_device(device.name)
        if cal is not None:
            self.load_calibration_from_profile(cal)
        else:
            self.clear_calibration()

    # ------------------------------------------------------------------ #
    # Tap detector control (delegated to _proc_thread)
    # ------------------------------------------------------------------ #

    def reset_tap_detector(self) -> None:
        if self._proc_thread is not None:
            self._proc_thread.reset_tap_detector()

    def set_tap_threshold(self, value: int) -> None:
        if self._proc_thread is not None:
            self._proc_thread.set_tap_threshold(value)

    def set_hysteresis_margin(self, value: float) -> None:
        if self._proc_thread is not None:
            self._proc_thread.set_hysteresis_margin(value)

    def pause_tap_detection(self) -> None:
        if self._proc_thread is not None:
            self._proc_thread.pause_tap_detection()
        self.tapDetectionPaused.emit(True)

    def resume_tap_detection(self) -> None:
        if self._proc_thread is not None:
            self._proc_thread.reset_tap_detector()  # WARMUP — matches Swift resumeTapDetection
        self.tapDetectionPaused.emit(False)

    def cancel_tap_sequence(self) -> None:
        self._tap_spectra.clear()
        if self._proc_thread is not None:
            self._proc_thread.reset_tap_detector()  # WARMUP — matches Swift cancelTapSequence
        self.tapCountChanged.emit(0, self._tap_num)

    # ------------------------------------------------------------------ #
    # Tap sequence management
    # ------------------------------------------------------------------ #

    def start_tap_sequence(self) -> None:
        """Begin a fresh tap sequence: clear accumulated spectra and restart warmup."""
        self._tap_spectra.clear()
        self.reset_tap_detector()
        self.tapCountChanged.emit(0, self._tap_num)

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing.

        Mirrors Swift numberOfTaps.didSet: if the user reduces the tap count
        to at or below what has already been captured mid-sequence, process
        immediately rather than waiting for more taps.
        """
        import numpy as np
        new_num = max(1, n)
        captured = len(self._tap_spectra)
        if captured >= new_num and captured > 0:
            # Already have enough — process now (mirrors Swift numberOfTaps.didSet)
            self._tap_num = new_num
            stacked = np.stack(self._tap_spectra[:new_num])
            avg_db = 10.0 * np.log10(np.mean(np.power(10.0, stacked / 10.0), axis=0))
            self.saved_mag_y_db = avg_db
            _, _ = self.find_peaks(avg_db)
            self._tap_spectra.clear()
            self.tapDetectedSignal.emit()
        else:
            self._tap_num = new_num
            # Don't clear spectra when count is raised mid-sequence — keep what
            # was already captured (mirrors Swift which never clears capturedTaps here).

    # ------------------------------------------------------------------ #
    # Measurement type
    # ------------------------------------------------------------------ #

    def set_measurement_type(self, measurement_type) -> None:
        """Switch between Guitar / Plate / Brace analysis modes."""
        import models.measurement_type as _mt_mod
        if isinstance(measurement_type, str):
            measurement_type = _mt_mod.MeasurementType.from_combo_values(measurement_type, "")
        self._measurement_type = measurement_type
        if self._proc_thread is not None:
            self._proc_thread.set_measurement_type(measurement_type.is_guitar)

    # ------------------------------------------------------------------ #
    # Axis and parameter setters
    # ------------------------------------------------------------------ #

    def set_threshold(self, threshold: int) -> None:
        """Set the peak-detection threshold (0-100 scale)."""
        self.threshold = threshold
        if self._loaded_measurement_peaks is not None:
            self._emit_loaded_peaks_at_threshold()
        else:
            self.find_peaks(self.saved_mag_y_db)

    def set_fmin(self, fmin: int) -> None:
        self.update_axis(fmin, self.fmax)

    def set_fmax(self, fmax: int) -> None:
        self.update_axis(self.fmin, fmax)

    def update_axis(self, fmin: int, fmax: int, init: bool = False) -> None:
        """Update the frequency analysis range."""
        if fmin < fmax:
            self.fmin = fmin
            self.fmax = fmax
            self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
            self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq
        if not init:
            if self._loaded_measurement_peaks is not None:
                self._emit_loaded_peaks_at_threshold()
            else:
                self.find_peaks(self.saved_mag_y_db)

    def set_max_average_count(self, max_average_count: int) -> None:
        self.max_average_count = max_average_count

    def reset_averaging(self) -> None:
        self.num_averages = 0

    def set_avg_enable(self, avg_enable: bool) -> None:
        self.avg_enable = avg_enable

    def set_auto_scale(self, enabled: bool) -> None:
        self._auto_scale_db = enabled
