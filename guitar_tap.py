""" Samples audio signal and finds the peaks of the guitar tap resonances
"""

import sys
import os

import numpy as np
import sounddevice as sd
from PyQt6 import QtWidgets, QtGui, QtCore

import fft_canvas as fft_c
import fft_toolbar as fft_t
import peaks_table as PT
import show_devices as SD
import app_settings as AS
import measurement as M
import measurements_dialog as MD
import plate_analysis as PA
import plate_dialog as PD
import guitar_modes as GM
import help_dialog as HD
import gt_images as gt_i
import qtawesome as qta

basedir = os.path.dirname(__file__)

if os.name == "nt":
    import named_mutex as NM
    from ctypes import windll
    MY_APP_ID = "dolcesfogato.guitar-tap.guitar-tap.0.5"
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(MY_APP_ID)



def _vsep() -> QtWidgets.QFrame:
    """Thin vertical separator for horizontal toolbars."""
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return sep


def _hsep() -> QtWidgets.QFrame:
    """Thin horizontal separator."""
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return sep


class MainWindow(QtWidgets.QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()

        self.saved_path: str = ""
        self._ring_out_s: float | None = None
        self._is_running: bool = False
        self._is_paused: bool = False
        self._is_frozen: bool = False
        self._tap_count_captured: int = 0
        self._plate_dialog: PD.PlateDialog | None = None
        self._help_dialog: HD.HelpDialog | None = None
        self._metrics_dialog: QtWidgets.QDialog | None = None
        self._proc_times: list[float] = []          # rolling 30-frame processing times
        self.avg_enable_saved: bool = False

        with open(os.path.join(basedir, "./version"), "r", encoding="UTF-8") as fh:
            version = fh.read().rstrip()
        self.setWindowTitle(f"Guitar Tap {version}")

        # Menu bar — Help menu
        help_menu = self.menuBar().addMenu("Help")
        help_action = QtGui.QAction("Guitar Tap Help", self)
        help_action.setShortcut(QtGui.QKeySequence("Ctrl+?"))
        help_action.triggered.connect(self._show_help)
        help_menu.addAction(help_action)

        # Window geometry
        geom = AS.AppSettings.window_geometry()
        if geom:
            self.restoreGeometry(geom)
            screen = QtWidgets.QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                w = min(self.width(), available.width() - 40)
                h = min(self.height(), available.height() - 40)
                self.resize(w, h)
                fg = self.frameGeometry()
                if not available.contains(fg.topLeft()):
                    self.move(available.center() - self.rect().center())
        else:
            self.resize(1200, 760)

        # Audio / FFT parameters
        self.threshold: int = AS.AppSettings.threshold()
        fft_settings: dict[str, int] = {
            "sampling_rate": 48000,
            "window_length": 4 * 16384,
        }
        f_range: dict[str, int] = {
            "f_min": AS.AppSettings.f_min(),
            "f_max": AS.AppSettings.f_max(),
        }

        # Build FftCanvas first — everything else references it
        self.fft_canvas = fft_c.FftCanvas(
            fft_settings["window_length"],
            fft_settings["sampling_rate"],
            f_range,
            self.threshold,
        )
        self.fft_canvas.setMinimumSize(500, 350)

        # ── Root layout (vertical) ───────────────────────────────────────
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        root = QtWidgets.QVBoxLayout(main_widget)
        root.setSpacing(0)
        root.setContentsMargins(2, 2, 2, 2)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_controls_bar(fft_settings))

        # Content row: canvas (stretch) + divider + results panel (content-sized, always visible)
        content = QtWidgets.QWidget()
        ch = QtWidgets.QHBoxLayout(content)
        ch.setSpacing(0)
        ch.setContentsMargins(0, 4, 0, 0)
        root.addWidget(content, stretch=1)

        # Left: canvas + pyqtgraph toolbar
        canvas_widget = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(canvas_widget)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.fft_canvas, stretch=1)
        self._fft_toolbar = fft_t.FftToolbar(self.fft_canvas, canvas_widget)
        cv.addWidget(self._fft_toolbar)
        ch.addWidget(canvas_widget, stretch=1)

        ch.addWidget(_vsep())

        # Right: results panel — sizes to its content, never hidden
        self._right_panel = self._build_right_panel(f_range)
        ch.addWidget(self._right_panel)

        # Bottom status bar
        root.addWidget(self._build_status_bar())

        # Wire everything up
        self._connect_signals()
        self._init_state(f_range)

    # ================================================================
    # Layout builders
    # ================================================================

    def _build_toolbar(self) -> QtWidgets.QWidget:
        """Top button bar: display toggles, save, measurements."""
        bar = QtWidgets.QWidget()
        bar.setObjectName("toolbar")
        bar.setStyleSheet("#toolbar { border-bottom: 1px solid palette(mid); }")
        hl = QtWidgets.QHBoxLayout(bar)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        hl.addStretch()

        self.auto_db_btn = QtWidgets.QToolButton()
        self.auto_db_btn.setIcon(qta.icon("mdi.swap-vertical-circle-outline"))
        self.auto_db_btn.setIconSize(QtCore.QSize(18, 18))
        self.auto_db_btn.setText("Auto dB")
        self.auto_db_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.auto_db_btn.setStyleSheet("border: none")
        self.auto_db_btn.setCheckable(True)
        self.auto_db_btn.setChecked(False)
        self.auto_db_btn.setToolTip("Automatically scale the dB axis to the spectrum floor")
        hl.addWidget(self.auto_db_btn)

        hl.addSpacing(4)

        self.annotations_btn = QtWidgets.QToolButton()
        self.annotations_btn.setIcon(qta.icon("fa5.star"))
        self.annotations_btn.setIconSize(QtCore.QSize(16, 16))
        self.annotations_btn.setText("Annotations")
        self.annotations_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.annotations_btn.setStyleSheet("border: none")
        self.annotations_btn.setToolTip(
            "Annotation visibility: Selected\nClick to cycle: Selected → None → All"
        )
        self._ann_mode_idx: int = 0
        hl.addWidget(self.annotations_btn)

        hl.addSpacing(4)

        self.save_measurement_btn = QtWidgets.QPushButton(
            qta.icon("fa5.save"), "Save"
        )
        self.save_measurement_btn.setToolTip("Save the current held peaks to a JSON file")
        self.save_measurement_btn.setEnabled(False)
        hl.addWidget(self.save_measurement_btn)

        self.open_measurements_btn = QtWidgets.QPushButton(
            qta.icon("fa5s.clipboard-list"), "Measurements"
        )
        self.open_measurements_btn.setToolTip("Browse, load, or delete saved measurements")
        hl.addWidget(self.open_measurements_btn)

        metrics_btn = QtWidgets.QPushButton(qta.icon("fa5.chart-bar"), "Metrics")
        metrics_btn.setToolTip("Show FFT diagnostics: frame rate, sample time, processing time")
        metrics_btn.clicked.connect(self._show_metrics)
        hl.addWidget(metrics_btn)

        hl.addWidget(_vsep())

        settings_btn = QtWidgets.QPushButton(qta.icon("fa5s.cog"), "Settings")
        settings_btn.setToolTip(
            "Frequency range, spectrum averaging, audio and calibration settings"
        )
        settings_btn.clicked.connect(self._show_settings)
        hl.addWidget(settings_btn)

        return bar

    def _build_controls_bar(self, fft_settings: dict[str, int]) -> QtWidgets.QWidget:
        """Controls bar: Taps | Threshold | Hysteresis | Peak Min || New Tap | Pause | Cancel"""
        bar = QtWidgets.QWidget()
        bar.setObjectName("controls_bar")
        bar.setStyleSheet(
            "#controls_bar { border-bottom: 1px solid palette(mid); }"
        )
        hl = QtWidgets.QHBoxLayout(bar)
        hl.setContentsMargins(6, 2, 6, 2)
        hl.setSpacing(4)

        app_pt = QtWidgets.QApplication.font().pointSize()
        caption_font = QtGui.QFont(bar.font())
        caption_font.setPointSize(max(8, (app_pt if app_pt > 0 else 13) - 2))

        def _lbl(text: str) -> QtWidgets.QLabel:
            w = QtWidgets.QLabel(text)
            w.setFont(caption_font)
            return w

        def _db_slider_group(
            label: str,
            min_db: int,
            max_db: int,
            current_val: int,   # canvas 0-100 scale
            default_val: int,   # canvas 0-100 scale
            tip: str,
        ) -> tuple[QtWidgets.QSlider, QtWidgets.QLabel, QtWidgets.QToolButton]:
            """Add label + slider + dB readout + reset button to hl; return (slider, readout, reset)."""
            hl.addWidget(_lbl(label))
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
            slider.setRange(min_db, max_db)
            slider.setValue(current_val - 100)   # convert to dB
            slider.setFixedWidth(80)
            slider.setToolTip(tip)
            hl.addWidget(slider)

            readout = QtWidgets.QLabel(f"{current_val - 100} dB")
            readout.setFont(caption_font)
            readout.setMinimumWidth(40)
            readout.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            hl.addWidget(readout)

            reset_btn = QtWidgets.QToolButton()
            reset_btn.setIcon(qta.icon("mdi.undo"))
            reset_btn.setStyleSheet("border: none")
            reset_btn.setToolTip(f"Reset to default ({default_val - 100} dB)")
            reset_btn.setFixedSize(18, 18)
            hl.addWidget(reset_btn)

            return slider, readout, reset_btn

        # ── Taps ──────────────────────────────────────────────────────────
        hl.addWidget(_lbl("Taps:"))
        self.tap_num_spin = QtWidgets.QSpinBox()
        self.tap_num_spin.setMinimum(1)
        self.tap_num_spin.setMaximum(10)
        self.tap_num_spin.setValue(1)
        self.tap_num_spin.setFixedWidth(45)
        self.tap_num_spin.setToolTip("Number of taps to accumulate and average")
        hl.addWidget(self.tap_num_spin)

        hl.addWidget(_vsep())

        # ── Threshold (tap detection) ──────────────────────────────────────
        tap_thresh_val = AS.AppSettings.tap_threshold()   # 0-100 scale
        self.tap_threshold_slider, self.tap_threshold_readout, _tap_reset = \
            _db_slider_group(
                "Threshold:", -80, -20, tap_thresh_val, 60,
                "Signal level that triggers tap detection\n"
                "(shown as orange dashed line on the spectrum)",
            )
        _tap_reset.clicked.connect(lambda: self.tap_threshold_slider.setValue(-40))

        hl.addWidget(_vsep())

        # ── Peak Min ──────────────────────────────────────────────────────
        peak_min_val = AS.AppSettings.threshold()   # 0-100 scale
        self.threshold_slider, self.peak_min_readout, _peak_reset = \
            _db_slider_group(
                "Peak Min:", -100, -20, peak_min_val, 40,
                "Minimum magnitude a spectral peak must have to be reported\n"
                "(shown as green line on the spectrum)",
            )
        _peak_reset.clicked.connect(lambda: self.threshold_slider.setValue(-60))

        hl.addStretch()

        # ── Plate / Brace (hidden until plate/brace mode) ─────────────────
        self.plate_analysis_btn = QtWidgets.QPushButton("Plate / Brace Analysis…")
        self.plate_analysis_btn.setVisible(False)
        self.plate_analysis_btn.setToolTip("Open the plate/brace material analysis dialog")
        hl.addWidget(self.plate_analysis_btn)

        # ── New Tap ───────────────────────────────────────────────────────
        self.new_tap_btn = QtWidgets.QPushButton("New Tap")
        self.new_tap_btn.setIcon(qta.icon("mdi.gesture-tap"))
        self.new_tap_btn.setToolTip("Clear held results and listen for the next tap")
        self.new_tap_btn.setEnabled(False)
        hl.addWidget(self.new_tap_btn)

        # ── Pause / Resume ────────────────────────────────────────────────
        self.pause_tap_btn = QtWidgets.QPushButton("Pause")
        self.pause_tap_btn.setIcon(qta.icon("fa5.pause-circle"))
        self.pause_tap_btn.setToolTip("Pause tap detection (spectrum keeps updating)")
        self.pause_tap_btn.setEnabled(False)
        hl.addWidget(self.pause_tap_btn)

        # ── Cancel ────────────────────────────────────────────────────────
        self.cancel_tap_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_tap_btn.setIcon(qta.icon("fa5.times-circle"))
        self.cancel_tap_btn.setToolTip("Cancel the current multi-tap sequence")
        self.cancel_tap_btn.setEnabled(False)
        hl.addWidget(self.cancel_tap_btn)

        return bar

    def _build_right_panel(self, f_range: dict[str, int]) -> QtWidgets.QWidget:
        """Analysis Results panel (collapsible, right side of splitter)."""
        small_font = QtGui.QFont()
        small_font.setPointSize(10)
        info_font = QtGui.QFont()
        info_font.setPointSize(9)

        panel = QtWidgets.QWidget()
        panel.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        vbox = QtWidgets.QVBoxLayout(panel)
        vbox.setContentsMargins(6, 4, 6, 4)
        vbox.setSpacing(4)

        # Title
        title = QtWidgets.QLabel("Analysis Results")
        bold_font = QtGui.QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(13)
        title.setFont(bold_font)
        vbox.addWidget(title)

        # Guitar type and measurement type — hidden; shown in Settings dialog
        self.guitar_type_combo = QtWidgets.QComboBox()
        self.guitar_type_combo.addItems(["Classical", "Flamenco", "Acoustic"])
        self.guitar_type_combo.setToolTip(
            "Select the guitar type to set mode classification frequency bands"
        )
        self.measurement_type_combo = QtWidgets.QComboBox()
        self.measurement_type_combo.addItems(["Guitar", "Plate", "Brace"])
        self.measurement_type_combo.setToolTip(
            "Guitar: FFT peak analysis\nPlate / Brace: two-tap material property analysis"
        )

        # Frequency range label + measurement type badge (read-only)
        freq_row = QtWidgets.QHBoxLayout()
        self.freq_range_label = QtWidgets.QLabel(
            f"Showing {f_range['f_min']} – {f_range['f_max']} Hz"
        )
        self.freq_range_label.setFont(small_font)
        freq_row.addWidget(self.freq_range_label, stretch=1)

        self.measurement_type_badge = QtWidgets.QLabel("Guitar")
        self.measurement_type_badge.setFont(small_font)
        self.measurement_type_badge.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.measurement_type_badge.setStyleSheet(
            "background: rgba(0,100,255,0.15); border-radius: 4px;"
            "padding: 1px 6px;"
        )
        freq_row.addWidget(self.measurement_type_badge)
        vbox.addLayout(freq_row)

        vbox.addWidget(_hsep())

        # "Detected Peaks & Modes" header + Select All / Deselect All buttons
        peaks_header = QtWidgets.QHBoxLayout()
        peaks_lbl = QtWidgets.QLabel("Detected Peaks & Modes")
        peaks_lbl.setFont(small_font)
        peaks_header.addWidget(peaks_lbl, stretch=1)

        style = self.style()
        self.select_all_btn = QtWidgets.QToolButton()
        self.select_all_btn.setIcon(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton)
            if style else QtGui.QIcon()
        )
        self.select_all_btn.setIconSize(QtCore.QSize(14, 14))
        self.select_all_btn.setFixedSize(22, 22)
        self.select_all_btn.setToolTip("Select all peaks")
        self.select_all_btn.setEnabled(False)
        peaks_header.addWidget(self.select_all_btn)

        self.deselect_all_btn = QtWidgets.QToolButton()
        self.deselect_all_btn.setIcon(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCancelButton)
            if style else QtGui.QIcon()
        )
        self.deselect_all_btn.setIconSize(QtCore.QSize(14, 14))
        self.deselect_all_btn.setFixedSize(22, 22)
        self.deselect_all_btn.setToolTip("Deselect all peaks")
        self.deselect_all_btn.setEnabled(False)
        peaks_header.addWidget(self.deselect_all_btn)

        vbox.addLayout(peaks_header)

        # Peaks table — the main content (takes all available vertical space)
        self.peak_widget = PT.PeakTable()
        vbox.addWidget(self.peak_widget, stretch=1)

        vbox.addWidget(_hsep())

        # Ring-Out time
        def _result_row(label: str) -> QtWidgets.QLabel:
            row = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setFont(small_font)
            val = QtWidgets.QLabel("—")
            val.setFont(small_font)
            val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            row.addWidget(lbl)
            row.addWidget(val)
            vbox.addLayout(row)
            return val

        ring_out_lbl = QtWidgets.QLabel("Ring-Out Time")
        ring_out_lbl.setFont(small_font)
        vbox.addWidget(ring_out_lbl)
        self.ring_out_value = _result_row("Decay:")

        vbox.addWidget(_hsep())

        # Tap tone ratios
        ratios_title = QtWidgets.QLabel("Tap Tone Ratio")
        ratios_title.setFont(small_font)
        vbox.addWidget(ratios_title)

        self.ratio_top_helm  = _result_row("Top / Helm:")
        self.ratio_back_helm = _result_row("Back / Helm:")
        self.ratio_top_back  = _result_row("Top / Back:")

        vbox.addWidget(_hsep())

        # Export buttons
        self.export_spectrum_btn = QtWidgets.QPushButton("Export Spectrum")
        self.export_spectrum_btn.setEnabled(False)
        self.export_spectrum_btn.setToolTip("Export the current spectrum as a PNG image")
        vbox.addWidget(self.export_spectrum_btn)

        self.export_pdf_btn = QtWidgets.QPushButton("Export PDF Report")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.setToolTip("Export the current measurement to a PDF report")
        vbox.addWidget(self.export_pdf_btn)

        # Averaging widgets: shown in Settings dialog, not in main layout
        self.num_averages = QtWidgets.QSpinBox()
        self.num_averages.setMinimum(0)
        self.num_averages.setMaximum(10)
        self.num_averages.setValue(0)

        self.avg_enable = QtWidgets.QToolButton()
        self.avg_enable.setCheckable(True)
        self.avg_enable.setChecked(False)

        self.avg_restart = QtWidgets.QPushButton()
        _style = self.style()
        if _style is not None:
            pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, "SP_MediaSkipBackward")
            self.avg_restart.setIcon(_style.standardIcon(pixmapi))

        self.avg_completed = QtWidgets.QLabel("0")

        self.avg_done = QtWidgets.QLabel()
        _red_px = gt_i.GtImages.red_pixmap()
        if _red_px is not None:
            self.avg_done.setPixmap(_red_px)

        # Frequency range spinners: shown in Settings dialog
        self.min_spin = QtWidgets.QSpinBox()
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(int(f_range["f_min"]))

        self.max_spin = QtWidgets.QSpinBox()
        self.max_spin.setMinimum(0)
        self.max_spin.setMaximum(22050)
        self.max_spin.setValue(int(f_range["f_max"]))

        return panel

    def _build_decay_strip(self) -> QtWidgets.QWidget:
        """Thin strip below the spectrum showing ring-out decay time."""
        strip = QtWidgets.QWidget()
        strip.setObjectName("decay_strip")
        strip.setStyleSheet("#decay_strip { border-top: 1px solid palette(mid); }")
        hl = QtWidgets.QHBoxLayout(strip)
        hl.setContentsMargins(8, 2, 8, 2)

        small_font = QtGui.QFont()
        small_font.setPointSize(10)

        lbl = QtWidgets.QLabel("Decay:")
        lbl.setFont(small_font)
        hl.addWidget(lbl)

        self.ring_out_value = QtWidgets.QLabel("—")
        self.ring_out_value.setFont(small_font)
        self.ring_out_value.setToolTip("Ring-out: time from tap peak to 15 dB drop")
        hl.addWidget(self.ring_out_value)

        hl.addStretch()
        return strip

    def _build_status_bar(self) -> QtWidgets.QWidget:
        """Bottom status bar: device name | calibration | running status."""
        bar = QtWidgets.QWidget()
        bar.setObjectName("bottom_status_bar")
        bar.setStyleSheet("#bottom_status_bar { border-top: 1px solid palette(mid); }")
        hl = QtWidgets.QHBoxLayout(bar)
        hl.setContentsMargins(8, 3, 8, 3)
        hl.setSpacing(8)

        small_font = QtGui.QFont()
        small_font.setPointSize(10)

        self.device_status_lbl = QtWidgets.QLabel("No device")
        self.device_status_lbl.setFont(small_font)
        hl.addWidget(self.device_status_lbl)

        hl.addWidget(_vsep())

        self.cal_status = QtWidgets.QLabel("Calibration: none")
        self.cal_status.setFont(small_font)
        hl.addWidget(self.cal_status)

        hl.addStretch()

        self.status_label = QtWidgets.QLabel("● Stopped")
        self.status_label.setFont(small_font)
        hl.addWidget(self.status_label)

        return bar

    def _show_metrics(self) -> None:
        """Non-modal dialog showing live FFT diagnostics."""
        if self._metrics_dialog and self._metrics_dialog.isVisible():
            self._metrics_dialog.raise_()
            self._metrics_dialog.activateWindow()
            return

        fft_settings = {"sampling_rate": 48000, "window_length": 4 * 16384}
        sr          = fft_settings["sampling_rate"]
        wl          = fft_settings["window_length"]
        spectral_res = sr / wl
        bandwidth    = sr / 2
        sample_len   = wl / sr
        bin_count    = wl // 2 + 1

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("FFT Metrics")
        dlg.setMinimumWidth(380)
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda: setattr(self, "_metrics_dialog", None))
        self._metrics_dialog = dlg

        sub_font = QtGui.QFont(dlg.font())
        sub_font.setPointSize(max(8, sub_font.pointSize() - 2))
        mono_font = QtGui.QFont(dlg.font())
        mono_font.setFamily("Menlo, Courier, monospace")
        mono_font.setStyleHint(QtGui.QFont.StyleHint.Monospace)

        def _fmt_freq(hz: float) -> str:
            return f"{hz/1000:.2f} kHz" if hz >= 1000 else f"{hz:.1f} Hz"

        def _divider() -> QtWidgets.QFrame:
            f = QtWidgets.QFrame()
            f.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            f.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            return f

        def _metric_row(
            label: str, subtitle: str, value: str = "—", color: str = ""
        ) -> tuple[QtWidgets.QHBoxLayout, QtWidgets.QLabel]:
            """Replicates Swift MetricRow: label+subtitle left, monospaced value right."""
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            lv = QtWidgets.QVBoxLayout()
            lv.setContentsMargins(0, 0, 0, 0)
            lv.setSpacing(1)
            lv.addWidget(QtWidgets.QLabel(label))
            sub = QtWidgets.QLabel(subtitle)
            sub.setFont(sub_font)
            sub.setStyleSheet("color: gray")
            lv.addWidget(sub)
            row.addLayout(lv)
            row.addStretch()
            val = QtWidgets.QLabel(value)
            val.setFont(mono_font)
            val.setStyleSheet(f"font-weight: bold; color: {color}" if color else "font-weight: bold")
            row.addWidget(val)
            return row, val

        def _group(title: str, rows_and_dividers: list) -> QtWidgets.QGroupBox:
            grp = QtWidgets.QGroupBox(title)
            vl = QtWidgets.QVBoxLayout(grp)
            vl.setContentsMargins(8, 8, 8, 8)
            vl.setSpacing(4)
            for item in rows_and_dividers:
                if isinstance(item, QtWidgets.QFrame):
                    vl.addWidget(item)
                else:
                    vl.addLayout(item)
            return grp

        outer = QtWidgets.QVBoxLayout(dlg)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # ── Analysis Configuration ────────────────────────────────────────
        r1, _  = _metric_row("Frequency Resolution", "Hz per bin", _fmt_freq(spectral_res))
        r2, _  = _metric_row("Bin Count", "FFT output bins (guitar mode only)", f"{bin_count:,}")
        r3, _  = _metric_row("Sample Rate", "Hardware capture rate", f"{sr:,.0f} Hz")
        r4, _  = _metric_row("Bandwidth", "0 Hz to Nyquist", _fmt_freq(bandwidth))
        r5, _  = _metric_row("Sample Length", "Time window duration", f"{sample_len:.2f} s")
        r6, self._metrics_framerate_lbl = _metric_row("Frame Rate", "FFT calculations/sec")
        outer.addWidget(_group("Analysis Configuration", [
            r1, _divider(), r2, _divider(), r3, _divider(), r4, _divider(), r5, _divider(), r6,
        ]))

        # ── Performance ───────────────────────────────────────────────────
        r7,  self._metrics_proctime_lbl     = _metric_row("Processing Time",    "Last frame")
        r8,  self._metrics_avg_proctime_lbl = _metric_row("Average Processing", "30-frame average")
        r9,  self._metrics_cpu_lbl          = _metric_row("CPU Usage",          "Of available frame time")
        outer.addWidget(_group("Performance", [
            r7, _divider(), r8, _divider(), r9,
        ]))

        # ── Peak Detection ────────────────────────────────────────────────
        r10, self._metrics_peak_freq_lbl = _metric_row("Peak Frequency", "Dominant frequency")
        r11, self._metrics_peak_mag_lbl  = _metric_row("Peak Magnitude", "Signal strength")
        outer.addWidget(_group("Peak Detection", [
            r10, _divider(), r11,
        ]))

        # ── Status (small, caption style, matches Swift HStack) ───────────
        status_row = QtWidgets.QHBoxLayout()
        self._metrics_status_dot = QtWidgets.QLabel("●")
        self._metrics_status_dot.setFont(sub_font)
        status_row.addWidget(self._metrics_status_dot)
        self._metrics_status_lbl = QtWidgets.QLabel()
        self._metrics_status_lbl.setFont(sub_font)
        self._metrics_status_lbl.setStyleSheet("color: gray")
        status_row.addWidget(self._metrics_status_lbl)
        status_row.addStretch()
        if self._is_running:
            self._metrics_status_dot.setStyleSheet("color: green")
            self._metrics_status_lbl.setText("Analyzing")
        else:
            self._metrics_status_dot.setStyleSheet("color: gray")
            self._metrics_status_lbl.setText("Stopped")
        outer.addLayout(status_row)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        outer.addWidget(close_btn)

        dlg.show()

    # ================================================================
    # Signal connections
    # ================================================================

    def _connect_signals(self) -> None:
        canvas = self.fft_canvas

        # Peak Min slider (dB) ↔ canvas (0-100 scale)
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)

        # Tap detection threshold slider (dB) ↔ canvas (0-100 scale)
        self.tap_threshold_slider.valueChanged.connect(self._on_tap_threshold_changed)

        # Pause / Cancel / tap-detection-paused
        self.pause_tap_btn.clicked.connect(self._on_pause_tap)
        self.cancel_tap_btn.clicked.connect(self._on_cancel_tap)
        canvas.tapDetectionPaused.connect(self._on_tap_detection_paused)

        # Frequency range spinners → canvas + label + persist
        self.min_spin.valueChanged.connect(self._on_fmin_changed)
        self.max_spin.valueChanged.connect(self._on_fmax_changed)

        # Auto dB
        self.auto_db_btn.toggled.connect(canvas.set_auto_scale)
        self.auto_db_btn.toggled.connect(self._on_auto_db_toggled)

        # Annotations cycling button
        self.annotations_btn.clicked.connect(self._on_cycle_annotation_mode)

        # Select / deselect all peaks
        self.select_all_btn.clicked.connect(self._on_select_all_peaks)
        self.deselect_all_btn.clicked.connect(self._on_deselect_all_peaks)

        # Guitar type
        self.guitar_type_combo.currentTextChanged.connect(self._on_guitar_type_changed)

        # Measurement type + plate dialog
        self.measurement_type_combo.currentTextChanged.connect(
            self._on_measurement_type_changed
        )
        self.plate_analysis_btn.clicked.connect(self._on_open_plate_dialog)
        canvas.plateStatusChanged.connect(self._on_plate_status_changed)
        canvas.plateAnalysisComplete.connect(self._on_plate_analysis_complete)

        # Peaks table ← canvas
        canvas.peaksChanged.connect(self.peak_widget.update_data)
        canvas.peaksChanged.connect(self._on_peaks_changed_ratios)
        canvas.peakSelected.connect(self.peak_widget.select_row)
        canvas.peakDeselected.connect(self.peak_widget.clear_selection)
        canvas.averagesChanged.connect(self.set_avg_completed)
        canvas.framerateUpdate.connect(self._on_framerate_update)
        canvas.newSample.connect(self.peak_widget.new_data)
        canvas.annotations.restoreFocus.connect(self.peak_widget.restore_focus)

        # Peaks table → canvas annotations
        model = self.peak_widget.model
        model.annotationUpdate.connect(canvas.annotations.update_annotation)
        model.clearAnnotations.connect(canvas.annotations.clear_annotations)
        model.showAnnotation.connect(canvas.annotations.show_annotation)
        model.hideAnnotation.connect(canvas.annotations.hide_annotation)
        model.hideAnnotations.connect(canvas.annotations.hide_annotations)

        self.peak_widget.peaks_table.clearPeaks.connect(canvas.clear_selected_peak)
        self.peak_widget.peaks_table.clearPeaks.connect(
            self.peak_widget.clear_selected_peak
        )
        self.peak_widget.peaks_table.selectionModel().selectionChanged.connect(
            self.peak_selection_changed
        )

        # Tap events
        canvas.tapDetected.connect(self._on_tap_detected)
        canvas.ringOutMeasured.connect(self.set_ring_out)
        canvas.ringOutMeasured.connect(self._on_ring_out_measured)
        canvas.tapCountChanged.connect(self.set_tap_count)
        canvas.devicesChanged.connect(self._on_devices_changed)
        canvas.currentDeviceLost.connect(self._on_device_lost)
        try:
            self._known_input_device_names: set[str] = {
                str(d["name"]) for d in sd.query_devices() if d["max_input_channels"] > 0
            }
        except Exception:
            self._known_input_device_names = set()

        # Toolbar / controls buttons
        self.new_tap_btn.clicked.connect(self._on_new_tap)
        self.save_measurement_btn.clicked.connect(self._on_save_measurement)
        self.open_measurements_btn.clicked.connect(self._on_open_measurements)
        self.export_spectrum_btn.clicked.connect(self._on_export_spectrum)
        self.export_pdf_btn.clicked.connect(self._on_export_pdf)

        # Tap accumulator
        self.tap_num_spin.valueChanged.connect(canvas.set_tap_num)

    def _init_state(self, f_range: dict[str, int]) -> None:
        """Restore saved values and initialise display state."""
        canvas = self.fft_canvas

        saved_gt = AS.AppSettings.guitar_type()
        self.guitar_type_combo.setCurrentText(saved_gt)
        self.peak_widget.model.set_guitar_type(saved_gt)
        canvas.set_guitar_type_bands(saved_gt)

        self.set_frozen(False)

        # Restore calibration status label and device name in status bar
        device_name = canvas.current_calibration_device() or AS.AppSettings.device_name()
        if device_name:
            self.device_status_lbl.setText(device_name)
            cal_path = AS.AppSettings.calibration_for_device(device_name)
            self.set_calibration_status(cal_path)

        self._start_analyzer()

    # ================================================================
    # State update methods (formerly in PeakControls)
    # ================================================================

    def set_running(self, running: bool) -> None:
        if running:
            self.status_label.setText("● Listening for tap…")
        else:
            self.status_label.setText("● Stopped")
            self._is_paused = False
        self._update_tap_buttons()

    def set_tap_count(self, captured: int, total: int) -> None:
        self._tap_count_captured = captured
        if total > 1:
            self.status_label.setText(f"● Tap {captured} / {total}")
        self._update_tap_buttons()

    def set_ring_out(self, time_s: float) -> None:
        self.ring_out_value.setText(f"{time_s:.2f} s")

    def set_calibration_status(self, path: str) -> None:
        if path:
            self.cal_status.setText(f"Cal: {os.path.basename(path)}")
        else:
            self.cal_status.setText("Calibration: none")

    def _on_auto_db_toggled(self, enabled: bool) -> None:
        if enabled:
            self.auto_db_btn.setIcon(qta.icon("mdi.swap-vertical-circle", color="#27ae60"))
        else:
            self.auto_db_btn.setIcon(qta.icon("mdi.swap-vertical-circle-outline"))

    def _on_framerate_update(
        self, framerate: float, _sampletime: float, processingtime: float
    ) -> None:
        # Maintain rolling 30-frame average of processing time
        self._proc_times.append(processingtime)
        if len(self._proc_times) > 30:
            self._proc_times.pop(0)

        if not (self._metrics_dialog and self._metrics_dialog.isVisible()):
            return

        proc_ms = processingtime * 1000
        avg_ms  = (sum(self._proc_times) / len(self._proc_times)) * 1000
        cpu_pct = (avg_ms / (1000 / framerate)) * 100 if framerate > 0 else 0

        self._metrics_framerate_lbl.setText(f"{framerate:.1f} Hz")
        self._metrics_proctime_lbl.setText(f"{proc_ms:.3f} ms")
        self._metrics_avg_proctime_lbl.setText(f"{avg_ms:.3f} ms")

        if cpu_pct < 50:
            cpu_color = "green"
        elif cpu_pct < 80:
            cpu_color = "orange"
        elif cpu_pct < 95:
            cpu_color = "darkorange"
        else:
            cpu_color = "red"
        self._metrics_cpu_lbl.setText(f"{cpu_pct:.1f}%")
        self._metrics_cpu_lbl.setStyleSheet(f"color: {cpu_color}")

        # Color-code processing time using same thresholds as CPU
        frame_ms = (1000 / framerate) if framerate > 0 else 100
        proc_pct = (proc_ms / frame_ms) * 100
        if proc_pct < 50:
            proc_color = "green"
        elif proc_pct < 80:
            proc_color = "orange"
        elif proc_pct < 95:
            proc_color = "darkorange"
        else:
            proc_color = "red"
        self._metrics_proctime_lbl.setStyleSheet(f"color: {proc_color}")
        self._metrics_avg_proctime_lbl.setStyleSheet(f"color: {cpu_color}")

        # Peak detection — dominant peak by magnitude
        peaks = self.fft_canvas.saved_peaks
        if peaks.ndim == 2 and peaks.shape[0] > 0:
            best = int(np.argmax(peaks[:, 1]))
            self._metrics_peak_freq_lbl.setText(f"{peaks[best, 0]:.1f} Hz")
            self._metrics_peak_mag_lbl.setText(f"{peaks[best, 1]:.1f} dB")
        else:
            self._metrics_peak_freq_lbl.setText("—")
            self._metrics_peak_mag_lbl.setText("—")

        # Status
        if self._is_running:
            self._metrics_status_dot.setStyleSheet("color: green")
            self._metrics_status_lbl.setText("Analyzing")
        else:
            self._metrics_status_dot.setStyleSheet("color: gray")
            self._metrics_status_lbl.setText("Stopped")

    def update_tap_tone_ratios(self, mode_freqs: dict[str, float]) -> None:
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

    def set_avg_enable(self, state: bool) -> None:
        self.fft_canvas.set_avg_enable(state)
        if state:
            self.avg_enable.setIcon(gt_i.GtImages.green_button_icon() or QtGui.QIcon())
            self.avg_restart.setEnabled(True)
        else:
            self.avg_enable.setIcon(gt_i.GtImages.red_button_icon() or QtGui.QIcon())
            self.avg_restart.setEnabled(False)

    def set_frozen(self, checked: bool) -> None:
        self._is_frozen = checked
        self.fft_canvas.set_frozen(checked)
        self.peak_widget.data_held(checked)
        if checked:
            # Re-apply the current annotation mode (data_held always defaults to Selected)
            current_mode = self._ANN_MODES[self._ann_mode_idx][0]
            if current_mode != "Selected":
                self._apply_annotation_mode(current_mode)
            # Disable auto-scale when spectrum is frozen (matches Swift behaviour)
            if self.auto_db_btn.isChecked():
                self.auto_db_btn.setChecked(False)

        if checked:
            self.avg_enable_saved = self.avg_enable.isChecked()
            self.set_avg_enable(False)
            self.avg_enable.setEnabled(False)
            self.avg_restart.setEnabled(False)
            self.save_measurement_btn.setEnabled(True)
            self.export_spectrum_btn.setEnabled(True)
            self.export_pdf_btn.setEnabled(True)
            self.select_all_btn.setEnabled(True)
            self.deselect_all_btn.setEnabled(True)
        else:
            self.avg_enable.setEnabled(True)
            self.save_measurement_btn.setEnabled(False)
            self.export_spectrum_btn.setEnabled(False)
            self.export_pdf_btn.setEnabled(False)
            self.select_all_btn.setEnabled(False)
            self.deselect_all_btn.setEnabled(False)
        self._update_tap_buttons()

    def reset_averaging(self) -> None:
        self.fft_canvas.reset_averaging()
        self.set_avg_completed(0)
        _px = gt_i.GtImages.red_pixmap()
        if _px is not None:
            self.avg_done.setPixmap(_px)
        if self._is_frozen:
            self.set_frozen(False)

    def set_avg_completed(self, count: int) -> None:
        self.avg_completed.setText(str(count))
        if count >= self.num_averages.value():
            _px = gt_i.GtImages.green_pixmap()
            if _px is not None:
                self.avg_done.setPixmap(_px)
            self.num_averages.setEnabled(True)
            self.set_frozen(True)
            self.avg_restart.setEnabled(True)
        else:
            self.num_averages.setEnabled(False)
            self.avg_restart.setEnabled(False)
            self.avg_enable.setEnabled(False)

    # ================================================================
    # Frequency range
    # ================================================================

    def _on_fmin_changed(self, value: int) -> None:
        self.fft_canvas.set_fmin(value)
        AS.AppSettings.set_f_min(value)
        self._update_freq_range_label()

    def _on_fmax_changed(self, value: int) -> None:
        self.fft_canvas.set_fmax(value)
        AS.AppSettings.set_f_max(value)
        self._update_freq_range_label()

    def _update_freq_range_label(self) -> None:
        self.freq_range_label.setText(
            f"Showing {self.min_spin.value()} – {self.max_spin.value()} Hz"
        )

    # ================================================================
    # Annotation visibility cycling
    # ================================================================

    # (mode, icon_name) — order defines the cycle; matches Swift: selected→all→none
    _ANN_MODES: tuple[tuple[str, str], ...] = (
        ("Selected", "fa5.star"),       # star.fill
        ("None",     "fa5.eye-slash"),  # eye.slash
        ("All",      "fa5.eye"),        # eye
    )

    def _on_cycle_annotation_mode(self) -> None:
        self._ann_mode_idx = (self._ann_mode_idx + 1) % len(self._ANN_MODES)
        next_mode, next_icon = self._ANN_MODES[self._ann_mode_idx]
        self.annotations_btn.setIcon(qta.icon(next_icon))
        self.annotations_btn.setToolTip(
            f"Annotation visibility: {next_mode}\n"
            "Click to cycle: Selected → None → All"
        )
        self._apply_annotation_mode(next_mode)

    def _apply_annotation_mode(self, mode: str) -> None:
        model = self.peak_widget.model
        canvas = self.fft_canvas
        if mode == "All":
            model.show_all_annotations()
        elif mode == "Selected":
            canvas.annotations.hide_annotations()
            model.show_annotations()
        else:  # "None"
            canvas.annotations.hide_annotations()

    # ================================================================
    # Threshold / hysteresis
    # ================================================================

    def _on_threshold_changed(self, db_val: int) -> None:
        self.fft_canvas.set_threshold(db_val + 100)
        AS.AppSettings.set_threshold(db_val + 100)
        self.peak_min_readout.setText(f"{db_val} dB")

    def _on_tap_threshold_changed(self, db_val: int) -> None:
        self.fft_canvas.set_tap_threshold(db_val + 100)
        AS.AppSettings.set_tap_threshold(db_val + 100)
        self.tap_threshold_readout.setText(f"{db_val} dB")

    # ================================================================
    # Tap button state
    # ================================================================

    def _update_tap_buttons(self) -> None:
        """Refresh enabled/disabled state of New Tap, Pause, and Cancel buttons."""
        tap_num = self.tap_num_spin.value()
        is_plate = self.measurement_type_combo.currentText() in ("Plate", "Brace")
        is_detecting = self._is_running and not self._is_frozen

        # New Tap is only meaningful when the spectrum is frozen (results held).
        # On startup the app auto-listens, so New Tap is disabled until a tap is captured.
        self.new_tap_btn.setEnabled(self._is_running and self._is_frozen)

        self.pause_tap_btn.setEnabled(is_detecting and (tap_num > 1 or is_plate))
        self.cancel_tap_btn.setEnabled(
            is_detecting and tap_num > 1
            and 0 < self._tap_count_captured < tap_num
        )

    # ================================================================
    # Pause / Cancel tap detection
    # ================================================================

    def _on_pause_tap(self) -> None:
        if self._is_paused:
            self.fft_canvas.resume_tap_detection()
        else:
            self.fft_canvas.pause_tap_detection()

    def _on_cancel_tap(self) -> None:
        self._is_paused = False
        self.fft_canvas.cancel_tap_sequence()
        self._tap_count_captured = 0
        self._update_tap_buttons()

    def _on_tap_detection_paused(self, paused: bool) -> None:
        self._is_paused = paused
        if paused:
            self.pause_tap_btn.setText("Resume")
            self.pause_tap_btn.setIcon(qta.icon("fa5.play-circle"))
        else:
            self.pause_tap_btn.setText("Pause")
            self.pause_tap_btn.setIcon(qta.icon("fa5.pause-circle"))
        self._update_tap_buttons()

    # ================================================================
    # Start / Stop
    # ================================================================

    def _start_analyzer(self) -> None:
        self._is_running = True
        self.set_running(True)
        self.fft_canvas.start_analyzer()

    def _stop_analyzer(self) -> None:
        self._is_running = False
        self.set_running(False)
        self.fft_canvas.stop_analyzer()

    # ================================================================
    # Tap events
    # ================================================================

    def _on_tap_detected(self) -> None:
        """Auto-hold results when a tap fires (guitar mode only)."""
        if self.measurement_type_combo.currentText() != "Guitar":
            return
        if not self._is_frozen:
            self.set_frozen(True)

    def _on_new_tap(self) -> None:
        """Begin a new tap sequence, clearing any in-progress accumulated spectra."""
        if self._is_frozen:
            self.set_frozen(False)
        self._is_paused = False
        # start_tap_sequence clears accumulated spectra and restarts the warmup,
        # preventing leftover spectra from a previous partial sequence polluting the next one.
        self.fft_canvas.start_tap_sequence()
        n = self.tap_num_spin.value()
        if n == 1:
            self.status_label.setText("● Listening for tap…")

    def _on_ring_out_measured(self, time_s: float) -> None:
        self._ring_out_s = time_s

    # ================================================================
    # Peak select / deselect all
    # ================================================================

    def _on_select_all_peaks(self) -> None:
        self.peak_widget.model.select_all_peaks()

    def _on_deselect_all_peaks(self) -> None:
        self.peak_widget.model.deselect_all_peaks()

    # ================================================================
    # Guitar type
    # ================================================================

    def _on_guitar_type_changed(self, guitar_type: str) -> None:
        AS.AppSettings.set_guitar_type(guitar_type)
        self.peak_widget.model.set_guitar_type(guitar_type)
        self.fft_canvas.set_guitar_type_bands(guitar_type)

    # ================================================================
    # Peaks / ratios
    # ================================================================

    def _on_peaks_changed_ratios(self, peaks: object) -> None:
        import numpy as np
        if not isinstance(peaks, np.ndarray) or peaks.ndim != 2 or peaks.shape[0] == 0:
            return
        guitar_type_str = self.guitar_type_combo.currentText()
        try:
            guitar_type = GM.GuitarType(guitar_type_str)
        except ValueError:
            return
        mode_freqs: dict[str, float] = {}
        for row in range(peaks.shape[0]):
            freq = float(peaks[row, 0])
            mode = GM.classify_peak(freq, guitar_type)
            if mode and mode not in mode_freqs:
                mode_freqs[mode] = freq
        self.update_tap_tone_ratios(mode_freqs)

    def peak_selection_changed(
        self, selected: QtCore.QItemSelection, deselected: QtCore.QItemSelection
    ) -> None:
        if len(deselected.indexes()) > 0:
            self._row_deselect(deselected.indexes()[0])
        if len(selected.indexes()) > 0:
            self._row_select(selected.indexes()[0])

    def _row_deselect(self, proxy_idx: QtCore.QModelIndex) -> None:
        proxy_model = self.peak_widget.peaks_table.model()
        src_idx = proxy_model.mapToSource(proxy_idx)
        freq = proxy_model.sourceModel().freq_value(src_idx)
        self.fft_canvas.deselect_peak(freq)

    def _row_select(self, proxy_idx: QtCore.QModelIndex) -> None:
        proxy_model = self.peak_widget.peaks_table.model()
        src_idx = proxy_model.mapToSource(proxy_idx)
        freq = proxy_model.sourceModel().freq_value(src_idx)
        self.fft_canvas.select_peak(freq)
        self.peak_widget.selected_freq = freq
        self.peak_widget.selected_freq_index = src_idx.row()

    # ================================================================
    # Measurement type / plate analysis
    # ================================================================

    def _on_measurement_type_changed(self, measurement_type: str) -> None:
        self.fft_canvas.set_measurement_type(measurement_type)
        self.plate_analysis_btn.setVisible(
            measurement_type in ("Plate", "Brace")
        )
        # Update read-only badge in results panel
        is_guitar = measurement_type not in ("Plate", "Brace")
        self.measurement_type_badge.setText(measurement_type)
        self.measurement_type_badge.setStyleSheet(
            "background: rgba(0,100,255,0.15); border-radius: 4px; padding: 1px 6px;"
            if is_guitar else
            "background: rgba(255,140,0,0.20); border-radius: 4px; padding: 1px 6px;"
        )

    def _on_open_plate_dialog(self) -> None:
        if self._plate_dialog is None or not self._plate_dialog.isVisible():
            self._plate_dialog = PD.PlateDialog(self)
            self._plate_dialog.startAnalysis.connect(
                self.fft_canvas.start_plate_analysis
            )
            self._plate_dialog.resetAnalysis.connect(
                self.fft_canvas.reset_plate_analysis
            )
        self._plate_dialog.show()
        self._plate_dialog.raise_()
        self._plate_dialog.activateWindow()

    def _on_plate_status_changed(self, status: str) -> None:
        if self._plate_dialog and self._plate_dialog.isVisible():
            self._plate_dialog.set_status(status)

    def _on_plate_analysis_complete(self, f_long: float, f_cross: float) -> None:
        if self._plate_dialog is None:
            return
        dims = self._plate_dialog.dimensions()
        if dims is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Dimensions",
                "Plate dimensions are required to calculate material properties.",
            )
            return
        try:
            props = PA.calculate_properties(dims, f_long, f_cross)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Calculation Error", str(exc))
            return
        self._plate_dialog.show_results(f_long, f_cross, props)

    # ================================================================
    # Measurements save / load / export
    # ================================================================

    def _collect_measurement(self) -> M.PeakMeasurement:
        canvas = self.fft_canvas
        model  = self.peak_widget.model

        peaks: list[M.PeakEntry] = []
        for row in range(model.rowCount(QtCore.QModelIndex())):
            idx  = model.index(row, 0)
            freq = model.freq_value(idx)
            mag  = model.magnitude_value(idx)
            q    = model.q_value(idx)
            show = model.show_value(idx)
            mode = model.mode_value(idx)
            peaks.append(M.PeakEntry(freq=freq, mag=mag, q=q, show=show, mode=mode))

        annotations: list[M.AnnotationEntry] = []
        for ann_dict in canvas.annotations.annotations:
            annotations.append(
                M.AnnotationEntry(
                    freq=ann_dict["freq"],
                    mag=ann_dict["mag"],
                    text=ann_dict["text"],
                    xytext=list(ann_dict["xytext"]),
                )
            )

        return M.PeakMeasurement.create(
            guitar_type=self.guitar_type_combo.currentText(),
            f_min=self.min_spin.value(),
            f_max=self.max_spin.value(),
            threshold=self.threshold_slider.value() + 100,  # dB → 0-100 scale
            ring_out=self._ring_out_s,
            notes="",
            peaks=peaks,
            annotations=annotations,
        )

    def _on_save_measurement(self) -> None:
        m = self._collect_measurement()
        try:
            path = M.save_measurement(m)
            QtWidgets.QMessageBox.information(
                self, "Measurement Saved", f"Saved to:\n{path}"
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Save Error", f"Could not save measurement:\n{exc}"
            )

    def _on_open_measurements(self) -> None:
        dlg = MD.MeasurementsDialog(self)
        dlg.measurementSelected.connect(self._restore_measurement)
        dlg.exec()

    def _restore_measurement(self, m: M.PeakMeasurement) -> None:
        import numpy as np

        canvas = self.fft_canvas

        if self._is_frozen:
            self.set_frozen(False)

        self.guitar_type_combo.setCurrentText(m.guitar_type)
        self.min_spin.setValue(m.f_min)
        self.max_spin.setValue(m.f_max)
        self.threshold_slider.setValue(m.threshold - 100)  # 0-100 scale → dB
        self._ring_out_s = m.ring_out
        if m.ring_out is not None:
            self.set_ring_out(m.ring_out)

        if m.peaks:
            peaks_array = np.array(
                [[p.freq, p.mag, p.q] for p in m.peaks], dtype=np.float64
            )
        else:
            peaks_array = np.zeros((0, 3), dtype=np.float64)

        canvas.saved_peaks = peaks_array
        canvas.b_peaks_freq = peaks_array[:, 0] if len(peaks_array) > 0 else []
        canvas.peaks_f_min_index = 0
        canvas.peaks_f_max_index = len(peaks_array)
        canvas.peaksChanged.emit(peaks_array)

        model = self.peak_widget.model
        model.modes = {
            p.freq: p.mode for p in m.peaks if p.mode and p.mode != ""
        }
        model.show = {p.freq: p.show for p in m.peaks if p.show == "on"}

        canvas.annotations.clear_annotations()
        for ann in m.annotations:
            canvas.annotations.annotations.append(
                {
                    "freq": ann.freq,
                    "annotation": None,
                    "arrow_line": None,
                    "annotation_range": None,
                    "mag": ann.mag,
                    "text": ann.text,
                    "xytext": tuple(ann.xytext),
                }
            )

        self.set_frozen(True)

    def _on_export_spectrum(self) -> None:
        from pyqtgraph.exporters import ImageExporter
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Spectrum",
            os.path.expanduser("~/Documents/GuitarTap"),
            "PNG images (*.png)",
        )
        if not path:
            return
        if not path.endswith(".png"):
            path += ".png"
        try:
            exporter = ImageExporter(self.fft_canvas.getPlotItem())
            exporter.export(path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Failed", str(exc))

    def _on_export_pdf(self) -> None:
        import tempfile
        from pyqtgraph.exporters import ImageExporter

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            os.path.expanduser("~/Documents/GuitarTap"),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        if not path.endswith(".pdf"):
            path += ".pdf"

        png_path: str | None = None
        try:
            exporter = ImageExporter(self.fft_canvas.getPlotItem())
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            png_path = tmp.name
            exporter.export(png_path)
        except Exception:
            png_path = None

        m = self._collect_measurement()
        try:
            M.export_pdf(m, png_path, path)
            QtWidgets.QMessageBox.information(
                self, "PDF Exported", f"Report saved to:\n{path}"
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export Error", f"Could not export PDF:\n{exc}"
            )
        finally:
            if png_path and os.path.exists(png_path):
                try:
                    os.remove(png_path)
                except OSError:
                    pass

    # ================================================================
    # Device management
    # ================================================================

    def _on_devices_changed(self, device_names: list[str]) -> None:
        """A device was added or removed. Auto-select any newly arrived device."""
        new_names = set(device_names)
        added = new_names - self._known_input_device_names
        self._known_input_device_names = new_names

        if not added:
            return

        # Find the index of the first newly arrived device and select it
        new_name = next(iter(added))
        try:
            for d in sd.query_devices():
                if str(d["name"]) == new_name and d["max_input_channels"] > 0:
                    self.fft_canvas.set_device(int(d["index"]))
                    AS.AppSettings.set_device_name(new_name)
                    self.device_status_lbl.setText(new_name)
                    self.set_calibration_status(
                        AS.AppSettings.calibration_for_device(new_name)
                    )
                    break
        except Exception:
            pass

    def _on_device_lost(self, device_name: str) -> None:
        """Active device disconnected — fall back to system default input."""
        try:
            default_idx = int(sd.default.device[0])
            default_info = sd.query_devices(default_idx)
            if default_info["max_input_channels"] > 0:
                fallback_idx = default_idx
                fallback_name = str(default_info["name"])
            else:
                raise ValueError("default device has no input channels")
        except Exception:
            # No system default — take first available input
            try:
                available = [
                    (int(d["index"]), str(d["name"]))
                    for d in sd.query_devices()
                    if d["max_input_channels"] > 0
                ]
            except Exception:
                available = []
            if not available:
                self.device_status_lbl.setText("⚠ No audio input device available")
                return
            fallback_idx, fallback_name = available[0]

        self.fft_canvas.set_device(fallback_idx)
        AS.AppSettings.set_device_name(fallback_name)
        self.device_status_lbl.setText(fallback_name)
        self.set_calibration_status(AS.AppSettings.calibration_for_device(fallback_name))

    def import_calibration(self) -> None:
        start_dir = AS.AppSettings.calibration_path() or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import Microphone Calibration",
            start_dir,
            "Calibration files (*.cal *.txt);;All files (*)",
        )
        if not path:
            return
        canvas = self.fft_canvas
        if canvas.load_calibration(path):
            AS.AppSettings.set_calibration_path(os.path.dirname(path))
            device_name = canvas.current_calibration_device()
            if device_name:
                AS.AppSettings.set_calibration_for_device(device_name, path)
            self.set_calibration_status(path)
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Calibration Error",
                f"Could not parse calibration file:\n{path}",
            )

    def show_device_dialog(self) -> None:
        current_index = self.fft_canvas.mic.device_index or -1
        dlg = SD.ShowInputDevices(current_device_index=current_index)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            chosen = dlg.selected_device_index()
            if chosen >= 0 and chosen != current_index:
                self.fft_canvas.set_device(chosen)
                dev_info = sd.query_devices(chosen)
                dev_name = str(dev_info["name"])  # type: ignore[index]
                AS.AppSettings.set_device_name(dev_name)
                self.device_status_lbl.setText(dev_name)
                cal_path = AS.AppSettings.calibration_for_device(dev_name)
                self.set_calibration_status(cal_path)

    # ================================================================
    # Settings dialog
    # ================================================================

    def _show_settings(self) -> None:  # noqa: C901
        """Modal settings dialog matching the Swift TapSettingsView structure."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setMinimumWidth(460)

        # Outer layout wraps a scroll area so the dialog stays manageable on small screens
        outer = QtWidgets.QVBoxLayout(dlg)
        outer.setContentsMargins(8, 8, 8, 8)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(content)
        vbox.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(dlg.accept)
        outer.addWidget(close_btn)

        # Shared font helpers
        small = QtGui.QFont(dlg.font())
        small.setPointSize(max(8, dlg.font().pointSize() - 1))
        hdr_font = QtGui.QFont(small)
        hdr_font.setBold(True)

        def _group_header(icon_name: str, text: str) -> QtWidgets.QWidget:
            """Bold icon + text header row matching Swift section Label style."""
            w = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(w)
            row.setContentsMargins(0, 2, 0, 4)
            row.setSpacing(6)
            icon_lbl = QtWidgets.QLabel()
            icon_lbl.setPixmap(qta.icon(icon_name).pixmap(16, 16))
            row.addWidget(icon_lbl)
            title_lbl = QtWidgets.QLabel(text)
            title_lbl.setFont(hdr_font)
            row.addWidget(title_lbl)
            row.addStretch()
            return w

        # =====================================================
        # 1. Measurement Type Section
        # =====================================================
        meas_group = QtWidgets.QGroupBox("")
        mg = QtWidgets.QVBoxLayout(meas_group)
        mg.addWidget(_group_header("mdi.music", "Measurement Type"))

        MEAS_TYPES = [
            "Classical Guitar",
            "Flamenco Guitar",
            "Acoustic Guitar",
            "Material (Plate)",
            "Material (Brace)",
        ]
        MEAS_DESCRIPTIONS = {
            "Classical Guitar": "Nylon string, fan-braced, deep body",
            "Flamenco Guitar": "Nylon string, light bracing, shallow body",
            "Acoustic Guitar": "Steel string, X-braced (Dreadnought, OM, etc.)",
            "Material (Plate)": "Rectangular wood plate for calculating stiffness and sound radiation",
            "Material (Brace)": "Brace strip — measures longitudinal stiffness (fL only)",
        }
        # Maps unified name → (measurement_type_combo value, guitar_type_combo value | None)
        MEAS_TO_COMBO: dict[str, tuple[str, str | None]] = {
            "Classical Guitar": ("Guitar", "Classical"),
            "Flamenco Guitar": ("Guitar", "Flamenco"),
            "Acoustic Guitar": ("Guitar", "Acoustic"),
            "Material (Plate)": ("Plate", None),
            "Material (Brace)": ("Brace", None),
        }
        GUITAR_TYPE_MAP = {
            "Classical Guitar": "Classical",
            "Flamenco Guitar": "Flamenco",
            "Acoustic Guitar": "Acoustic",
        }

        # Derive the current unified type from the existing hidden combos
        cur_meas = self.measurement_type_combo.currentText()
        cur_guitar = self.guitar_type_combo.currentText()
        cur_unified = f"{cur_guitar} Guitar" if cur_meas == "Guitar" else f"Material ({cur_meas})"

        meas_type_row = QtWidgets.QHBoxLayout()
        meas_type_row.addWidget(QtWidgets.QLabel("Measurement Type:"))
        meas_type_combo = QtWidgets.QComboBox()
        meas_type_combo.addItems(MEAS_TYPES)
        meas_type_combo.setCurrentText(cur_unified)
        meas_type_combo.setEditable(True)
        le = meas_type_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        meas_type_row.addWidget(meas_type_combo, stretch=1)
        mg.addLayout(meas_type_row)

        meas_desc_lbl = QtWidgets.QLabel(MEAS_DESCRIPTIONS.get(cur_unified, ""))
        meas_desc_lbl.setFont(small)
        meas_desc_lbl.setWordWrap(True)
        mg.addWidget(meas_desc_lbl)

        # ---- Guitar-specific content ----
        guitar_widget = QtWidgets.QWidget()
        guitar_layout = QtWidgets.QVBoxLayout(guitar_widget)
        guitar_layout.setContentsMargins(0, 4, 0, 0)
        guitar_layout.setSpacing(4)

        mode_header = QtWidgets.QLabel("Mode Frequency Ranges")
        mode_header.setFont(hdr_font)
        guitar_layout.addWidget(mode_header)

        mode_ranges_lbl = QtWidgets.QLabel()
        mode_ranges_lbl.setFont(small)
        mode_ranges_lbl.setWordWrap(True)
        guitar_layout.addWidget(mode_ranges_lbl)

        mg.addWidget(guitar_widget)

        # ---- Plate-specific content ----
        plate_widget = QtWidgets.QWidget()
        plate_layout = QtWidgets.QVBoxLayout(plate_widget)
        plate_layout.setContentsMargins(0, 4, 0, 0)
        plate_layout.setSpacing(4)
        plate_layout.addWidget(_hsep())

        plate_dims_hdr = QtWidgets.QLabel("Sample Dimensions")
        plate_dims_hdr.setFont(hdr_font)
        plate_layout.addWidget(plate_dims_hdr)

        def _dim_spinbox(suffix: str, max_val: float = 2000.0) -> QtWidgets.QDoubleSpinBox:
            sb = QtWidgets.QDoubleSpinBox()
            sb.setDecimals(1)
            sb.setMinimum(0.1)
            sb.setMaximum(max_val)
            sb.setSuffix(f" {suffix}")
            return sb

        plate_form = QtWidgets.QFormLayout()
        plate_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        plate_length_spin = _dim_spinbox("mm", 2000.0)
        plate_length_spin.setValue(AS.AppSettings.plate_length())
        plate_form.addRow("Length (along grain):", plate_length_spin)

        plate_width_spin = _dim_spinbox("mm", 1000.0)
        plate_width_spin.setValue(AS.AppSettings.plate_width())
        plate_form.addRow("Width (cross grain):", plate_width_spin)

        plate_thick_spin = _dim_spinbox("mm", 50.0)
        plate_thick_spin.setValue(AS.AppSettings.plate_thickness())
        plate_form.addRow("Thickness:", plate_thick_spin)

        plate_mass_spin = _dim_spinbox("g", 5000.0)
        plate_mass_spin.setValue(AS.AppSettings.plate_mass())
        plate_form.addRow("Mass:", plate_mass_spin)

        plate_density_lbl = QtWidgets.QLabel("—")
        plate_density_lbl.setFont(small)
        plate_form.addRow("Calculated Density:", plate_density_lbl)

        plate_layout.addLayout(plate_form)

        def _update_plate_density() -> None:
            L = plate_length_spin.value()
            W = plate_width_spin.value()
            T = plate_thick_spin.value()
            m = plate_mass_spin.value()
            if L > 0 and W > 0 and T > 0 and m > 0:
                density = m / ((L / 10) * (W / 10) * (T / 10))
                plate_density_lbl.setText(f"{density:.3f} g/cm³")
            else:
                plate_density_lbl.setText("—")

        plate_length_spin.valueChanged.connect(lambda _: _update_plate_density())
        plate_width_spin.valueChanged.connect(lambda _: _update_plate_density())
        plate_thick_spin.valueChanged.connect(lambda _: _update_plate_density())
        plate_mass_spin.valueChanged.connect(lambda _: _update_plate_density())
        _update_plate_density()

        plate_layout.addWidget(_hsep())

        measure_flc_cb = QtWidgets.QCheckBox("Measure FLC (Diagonal Tap)")
        measure_flc_cb.setChecked(AS.AppSettings.measure_flc())
        flc_desc = QtWidgets.QLabel(
            "Add a 3rd tap: hold plate at midpoint of one long edge, tap near opposite corner. "
            "Measures shear stiffness for Gore target thickness."
        )
        flc_desc.setFont(small)
        flc_desc.setWordWrap(True)
        plate_layout.addWidget(measure_flc_cb)
        plate_layout.addWidget(flc_desc)
        plate_layout.addWidget(_hsep())

        gore_hdr = QtWidgets.QLabel("Gore Target Thickness — Body Dimensions")
        gore_hdr.setFont(hdr_font)
        plate_layout.addWidget(gore_hdr)
        gore_desc = QtWidgets.QLabel(
            "Finished guitar body dimensions used in Gore's Eq. 4.5-7 to calculate target plate thickness."
        )
        gore_desc.setFont(small)
        gore_desc.setWordWrap(True)
        plate_layout.addWidget(gore_desc)

        gore_form = QtWidgets.QFormLayout()
        gore_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        gore_body_len_spin = _dim_spinbox("mm", 1000.0)
        gore_body_len_spin.setValue(AS.AppSettings.guitar_body_length())
        gore_form.addRow("Body Length (a):", gore_body_len_spin)
        gore_body_wid_spin = _dim_spinbox("mm", 1000.0)
        gore_body_wid_spin.setValue(AS.AppSettings.guitar_body_width())
        gore_form.addRow("Lower Bout Width (b):", gore_body_wid_spin)
        plate_layout.addLayout(gore_form)
        plate_layout.addWidget(_hsep())

        fvs_hdr = QtWidgets.QLabel("Plate Vibrational Stiffness (f_vs)")
        fvs_hdr.setFont(hdr_font)
        plate_layout.addWidget(fvs_hdr)

        PRESET_DISPLAY_NAMES = [
            "Steel String Top (75)",
            "Steel String Back (55)",
            "Classical Top (60)",
            "Classical Back (50)",
            "Custom",
        ]
        PRESET_STORAGE_NAMES = [
            "Steel String Top",
            "Steel String Back",
            "Classical Top",
            "Classical Back",
            "Custom",
        ]
        fvs_combo = QtWidgets.QComboBox()
        fvs_combo.addItems(PRESET_DISPLAY_NAMES)
        saved_preset = AS.AppSettings.plate_stiffness_preset()
        if saved_preset in PRESET_STORAGE_NAMES:
            fvs_combo.setCurrentIndex(PRESET_STORAGE_NAMES.index(saved_preset))
        plate_layout.addWidget(fvs_combo)

        custom_fvs_widget = QtWidgets.QWidget()
        custom_fvs_row = QtWidgets.QHBoxLayout(custom_fvs_widget)
        custom_fvs_row.setContentsMargins(0, 0, 0, 0)
        custom_fvs_row.addWidget(QtWidgets.QLabel("Custom f_vs value:"))
        custom_fvs_spin = QtWidgets.QDoubleSpinBox()
        custom_fvs_spin.setDecimals(1)
        custom_fvs_spin.setMinimum(1.0)
        custom_fvs_spin.setMaximum(500.0)
        custom_fvs_spin.setValue(AS.AppSettings.custom_plate_stiffness())
        custom_fvs_row.addWidget(custom_fvs_spin)
        custom_fvs_widget.setVisible(fvs_combo.currentText() == "Custom")
        fvs_combo.currentTextChanged.connect(
            lambda t: custom_fvs_widget.setVisible(t == "Custom")
        )
        plate_layout.addWidget(custom_fvs_widget)
        mg.addWidget(plate_widget)

        # ---- Brace-specific content ----
        brace_widget = QtWidgets.QWidget()
        brace_layout = QtWidgets.QVBoxLayout(brace_widget)
        brace_layout.setContentsMargins(0, 4, 0, 0)
        brace_layout.setSpacing(4)
        brace_layout.addWidget(_hsep())

        brace_dims_hdr = QtWidgets.QLabel("Brace Dimensions")
        brace_dims_hdr.setFont(hdr_font)
        brace_layout.addWidget(brace_dims_hdr)

        brace_form = QtWidgets.QFormLayout()
        brace_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        brace_length_spin = _dim_spinbox("mm", 1000.0)
        brace_length_spin.setValue(AS.AppSettings.brace_length())
        brace_form.addRow("Length (along grain):", brace_length_spin)

        brace_width_spin = _dim_spinbox("mm", 200.0)
        brace_width_spin.setValue(AS.AppSettings.brace_width())
        brace_form.addRow("Width (breadth):", brace_width_spin)

        brace_thick_spin = _dim_spinbox("mm", 200.0)
        brace_thick_spin.setValue(AS.AppSettings.brace_thickness())
        brace_form.addRow("Height (tap direction):", brace_thick_spin)

        height_note = QtWidgets.QLabel(
            "Brace height when lying flat — this is the t dimension in the stiffness formula"
        )
        height_note.setFont(small)
        height_note.setWordWrap(True)
        brace_form.addRow("", height_note)

        brace_mass_spin = _dim_spinbox("g", 500.0)
        brace_mass_spin.setValue(AS.AppSettings.brace_mass())
        brace_form.addRow("Mass:", brace_mass_spin)

        brace_density_lbl = QtWidgets.QLabel("—")
        brace_density_lbl.setFont(small)
        brace_form.addRow("Calculated Density:", brace_density_lbl)
        brace_layout.addLayout(brace_form)

        def _update_brace_density() -> None:
            L = brace_length_spin.value()
            W = brace_width_spin.value()
            T = brace_thick_spin.value()
            m = brace_mass_spin.value()
            if L > 0 and W > 0 and T > 0 and m > 0:
                density = m / ((L / 10) * (W / 10) * (T / 10))
                brace_density_lbl.setText(f"{density:.3f} g/cm³")
            else:
                brace_density_lbl.setText("—")

        brace_length_spin.valueChanged.connect(lambda _: _update_brace_density())
        brace_width_spin.valueChanged.connect(lambda _: _update_brace_density())
        brace_thick_spin.valueChanged.connect(lambda _: _update_brace_density())
        brace_mass_spin.valueChanged.connect(lambda _: _update_brace_density())
        _update_brace_density()
        mg.addWidget(brace_widget)

        # ---- Mode ranges display ----
        _MODE_DISPLAY_NAMES = {
            "Helmholtz T(1,1)_1": "Air",
            "Top T(1,1)_2": "Top",
            "Back T(1,1)_3": "Back",
            "Long Dipole T(1,2)": "Dipole",
            "Cross Tripole T(3,1)": "Ring",
        }

        def _update_mode_ranges(unified_type: str) -> None:
            gt_str = GUITAR_TYPE_MAP.get(unified_type)
            if gt_str is None:
                return
            try:
                gt = GM.GuitarType(gt_str)
            except ValueError:
                return
            bands = GM.get_bands(gt)
            parts = [
                f"{_MODE_DISPLAY_NAMES[name]}: {int(lo)}–{int(hi)} Hz"
                for lo, hi, name, _ in bands
                if name in _MODE_DISPLAY_NAMES
            ]
            mode_ranges_lbl.setText("  |  ".join(parts))

        # ---- Show/hide type-specific widgets ----
        def _on_meas_type_changed(unified: str) -> None:
            meas_t, guitar_t = MEAS_TO_COMBO[unified]
            self.measurement_type_combo.setCurrentText(meas_t)
            if guitar_t:
                self.guitar_type_combo.setCurrentText(guitar_t)
            is_guitar = meas_t == "Guitar"
            meas_desc_lbl.setText(MEAS_DESCRIPTIONS.get(unified, ""))
            guitar_widget.setVisible(is_guitar)
            plate_widget.setVisible(meas_t == "Plate")
            brace_widget.setVisible(meas_t == "Brace")
            show_unknown_widget.setEnabled(is_guitar)
            peak_thresh_widget.setEnabled(is_guitar)
            max_peaks_widget.setEnabled(is_guitar)
            if is_guitar and guitar_t:
                _update_mode_ranges(unified)

        meas_type_combo.currentTextChanged.connect(_on_meas_type_changed)

        # =====================================================
        # 2. Display Settings Section
        # =====================================================
        disp_group = QtWidgets.QGroupBox("")
        dg = QtWidgets.QVBoxLayout(disp_group)
        dg.addWidget(_group_header("mdi.chart-line", "Display Settings"))

        disp_form = QtWidgets.QFormLayout()
        disp_form.addRow("Start (Hz):", self.min_spin)
        disp_form.addRow("Stop (Hz):", self.max_spin)

        db_min_spin = QtWidgets.QDoubleSpinBox()
        db_min_spin.setRange(-120, 20)
        db_min_spin.setDecimals(1)
        db_min_spin.setSuffix(" dB")
        db_min_spin.setValue(AS.AppSettings.db_min())
        disp_form.addRow("Min Magnitude:", db_min_spin)

        db_max_spin = QtWidgets.QDoubleSpinBox()
        db_max_spin.setRange(-120, 20)
        db_max_spin.setDecimals(1)
        db_max_spin.setSuffix(" dB")
        db_max_spin.setValue(AS.AppSettings.db_max())
        disp_form.addRow("Max Magnitude:", db_max_spin)
        dg.addLayout(disp_form)

        db_min_spin.valueChanged.connect(lambda v: AS.AppSettings.set_db_min(v))
        db_max_spin.valueChanged.connect(lambda v: AS.AppSettings.set_db_max(v))

        save_view_btn = QtWidgets.QPushButton("Save Current View")
        save_view_btn.setToolTip("Persist the current pan/zoom state as the default view")

        def _save_current_view() -> None:
            vb = self.fft_canvas.getPlotItem().vb
            x_range, y_range = vb.viewRange()
            meas_t = self.measurement_type_combo.currentText()
            AS.AppSettings.set_f_min(int(x_range[0]), meas_t)
            AS.AppSettings.set_f_max(int(x_range[1]), meas_t)
            AS.AppSettings.set_db_min(y_range[0])
            AS.AppSettings.set_db_max(y_range[1])
            self.min_spin.setValue(int(x_range[0]))
            self.max_spin.setValue(int(x_range[1]))
            db_min_spin.setValue(y_range[0])
            db_max_spin.setValue(y_range[1])

        save_view_btn.clicked.connect(_save_current_view)
        dg.addWidget(save_view_btn)

        reset_disp_btn = QtWidgets.QPushButton("Reset to Defaults")
        reset_disp_btn.setToolTip("Restore factory display settings for the current measurement type")

        def _reset_display_defaults() -> None:
            meas_t = self.measurement_type_combo.currentText()
            f_min_def = {"Plate": 30, "Brace": 30}.get(meas_t, 75)
            f_max_def = {"Plate": 600, "Brace": 1000}.get(meas_t, 350)
            self.min_spin.setValue(f_min_def)
            self.max_spin.setValue(f_max_def)
            db_min_spin.setValue(-100.0)
            db_max_spin.setValue(0.0)

        reset_disp_btn.clicked.connect(_reset_display_defaults)
        dg.addWidget(reset_disp_btn)

        # =====================================================
        # 3. Analysis Settings Section
        # =====================================================
        analysis_group = QtWidgets.QGroupBox("")
        an = QtWidgets.QVBoxLayout(analysis_group)
        an.addWidget(_group_header("mdi.pulse", "Analysis Settings"))

        an_form = QtWidgets.QFormLayout()

        an_f_min_spin = QtWidgets.QDoubleSpinBox()
        an_f_min_spin.setRange(0, 22050)
        an_f_min_spin.setDecimals(0)
        an_f_min_spin.setSuffix(" Hz")
        an_f_min_spin.setValue(AS.AppSettings.analysis_f_min())
        an_form.addRow("Analysis Min:", an_f_min_spin)

        an_f_max_spin = QtWidgets.QDoubleSpinBox()
        an_f_max_spin.setRange(0, 22050)
        an_f_max_spin.setDecimals(0)
        an_f_max_spin.setSuffix(" Hz")
        an_f_max_spin.setValue(AS.AppSettings.analysis_f_max())
        an_form.addRow("Analysis Max:", an_f_max_spin)
        an.addLayout(an_form)

        an_f_min_spin.valueChanged.connect(lambda v: AS.AppSettings.set_analysis_f_min(v))
        an_f_max_spin.valueChanged.connect(lambda v: AS.AppSettings.set_analysis_f_max(v))

        # Show Unknown Modes (guitar only)
        show_unknown_widget = QtWidgets.QWidget()
        su_layout = QtWidgets.QVBoxLayout(show_unknown_widget)
        su_layout.setContentsMargins(0, 4, 0, 0)
        su_layout.setSpacing(2)
        show_unknown_cb = QtWidgets.QCheckBox("Show Unknown Modes")
        show_unknown_cb.setToolTip("Display peaks that don't fall within known mode classification ranges")
        show_unknown_cb.setChecked(AS.AppSettings.show_unknown_modes())
        show_unknown_cb.toggled.connect(AS.AppSettings.set_show_unknown_modes)
        unknown_desc = QtWidgets.QLabel("Display peaks outside known mode ranges")
        unknown_desc.setFont(small)
        su_layout.addWidget(show_unknown_cb)
        su_layout.addWidget(unknown_desc)
        an.addWidget(show_unknown_widget)

        # Peak Detection Minimum (guitar only)
        peak_thresh_widget = QtWidgets.QWidget()
        pt_layout = QtWidgets.QVBoxLayout(peak_thresh_widget)
        pt_layout.setContentsMargins(0, 4, 0, 0)
        pt_layout.setSpacing(4)
        pt_hdr = QtWidgets.QLabel("Peak Detection Minimum")
        pt_hdr.setFont(hdr_font)
        pt_layout.addWidget(pt_hdr)
        pt_row = QtWidgets.QHBoxLayout()
        peak_thresh_spin = QtWidgets.QDoubleSpinBox()
        peak_thresh_spin.setRange(-120, 0)
        peak_thresh_spin.setDecimals(1)
        peak_thresh_spin.setSuffix(" dB")
        peak_thresh_spin.setValue(AS.AppSettings.peak_threshold())
        pt_row.addWidget(peak_thresh_spin)
        pt_row.addStretch()
        pt_layout.addLayout(pt_row)
        pt_desc = QtWidgets.QLabel("Minimum magnitude for peak detection. Typical range: -60 to -40 dB")
        pt_desc.setFont(small)
        pt_desc.setWordWrap(True)
        pt_layout.addWidget(pt_desc)
        peak_thresh_spin.valueChanged.connect(lambda v: AS.AppSettings.set_peak_threshold(v))
        an.addWidget(peak_thresh_widget)

        # Maximum Peaks (guitar only)
        max_peaks_widget = QtWidgets.QWidget()
        mp_layout = QtWidgets.QVBoxLayout(max_peaks_widget)
        mp_layout.setContentsMargins(0, 4, 0, 0)
        mp_layout.setSpacing(4)
        mp_hdr = QtWidgets.QLabel("Maximum Peaks")
        mp_hdr.setFont(hdr_font)
        mp_layout.addWidget(mp_hdr)
        mp_row = QtWidgets.QHBoxLayout()
        saved_max_peaks = AS.AppSettings.max_peaks()
        mp_spin = QtWidgets.QSpinBox()
        mp_spin.setRange(1, 100)
        mp_spin.setValue(saved_max_peaks if saved_max_peaks > 0 else 10)
        mp_spin.setEnabled(saved_max_peaks != 0)
        mp_row.addWidget(mp_spin)
        mp_row.addWidget(QtWidgets.QLabel("peaks"))
        mp_row.addStretch()
        mp_layout.addLayout(mp_row)
        mp_all_cb = QtWidgets.QCheckBox("Capture all peaks in analysis range")
        mp_all_cb.setChecked(saved_max_peaks == 0)
        mp_desc = QtWidgets.QLabel(
            "Maximum number of peaks to detect. Set to 'All' to capture every peak above the threshold."
        )
        mp_desc.setFont(small)
        mp_desc.setWordWrap(True)
        mp_layout.addWidget(mp_all_cb)
        mp_layout.addWidget(mp_desc)

        def _on_all_peaks_toggled(checked: bool) -> None:
            mp_spin.setEnabled(not checked)
            AS.AppSettings.set_max_peaks(0 if checked else mp_spin.value())

        mp_all_cb.toggled.connect(_on_all_peaks_toggled)
        mp_spin.valueChanged.connect(
            lambda v: AS.AppSettings.set_max_peaks(v) if not mp_all_cb.isChecked() else None
        )
        an.addWidget(max_peaks_widget)

        # Hysteresis Margin
        an.addWidget(QtWidgets.QLabel("Hysteresis Margin"))
        hyst_row = QtWidgets.QHBoxLayout()
        hyst_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        # Steps of 0.5 dB over 1.0–10.0 dB range: slider range 2–20, value = steps * 0.5
        hyst_slider.setRange(2, 20)
        saved_hyst = AS.AppSettings.hysteresis_margin()
        hyst_slider.setValue(int(saved_hyst * 2))
        hyst_slider.setToolTip(
            "How far the signal must drop below the threshold before the\n"
            "detector resets and is ready for the next tap"
        )
        hyst_row.addWidget(hyst_slider)
        hyst_readout = QtWidgets.QLabel(f"{saved_hyst:.1f} dB")
        hyst_readout.setMinimumWidth(50)
        hyst_readout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        hyst_row.addWidget(hyst_readout)
        hyst_reset = QtWidgets.QToolButton()
        hyst_reset.setIcon(qta.icon("mdi.undo"))
        hyst_reset.setStyleSheet("border: none")
        hyst_reset.setToolTip("Reset to default (3.0 dB)")
        hyst_reset.clicked.connect(lambda: hyst_slider.setValue(6))  # 6 steps × 0.5 = 3.0 dB
        hyst_row.addWidget(hyst_reset)
        an.addLayout(hyst_row)
        hyst_desc = QtWidgets.QLabel(
            "How far the signal must drop below the detection threshold before the detector resets "
            "and is ready for the next tap. A higher value prevents a single loud tap from "
            "triggering multiple detections."
        )
        hyst_desc.setWordWrap(True)
        hyst_desc.setFont(small)
        an.addWidget(hyst_desc)

        def _on_hyst_changed(val: int) -> None:
            db = val * 0.5
            self.fft_canvas.set_hysteresis_margin(db)
            AS.AppSettings.set_hysteresis_margin(db)
            hyst_readout.setText(f"{db:.1f} dB")

        hyst_slider.valueChanged.connect(_on_hyst_changed)

        reset_analysis_btn = QtWidgets.QPushButton("Reset Analysis Settings")

        def _reset_analysis_settings() -> None:
            an_f_min_spin.setValue(30.0)
            an_f_max_spin.setValue(2000.0)
            peak_thresh_spin.setValue(-60.0)
            mp_all_cb.setChecked(True)
            hyst_slider.setValue(6)  # 6 steps × 0.5 = 3.0 dB default

        reset_analysis_btn.clicked.connect(_reset_analysis_settings)
        an.addWidget(reset_analysis_btn)

        # =====================================================
        # 4. Audio Input & Calibration Section
        # =====================================================
        audio_group = QtWidgets.QGroupBox("")
        aud = QtWidgets.QVBoxLayout(audio_group)
        aud.addWidget(_group_header("mdi.microphone", "Audio Input & Calibration"))

        dev_row = QtWidgets.QHBoxLayout()
        dev_row.addWidget(QtWidgets.QLabel("Audio Input Device:"))
        device_combo = QtWidgets.QComboBox()
        device_combo.setToolTip("Select the microphone or audio input device to use")
        device_combo.setEditable(True)
        le = device_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        dev_row.addWidget(device_combo, stretch=1)
        aud.addLayout(dev_row)

        input_devices: list[tuple[int, str, float]] = []
        try:
            default_input = sd.query_devices(kind="input")
            default_input_name: str = str(default_input["name"]) if default_input else ""
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    input_devices.append((i, str(dev["name"]), float(dev["default_samplerate"])))
        except Exception:
            default_input_name = ""

        saved_dev_name = AS.AppSettings.device_name()
        current_dev_idx = -1
        for list_idx, (_, dev_name, _) in enumerate(input_devices):
            device_combo.addItem(dev_name)
            if dev_name == saved_dev_name:
                current_dev_idx = list_idx
        if current_dev_idx >= 0:
            device_combo.setCurrentIndex(current_dev_idx)

        sr_row = QtWidgets.QHBoxLayout()
        sr_lbl = QtWidgets.QLabel("Sample Rate:")
        sr_lbl.setFont(small)
        sr_val = QtWidgets.QLabel()
        sr_val.setFont(small)
        sr_val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        sr_row.addWidget(sr_lbl)
        sr_row.addWidget(sr_val, stretch=1)
        aud.addLayout(sr_row)

        def _update_sr_lbl(combo_idx: int) -> None:
            if 0 <= combo_idx < len(input_devices):
                sr_val.setText(f"{input_devices[combo_idx][2] / 1000:.0f} kHz")
            else:
                sr_val.setText("")

        _update_sr_lbl(device_combo.currentIndex())
        device_combo.currentIndexChanged.connect(_update_sr_lbl)

        def _on_device_selected(combo_idx: int) -> None:
            if 0 <= combo_idx < len(input_devices):
                dev_idx, dev_name, _ = input_devices[combo_idx]
                if dev_name != AS.AppSettings.device_name():
                    self.fft_canvas.set_device(dev_idx)
                    AS.AppSettings.set_device_name(dev_name)
                    self.device_status_lbl.setText(dev_name)
                    self.set_calibration_status(AS.AppSettings.calibration_for_device(dev_name))
                    _update_cal_display()

        device_combo.currentIndexChanged.connect(_on_device_selected)

        def _rebuild_device_combo(_: list[str]) -> None:
            """Refresh the device combo when sounddevice reports a change."""
            nonlocal input_devices
            try:
                new_devices: list[tuple[int, str, float]] = [
                    (int(dev["index"]), str(dev["name"]), float(dev["default_samplerate"]))
                    for dev in sd.query_devices()
                    if dev["max_input_channels"] > 0
                ]
            except Exception:
                return
            input_devices = new_devices
            saved = AS.AppSettings.device_name()
            device_combo.blockSignals(True)
            device_combo.clear()
            restore_idx = -1
            for list_idx, (_, dev_name, _) in enumerate(input_devices):
                device_combo.addItem(dev_name)
                if dev_name == saved:
                    restore_idx = list_idx
            device_combo.blockSignals(False)
            if restore_idx >= 0:
                device_combo.setCurrentIndex(restore_idx)
            elif input_devices:
                device_combo.setCurrentIndex(0)
            _update_sr_lbl(device_combo.currentIndex())

        aud.addWidget(_hsep())

        # Calibration picker
        cal_row = QtWidgets.QHBoxLayout()
        cal_row.addWidget(QtWidgets.QLabel("Calibration:"))
        cal_combo = QtWidgets.QComboBox()
        cal_combo.setEditable(True)
        le = cal_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        cal_row.addWidget(cal_combo, stretch=1)
        aud.addLayout(cal_row)

        def _rebuild_cal_combo() -> None:
            cal_combo.blockSignals(True)
            cal_combo.clear()
            cal_combo.addItem("None (Uncalibrated)")
            for dev_name, path in AS.AppSettings.all_calibrations().items():
                if path:
                    cal_combo.addItem(
                        f"{dev_name}: {os.path.basename(path)}",
                        userData=(dev_name, path),
                    )
            cal_combo.blockSignals(False)

        def _update_cal_display() -> None:
            _rebuild_cal_combo()
            # Use the device currently shown in the combo, not the stale saved name.
            # AppSettings.device_name() may refer to a device from a previous session
            # that is no longer active (e.g. UMIK-1 saved but not plugged in).
            cur_dev = device_combo.currentText()
            cur_cal = AS.AppSettings.calibration_for_device(cur_dev)
            if cur_cal:
                for i in range(cal_combo.count()):
                    data = cal_combo.itemData(i)
                    if data and data[1] == cur_cal:
                        cal_combo.setCurrentIndex(i)
                        break
            else:
                cal_combo.setCurrentIndex(0)

        _update_cal_display()

        def _import_cal() -> None:
            start_dir = AS.AppSettings.calibration_path() or os.path.expanduser("~")
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                dlg,
                "Import Microphone Calibration",
                start_dir,
                "Calibration files (*.cal *.txt);;All files (*)",
            )
            if not path:
                return
            if self.fft_canvas.load_calibration(path):
                AS.AppSettings.set_calibration_path(os.path.dirname(path))
                dev_name = self.fft_canvas.current_calibration_device() or AS.AppSettings.device_name()
                if dev_name:
                    AS.AppSettings.set_calibration_for_device(dev_name, path)
                self.set_calibration_status(path)
                _update_cal_display()
            else:
                QtWidgets.QMessageBox.warning(
                    dlg,
                    "Calibration Error",
                    f"Could not parse calibration file:\n{path}",
                )

        import_btn = QtWidgets.QPushButton(
            qta.icon("mdi.file-plus-outline"), "Import Calibration File..."
        )
        import_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        )
        import_btn.clicked.connect(_import_cal)
        import_row = QtWidgets.QHBoxLayout()
        import_row.addWidget(import_btn)
        import_row.addStretch()
        aud.addLayout(import_row)

        # Calibration metadata display
        cal_meta_widget = QtWidgets.QWidget()
        cal_meta_layout = QtWidgets.QHBoxLayout(cal_meta_widget)
        cal_meta_layout.setContentsMargins(0, 2, 0, 2)
        cal_meta_layout.setSpacing(4)
        cal_meta_left = QtWidgets.QVBoxLayout()
        cal_meta_left.setSpacing(1)
        cal_meta_sens_lbl = QtWidgets.QLabel()
        cal_meta_sens_lbl.setFont(small)
        cal_meta_points_lbl = QtWidgets.QLabel()
        cal_meta_points_lbl.setFont(small)
        cal_meta_left.addWidget(cal_meta_sens_lbl)
        cal_meta_left.addWidget(cal_meta_points_lbl)
        cal_meta_range_lbl = QtWidgets.QLabel()
        cal_meta_range_lbl.setFont(small)
        cal_meta_range_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        cal_meta_layout.addLayout(cal_meta_left)
        cal_meta_layout.addStretch()
        cal_meta_layout.addWidget(cal_meta_range_lbl)
        cal_meta_widget.setVisible(False)
        aud.addWidget(cal_meta_widget)

        def _update_cal_meta() -> None:
            import mic_calibration as _mc
            idx = cal_combo.currentIndex()
            data = cal_combo.itemData(idx)
            if not data:
                cal_meta_widget.setVisible(False)
                return
            _, path = data
            try:
                meta = _mc.parse_cal_metadata(path)
            except Exception:
                cal_meta_widget.setVisible(False)
                return
            if meta["sensitivity_db"] is not None:
                cal_meta_sens_lbl.setText(f"Sensitivity: {meta['sensitivity_db']:.2f} dB")
                cal_meta_sens_lbl.setVisible(True)
            else:
                cal_meta_sens_lbl.setVisible(False)
            cal_meta_points_lbl.setText(f"Data points: {meta['data_points']}")
            if meta["freq_min"] is not None and meta["freq_max"] is not None:
                cal_meta_range_lbl.setText(
                    f"{meta['freq_min']:.0f}–{meta['freq_max']:.0f} Hz"
                )
            else:
                cal_meta_range_lbl.setText("")
            cal_meta_widget.setVisible(True)

        cal_combo.currentIndexChanged.connect(lambda _: _update_cal_meta())
        _update_cal_meta()

        delete_cal_btn = QtWidgets.QPushButton(
            qta.icon("mdi.trash-can-outline"), "Delete All Calibrations"
        )
        delete_cal_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        )

        def _delete_all_calibrations() -> None:
            reply = QtWidgets.QMessageBox.question(
                dlg,
                "Delete All Calibrations",
                "Remove all stored calibration files?",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                AS.AppSettings.delete_all_calibrations()
                self.set_calibration_status("")
                _update_cal_display()

        delete_cal_btn.clicked.connect(_delete_all_calibrations)
        delete_row = QtWidgets.QHBoxLayout()
        delete_row.addWidget(delete_cal_btn)
        delete_row.addStretch()
        aud.addLayout(delete_row)

        cal_footer = QtWidgets.QLabel(
            "Select audio input device. Import a calibration file (.txt or .cal) "
            "from your measurement microphone to compensate for its frequency "
            "response. Calibrations are automatically associated with each device."
        )
        cal_footer.setFont(small)
        cal_footer.setWordWrap(True)
        aud.addWidget(cal_footer)

        # =====================================================
        # 5. FFT Processing Section
        # =====================================================
        fft_group = QtWidgets.QGroupBox("")
        fg = QtWidgets.QVBoxLayout(fft_group)
        fg.addWidget(_group_header("mdi.waveform", "FFT Processing"))

        hop_hdr_row = QtWidgets.QHBoxLayout()
        hop_hdr = QtWidgets.QLabel("Hop Size Overlap")
        hop_hdr.setFont(hdr_font)
        hop_hdr_row.addWidget(hop_hdr)
        hop_hdr_row.addStretch()
        hop_readout = QtWidgets.QLabel(f"{int(AS.AppSettings.hop_size_overlap())}%")
        hop_readout.setFont(hdr_font)
        hop_hdr_row.addWidget(hop_readout)
        fg.addLayout(hop_hdr_row)

        hop_row = QtWidgets.QHBoxLayout()
        hop_zero_lbl = QtWidgets.QLabel("0%")
        hop_zero_lbl.setFont(small)
        hop_row.addWidget(hop_zero_lbl)
        hop_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        hop_slider.setRange(0, 15)   # 0–15 steps × 5 % = 0–75 %
        hop_slider.setValue(int(AS.AppSettings.hop_size_overlap() / 5))
        hop_row.addWidget(hop_slider)
        hop_max_lbl = QtWidgets.QLabel("75%")
        hop_max_lbl.setFont(small)
        hop_row.addWidget(hop_max_lbl)
        fg.addLayout(hop_row)

        hop_context_lbl = QtWidgets.QLabel()
        hop_context_lbl.setFont(small)
        hop_context_lbl.setWordWrap(True)

        def _hop_context(pct: int) -> str:
            if pct == 0:
                return "0% overlap: Maximum frame rate, no smoothing"
            if pct <= 25:
                return "Low overlap: Fast response with minimal smoothing"
            if pct <= 50:
                return "Medium overlap: Balanced response and smoothness"
            return "High overlap: Smooth results, slower response"

        def _on_hop_changed(steps: int) -> None:
            pct = steps * 5
            hop_readout.setText(f"{pct}%")
            hop_context_lbl.setText(_hop_context(pct))
            AS.AppSettings.set_hop_size_overlap(float(pct))

        hop_slider.valueChanged.connect(_on_hop_changed)
        _on_hop_changed(hop_slider.value())
        fg.addWidget(hop_context_lbl)

        hop_note = QtWidgets.QLabel(
            "Controls the overlap between FFT windows. Higher overlap provides smoother results "
            "but reduces frame rate. Changes take effect on next analyzer restart."
        )
        hop_note.setFont(small)
        hop_note.setWordWrap(True)
        fg.addWidget(hop_note)

        # =====================================================
        # 6. About & Help Section
        # =====================================================
        about_group = QtWidgets.QGroupBox("")
        ab = QtWidgets.QVBoxLayout(about_group)
        ab.addWidget(_group_header("mdi.information", "About & Help"))

        try:
            with open(os.path.join(basedir, "version"), "r", encoding="UTF-8") as fh:
                ver = fh.read().strip()
        except OSError:
            ver = "—"

        ver_row = QtWidgets.QHBoxLayout()
        ver_lbl = QtWidgets.QLabel("Version")
        ver_val = QtWidgets.QLabel(ver)
        ver_val.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        ver_row.addWidget(ver_lbl)
        ver_row.addWidget(ver_val, stretch=1)
        ab.addLayout(ver_row)

        copyright_lbl = QtWidgets.QLabel(
            "Copyright \u00a9 2026 David W. Smith dba Dolce Sfogato"
        )
        copyright_lbl.setFont(small)
        copyright_lbl.setWordWrap(True)
        ab.addWidget(copyright_lbl)

        help_btn = QtWidgets.QPushButton("Help")
        help_btn.clicked.connect(self._show_help)
        ab.addWidget(help_btn)

        # =====================================================
        # Final layout — matches Swift TapSettingsView.body order:
        # audioInputSection, measurementTypeSection,
        # Advanced (collapsible: Display, Analysis, FFT), aboutSection
        # =====================================================
        vbox.addWidget(audio_group)
        vbox.addWidget(meas_group)

        # Advanced collapsible section header — flat QPushButton avoids QToolButton sizing issues
        adv_btn = QtWidgets.QPushButton("\u25b6  Advanced")
        adv_btn.setCheckable(True)
        adv_btn.setChecked(False)
        adv_btn.setFlat(True)
        adv_btn.setFont(hdr_font)
        adv_btn.setStyleSheet("QPushButton { text-align: left; padding: 4px 6px; }")
        vbox.addWidget(adv_btn)

        # Advanced collapsible content (Display, Analysis, FFT)
        adv_content = QtWidgets.QWidget()
        adv_cl = QtWidgets.QVBoxLayout(adv_content)
        adv_cl.setContentsMargins(0, 0, 0, 0)
        adv_cl.setSpacing(8)
        adv_cl.addWidget(disp_group)
        adv_cl.addWidget(analysis_group)
        adv_cl.addWidget(fft_group)
        adv_content.setVisible(False)
        vbox.addWidget(adv_content)

        def _toggle_advanced(checked: bool) -> None:
            adv_btn.setText("\u25bc  Advanced" if checked else "\u25b6  Advanced")
            adv_content.setVisible(checked)

        adv_btn.toggled.connect(_toggle_advanced)

        vbox.addWidget(about_group)

        # Apply initial visibility
        _on_meas_type_changed(cur_unified)

        def _on_device_list_changed(_: list[str]) -> None:
            """Update device combo, calibration combo and metadata when devices change."""
            _rebuild_device_combo(_)
            _update_cal_display()
            _update_cal_meta()

        # Refresh device and calibration display live while the dialog is open
        self.fft_canvas.devicesChanged.connect(_on_device_list_changed)
        dlg.resize(460, 700)
        dlg.exec()
        self.fft_canvas.devicesChanged.disconnect(_on_device_list_changed)

        # Persist plate / brace / gore / f_vs settings on close
        AS.AppSettings.set_plate_length(plate_length_spin.value())
        AS.AppSettings.set_plate_width(plate_width_spin.value())
        AS.AppSettings.set_plate_thickness(plate_thick_spin.value())
        AS.AppSettings.set_plate_mass(plate_mass_spin.value())
        AS.AppSettings.set_measure_flc(measure_flc_cb.isChecked())
        AS.AppSettings.set_guitar_body_length(gore_body_len_spin.value())
        AS.AppSettings.set_guitar_body_width(gore_body_wid_spin.value())
        fvs_idx = fvs_combo.currentIndex()
        AS.AppSettings.set_plate_stiffness_preset(
            PRESET_STORAGE_NAMES[fvs_idx] if 0 <= fvs_idx < len(PRESET_STORAGE_NAMES) else "Steel String Top"
        )
        AS.AppSettings.set_custom_plate_stiffness(custom_fvs_spin.value())
        AS.AppSettings.set_brace_length(brace_length_spin.value())
        AS.AppSettings.set_brace_width(brace_width_spin.value())
        AS.AppSettings.set_brace_thickness(brace_thick_spin.value())
        AS.AppSettings.set_brace_mass(brace_mass_spin.value())

        # Re-hide the reparented widgets
        self.min_spin.setParent(None)  # type: ignore[call-overload]
        self.max_spin.setParent(None)  # type: ignore[call-overload]
        self.num_averages.setParent(None)  # type: ignore[call-overload]
        self.avg_enable.setParent(None)  # type: ignore[call-overload]
        self.avg_completed.setParent(None)  # type: ignore[call-overload]
        self.avg_done.setParent(None)  # type: ignore[call-overload]
        self.avg_restart.setParent(None)  # type: ignore[call-overload]

    # ================================================================
    # Help
    # ================================================================

    def _show_help(self) -> None:
        if self._help_dialog is None or not self._help_dialog.isVisible():
            self._help_dialog = HD.HelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    # ================================================================
    # Window lifecycle
    # ================================================================

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        AS.AppSettings.set_window_geometry(self.saveGeometry())
        super().closeEvent(event)


def _redirect_logs_if_needed() -> None:
    """Redirect stdout/stderr to a log file when not running under a debugger."""
    if sys.gettrace() is not None:
        return
    debug_env = (
        "VSCODE_PID", "PYTHONDEBUG", "PYCHARM_HOSTED", "DEBUGGER", "PYDEVD_USE_FRAME_EVAL"
    )
    if any(v in os.environ for v in debug_env):
        return
    log_dir = os.path.expanduser("~/Library/Logs/GuitarTap")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "GuitarTap-debug.log")
    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: WPS515
        sys.stdout = log_file
        sys.stderr = log_file
    except OSError:
        pass


if __name__ == "__main__":
    _redirect_logs_if_needed()

    if os.name == "nt":
        mutex = NM.NamedMutex("guitar-tap-running", True)

    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.setWindowIcon(QtGui.QIcon(os.path.join(basedir, "icons/guitar-tap.svg")))
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
