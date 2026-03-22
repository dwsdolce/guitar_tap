"""
    Custom widget containing all of the controls for calculating peaks from the FFT.
"""

import os

from PyQt6 import QtWidgets, QtCore, QtGui
import gt_images as gt_i

basedir = os.path.dirname(__file__)



def _row(label_text: str, widget: QtWidgets.QWidget) -> QtWidgets.QHBoxLayout:
    """Helper: left label + right-aligned widget in an HBoxLayout."""
    layout = QtWidgets.QHBoxLayout()
    lbl = QtWidgets.QLabel(label_text)
    lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(lbl)
    layout.addWidget(widget)
    return layout


# pylint: disable=too-many-instance-attributes
class PeakControls(QtWidgets.QWidget):
    """Layout of the controls for calculating peaks from the FFT."""

    # pylint: disable=too-many-locals
    # pylint: disable=too-many-statements
    def __init__(self, f_range: dict[str, int], fft_settings: dict[str, int]) -> None:
        super().__init__()

        spectral_line_resolution = (
            fft_settings["sampling_rate"] / fft_settings["window_length"]
        )
        bandwidth = fft_settings["sampling_rate"] / 2
        sample_size = fft_settings["window_length"] / fft_settings["sampling_rate"]

        pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, "SP_MediaSkipBackward")
        restart_icon = self.style().standardIcon(pixmapi)

        # ---- inner widget lives inside a scroll area --------------------
        self._inner = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(self._inner)   # cl = control_layout
        cl.setSpacing(4)
        cl.setContentsMargins(6, 6, 6, 6)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self._inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.setMaximumWidth(240)

        # Status label
        self.status_label = QtWidgets.QLabel("Stopped")
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        small_font = QtGui.QFont()
        small_font.setPointSize(10)
        self.status_label.setFont(small_font)
        cl.addWidget(self.status_label)

        cl.addSpacing(4)

        # ================================================================
        # MEASUREMENT GROUP
        # ================================================================
        meas_group = QtWidgets.QGroupBox("Measurement")
        meas_gl = QtWidgets.QVBoxLayout(meas_group)
        meas_gl.setSpacing(3)

        # Measurement type
        self.measurement_type_combo = QtWidgets.QComboBox()
        self.measurement_type_combo.addItems(["Guitar", "Plate", "Brace"])
        self.measurement_type_combo.setToolTip(
            "Guitar: FFT peak analysis\n"
            "Plate / Brace: two-tap material property analysis"
        )
        meas_gl.addLayout(_row("Type:", self.measurement_type_combo))

        # Guitar type
        self.guitar_type_combo = QtWidgets.QComboBox()
        self.guitar_type_combo.addItems(["Classical", "Flamenco", "Acoustic"])
        self.guitar_type_combo.setToolTip(
            "Select the guitar type to set mode classification frequency bands"
        )
        meas_gl.addLayout(_row("Guitar:", self.guitar_type_combo))

        # Show mode bands LED
        self.show_bands_btn = QtWidgets.QToolButton()
        self.show_bands_btn.setIcon(gt_i.GtImages.green_button_icon())
        self.show_bands_btn.setIconSize(QtCore.QSize(21, 21))
        self.show_bands_btn.setStyleSheet("border: none")
        self.show_bands_btn.setCheckable(True)
        self.show_bands_btn.setChecked(True)
        self.show_bands_btn.setToolTip("Toggle frequency band overlays on the spectrum")
        meas_gl.addLayout(_row("Mode bands:", self.show_bands_btn))

        cl.addWidget(meas_group)

        # ================================================================
        # TAP CONTROLS GROUP
        # ================================================================
        tap_group = QtWidgets.QGroupBox("Tap Controls")
        tap_gl = QtWidgets.QVBoxLayout(tap_group)
        tap_gl.setSpacing(3)

        # Taps to average
        self.tap_num_spin = QtWidgets.QSpinBox()
        self.tap_num_spin.setMinimum(1)
        self.tap_num_spin.setMaximum(10)
        self.tap_num_spin.setValue(1)
        self.tap_num_spin.setToolTip(
            "Number of taps to accumulate and average before freezing results"
        )
        tap_gl.addLayout(_row("Taps to avg:", self.tap_num_spin))

        # Taps captured
        self.tap_count_value = QtWidgets.QLabel("0 / 1")
        self.tap_count_value.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        tap_gl.addLayout(_row("Captured:", self.tap_count_value))

        # New Tap button
        self.new_tap_btn = QtWidgets.QPushButton("New Tap")
        self.new_tap_btn.setToolTip("Clear held results and listen for the next tap")
        self.new_tap_btn.setEnabled(False)
        tap_gl.addWidget(self.new_tap_btn)

        # Plate / Brace analysis button (hidden unless in plate/brace mode)
        self.plate_analysis_btn = QtWidgets.QPushButton("Plate / Brace Analysis…")
        self.plate_analysis_btn.setToolTip(
            "Open the plate/brace tap-tone material analysis dialog"
        )
        self.plate_analysis_btn.setVisible(False)
        tap_gl.addWidget(self.plate_analysis_btn)

        # Tap detection threshold
        self.tap_threshold_spin = QtWidgets.QSpinBox()
        self.tap_threshold_spin.setMinimum(0)
        self.tap_threshold_spin.setMaximum(100)
        self.tap_threshold_spin.setValue(60)
        self.tap_threshold_spin.setToolTip(
            "Amplitude level (0–100) that triggers automatic tap detection\n"
            "(shown as orange dashed line on spectrum)"
        )
        tap_gl.addLayout(_row("Tap threshold:", self.tap_threshold_spin))

        # Ring-out
        self.ring_out_value = QtWidgets.QLabel("--")
        self.ring_out_value.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        tap_gl.addLayout(_row("Ring-out:", self.ring_out_value))

        cl.addWidget(tap_group)

        # ================================================================
        # RESULTS GROUP
        # ================================================================
        results_group = QtWidgets.QGroupBox("Results")
        results_gl = QtWidgets.QVBoxLayout(results_group)
        results_gl.setSpacing(3)

        # Auto-scale dB
        self.auto_db_btn = QtWidgets.QToolButton()
        self.auto_db_btn.setIcon(gt_i.GtImages.red_button_icon())
        self.auto_db_btn.setIconSize(QtCore.QSize(21, 21))
        self.auto_db_btn.setStyleSheet("border: none")
        self.auto_db_btn.setCheckable(True)
        self.auto_db_btn.setChecked(False)
        self.auto_db_btn.setToolTip("Automatically scale the dB axis to the spectrum floor")
        results_gl.addLayout(_row("Auto scale dB:", self.auto_db_btn))

        # Tap tone ratios
        self.ratio_top_helm = QtWidgets.QLabel("—")
        self.ratio_top_helm.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        results_gl.addLayout(_row("Top / Helm:", self.ratio_top_helm))

        self.ratio_back_helm = QtWidgets.QLabel("—")
        self.ratio_back_helm.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        results_gl.addLayout(_row("Back / Helm:", self.ratio_back_helm))

        self.ratio_top_back = QtWidgets.QLabel("—")
        self.ratio_top_back.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        results_gl.addLayout(_row("Top / Back:", self.ratio_top_back))

        cl.addWidget(results_group)

        # ================================================================
        # SPECTRUM AVERAGING GROUP
        # ================================================================
        avg_group = QtWidgets.QGroupBox("Spectrum Averaging")
        avg_gl = QtWidgets.QVBoxLayout(avg_group)
        avg_gl.setSpacing(3)

        self.num_averages = QtWidgets.QSpinBox()
        self.num_averages.setMinimum(0)
        self.num_averages.setMaximum(10)
        self.num_averages.setValue(0)
        self.num_averages.setToolTip("Set the number of fft samples to average")
        avg_gl.addLayout(_row("Num averages:", self.num_averages))

        self.avg_enable = QtWidgets.QToolButton()
        self.avg_enable.setIcon(gt_i.GtImages.red_button_icon())
        self.avg_enable.setIconSize(QtCore.QSize(21, 21))
        self.avg_enable.setStyleSheet("border: none")
        self.avg_enable.setCheckable(True)
        self.avg_enable.setChecked(False)
        self.avg_enable.setToolTip("Select to start averaging the fft samples.")
        avg_gl.addLayout(_row("Averaging:", self.avg_enable))
        self.avg_enable_saved: bool = self.avg_enable.isChecked()

        self.avg_completed = QtWidgets.QLabel("0")
        self.avg_completed.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        avg_gl.addLayout(_row("Completed:", self.avg_completed))

        avg_done_row = QtWidgets.QHBoxLayout()
        avg_done_label = QtWidgets.QLabel("Done:")
        avg_done_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        avg_done_row.addWidget(avg_done_label)
        self.avg_done = QtWidgets.QLabel()
        self.avg_done.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.avg_done.setMaximumSize(21, 21)
        self.avg_done.setPixmap(gt_i.GtImages.red_pixmap())
        self.avg_done.setScaledContents(True)
        avg_done_row.addWidget(self.avg_done)
        avg_gl.addLayout(avg_done_row)

        avg_restart_row = QtWidgets.QHBoxLayout()
        avg_restart_label = QtWidgets.QLabel("Restart:")
        avg_restart_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        avg_restart_row.addWidget(avg_restart_label)
        self.avg_restart = QtWidgets.QPushButton()
        self.avg_restart.setIcon(restart_icon)
        self.avg_restart.setToolTip("Reset the number of averages and start again")
        avg_restart_row.addWidget(self.avg_restart)
        avg_gl.addLayout(avg_restart_row)

        cl.addWidget(avg_group)

        # ================================================================
        # FREQUENCY RANGE
        # ================================================================
        freq_group = QtWidgets.QGroupBox("Frequency Range")
        freq_gl = QtWidgets.QVBoxLayout(freq_group)
        freq_gl.setSpacing(3)

        self.min_spin = QtWidgets.QSpinBox()
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(f_range["f_min"])
        self.min_spin.setToolTip("The lowest frequency for which peaks are reported")
        freq_gl.addLayout(_row("Start (Hz):", self.min_spin))

        self.max_spin = QtWidgets.QSpinBox()
        self.max_spin.setMinimum(0)
        self.max_spin.setMaximum(22050)
        self.max_spin.setValue(f_range["f_max"])
        self.max_spin.setToolTip("The highest frequency for which peaks are reported")
        freq_gl.addLayout(_row("Stop (Hz):", self.max_spin))

        cl.addWidget(freq_group)

        # ================================================================
        # MEASUREMENTS / EXPORT
        # ================================================================
        export_group = QtWidgets.QGroupBox("Measurements")
        export_gl = QtWidgets.QVBoxLayout(export_group)
        export_gl.setSpacing(3)

        self.save_measurement_btn = QtWidgets.QPushButton("Save Measurement")
        self.save_measurement_btn.setToolTip(
            "Save the current held peaks to a JSON measurement file"
        )
        self.save_measurement_btn.setEnabled(False)
        export_gl.addWidget(self.save_measurement_btn)

        self.open_measurements_btn = QtWidgets.QPushButton("Measurements…")
        self.open_measurements_btn.setToolTip("Browse, load, or delete saved measurements")
        export_gl.addWidget(self.open_measurements_btn)

        self.export_pdf_btn = QtWidgets.QPushButton("Export PDF…")
        self.export_pdf_btn.setToolTip("Export the current measurement to a PDF report")
        self.export_pdf_btn.setEnabled(False)
        export_gl.addWidget(self.export_pdf_btn)

        cl.addWidget(export_group)

        # ================================================================
        # AUDIO / CALIBRATION
        # ================================================================
        audio_group = QtWidgets.QGroupBox("Audio")
        audio_gl = QtWidgets.QVBoxLayout(audio_group)
        audio_gl.setSpacing(3)

        self.import_cal_btn = QtWidgets.QPushButton("Import Calibration…")
        self.import_cal_btn.setToolTip(
            "Load a UMIK-1 / REW .cal calibration file for the current microphone"
        )
        audio_gl.addWidget(self.import_cal_btn)

        self.cal_status = QtWidgets.QLabel("Calibration: none")
        self.cal_status.setWordWrap(True)
        self.cal_status.setFont(small_font)
        audio_gl.addWidget(self.cal_status)

        self.show_devices = QtWidgets.QPushButton("Input Devices")
        self.show_devices.setToolTip("Display the default and all input devices")
        audio_gl.addWidget(self.show_devices)

        cl.addWidget(audio_group)

        # ================================================================
        # FFT INFO (compact, bottom)
        # ================================================================
        info_group = QtWidgets.QGroupBox("FFT Info")
        info_gl = QtWidgets.QVBoxLayout(info_group)
        info_gl.setSpacing(2)
        info_gl.setContentsMargins(6, 4, 6, 4)

        def _info_row(label: str, value: str) -> tuple[QtWidgets.QHBoxLayout, QtWidgets.QLabel]:
            lyt = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setFont(small_font)
            val = QtWidgets.QLabel(value)
            val.setFont(small_font)
            val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            lyt.addWidget(lbl)
            lyt.addWidget(val)
            return lyt, val

        lyt, _ = _info_row("Freq res:", f"{spectral_line_resolution:.2g} Hz")
        info_gl.addLayout(lyt)
        lyt, _ = _info_row("Bandwidth:", f"{bandwidth:.0f} Hz")
        info_gl.addLayout(lyt)
        lyt, _ = _info_row("Sample len:", f"{sample_size:.1f} s")
        info_gl.addLayout(lyt)

        lyt, self.framerate = _info_row("Frame rate:", "—")
        info_gl.addLayout(lyt)
        lyt, self.sampletime = _info_row("Sample time:", "—")
        info_gl.addLayout(lyt)
        lyt, self.processingtime = _info_row("Processing:", "—")
        info_gl.addLayout(lyt)

        cl.addWidget(info_group)

        cl.addSpacing(8)

        # ----------------------------------------------------------------
        # hold_results: kept as a hidden, non-visible widget so that
        # internal averaging logic (set_avg_completed / reset_averaging)
        # can still toggle it programmatically without needing a refactor.
        # The user never sees this button.
        # ----------------------------------------------------------------
        self.hold_results = QtWidgets.QToolButton()
        self.hold_results.setCheckable(True)
        self.hold_results.setChecked(False)
        self.hold_results.setVisible(False)

    # ================================================================
    # Public update methods
    # ================================================================

    def set_running(self, running: bool) -> None:
        if running:
            self.status_label.setText("Listening for tap…")
            self.new_tap_btn.setEnabled(True)
        else:
            self.status_label.setText("Stopped")
            self.new_tap_btn.setEnabled(False)

    def set_status(self, text: str) -> None:
        """Update the one-line status label below the Start button."""
        self.status_label.setText(text)

    def update_tap_tone_ratios(self, mode_freqs: dict[str, float]) -> None:
        """Recompute and display tap tone ratios from a {mode_name: freq_Hz} dict."""
        helm = mode_freqs.get("Helmholtz T(1,1)_1")
        top  = mode_freqs.get("Top T(1,1)_2")
        back = mode_freqs.get("Back T(1,1)_3")

        def _fmt(a: float | None, b: float | None) -> str:
            if a and b and b > 0:
                return f"{a / b:.3f}"
            return "—"

        self.ratio_top_helm.setText(_fmt(top, helm))
        self.ratio_back_helm.setText(_fmt(back, helm))
        self.ratio_top_back.setText(_fmt(top, back))

    def set_measurement_type_ui(self, measurement_type: str) -> None:
        """Show plate analysis button only for Plate/Brace measurement types."""
        self.plate_analysis_btn.setVisible(measurement_type in ("Plate", "Brace"))

    def set_calibration_status(self, path: str) -> None:
        """Show the active calibration file name (or 'none')."""
        if path:
            self.cal_status.setText(f"Calibration: {os.path.basename(path)}")
        else:
            self.cal_status.setText("Calibration: none")

    def set_tap_count(self, captured: int, total: int) -> None:
        """Update the tap accumulator progress display."""
        self.tap_count_value.setText(f"{captured} / {total}")

    def set_auto_db(self, enabled: bool) -> None:
        """Update the auto-scale button icon to reflect state."""
        icon = gt_i.GtImages.green_button_icon() if enabled else gt_i.GtImages.red_button_icon()
        self.auto_db_btn.setIcon(icon)

    def set_ring_out(self, time_s: float) -> None:
        """Display the measured ring-out time."""
        self.ring_out_value.setText(f"{time_s:.2f} s")

    def set_framerate(
        self, framerate: float, sampletime: float, processingtime: float
    ) -> None:
        """Update the FFT Info status labels."""
        self.framerate.setText(f"{framerate:.1f} fps")
        self.sampletime.setText(f"{sampletime:.1f} s")
        self.processingtime.setText(f"{processingtime * 1000:.1f} ms")

    def set_avg_enable(self, state: bool) -> None:
        """Change the averaging LED and enable/disable restart."""
        if state:
            self.avg_enable.setIcon(gt_i.GtImages.green_button_icon())
            self.avg_restart.setEnabled(True)
        else:
            self.avg_enable.setIcon(gt_i.GtImages.red_button_icon())
            self.avg_restart.setEnabled(False)

    def set_hold_results(self, state: bool) -> None:
        """React to hold state changes: gate averaging controls and export buttons."""
        if state:
            self.avg_enable_saved = self.avg_enable.isChecked()
            self.set_avg_enable(False)
            self.avg_enable.setEnabled(False)
            self.avg_restart.setEnabled(False)
            self.save_measurement_btn.setEnabled(True)
            self.export_pdf_btn.setEnabled(True)
        else:
            self.avg_enable.setEnabled(True)
            self.save_measurement_btn.setEnabled(False)
            self.export_pdf_btn.setEnabled(False)

    def reset_averaging(self) -> None:
        """Reset averaging controls and release any hold."""
        self.set_avg_completed(0)
        self.avg_done.setPixmap(gt_i.GtImages.red_pixmap())
        if self.hold_results.isChecked():
            self.hold_results.click()

    def set_avg_completed(self, count: int) -> None:
        """Check whether the maximum number of averages has been reached."""
        self.avg_completed.setText(str(count))
        if count >= self.num_averages.value():
            self.avg_done.setPixmap(gt_i.GtImages.green_pixmap())
            self.num_averages.setEnabled(True)
            self.hold_results.click()          # triggers set_hold_results via signal
            self.avg_restart.setEnabled(True)
        else:
            self.num_averages.setEnabled(False)
            self.avg_restart.setEnabled(False)
            self.avg_enable.setEnabled(False)
