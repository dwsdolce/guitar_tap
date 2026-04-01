""" Samples audio signal and finds the peaks of the guitar tap resonances
"""

import sys
import os

import numpy as np
import sounddevice as sd
from PyQt6 import QtWidgets, QtGui, QtCore

import fft_canvas as fft_c
from fft_canvas import DisplayMode
import fft_toolbar as fft_t
import peak_card_widget as PT
import show_devices as SD
import app_settings as AS
import measurement as M
from models import TapToneMeasurement, ResonantPeak, SpectrumSnapshot
from models import plate_stiffness_preset as PSP
from models import guitar_type as GT
from models import guitar_mode as GM
from models import measurement_type as MT
from models import microphone_calibration as _mc_mod
import measurements_dialog as MD
import save_measurement_dialog as SMD
import plate_analysis as PA
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


class MaterialPeakListWidget(QtWidgets.QWidget):
    """Plate/brace peak list with L/C/FLC mode-assignment buttons.

    Mirrors Swift's MaterialPeakRowView rows inside peaksAndModesSection.
    Each row shows: star toggle | frequency | magnitude | L button | [C] | [FLC]
    Instruction text is shown below the peak list.
    """

    # Emits (long_freq, cross_freq, flc_freq); 0.0 = not assigned.
    assignmentChanged = QtCore.pyqtSignal(float, float, float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks:      list[tuple[float, float]] = []
        self._long_freq:  float = 0.0
        self._cross_freq: float = 0.0
        self._flc_freq:   float = 0.0
        self._show_cross: bool  = True   # False for brace
        self._show_flc:   bool  = False
        self._selected:   set[float] = set()

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── peak rows (no internal scroll — parent scroll area handles it) ──
        self._peak_container = QtWidgets.QWidget()
        self._peak_layout = QtWidgets.QVBoxLayout(self._peak_container)
        self._peak_layout.setContentsMargins(0, 0, 0, 0)
        self._peak_layout.setSpacing(2)
        self._peak_layout.addStretch()
        outer.addWidget(self._peak_container)

        # ── separator + instruction section ────────────────────────────────
        outer.addWidget(_hsep())

        instr = QtWidgets.QWidget()
        il = QtWidgets.QVBoxLayout(instr)
        il.setContentsMargins(0, 4, 0, 0)
        il.setSpacing(4)

        _bold9 = QtGui.QFont()
        _bold9.setPointSize(9)
        _bold9.setBold(True)
        self._instr_title = QtWidgets.QLabel()
        self._instr_title.setFont(_bold9)
        il.addWidget(self._instr_title)

        # Steps container — rebuilt per mode
        self._instr_steps_widget = QtWidgets.QWidget()
        self._instr_steps_layout = QtWidgets.QVBoxLayout(self._instr_steps_widget)
        self._instr_steps_layout.setContentsMargins(0, 0, 0, 0)
        self._instr_steps_layout.setSpacing(6)
        il.addWidget(self._instr_steps_widget)

        _italic9 = QtGui.QFont()
        _italic9.setPointSize(9)
        _italic9.setItalic(True)
        self._instr_footer = QtWidgets.QLabel()
        self._instr_footer.setFont(_italic9)
        self._instr_footer.setWordWrap(True)
        self._instr_footer.setStyleSheet("color: palette(shadow);")
        il.addWidget(self._instr_footer)

        outer.addWidget(instr)
        self._rebuild_instructions()

    # ── public API ──────────────────────────────────────────────────────

    def set_mode(self, show_cross: bool, show_flc: bool) -> None:
        self._show_cross = show_cross
        self._show_flc   = show_flc
        self._rebuild_instructions()
        self._rebuild_rows()

    def update_peaks(self, data: np.ndarray) -> None:
        """Refresh from a (N, ≥2) numpy array [freq, mag, ...]."""
        if isinstance(data, np.ndarray) and data.ndim == 2 and data.shape[0] > 0:
            self._peaks = [(float(data[i, 0]), float(data[i, 1]))
                           for i in range(data.shape[0])]
        else:
            self._peaks = []
        existing = {f for f, _ in self._peaks}
        if self._long_freq  not in existing: self._long_freq  = 0.0
        if self._cross_freq not in existing: self._cross_freq = 0.0
        if self._flc_freq   not in existing: self._flc_freq   = 0.0
        self._selected = set(existing)
        self._rebuild_rows()

    def set_assignment(self, long_freq: float, cross_freq: float = 0.0,
                       flc_freq: float = 0.0) -> None:
        self._long_freq  = long_freq
        self._cross_freq = cross_freq
        self._flc_freq   = flc_freq
        self._rebuild_rows()

    def long_freq(self)  -> float: return self._long_freq
    def cross_freq(self) -> float: return self._cross_freq
    def flc_freq(self)   -> float: return self._flc_freq

    def select_all(self) -> None:
        self._selected = {f for f, _ in self._peaks}
        self._rebuild_rows()

    def deselect_all(self) -> None:
        self._selected.clear()
        self._rebuild_rows()

    # ── private helpers ─────────────────────────────────────────────────

    def _rebuild_rows(self) -> None:
        # Remove all rows (everything before the trailing stretch)
        while self._peak_layout.count() > 1:
            item = self._peak_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for freq, mag in sorted(self._peaks, key=lambda x: x[0]):
            row = self._make_row(freq, mag)
            self._peak_layout.insertWidget(self._peak_layout.count() - 1, row)

    def _make_row(self, freq: float, mag: float) -> QtWidgets.QWidget:
        w  = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(w)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(8)

        # Star toggle — same style as peak_card_widget
        star = QtWidgets.QToolButton()
        star.setFixedSize(24, 24)
        is_sel = freq in self._selected
        star.setText("★" if is_sel else "☆")
        star_color = "rgb(30,120,255)" if is_sel else "rgb(160,160,160)"
        star.setStyleSheet(
            f"QToolButton {{ border: none; background: transparent; color: {star_color}; }}"
        )
        star_fnt = QtGui.QFont()
        star_fnt.setPointSize(14)
        star.setFont(star_fnt)
        star.setCheckable(True)
        star.setChecked(is_sel)
        star.clicked.connect(lambda _chk, f=freq: self._toggle_sel(f))
        hl.addWidget(star)

        # Frequency + magnitude labels
        txt = QtWidgets.QWidget()
        tv  = QtWidgets.QVBoxLayout(txt)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        f_lbl = QtWidgets.QLabel(f"{freq:.1f} Hz")
        f_fnt = QtGui.QFont()
        f_fnt.setBold(True)
        f_fnt.setPointSize(11)
        f_lbl.setFont(f_fnt)
        tv.addWidget(f_lbl)
        m_lbl = QtWidgets.QLabel(f"{mag:.1f} dB")
        m_fnt = QtGui.QFont()
        m_fnt.setPointSize(9)
        m_lbl.setFont(m_fnt)
        m_lbl.setStyleSheet("color: palette(shadow);")
        tv.addWidget(m_lbl)
        hl.addWidget(txt, stretch=1)

        # L button (always shown)
        is_l = (freq == self._long_freq)
        l_btn = self._mode_btn("L", is_l, "#1976D2")
        l_btn.clicked.connect(lambda _, f=freq: self._assign_long(f))
        hl.addWidget(l_btn)

        # C button (plate only)
        if self._show_cross:
            is_c = (freq == self._cross_freq)
            c_btn = self._mode_btn("C", is_c, "#E65100")
            c_btn.clicked.connect(lambda _, f=freq: self._assign_cross(f))
            hl.addWidget(c_btn)

        # FLC button (plate + FLC only)
        if self._show_flc:
            is_flc = (freq == self._flc_freq)
            flc_btn = self._mode_btn("FLC", is_flc, "#7B1FA2", width=42)
            flc_btn.clicked.connect(lambda _, f=freq: self._assign_flc(f))
            hl.addWidget(flc_btn)

        return w

    @staticmethod
    def _mode_btn(label: str, active: bool, color: str,
                  width: int = 36) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(label)
        fnt = QtGui.QFont()
        fnt.setBold(True)
        fnt.setPointSize(10 if len(label) <= 1 else 8)
        btn.setFont(fnt)
        btn.setFixedSize(width, 32)
        bg  = color if active else "rgba(128,128,128,0.2)"
        clr = "white" if active else "palette(text)"
        btn.setStyleSheet(
            f"QPushButton {{background-color: {bg}; color: {clr};"
            "border-radius: 6px; border: none;}"
        )
        return btn

    def _toggle_sel(self, freq: float) -> None:
        if freq in self._selected: self._selected.discard(freq)
        else:                      self._selected.add(freq)
        self._rebuild_rows()

    def _assign_long(self, freq: float) -> None:
        if self._long_freq == freq:
            self._long_freq = 0.0
        else:
            if self._cross_freq == freq: self._cross_freq = 0.0
            if self._flc_freq   == freq: self._flc_freq   = 0.0
            self._long_freq = freq
        self._rebuild_rows()
        self.assignmentChanged.emit(self._long_freq, self._cross_freq, self._flc_freq)

    def _assign_cross(self, freq: float) -> None:
        if self._cross_freq == freq:
            self._cross_freq = 0.0
        else:
            if self._long_freq == freq: self._long_freq = 0.0
            if self._flc_freq  == freq: self._flc_freq  = 0.0
            self._cross_freq = freq
        self._rebuild_rows()
        self.assignmentChanged.emit(self._long_freq, self._cross_freq, self._flc_freq)

    def _assign_flc(self, freq: float) -> None:
        if self._flc_freq == freq:
            self._flc_freq = 0.0
        else:
            if self._long_freq  == freq: self._long_freq  = 0.0
            if self._cross_freq == freq: self._cross_freq = 0.0
            self._flc_freq = freq
        self._rebuild_rows()
        self.assignmentChanged.emit(self._long_freq, self._cross_freq, self._flc_freq)

    def _step_row(self, dot_color: str, bold_title: str, body: str) -> QtWidgets.QWidget:
        """One instruction step: colored circle + bold title + body text."""
        _sm = QtGui.QFont()
        _sm.setPointSize(9)
        _bold = QtGui.QFont()
        _bold.setPointSize(9)
        _bold.setBold(True)

        w  = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

        dot = QtWidgets.QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"QLabel {{ background-color: {dot_color}; border-radius: 4px; }}"
        )
        hl.addWidget(dot, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        txt_vbox = QtWidgets.QVBoxLayout()
        txt_vbox.setContentsMargins(0, 0, 0, 0)
        txt_vbox.setSpacing(2)
        title_lbl = QtWidgets.QLabel(bold_title)
        title_lbl.setFont(_bold)
        txt_vbox.addWidget(title_lbl)
        body_lbl = QtWidgets.QLabel(body)
        body_lbl.setFont(_sm)
        body_lbl.setWordWrap(True)
        body_lbl.setStyleSheet("color: palette(shadow);")
        txt_vbox.addWidget(body_lbl)
        hl.addLayout(txt_vbox, stretch=1)
        return w

    def _rebuild_instructions(self) -> None:
        # Clear existing step widgets
        while self._instr_steps_layout.count() > 0:
            item = self._instr_steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._show_cross:
            has_flc = self._show_flc
            self._instr_title.setText(
                "Three-Tap Measurement Process:" if has_flc
                else "Two-Tap Measurement Process:"
            )
            self._instr_steps_layout.addWidget(self._step_row(
                "#1976D2", "1. Longitudinal (L) Tap",
                "Hold plate at 22% from one end along the length, near one long edge "
                "(not at the width node). Tap center.",
            ))
            self._instr_steps_layout.addWidget(self._step_row(
                "#E65100", "2. Cross-grain (C) Tap",
                "Rotate 90°. Hold plate at 22% from one end along the width, near one "
                "short edge (not at the length node). Tap center.",
            ))
            if has_flc:
                self._instr_steps_layout.addWidget(self._step_row(
                    "#7B1FA2", "3. FLC (Diagonal) Tap",
                    "Hold plate at the midpoint of one long edge. Tap near the opposite "
                    "corner (~22% from both the end and the side). Measures shear stiffness.",
                ))
        else:
            self._instr_title.setText("Single-Tap Measurement (fL only):")
            self._instr_steps_layout.addWidget(self._step_row(
                "#1976D2", "1. Longitudinal (fL) Tap",
                "Hold brace at 22% from one end along the length. Tap center.",
            ))
        self._instr_footer.setText(
            "The strongest peak is auto-selected. Adjust if needed."
        )


class MainWindow(QtWidgets.QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()

        self.saved_path: str = ""
        self._ring_out_s: float | None = None
        self._is_running: bool = False
        self._is_paused: bool = False
        self._is_measurement_complete: bool = False
        self._tap_count_captured: int = 0
        self._tap_count_total: int = 1
        # Loaded-settings warning — mirrors Swift showLoadedSettingsWarning
        self._show_loaded_settings_warning: bool = False
        self._loaded_tap_threshold: int | None = None   # dB value at load time
        self._loaded_tap_num: int | None = None         # tap count at load time
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
        cv.setContentsMargins(0, 0, 8, 0)
        cv.setSpacing(0)
        cv.addWidget(self.fft_canvas, stretch=1)

        # Material instructions panel (below graph, plate/brace only)
        self._material_instr_panel = self._build_material_instr_panel()
        cv.addWidget(self._material_instr_panel)

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

        # Row 1: "Analysis Results" (bold) + measurement type badge
        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Analysis Results")
        bold_font = QtGui.QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(13)
        title.setFont(bold_font)
        title_row.addWidget(title, stretch=1)

        self.measurement_type_badge = QtWidgets.QLabel("Guitar")
        self.measurement_type_badge.setFont(small_font)
        self.measurement_type_badge.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.measurement_type_badge.setStyleSheet(
            "background: rgba(0,100,255,0.15); border-radius: 4px;"
            "padding: 1px 6px;"
        )
        title_row.addWidget(self.measurement_type_badge)
        vbox.addLayout(title_row)

        # Row 2: "Showing …" (left) + Select All / Deselect All / Reset buttons (right)
        freq_row = QtWidgets.QHBoxLayout()
        self.freq_range_label = QtWidgets.QLabel(
            f"Showing {f_range['f_min']} – {f_range['f_max']} Hz"
        )
        self.freq_range_label.setFont(small_font)
        freq_row.addWidget(self.freq_range_label, stretch=1)

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
        freq_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QtWidgets.QToolButton()
        self.deselect_all_btn.setIcon(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCancelButton)
            if style else QtGui.QIcon()
        )
        self.deselect_all_btn.setIconSize(QtCore.QSize(14, 14))
        self.deselect_all_btn.setFixedSize(22, 22)
        self.deselect_all_btn.setToolTip("Deselect all peaks")
        self.deselect_all_btn.setEnabled(False)
        freq_row.addWidget(self.deselect_all_btn)

        self.reset_auto_selection_btn = QtWidgets.QToolButton()
        self.reset_auto_selection_btn.setIcon(qta.icon("fa5s.magic", color="gray"))
        self.reset_auto_selection_btn.setIconSize(QtCore.QSize(14, 14))
        self.reset_auto_selection_btn.setFixedSize(22, 22)
        self.reset_auto_selection_btn.setToolTip("Reset to automatic mode selection")
        self.reset_auto_selection_btn.setEnabled(False)
        self.reset_auto_selection_btn.setVisible(False)
        freq_row.addWidget(self.reset_auto_selection_btn)

        vbox.addLayout(freq_row)

        vbox.addWidget(_hsep())

        # Comparison mode placeholder — shown instead of peak list while comparing.
        self._comparing_lbl = QtWidgets.QLabel()
        self._comparing_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._comparing_lbl.setStyleSheet("color: gray; font-size: 13px;")
        self._comparing_lbl.setVisible(False)
        vbox.addWidget(self._comparing_lbl, stretch=1)

        # Peaks table — the main content for guitar mode
        self.peak_widget = PT.PeakListWidget()
        vbox.addWidget(self.peak_widget, stretch=1)

        # Material peak list — replaces peak_widget for plate/brace mode
        # (added to scroll container below, not directly to vbox)
        self._material_peak_widget = MaterialPeakListWidget()

        # ── Material Properties section (plate/brace only) ───────────────────
        self._material_section = QtWidgets.QWidget()
        ms_vbox = QtWidgets.QVBoxLayout(self._material_section)
        ms_vbox.setContentsMargins(0, 0, 0, 0)
        ms_vbox.setSpacing(4)

        self._mat_title = QtWidgets.QLabel("Brace Properties")
        _mat_title_font = QtGui.QFont()
        _mat_title_font.setPointSize(small_font.pointSize())
        _mat_title_font.setBold(True)
        self._mat_title.setFont(_mat_title_font)
        ms_vbox.addWidget(self._mat_title)

        def _ms_row(label: str, parent: QtWidgets.QVBoxLayout) -> QtWidgets.QLabel:
            row = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setFont(small_font)
            val = QtWidgets.QLabel("—")
            val.setFont(small_font)
            val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            row.addWidget(lbl)
            row.addWidget(val)
            parent.addLayout(row)
            return val

        # ── Brace sub-section ────────────────────────────────────────────────
        self._brace_section = QtWidgets.QWidget()
        bs_vbox = QtWidgets.QVBoxLayout(self._brace_section)
        bs_vbox.setContentsMargins(0, 0, 0, 0)
        bs_vbox.setSpacing(2)

        # Placeholder shown when no L peak is assigned
        self._brace_placeholder = QtWidgets.QWidget()
        _bp_vbox = QtWidgets.QVBoxLayout(self._brace_placeholder)
        _bp_vbox.setContentsMargins(0, 8, 0, 8)
        _bp_p1 = QtWidgets.QLabel("Select the fL (L) peak above to calculate properties")
        _bp_p1.setWordWrap(True)
        _bp_p1.setStyleSheet("color: palette(shadow);")
        _bp_p1.setFont(small_font)
        _bp_vbox.addWidget(_bp_p1)
        _bp_p2 = QtWidgets.QLabel("Tip: The dominant peak is auto-selected after tapping")
        _bp_p2.setWordWrap(True)
        _bp_p2.setStyleSheet("color: palette(shadow);")
        _bp_p2.setFont(small_font)
        _bp_vbox.addWidget(_bp_p2)
        bs_vbox.addWidget(self._brace_placeholder)

        # Content shown when L peak IS assigned
        self._brace_content = QtWidgets.QWidget()
        bc_vbox = QtWidgets.QVBoxLayout(self._brace_content)
        bc_vbox.setContentsMargins(0, 0, 0, 0)
        bc_vbox.setSpacing(2)
        self._brace_content.setVisible(False)
        bs_vbox.addWidget(self._brace_content)

        # Redirect _ms_row to bc_vbox for brace content
        bs_vbox = bc_vbox  # remaining rows go into the content widget

        self._brace_subtitle = QtWidgets.QLabel("—")
        self._brace_subtitle.setFont(small_font)
        self._brace_subtitle.setStyleSheet("color: palette(shadow);")
        bs_vbox.addWidget(self._brace_subtitle)
        bs_vbox.addWidget(_hsep())

        self._brace_c_long = _ms_row("Speed of Sound:", bs_vbox)
        self._brace_E_long = _ms_row("Young's Modulus (E):", bs_vbox)

        # Specific modulus box
        _spec_frame_b = QtWidgets.QFrame()
        _spec_frame_b.setStyleSheet(
            "QFrame { background-color: palette(alternateBase); border-radius: 4px; }"
        )
        _sfb_vbox = QtWidgets.QVBoxLayout(_spec_frame_b)
        _sfb_vbox.setContentsMargins(6, 4, 6, 4)
        _sfb_vbox.setSpacing(2)
        _sfb_title = QtWidgets.QLabel("Specific Modulus (E/\u03c1)")
        _sfb_title.setFont(small_font)
        _sfb_vbox.addWidget(_sfb_title)
        _sfb_row = QtWidgets.QHBoxLayout()
        _big_font = QtGui.QFont()
        _big_font.setPointSize(14)
        _big_font.setBold(True)
        self._brace_spec_value = QtWidgets.QLabel("—")
        self._brace_spec_value.setFont(_big_font)
        _sfb_unit = QtWidgets.QLabel("GPa/(g/cm\u00b3)")
        _sfb_unit.setFont(small_font)
        _sfb_unit.setStyleSheet("color: palette(shadow);")
        _sfb_row.addWidget(self._brace_spec_value)
        _sfb_row.addWidget(_sfb_unit)
        _sfb_row.addStretch()
        _sfb_vbox.addLayout(_sfb_row)
        self._brace_quality_lbl = QtWidgets.QLabel("—")
        self._brace_quality_lbl.setFont(small_font)
        _sfb_vbox.addWidget(self._brace_quality_lbl)
        bs_vbox.addWidget(_spec_frame_b)

        self._brace_rad_ratio = _ms_row("Radiation Ratio (R):", bs_vbox)
        ms_vbox.addWidget(self._brace_section)

        # ── Plate sub-section ────────────────────────────────────────────────
        self._plate_section = QtWidgets.QWidget()
        ps_vbox = QtWidgets.QVBoxLayout(self._plate_section)
        ps_vbox.setContentsMargins(0, 0, 0, 0)
        ps_vbox.setSpacing(2)

        # Placeholder shown when L or C peak not yet assigned
        self._plate_placeholder = QtWidgets.QWidget()
        _pp_vbox = QtWidgets.QVBoxLayout(self._plate_placeholder)
        _pp_vbox.setContentsMargins(0, 8, 0, 8)
        self._plate_placeholder_lbl = QtWidgets.QLabel(
            "Select peaks above to calculate properties"
        )
        self._plate_placeholder_lbl.setWordWrap(True)
        self._plate_placeholder_lbl.setStyleSheet("color: palette(shadow);")
        self._plate_placeholder_lbl.setFont(small_font)
        _pp_vbox.addWidget(self._plate_placeholder_lbl)
        _pp_p2 = QtWidgets.QLabel(
            "Tip: The longitudinal mode is typically the higher frequency peak"
        )
        _pp_p2.setWordWrap(True)
        _pp_p2.setStyleSheet("color: palette(shadow);")
        _pp_p2.setFont(small_font)
        _pp_vbox.addWidget(_pp_p2)
        ps_vbox.addWidget(self._plate_placeholder)

        # Content shown when L and C are assigned
        self._plate_content = QtWidgets.QWidget()
        pc_vbox = QtWidgets.QVBoxLayout(self._plate_content)
        pc_vbox.setContentsMargins(0, 0, 0, 0)
        pc_vbox.setSpacing(2)
        self._plate_content.setVisible(False)
        ps_vbox.addWidget(self._plate_content)

        # Redirect ps_vbox for remaining plate content rows
        ps_vbox = pc_vbox

        # Frequencies — one per line (fL, fC, optionally fLC)
        self._plate_fl_lbl = QtWidgets.QLabel("fL (Longitudinal): —")
        self._plate_fl_lbl.setFont(small_font)
        self._plate_fl_lbl.setStyleSheet("color: palette(shadow);")
        ps_vbox.addWidget(self._plate_fl_lbl)
        self._plate_fc_lbl = QtWidgets.QLabel("fC (Cross-grain): —")
        self._plate_fc_lbl.setFont(small_font)
        self._plate_fc_lbl.setStyleSheet("color: palette(shadow);")
        ps_vbox.addWidget(self._plate_fc_lbl)
        self._plate_flc_lbl = QtWidgets.QLabel("fLC (Diagonal): —")
        self._plate_flc_lbl.setFont(small_font)
        self._plate_flc_lbl.setStyleSheet("color: palette(shadow);")
        self._plate_flc_lbl.setVisible(False)
        ps_vbox.addWidget(self._plate_flc_lbl)

        ps_vbox.addWidget(_hsep())

        def _plate_row(label: str) -> tuple[QtWidgets.QLabel, QtWidgets.QLabel]:
            """Title on own line; 'L: —' / 'C: —' on line below."""
            _title_fnt = QtGui.QFont()
            _title_fnt.setPointSize(small_font.pointSize())
            _title_fnt.setBold(True)
            row_w = QtWidgets.QWidget()
            rv = QtWidgets.QVBoxLayout(row_w)
            rv.setContentsMargins(0, 0, 0, 0)
            rv.setSpacing(2)
            title_lbl = QtWidgets.QLabel(label)
            title_lbl.setFont(_title_fnt)
            rv.addWidget(title_lbl)
            inner = QtWidgets.QHBoxLayout()
            val_l = QtWidgets.QLabel("L: —")
            val_l.setFont(small_font)
            val_l.setStyleSheet("color: palette(shadow);")
            val_c = QtWidgets.QLabel("C: —")
            val_c.setFont(small_font)
            val_c.setStyleSheet("color: palette(shadow);")
            inner.addWidget(val_l)
            inner.addStretch()
            inner.addWidget(val_c)
            rv.addLayout(inner)
            ps_vbox.addWidget(row_w)
            return val_l, val_c

        self._plate_c_long, self._plate_c_cross = _plate_row("Speed of Sound")
        self._plate_E_long, self._plate_E_cross = _plate_row("Young's Modulus (E)")

        # GLC (Shear) line — shown below Young's Modulus when FLC was measured
        self._plate_glc_widget = QtWidgets.QWidget()
        _glc_hl = QtWidgets.QHBoxLayout(self._plate_glc_widget)
        _glc_hl.setContentsMargins(0, 0, 0, 0)
        _glc_hl.setSpacing(4)
        self._plate_glc_lbl = QtWidgets.QLabel("GLC (Shear):")
        self._plate_glc_lbl.setFont(small_font)
        self._plate_glc_lbl.setStyleSheet("color: palette(shadow);")
        self._plate_glc_val = QtWidgets.QLabel("—")
        self._plate_glc_val.setFont(small_font)
        self._plate_glc_val.setStyleSheet("color: palette(shadow);")
        _glc_hl.addWidget(self._plate_glc_lbl)
        _glc_hl.addStretch()
        _glc_hl.addWidget(self._plate_glc_val)
        self._plate_glc_widget.setVisible(False)
        ps_vbox.addWidget(self._plate_glc_widget)

        # Specific modulus box for plate (two-column)
        _spec_frame_p = QtWidgets.QFrame()
        _spec_frame_p.setStyleSheet(
            "QFrame { background-color: palette(alternateBase); border-radius: 4px; }"
        )
        _sfp_vbox = QtWidgets.QVBoxLayout(_spec_frame_p)
        _sfp_vbox.setContentsMargins(6, 4, 6, 4)
        _sfp_vbox.setSpacing(2)
        _sfp_title = QtWidgets.QLabel("Specific Modulus (E/\u03c1)")
        _sfp_title.setFont(small_font)
        _sfp_vbox.addWidget(_sfp_title)

        _sfp_cols = QtWidgets.QHBoxLayout()

        # Longitudinal column
        _sfp_l_vbox = QtWidgets.QVBoxLayout()
        _sfp_l_cap = QtWidgets.QLabel("Longitudinal:")
        _sfp_l_cap.setFont(small_font)
        _sfp_l_cap.setStyleSheet("color: palette(shadow);")
        _sfp_l_vbox.addWidget(_sfp_l_cap)
        _sfp_l_row = QtWidgets.QHBoxLayout()
        self._plate_spec_long_value = QtWidgets.QLabel("—")
        self._plate_spec_long_value.setFont(_big_font)
        _sfp_l_unit = QtWidgets.QLabel("GPa/(g/cm\u00b3)")
        _sfp_l_unit.setFont(small_font)
        _sfp_l_unit.setStyleSheet("color: palette(shadow);")
        _sfp_l_row.addWidget(self._plate_spec_long_value)
        _sfp_l_row.addWidget(_sfp_l_unit)
        _sfp_l_row.addStretch()
        _sfp_l_vbox.addLayout(_sfp_l_row)
        self._plate_quality_long = QtWidgets.QLabel("—")
        self._plate_quality_long.setFont(small_font)
        _sfp_l_vbox.addWidget(self._plate_quality_long)
        _sfp_cols.addLayout(_sfp_l_vbox)

        # Cross-grain column
        _sfp_c_vbox = QtWidgets.QVBoxLayout()
        _sfp_c_cap = QtWidgets.QLabel("Cross-grain:")
        _sfp_c_cap.setFont(small_font)
        _sfp_c_cap.setStyleSheet("color: palette(shadow);")
        _sfp_c_vbox.addWidget(_sfp_c_cap)
        _sfp_c_row = QtWidgets.QHBoxLayout()
        self._plate_spec_cross_value = QtWidgets.QLabel("—")
        self._plate_spec_cross_value.setFont(_big_font)
        _sfp_c_unit = QtWidgets.QLabel("GPa/(g/cm\u00b3)")
        _sfp_c_unit.setFont(small_font)
        _sfp_c_unit.setStyleSheet("color: palette(shadow);")
        _sfp_c_row.addWidget(self._plate_spec_cross_value)
        _sfp_c_row.addWidget(_sfp_c_unit)
        _sfp_c_vbox.addLayout(_sfp_c_row)
        self._plate_quality_cross = QtWidgets.QLabel("—")
        self._plate_quality_cross.setFont(small_font)
        _sfp_c_vbox.addWidget(self._plate_quality_cross)
        _sfp_cols.addLayout(_sfp_c_vbox)

        _sfp_vbox.addLayout(_sfp_cols)
        ps_vbox.addWidget(_spec_frame_p)

        self._plate_rad_long, self._plate_rad_cross = _plate_row("Radiation Ratio (R):")

        def _ratio_row(label: str, hint: str) -> QtWidgets.QLabel:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(label))
            val = QtWidgets.QLabel("—")
            val.setFont(small_font)
            hint_lbl = QtWidgets.QLabel(hint)
            hint_lbl.setFont(small_font)
            hint_lbl.setStyleSheet("color: palette(shadow);")
            row.addStretch()
            row.addWidget(val)
            row.addWidget(hint_lbl)
            ps_vbox.addLayout(row)
            return val

        self._plate_cross_long = _ratio_row("Cross/Long ratio:", "(typical: 0.04–0.08)")
        self._plate_long_cross = _ratio_row("Long/Cross ratio:", "(typical: 12–25)")

        ps_vbox.addWidget(_hsep())

        _overall_row = QtWidgets.QHBoxLayout()
        _overall_lbl = QtWidgets.QLabel("Overall Quality:")
        _overall_lbl.setFont(small_font)
        _overall_lbl.setStyleSheet("font-weight: bold;")
        self._plate_overall_quality = QtWidgets.QLabel("—")
        self._plate_overall_quality.setFont(small_font)
        _overall_row.addWidget(_overall_lbl)
        _overall_row.addStretch()
        _overall_row.addWidget(self._plate_overall_quality)
        ps_vbox.addLayout(_overall_row)

        # ── Gore Target Thickness box ─────────────────────────────────────
        self._gore_frame = QtWidgets.QFrame()
        self._gore_frame.setObjectName("gore_frame")
        # Swift: Color.accentColor.opacity(0.08); system blue = #007AFF → alpha ~20/255
        self._gore_frame.setStyleSheet(
            "#gore_frame { background-color: rgba(0,122,255,20);"
            " border-radius: 8px; }"
        )
        _gf_vbox = QtWidgets.QVBoxLayout(self._gore_frame)
        _gf_vbox.setContentsMargins(8, 4, 8, 4)
        _gf_vbox.setSpacing(3)

        _gore_hdr_fnt = QtGui.QFont()
        _gore_hdr_fnt.setPointSize(small_font.pointSize())
        _gore_hdr_fnt.setBold(True)
        _gore_title_lbl = QtWidgets.QLabel("Gore Target Thickness")
        _gore_title_lbl.setFont(_gore_hdr_fnt)
        _gf_vbox.addWidget(_gore_title_lbl)

        _gore_val_row = QtWidgets.QHBoxLayout()
        _gore_val_row.setSpacing(6)
        self._gore_thickness_value = QtWidgets.QLabel("—")
        _gv_fnt = QtGui.QFont()
        _gv_fnt.setPointSize(32)
        _gv_fnt.setBold(True)
        self._gore_thickness_value.setFont(_gv_fnt)
        self._gore_thickness_value.setStyleSheet("color: #007AFF;")
        _gore_val_row.addWidget(self._gore_thickness_value)
        _gore_mm_lbl = QtWidgets.QLabel("mm")
        _gore_mm_fnt = QtGui.QFont()
        _gore_mm_fnt.setPointSize(small_font.pointSize() + 4)
        _gore_mm_lbl.setFont(_gore_mm_fnt)
        _gore_mm_lbl.setStyleSheet("color: palette(shadow);")
        _gore_val_row.addWidget(_gore_mm_lbl)
        _gore_val_row.addStretch()
        _gf_vbox.addLayout(_gore_val_row)

        # GLC known: "Shear Modulus (GLC):"  [spacer]  "X.XXX GPa"
        _gore_glc_row_w = QtWidgets.QWidget()
        _gore_glc_hl = QtWidgets.QHBoxLayout(_gore_glc_row_w)
        _gore_glc_hl.setContentsMargins(0, 0, 0, 0)
        _gore_glc_title = QtWidgets.QLabel("Shear Modulus (GLC):")
        _gore_glc_title.setFont(small_font)
        _gore_glc_title.setStyleSheet("color: palette(shadow);")
        self._gore_glc_value = QtWidgets.QLabel("—")
        self._gore_glc_value.setFont(small_font)
        _gore_glc_hl.addWidget(_gore_glc_title)
        _gore_glc_hl.addStretch()
        _gore_glc_hl.addWidget(self._gore_glc_value)
        _gore_glc_row_w.setVisible(False)
        _gf_vbox.addWidget(_gore_glc_row_w)
        self._gore_glc_row_w = _gore_glc_row_w

        # GLC not known: info message
        self._gore_glc_info = QtWidgets.QLabel()
        self._gore_glc_info.setFont(small_font)
        self._gore_glc_info.setStyleSheet("color: palette(shadow);")
        self._gore_glc_info.setWordWrap(True)
        _gf_vbox.addWidget(self._gore_glc_info)

        self._gore_params_lbl = QtWidgets.QLabel()
        _gp_fnt = QtGui.QFont()
        _gp_fnt.setPointSize(max(small_font.pointSize() - 1, 8))
        self._gore_params_lbl.setFont(_gp_fnt)
        self._gore_params_lbl.setStyleSheet("color: palette(shadow);")
        _gf_vbox.addWidget(self._gore_params_lbl)

        self._gore_frame.setVisible(False)
        ps_vbox.addWidget(self._gore_frame)

        ms_vbox.addWidget(self._plate_section)

        self._brace_section.setVisible(False)
        self._plate_section.setVisible(False)
        self._material_section.setVisible(False)

        # ── Wrap _material_peak_widget + _material_section in a scroll area ──
        _mat_container = QtWidgets.QWidget()
        _mat_vbox = QtWidgets.QVBoxLayout(_mat_container)
        _mat_vbox.setContentsMargins(0, 0, 0, 0)
        _mat_vbox.setSpacing(8)
        _mat_vbox.addWidget(self._material_peak_widget)
        _mat_vbox.addWidget(self._material_section)
        _mat_vbox.addStretch()

        self._material_scroll = QtWidgets.QScrollArea()
        self._material_scroll.setWidgetResizable(True)
        self._material_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._material_scroll.setWidget(_mat_container)
        self._material_scroll.setVisible(False)
        vbox.addWidget(self._material_scroll, stretch=1)

        # ── Footer separator (matches Swift's Divider between scroll area and footer) ──
        vbox.addWidget(_hsep())

        # ── Guitar compact summary (guitar only) — matches Swift guitarAnalysisSummary ──
        self._guitar_summary = QtWidgets.QFrame()
        self._guitar_summary.setObjectName("guitar_summary")
        self._guitar_summary.setStyleSheet(
            "#guitar_summary { background-color: palette(alternateBase); border-radius: 8px; }"
        )
        _gsum_hl = QtWidgets.QHBoxLayout(self._guitar_summary)
        _gsum_hl.setContentsMargins(8, 6, 8, 6)
        _gsum_hl.setSpacing(12)

        _tiny_font = QtGui.QFont()
        _tiny_font.setPointSize(max(small_font.pointSize() - 2, 8))
        _sum_bold = QtGui.QFont()
        _sum_bold.setPointSize(small_font.pointSize() + 1)
        _sum_bold.setBold(True)

        # Ring-out column
        _ro_col = QtWidgets.QVBoxLayout()
        _ro_col.setSpacing(2)
        _ro_cap = QtWidgets.QLabel("Ring-Out")
        _ro_cap.setFont(_tiny_font)
        _ro_cap.setStyleSheet("color: palette(shadow);")
        _ro_col.addWidget(_ro_cap)
        _ro_val_row = QtWidgets.QHBoxLayout()
        _ro_val_row.setSpacing(4)
        self._gs_ro_value = QtWidgets.QLabel("Waiting\u2026")
        self._gs_ro_value.setFont(_sum_bold)
        _ro_val_row.addWidget(self._gs_ro_value)
        self._gs_ro_quality = QtWidgets.QLabel("")
        self._gs_ro_quality.setFont(small_font)
        _ro_val_row.addWidget(self._gs_ro_quality)
        _ro_val_row.addStretch()
        _ro_col.addLayout(_ro_val_row)
        _ro_sub = QtWidgets.QLabel("\u201315 dB")
        _ro_sub.setFont(_tiny_font)
        _ro_sub.setStyleSheet("color: palette(shadow);")
        _ro_col.addWidget(_ro_sub)
        _gsum_hl.addLayout(_ro_col)

        # Vertical divider
        _vdiv = QtWidgets.QFrame()
        _vdiv.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        _vdiv.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        _gsum_hl.addWidget(_vdiv)

        # Tap ratio column (Top / Air)
        _ratio_col = QtWidgets.QVBoxLayout()
        _ratio_col.setSpacing(2)
        _ratio_cap = QtWidgets.QLabel("Tap Ratio")
        _ratio_cap.setFont(_tiny_font)
        _ratio_cap.setStyleSheet("color: palette(shadow);")
        _ratio_col.addWidget(_ratio_cap)
        _ratio_val_row = QtWidgets.QHBoxLayout()
        _ratio_val_row.setSpacing(4)
        self._gs_ratio_value = QtWidgets.QLabel("Need Air & Top")
        self._gs_ratio_value.setFont(_sum_bold)
        _ratio_val_row.addWidget(self._gs_ratio_value)
        self._gs_ratio_quality = QtWidgets.QLabel("")
        self._gs_ratio_quality.setFont(small_font)
        _ratio_val_row.addWidget(self._gs_ratio_quality)
        _ratio_val_row.addStretch()
        _ratio_col.addLayout(_ratio_val_row)
        _ratio_sub = QtWidgets.QLabel("Ideal: 1.9\u20132.1")
        _ratio_sub.setFont(_tiny_font)
        _ratio_sub.setStyleSheet("color: palette(shadow);")
        _ratio_col.addWidget(_ratio_sub)
        _gsum_hl.addLayout(_ratio_col)

        vbox.addWidget(self._guitar_summary)

        # ── Footer row: status indicator + export buttons ─────────────────────
        _footer_row = QtWidgets.QHBoxLayout()
        _footer_row.setContentsMargins(0, 4, 0, 0)
        _footer_row.setSpacing(6)

        self._results_status_dot = QtWidgets.QLabel("\u25cf")
        self._results_status_dot.setFont(small_font)
        self._results_status_dot.setStyleSheet("color: gray;")
        _footer_row.addWidget(self._results_status_dot)

        self._results_status_lbl = QtWidgets.QLabel("Stopped")
        self._results_status_lbl.setFont(small_font)
        self._results_status_lbl.setStyleSheet("color: gray;")
        _footer_row.addWidget(self._results_status_lbl)

        _footer_row.addStretch()

        self.export_spectrum_btn = QtWidgets.QPushButton("Export Spectrum")
        self.export_spectrum_btn.setEnabled(False)
        self.export_spectrum_btn.setToolTip("Export the current spectrum as a PNG image")
        _footer_row.addWidget(self.export_spectrum_btn)

        self.export_pdf_btn = QtWidgets.QPushButton("Export PDF Report")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.setToolTip("Export the current measurement to a PDF report")
        _footer_row.addWidget(self.export_pdf_btn)

        vbox.addLayout(_footer_row)

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
        """Bottom status bar matching the Swift fullStatusBar layout."""
        bar = QtWidgets.QWidget()
        bar.setObjectName("bottom_status_bar")
        bar.setStyleSheet("#bottom_status_bar { border-top: 1px solid palette(mid); }")

        vl = QtWidgets.QVBoxLayout(bar)
        vl.setContentsMargins(8, 3, 8, 3)
        vl.setSpacing(2)

        # ── Optional progress bar (shown when currentTapCount > 0) ──────
        self._sb_progress = QtWidgets.QProgressBar()
        self._sb_progress.setRange(0, 100)
        self._sb_progress.setFixedHeight(6)
        self._sb_progress.setTextVisible(False)
        self._sb_progress.setStyleSheet(
            "QProgressBar { border: none; border-radius: 3px;"
            " background: palette(mid); }"
            "QProgressBar::chunk { background: palette(highlight);"
            " border-radius: 3px; }"
        )
        self._sb_progress.setVisible(False)
        vl.addWidget(self._sb_progress)

        # ── Main row ──────────────────────────────────────────────────────
        hl = QtWidgets.QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

        small = QtGui.QFont()
        small.setPointSize(14)
        caption = QtGui.QFont()
        caption.setPointSize(12)

        # Hidden labels kept so existing call sites don't crash
        self.device_status_lbl = QtWidgets.QLabel()
        self.device_status_lbl.setVisible(False)
        self.cal_status = QtWidgets.QLabel()
        self.cal_status.setVisible(False)

        # Comparison mode row (hidden by default) — replaces tap state during comparison.
        # Left: "Comparing N measurements"   Right: "Press New Tap to exit comparison"
        self._sb_compare_wgt = QtWidgets.QWidget()
        _cmp_hl = QtWidgets.QHBoxLayout(self._sb_compare_wgt)
        _cmp_hl.setContentsMargins(0, 0, 0, 0)
        _cmp_hl.setSpacing(6)
        self._sb_compare_msg = QtWidgets.QLabel("Comparing 0 measurements")
        self._sb_compare_msg.setFont(small)
        _cmp_hl.addWidget(self._sb_compare_msg)
        _cmp_hl.addStretch(1)
        _cmp_exit = QtWidgets.QLabel("Press New Tap to exit comparison")
        _cmp_exit.setFont(small)
        _cmp_exit.setStyleSheet("color: gray;")
        _cmp_hl.addWidget(_cmp_exit)
        self._sb_compare_wgt.setVisible(False)
        hl.addWidget(self._sb_compare_wgt)

        # Normal tap state widgets (hidden while comparing)
        self._sb_normal_wgt = QtWidgets.QWidget()
        _norm_hl = QtWidgets.QHBoxLayout(self._sb_normal_wgt)
        _norm_hl.setContentsMargins(0, 0, 0, 0)
        _norm_hl.setSpacing(4)

        # Tap detection dot
        self._sb_tap_dot = QtWidgets.QLabel("●")
        self._sb_tap_dot.setFont(caption)
        self._sb_tap_dot.setStyleSheet("color: gray;")
        hl.addWidget(self._sb_tap_dot)

        # Tap message
        self._sb_tap_msg = QtWidgets.QLabel("Waiting for tap…")
        self._sb_tap_msg.setFont(small)
        self._sb_tap_msg.setStyleSheet("color: gray;")
        _norm_hl.addWidget(self._sb_tap_msg)

        # Bullet separator
        _b1 = QtWidgets.QLabel("•")
        _b1.setFont(caption)
        _b1.setStyleSheet("color: gray;")
        _norm_hl.addWidget(_b1)

        # Average magnitude
        self._sb_avg_lbl = QtWidgets.QLabel("-100.0 dB")
        self._sb_avg_lbl.setFont(small)
        self._sb_avg_lbl.setStyleSheet("color: gray;")
        _norm_hl.addWidget(self._sb_avg_lbl)

        _norm_hl.addStretch(1)

        # Frozen indicator (hidden by default)
        self._sb_frozen_wgt = QtWidgets.QWidget()
        frozen_hl = QtWidgets.QHBoxLayout(self._sb_frozen_wgt)
        frozen_hl.setContentsMargins(0, 0, 0, 0)
        frozen_hl.setSpacing(3)
        _frozen_icon = QtWidgets.QLabel("⏸")
        _frozen_icon.setFont(caption)
        _frozen_icon.setStyleSheet("color: orange;")
        frozen_hl.addWidget(_frozen_icon)
        _frozen_txt = QtWidgets.QLabel("Frozen")
        _frozen_txt.setFont(caption)
        _frozen_txt.setStyleSheet("color: orange;")
        frozen_hl.addWidget(_frozen_txt)
        _frozen_sep = QtWidgets.QLabel("•")
        _frozen_sep.setFont(caption)
        _frozen_sep.setStyleSheet("color: gray;")
        frozen_hl.addWidget(_frozen_sep)
        self._sb_frozen_wgt.setVisible(False)
        _norm_hl.addWidget(self._sb_frozen_wgt)

        # Peak info
        self._sb_peak_lbl = QtWidgets.QLabel("")
        self._sb_peak_lbl.setFont(caption)
        self._sb_peak_lbl.setStyleSheet("color: rgb(40,100,210);")
        _norm_hl.addWidget(self._sb_peak_lbl)

        # Detection state dot
        self._sb_detect_dot = QtWidgets.QLabel("●")
        self._sb_detect_dot.setFont(caption)
        self._sb_detect_dot.setStyleSheet("color: orange;")
        _norm_hl.addWidget(self._sb_detect_dot)

        # Status message
        self._sb_detect_msg = QtWidgets.QLabel("Stopped")
        self._sb_detect_msg.setFont(caption)
        self._sb_detect_msg.setStyleSheet("color: orange;")
        _norm_hl.addWidget(self._sb_detect_msg)

        # Tap count (hidden by default)
        self._sb_tap_count = QtWidgets.QLabel("")
        self._sb_tap_count.setFont(caption)
        self._sb_tap_count.setStyleSheet("color: rgb(40,100,210); font-weight: bold;")
        self._sb_tap_count.setVisible(False)
        _norm_hl.addWidget(self._sb_tap_count)

        # Plate/brace phase step indicator (hidden by default)
        self._sb_plate_step_lbl = QtWidgets.QLabel("")
        self._sb_plate_step_lbl.setFont(caption)
        self._sb_plate_step_lbl.setStyleSheet("color: rgb(40,100,210); font-weight: bold;")
        self._sb_plate_step_lbl.setVisible(False)
        _norm_hl.addWidget(self._sb_plate_step_lbl)

        hl.addWidget(self._sb_normal_wgt, stretch=1)

        # ── Loaded-settings warning banner (hidden by default) ────────────
        # Mirrors Swift showLoadedSettingsWarning — shown as an extra row
        # above the normal status row; the normal row stays unchanged.
        self._sb_warning_wgt = QtWidgets.QWidget()
        self._sb_warning_wgt.setObjectName("sb_warning_wgt")
        self._sb_warning_wgt.setStyleSheet(
            "#sb_warning_wgt { background: rgba(255,165,0,31);"
            " border-radius: 4px; }"
        )
        _warn_hl = QtWidgets.QHBoxLayout(self._sb_warning_wgt)
        _warn_hl.setContentsMargins(6, 2, 6, 2)
        _warn_hl.setSpacing(5)
        self._sb_warning_icon = QtWidgets.QLabel()
        _warn_pix = qta.icon("fa5s.exclamation-triangle", color="orange").pixmap(14, 14)
        self._sb_warning_icon.setPixmap(_warn_pix)
        self._sb_warning_icon.setFixedSize(14, 14)
        # Opacity effect drives the pulse animation (works on pixmap labels)
        self._warn_opacity_effect = QtWidgets.QGraphicsOpacityEffect(self._sb_warning_icon)
        self._warn_opacity_effect.setOpacity(1.0)
        self._sb_warning_icon.setGraphicsEffect(self._warn_opacity_effect)
        _warn_hl.addWidget(self._sb_warning_icon)
        self._sb_warning_msg = QtWidgets.QLabel("")
        self._sb_warning_msg.setFont(caption)
        self._sb_warning_msg.setStyleSheet("color: orange; font-weight: bold;")
        _warn_hl.addWidget(self._sb_warning_msg)
        _warn_hl.addStretch()
        self._sb_warning_wgt.setVisible(False)
        vl.addWidget(self._sb_warning_wgt)

        # Timer for pulsing the warning icon opacity (mirrors Swift warningIconOpacity animation:
        # easeInOut 0.6 s, repeating, autoreverses, range 0.2–1.0)
        import math as _math
        self._warn_pulse_timer = QtCore.QTimer(self)
        self._warn_pulse_timer.setInterval(50)   # 20 fps
        self._warn_pulse_t: float = 0.0
        def _pulse_tick() -> None:
            self._warn_pulse_t += 0.05 / 0.6     # advance phase; full period = 0.6 s
            opacity = 0.2 + 0.8 * (0.5 + 0.5 * _math.cos(_math.pi * self._warn_pulse_t))
            self._warn_opacity_effect.setOpacity(opacity)
        self._warn_pulse_timer.timeout.connect(_pulse_tick)

        vl.addLayout(hl)

        # Keep status_label as a no-op alias so old call sites don't crash
        self.status_label = self._sb_detect_msg

        return bar

    def _build_material_instr_panel(self) -> QtWidgets.QFrame:
        """Compact phase-instructions panel shown below the graph for plate/brace modes.

        Mirrors Swift's materialInstructionsView / decayTimeView.
        Visible only when measurement type is plate/brace; updates as PlateCapture
        state advances through IDLE → WAITING_L → WAITING_C → WAITING_FLC → COMPLETE.
        """
        frame = QtWidgets.QFrame()
        frame.setObjectName("material_instr_panel")
        frame.setStyleSheet(
            "#material_instr_panel { border-top: 1px solid palette(mid); }"
        )
        hl = QtWidgets.QHBoxLayout(frame)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.setSpacing(8)

        # Phase colour dot
        self._mip_dot = QtWidgets.QLabel()
        self._mip_dot.setFixedSize(10, 10)
        self._mip_dot.setStyleSheet(
            "QLabel { background-color: gray; border-radius: 5px; }"
        )
        hl.addWidget(self._mip_dot, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        # Title + body text (stacked)
        txt = QtWidgets.QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(1)

        _bold9 = QtGui.QFont()
        _bold9.setPointSize(9)
        _bold9.setBold(True)
        self._mip_title_lbl = QtWidgets.QLabel("Press New Tap to begin")
        self._mip_title_lbl.setFont(_bold9)
        txt.addWidget(self._mip_title_lbl)

        _sm9 = QtGui.QFont()
        _sm9.setPointSize(9)
        self._mip_body_lbl = QtWidgets.QLabel(
            "Press 'New Tap' to start the plate measurement."
        )
        self._mip_body_lbl.setFont(_sm9)
        self._mip_body_lbl.setStyleSheet("color: palette(shadow);")
        txt.addWidget(self._mip_body_lbl)

        hl.addLayout(txt, stretch=1)

        # Step counter on the right (e.g. "1/3", "2/3", "✓")
        _bold9r = QtGui.QFont()
        _bold9r.setPointSize(9)
        _bold9r.setBold(True)
        self._mip_step_lbl = QtWidgets.QLabel("")
        self._mip_step_lbl.setFont(_bold9r)
        self._mip_step_lbl.setStyleSheet("color: rgb(40,100,210);")
        self._mip_step_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        hl.addWidget(self._mip_step_lbl)

        frame.setVisible(False)  # Shown when plate/brace type is selected
        return frame

    def _show_metrics(self) -> None:
        """Non-modal dialog showing live FFT diagnostics."""
        if self._metrics_dialog and self._metrics_dialog.isVisible():
            self._metrics_dialog.raise_()
            self._metrics_dialog.activateWindow()
            return

        wl          = 4 * 16384
        sr          = self.fft_canvas.fft_data.sample_freq
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
        mono_font.setFamily("Courier New")
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

        # Canvas viewport pan/zoom → update spinboxes + persist
        canvas.freqRangeChanged.connect(self._on_canvas_freq_range_changed)

        # Auto dB
        self.auto_db_btn.toggled.connect(canvas.set_auto_scale)
        self.auto_db_btn.toggled.connect(self._on_auto_db_toggled)

        # Annotations cycling button
        self.annotations_btn.clicked.connect(self._on_cycle_annotation_mode)

        # Select / deselect / reset-auto all peaks
        self.select_all_btn.clicked.connect(self._on_select_all_peaks)
        self.deselect_all_btn.clicked.connect(self._on_deselect_all_peaks)
        self.reset_auto_selection_btn.clicked.connect(self._on_reset_auto_selection)
        self.peak_widget.model.userModifiedSelectionChanged.connect(
            self._on_user_modified_selection_changed
        )

        # Guitar type
        self.guitar_type_combo.currentTextChanged.connect(self._on_guitar_type_changed)

        # Measurement type + plate dialog
        self.measurement_type_combo.currentTextChanged.connect(
            self._on_measurement_type_changed
        )
        canvas.plateStatusChanged.connect(self._on_plate_status_changed)
        canvas.plateAnalysisComplete.connect(self._on_plate_analysis_complete)

        # Peaks table ← canvas
        canvas.peaksChanged.connect(self.peak_widget.update_data)
        canvas.peaksChanged.connect(self._on_peaks_changed_ratios)
        canvas.peaksChanged.connect(self._material_peak_widget.update_peaks)
        self._material_peak_widget.assignmentChanged.connect(
            self._on_material_assignment_changed
        )
        canvas.peakSelected.connect(self.peak_widget.select_row)
        canvas.peakDeselected.connect(self.peak_widget.clear_selection)
        canvas.averagesChanged.connect(self.set_avg_completed)
        canvas.framerateUpdate.connect(self._on_framerate_update)
        canvas.levelChanged.connect(self._on_level_changed)
        canvas.peakInfoChanged.connect(self._on_peak_info)
        canvas.newSample.connect(self.peak_widget.new_data)
        canvas.annotations.restoreFocus.connect(self.peak_widget.restore_focus)
        canvas.comparisonChanged.connect(self._on_comparison_changed)

        # Peaks table → canvas annotations
        model = self.peak_widget.model
        model.annotationUpdate.connect(canvas.annotations.update_annotation)
        model.clearAnnotations.connect(canvas.annotations.clear_annotations)
        model.showAnnotation.connect(canvas.annotations.show_annotation)
        model.hideAnnotation.connect(canvas.annotations.hide_annotation)
        model.hideAnnotations.connect(canvas.annotations.hide_annotations)
        model.modeColorsChanged.connect(canvas.update_mode_colors)

        self.peak_widget.clearPeaks.connect(canvas.clear_selected_peak)
        self.peak_widget.clearPeaks.connect(self.peak_widget.clear_selected_peak)
        self.peak_widget.peakSelected.connect(self._on_peak_selected)
        self.peak_widget.peakDeselected.connect(self._on_peak_deselected)

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
        self.tap_num_spin.valueChanged.connect(self._on_tap_num_changed)

    def _init_state(self, f_range: dict[str, int]) -> None:
        """Restore saved values and initialise display state."""
        canvas = self.fft_canvas

        saved_gt = AS.AppSettings.guitar_type()
        self.guitar_type_combo.setCurrentText(saved_gt)
        self.peak_widget.model.set_guitar_type(saved_gt)
        canvas.set_guitar_type_bands(saved_gt)
        self._update_measurement_badge()
        self.reset_auto_selection_btn.setVisible(self._current_mt().is_guitar)

        self.set_measurement_complete(False)

        # Restore calibration status label and device name in status bar
        device_name = canvas.current_calibration_device() or AS.AppSettings.device_name()
        if device_name:
            self.device_status_lbl.setText(device_name)
            _cal = _mc_mod.CalibrationStorage.calibration_for_device(device_name)
            self.set_calibration_status(_cal.name if _cal else "")

        self._start_analyzer()

    # ================================================================
    # State update methods (formerly in PeakControls)
    # ================================================================

    def set_running(self, running: bool) -> None:
        if running:
            self._sb_detect_dot.setStyleSheet("color: green;")
            self._sb_detect_msg.setText("Listening for tap…")
            self._sb_detect_msg.setStyleSheet("")
        else:
            self._sb_detect_dot.setStyleSheet("color: orange;")
            self._sb_detect_msg.setText("Stopped")
            self._sb_detect_msg.setStyleSheet("color: orange;")
            self._is_paused = False
        self._update_tap_buttons()

    def set_tap_count(self, captured: int, total: int) -> None:
        self._tap_count_captured = captured
        self._tap_count_total = total
        # Only show count/progress while actively detecting — mirrors Swift `isDetecting && currentTapCount > 0`
        show = captured > 0 and not self._is_measurement_complete
        if show:
            pct = int(min(captured, total) * 100 / max(total, 1))  # clamp — mirrors Swift min(1.0, ...)
            self._sb_progress.setValue(pct)
            self._sb_tap_count.setText(f"{captured}/{total}")
        self._sb_progress.setVisible(show)
        self._sb_tap_count.setVisible(show)
        self._update_tap_buttons()

    def set_ring_out(self, time_s: float) -> None:
        self._gs_ro_value.setText(f"{time_s:.2f}s")
        quality, color = self._decay_quality(time_s)
        self._gs_ro_quality.setText(quality)
        self._gs_ro_quality.setStyleSheet(f"color: {color};")

    def set_calibration_status(self, name: str) -> None:
        if name:
            self.cal_status.setText(f"Cal: {name}")
        else:
            self.cal_status.setText("Calibration: none")

    def _on_level_changed(self, amp: int) -> None:
        # Plate/brace mode: show RMS input level gated to FFT frame rate —
        # mirrors Swift fft.displayLevelDB used when !measurementType.isGuitar
        if self._is_running and not self._current_mt().is_guitar:
            self._sb_avg_lbl.setText(f"{amp - 100.0:.1f} dB")

    def _on_peak_info(self, peak_hz: float, peak_db: float) -> None:
        if self._is_running:
            # Guitar mode: show FFT peak magnitude — mirrors Swift fft.peakMagnitude
            # Plate/brace: _sb_avg_lbl is updated in _on_level_changed (displayLevelDB)
            if self._current_mt().is_guitar:
                self._sb_avg_lbl.setText(f"{peak_db:.1f} dB")
            self._sb_peak_lbl.setText(f"Peak: {peak_db:.1f} dB @ {peak_hz:.1f} Hz")

    def _sb_update_frozen_state(self, frozen: bool) -> None:
        if frozen:
            self._sb_tap_dot.setStyleSheet("color: green;")
            self._sb_tap_msg.setText("Tap Detected!")
            self._sb_tap_msg.setStyleSheet("color: green;")
        else:
            self._sb_tap_dot.setStyleSheet("color: rgba(128,128,128,77);")
            self._sb_tap_msg.setText("Waiting for tap…")
            self._sb_tap_msg.setStyleSheet("color: gray;")

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
            self._results_status_dot.setStyleSheet("color: green;")
            self._results_status_lbl.setStyleSheet("color: palette(text);")
            self._results_status_lbl.setText("Analyzing")
        else:
            self._metrics_status_dot.setStyleSheet("color: gray")
            self._metrics_status_lbl.setText("Stopped")
            self._results_status_dot.setStyleSheet("color: gray;")
            self._results_status_lbl.setStyleSheet("color: gray;")
            self._results_status_lbl.setText("Stopped")

    def update_tap_tone_ratios(self, mode_freqs: dict[str, float]) -> None:
        helm = mode_freqs.get("Air (Helmholtz)")
        top  = mode_freqs.get("Top")
        if top and helm and helm > 0:
            ratio = top / helm
            quality, color = self._tap_ratio_quality(ratio)
            self._gs_ratio_value.setText(f"{ratio:.2f}:1")
            self._gs_ratio_quality.setText(quality)
            self._gs_ratio_quality.setStyleSheet(f"color: {color};")
        else:
            self._gs_ratio_value.setText("Need Air & Top")
            self._gs_ratio_quality.setText("")

    @staticmethod
    def _tap_ratio_quality(ratio: float) -> tuple[str, str]:
        """Return (label, hex-color) for a Top/Air tap-tone ratio. Mirrors Swift."""
        if ratio < 1.7:
            return "Low",          "#F44336"
        if ratio < 1.9:
            return "Below Target", "#FF9800"
        if ratio <= 2.1:
            return "Ideal",        "#4CAF50"
        if ratio < 2.3:
            return "Above Target", "#FF9800"
        return "High",             "#F44336"

    def _decay_quality(self, time_s: float) -> tuple[str, str]:
        """Return (label, hex-color) for a ring-out time. Mirrors Swift decayQuality."""
        gt_text = self.guitar_type_combo.currentText() if hasattr(self, "guitar_type_combo") else ""
        if "Classical" in gt_text:
            vs, sh, mo, go = 0.15, 0.35, 0.60, 1.0
        elif "Flamenco" in gt_text:
            vs, sh, mo, go = 0.08, 0.20, 0.35, 0.55
        else:                         # acoustic / default
            vs, sh, mo, go = 0.10, 0.25, 0.45, 0.70
        if time_s < vs: return "Very Short", "#9E9E9E"
        if time_s < sh: return "Short",      "#FF9800"
        if time_s < mo: return "Moderate",   "#FFC107"
        if time_s < go: return "Good",       "#4CAF50"
        return "Excellent",                  "#2196F3"

    def set_avg_enable(self, state: bool) -> None:
        self.fft_canvas.set_avg_enable(state)
        if state:
            self.avg_enable.setIcon(gt_i.GtImages.green_button_icon() or QtGui.QIcon())
            self.avg_restart.setEnabled(True)
        else:
            self.avg_enable.setIcon(gt_i.GtImages.red_button_icon() or QtGui.QIcon())
            self.avg_restart.setEnabled(False)

    def set_measurement_complete(self, checked: bool) -> None:
        self._is_measurement_complete = checked
        self.fft_canvas.set_measurement_complete(checked)
        if not checked:
            self.fft_canvas.set_loaded_measurement_name(None)
        else:
            # Successful capture — clear loaded-settings warning (matches Swift isMeasurementComplete.didSet)
            self._clear_loaded_settings_warning()
        self.peak_widget.data_held(checked)
        mt = self._current_mt()
        if not mt.is_guitar:
            self._material_section.setVisible(checked)
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
            self.reset_auto_selection_btn.setEnabled(
                self.peak_widget.model.user_has_modified_peak_selection
            )
        else:
            self.avg_enable.setEnabled(True)
            self.save_measurement_btn.setEnabled(False)
            self.export_spectrum_btn.setEnabled(False)
            self.export_pdf_btn.setEnabled(False)
            self.select_all_btn.setEnabled(False)
            self.deselect_all_btn.setEnabled(False)
            self.reset_auto_selection_btn.setEnabled(False)
            # Reset guitar summary to waiting state
            self._gs_ro_value.setText("Waiting\u2026")
            self._gs_ro_quality.setText("")
            self._gs_ratio_value.setText("Need Air & Top")
            self._gs_ratio_quality.setText("")
        self._sb_frozen_wgt.setVisible(checked)
        self._sb_update_frozen_state(checked)
        self._update_tap_buttons()

    def reset_averaging(self) -> None:
        self.fft_canvas.reset_averaging()
        self.set_avg_completed(0)
        _px = gt_i.GtImages.red_pixmap()
        if _px is not None:
            self.avg_done.setPixmap(_px)
        if self._is_measurement_complete:
            self.set_measurement_complete(False)

    def set_avg_completed(self, count: int) -> None:
        self.avg_completed.setText(str(count))
        if count >= self.num_averages.value():
            _px = gt_i.GtImages.green_pixmap()
            if _px is not None:
                self.avg_done.setPixmap(_px)
            self.num_averages.setEnabled(True)
            self.set_measurement_complete(True)
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

    def _on_canvas_freq_range_changed(self, fmin: int, fmax: int) -> None:
        """Update the 'Showing X – Y Hz' label when the graph is panned or zoomed."""
        self.freq_range_label.setText(f"Showing {fmin} – {fmax} Hz")

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

    def _clear_loaded_settings_warning(self) -> None:
        """Hide the loaded-settings warning banner — mirrors Swift showLoadedSettingsWarning = false."""
        self._show_loaded_settings_warning = False
        self._warn_pulse_timer.stop()
        self._warn_opacity_effect.setOpacity(1.0)
        self._sb_warning_wgt.setVisible(False)

    def _on_tap_threshold_changed(self, db_val: int) -> None:
        self.fft_canvas.set_tap_threshold(db_val + 100)
        AS.AppSettings.set_tap_threshold(db_val + 100)
        self.tap_threshold_readout.setText(f"{db_val} dB")
        # Clear loaded-settings warning when user manually changes threshold
        # (mirrors Swift tapDetectionThreshold.didSet)
        if self._loaded_tap_threshold is not None and db_val != self._loaded_tap_threshold:
            self._clear_loaded_settings_warning()

    def _on_tap_num_changed(self, n: int) -> None:
        self.fft_canvas.set_tap_num(n)
        # Clear loaded-settings warning when user manually changes tap count
        # (mirrors Swift numberOfTaps.didSet)
        if self._loaded_tap_num is not None and n != self._loaded_tap_num:
            self._clear_loaded_settings_warning()

    # ================================================================
    # Tap button state
    # ================================================================

    def _update_tap_buttons(self) -> None:
        """Refresh enabled/disabled state of New Tap, Pause, and Cancel buttons."""
        tap_num = self.tap_num_spin.value()
        is_plate = not self._current_mt().is_guitar
        is_detecting = self._is_running and not self._is_measurement_complete

        # New Tap: enabled when frozen, OR when comparing (mirrors Swift: .disabled(
        # tap.comparisonSpectra.isEmpty && (!fft.isRunning || !tap.isReadyForDetection
        # || tap.isDetecting)) — comparison always unlocks the button so the user can
        # start a fresh tap while viewing the overlay).
        is_comparing = self.fft_canvas.is_comparing
        self.new_tap_btn.setEnabled(
            self._is_running and (self._is_measurement_complete or is_comparing)
        )

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
        if not self._current_mt().is_guitar:
            return
        if not self._is_measurement_complete:
            self.set_measurement_complete(True)
            try:
                guitar_type = GT.GuitarType(self.guitar_type_combo.currentText())
                self.peak_widget.model.auto_select_peaks_by_mode(guitar_type)
            except Exception:
                pass
        n_peaks = len(self.fft_canvas.saved_peaks)
        n_taps = max(self._tap_count_captured, 1)
        msg = (
            f"Analysis complete! {n_peaks} peaks identified"
            f" (from {n_taps} averaged tap{'s' if n_taps != 1 else ''})."
        )
        self._sb_detect_msg.setText(msg)
        self._sb_detect_msg.setStyleSheet("color: orange;")
        self._sb_detect_dot.setStyleSheet("color: orange;")

    def _on_new_tap(self) -> None:
        """Begin a new tap sequence, clearing any in-progress accumulated spectra."""
        # Exit comparison mode first — required when _is_measurement_complete is False
        # (e.g. user entered comparison from live-detecting state) since the
        # set_measurement_complete(False) path below would be skipped entirely.
        if self.fft_canvas.is_comparing:
            self.fft_canvas.clear_comparison()
        if self._is_measurement_complete:
            self.set_measurement_complete(False)
        self._is_paused = False
        # cancel_tap_sequence clears accumulated spectra and restarts warmup,
        # matching Swift's cancelTapSequence behaviour.
        self.fft_canvas.cancel_tap_sequence()
        self._tap_count_captured = 0
        self._sb_tap_count.setVisible(False)
        self._sb_progress.setVisible(False)
        self._sb_detect_msg.setText("Listening for tap…")
        self._sb_detect_msg.setStyleSheet("")
        # For plate/brace measurements, automatically arm the capture state machine.
        mt = self._current_mt()
        if not mt.is_guitar:
            self.fft_canvas.start_plate_analysis()

    def _on_ring_out_measured(self, time_s: float) -> None:
        self._ring_out_s = time_s

    # ================================================================
    # Peak select / deselect all
    # ================================================================

    def _on_select_all_peaks(self) -> None:
        self.peak_widget.model.select_all_peaks()

    def _on_deselect_all_peaks(self) -> None:
        self.peak_widget.model.deselect_all_peaks()

    def _on_reset_auto_selection(self) -> None:
        # Swift Fix 3: do NOT clear _loaded_measurement_peaks here.
        # Clearing it would cause subsequent threshold slider moves to switch to
        # spectrum re-analysis, losing peaks that only exist in the saved data.
        # The loaded peaks remain authoritative for the lifetime of the loaded
        # measurement — only unfreezing (returning to live capture) clears them.
        try:
            guitar_type = GT.GuitarType(self.guitar_type_combo.currentText())
            self.peak_widget.model.auto_select_peaks_by_mode(guitar_type)
        except Exception:
            pass

    def _on_user_modified_selection_changed(self, modified: bool) -> None:
        self.reset_auto_selection_btn.setEnabled(
            modified and self._is_measurement_complete
        )

    # ================================================================
    # Guitar type
    # ================================================================

    def _current_mt(self) -> MT.MeasurementType:
        """Return the MeasurementType that reflects both UI combos."""
        return MT.MeasurementType.from_combo_values(
            self.measurement_type_combo.currentText(),
            self.guitar_type_combo.currentText(),
        )

    def _on_guitar_type_changed(self, guitar_type: str) -> None:
        AS.AppSettings.set_guitar_type(guitar_type)
        self.peak_widget.model.set_guitar_type(guitar_type)
        self.fft_canvas.set_guitar_type_bands(guitar_type)
        self._update_measurement_badge()

    # ================================================================
    # Peaks / ratios
    # ================================================================

    def _on_peaks_changed_ratios(self, peaks: object) -> None:
        import numpy as np
        if not isinstance(peaks, np.ndarray) or peaks.ndim != 2 or peaks.shape[0] == 0:
            return
        guitar_type_str = self.guitar_type_combo.currentText()
        try:
            guitar_type = GT.GuitarType(guitar_type_str)
        except ValueError:
            return
        peaks_data = [(float(row[0]), float(row[1])) for row in peaks]
        idx_map = GM.GuitarMode.classify_all(peaks_data, guitar_type)
        mode_freqs: dict[str, float] = {}
        for i, mode in idx_map.items():
            if mode is not GM.GuitarMode.UNKNOWN:
                mode_val = mode.value
                if mode_val not in mode_freqs:
                    mode_freqs[mode_val] = peaks_data[i][0]
        self.update_tap_tone_ratios(mode_freqs)

    def _on_peak_selected(self, freq: float) -> None:
        self.fft_canvas.select_peak(freq)
        self.peak_widget.selected_freq = freq
        idx = self.peak_widget.model.freq_index(freq)
        self.peak_widget.selected_freq_index = int(idx) if idx >= 0 else -1

    def _on_peak_deselected(self, freq: float) -> None:
        self.fft_canvas.deselect_peak(freq)

    # ================================================================
    # Measurement type / plate analysis
    # ================================================================

    def _on_measurement_type_changed(self, _: str) -> None:
        mt = self._current_mt()
        self.fft_canvas.set_measurement_type(mt)
        self.reset_auto_selection_btn.setVisible(mt.is_guitar)
        self.threshold_slider.setEnabled(mt.is_guitar)
        self.peak_min_readout.setEnabled(mt.is_guitar)
        self._guitar_summary.setVisible(mt.is_guitar)
        self._material_section.setVisible(not mt.is_guitar and self._is_measurement_complete)
        # Toggle peak list: guitar → PeakListWidget; plate/brace → MaterialPeakListWidget
        self.peak_widget.setVisible(mt.is_guitar)
        self._material_scroll.setVisible(not mt.is_guitar)
        self._material_instr_panel.setVisible(not mt.is_guitar)
        if not mt.is_guitar:
            show_flc = (not mt.is_brace) and AS.AppSettings.measure_flc()
            self._material_peak_widget.set_mode(
                show_cross=not mt.is_brace,
                show_flc=show_flc,
            )
            self._mat_title.setText(
                "Brace Properties" if mt.is_brace else "Plate Properties"
            )
            self._update_plate_phase_ui()   # Reset panel to IDLE state for new type
        self._update_measurement_badge()

    def _on_material_assignment_changed(
        self, long_freq: float, cross_freq: float, flc_freq: float
    ) -> None:
        """Called when the user reassigns L/C/FLC buttons in the material peak list.

        Updates model.modes (so annotations and _collect_measurement stay correct)
        and recomputes/displays the material properties.
        """
        peak_model = self.peak_widget.model
        mt = self._current_mt()

        # Rebuild model.modes for plate/brace labels
        for freq in list(peak_model.modes.keys()):
            if peak_model.modes.get(freq) in ("Longitudinal", "Cross-grain", "FLC", "Peak"):
                del peak_model.modes[freq]

        peaks = self.fft_canvas.saved_peaks
        if peaks.ndim == 2 and peaks.shape[0] > 0:
            for f in peaks[:, 0]:
                ff = float(f)
                if long_freq  > 0 and abs(ff - long_freq)  < 0.5:
                    peak_model.modes[ff] = "Longitudinal"
                elif cross_freq > 0 and abs(ff - cross_freq) < 0.5:
                    peak_model.modes[ff] = "Cross-grain"
                elif flc_freq   > 0 and abs(ff - flc_freq)  < 0.5:
                    peak_model.modes[ff] = "FLC"
                else:
                    peak_model.modes[ff] = "Peak"
            peak_model.show_all_annotations()

        # Show/hide placeholder vs content and recalculate
        dims = self._get_current_dims()
        if dims and dims.is_valid() and long_freq > 0:
            try:
                if mt.is_brace:
                    self._populate_brace_section(
                        PA.calculate_brace_properties(dims, long_freq)
                    )
                elif cross_freq > 0:
                    _glc = (PA.calculate_glc_from_flc(dims, flc_freq)
                            if flc_freq > 0 else None)
                    self._populate_plate_section(
                        PA.calculate_plate_properties(dims, long_freq, cross_freq),
                        flc_freq=flc_freq,
                        glc_pa=_glc if _glc else None,
                    )
                else:
                    # L assigned but C not yet — show partial placeholder
                    self._plate_content.setVisible(False)
                    self._plate_placeholder.setVisible(True)
                    self._plate_placeholder_lbl.setText("Select a cross-grain (C) peak")
            except ValueError:
                pass
        else:
            # No valid assignment — show placeholder
            if mt.is_brace:
                self._brace_content.setVisible(False)
                self._brace_placeholder.setVisible(True)
            else:
                self._plate_content.setVisible(False)
                self._plate_placeholder.setVisible(True)
                self._plate_placeholder_lbl.setText(
                    "Select a longitudinal (L) peak"
                    if long_freq == 0 else "Select a cross-grain (C) peak"
                )

    def _update_measurement_badge(self) -> None:
        """Refresh the badge in the Analysis Results panel.

        Shows 'Comparison' with a purple tint in comparison mode (mirrors
        analyzer.displayMode == .comparison check in TapAnalysisResultsView.swift),
        otherwise shows the measurement type short name with blue/orange tint.
        """
        if self.fft_canvas.display_mode == DisplayMode.COMPARISON:
            self.measurement_type_badge.setText("Comparison")
            self.measurement_type_badge.setStyleSheet(
                "background: rgba(160,32,240,0.20); border-radius: 4px; padding: 1px 6px;"
            )
            return
        mt = MT.MeasurementType.from_combo_values(
            self.measurement_type_combo.currentText(),
            self.guitar_type_combo.currentText(),
        )
        self.measurement_type_badge.setText(mt.short_name)
        self.measurement_type_badge.setStyleSheet(
            "background: rgba(0,100,255,0.15); border-radius: 4px; padding: 1px 6px;"
            if mt.is_guitar else
            "background: rgba(255,140,0,0.20); border-radius: 4px; padding: 1px 6px;"
        )

    def _on_plate_status_changed(self, status: str) -> None:
        """Update instructions panel and status bar for plate/brace capture progress."""
        self._update_plate_phase_ui(status)

    def _update_plate_phase_ui(self, status: str = "") -> None:
        """Sync the material instructions panel and status bar to the current PlateCapture state.

        Called on every PlateCapture.stateChanged emission and on measurement type change.
        """
        mt = self._current_mt()
        pc = self.fft_canvas.plate_capture
        state = pc.state
        State = type(pc).State

        is_brace = mt.is_brace
        measure_flc = (not is_brace) and AS.AppSettings.measure_flc()
        total = 1 if is_brace else (3 if measure_flc else 2)

        # ── Instructions panel ──────────────────────────────────────────
        if state == State.IDLE:
            self._mip_dot.setStyleSheet(
                "QLabel { background-color: gray; border-radius: 5px; }"
            )
            self._mip_title_lbl.setText("Press New Tap to begin")
            self._mip_body_lbl.setText(
                f"Press \u2018New Tap\u2019 to start the "
                f"{'one' if is_brace else ('two' if not measure_flc else 'three')}"
                f"-tap {'brace' if is_brace else 'plate'} measurement."
            )
            self._mip_step_lbl.setText("")
            self._sb_plate_step_lbl.setVisible(False)

        elif state == State.WAITING_L:
            self._mip_dot.setStyleSheet(
                "QLabel { background-color: #1976D2; border-radius: 5px; }"
            )
            self._mip_title_lbl.setText("Step 1: Longitudinal (L)")
            self._mip_body_lbl.setText(
                "Hold brace at 22% from one end along the length. Tap center."
                if is_brace else
                "Hold plate at 22% from one end along the length, near one long edge. Tap center."
            )
            self._mip_step_lbl.setText(f"1/{total}")
            self._sb_plate_step_lbl.setText(f"Step\u00a01/{total}")
            self._sb_plate_step_lbl.setVisible(True)

        elif state == State.WAITING_C:
            self._mip_dot.setStyleSheet(
                "QLabel { background-color: #E65100; border-radius: 5px; }"
            )
            self._mip_title_lbl.setText("Step 2: Cross-grain (C)")
            self._mip_body_lbl.setText(
                "Rotate 90\u00b0. Hold plate at 22% from one end along the width, "
                "near one short edge. Tap center."
            )
            self._mip_step_lbl.setText(f"2/{total}")
            self._sb_plate_step_lbl.setText(f"Step\u00a02/{total}")
            self._sb_plate_step_lbl.setVisible(True)

        elif state == State.WAITING_FLC:
            self._mip_dot.setStyleSheet(
                "QLabel { background-color: #7B1FA2; border-radius: 5px; }"
            )
            self._mip_title_lbl.setText("Step 3: FLC (Diagonal)")
            self._mip_body_lbl.setText(
                "Hold plate at the midpoint of one long edge. "
                "Tap near the opposite corner (~22% from both end and side)."
            )
            self._mip_step_lbl.setText(f"3/{total}")
            self._sb_plate_step_lbl.setText(f"Step\u00a03/{total}")
            self._sb_plate_step_lbl.setVisible(True)

        else:  # COMPLETE
            self._mip_dot.setStyleSheet(
                "QLabel { background-color: #388E3C; border-radius: 5px; }"
            )
            self._mip_title_lbl.setText("Measurement Complete")
            self._mip_body_lbl.setText(
                "All modes captured. Review the peak selections in the results panel."
            )
            self._mip_step_lbl.setText("\u2713")
            self._sb_plate_step_lbl.setVisible(False)

        # ── Status bar detect message (left side) ───────────────────────
        if status:
            self._sb_detect_msg.setText(status)
            self._sb_detect_msg.setStyleSheet("")

    def _on_plate_analysis_complete(self, f_long: float, f_cross: float, f_flc: float) -> None:
        """Auto-compute material properties and display in results panel."""
        mt = self._current_mt()
        dims = self._get_current_dims()
        if dims is None or not dims.is_valid():
            QtWidgets.QMessageBox.warning(
                self, "Missing Dimensions",
                "Plate/brace dimensions are required.\n"
                "Please enter them in Settings → Measurement Type.",
            )
            return
        # Assign material mode labels to peaks; find actual snapped frequencies
        peak_model = self.peak_widget.model
        peaks = self.fft_canvas.saved_peaks
        actual_long = 0.0
        actual_cross = 0.0
        actual_flc = 0.0
        if len(peaks) > 0:
            freqs = peaks[:, 0]
            modes: dict[float, str] = {}
            used: set[int] = set()
            if f_long > 0:
                idx = int(np.argmin(np.abs(freqs - f_long)))
                used.add(idx)
                actual_long = float(freqs[idx])
                modes[actual_long] = "Longitudinal"
            if f_cross > 0 and not mt.is_brace:
                dists = np.abs(freqs - f_cross).copy()
                for i in used:
                    dists[i] = np.inf
                idx = int(np.argmin(dists))
                used.add(idx)
                actual_cross = float(freqs[idx])
                modes[actual_cross] = "Cross-grain"
            if f_flc > 0 and not mt.is_brace:
                dists = np.abs(freqs - f_flc).copy()
                for i in used:
                    dists[i] = np.inf
                idx = int(np.argmin(dists))
                used.add(idx)
                actual_flc = float(freqs[idx])
                modes[actual_flc] = "FLC"
            for i, f in enumerate(freqs):
                if i not in used:
                    modes[float(f)] = "Peak"
            peak_model.modes = modes

        # Update material peak widget with auto-assigned frequencies
        self._material_peak_widget.set_assignment(actual_long, actual_cross,
                                                   flc_freq=actual_flc)

        try:
            if mt.is_brace:
                self._populate_brace_section(PA.calculate_brace_properties(dims, f_long))
            else:
                glc_pa = PA.calculate_glc_from_flc(dims, actual_flc) if actual_flc > 0 else None
                self._populate_plate_section(
                    PA.calculate_plate_properties(dims, f_long, f_cross),
                    flc_freq=actual_flc,
                    glc_pa=glc_pa,
                )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Calculation Error", str(exc))
            return

        self.set_measurement_complete(True)
        peak_model.show_all_annotations()


    def _populate_brace_section(self, props: PA.BraceProperties) -> None:
        """Fill the brace material properties sub-section and make it visible."""
        self._brace_subtitle.setText(f"Longitudinal (fL): {props.f_long:.1f} Hz")
        self._brace_c_long.setText(f"{props.c_long_m_s:.0f} m/s")
        self._brace_E_long.setText(f"{props.E_long_GPa:.2f} GPa")
        color = PA.QUALITY_COLORS.get(props.quality, "#888888")
        self._brace_spec_value.setText(f"{props.specific_modulus:.1f}")
        self._brace_spec_value.setStyleSheet(f"color: {color};")
        self._brace_quality_lbl.setText(props.quality)
        self._brace_quality_lbl.setStyleSheet(f"color: {color};")
        self._brace_rad_ratio.setText(f"{props.radiation_ratio:.1f}")
        self._brace_placeholder.setVisible(False)
        self._brace_content.setVisible(True)
        self._brace_section.setVisible(True)
        self._plate_section.setVisible(False)
        self._material_section.setVisible(True)

    def _populate_plate_section(self, props: PA.PlateProperties,
                                flc_freq: float = 0.0,
                                glc_pa: float | None = None) -> None:
        """Fill the plate material properties sub-section and make it visible."""
        # Frequencies — one per line
        self._plate_fl_lbl.setText(f"fL (Longitudinal): {props.f_long:.1f} Hz")
        self._plate_fc_lbl.setText(f"fC (Cross-grain): {props.f_cross:.1f} Hz")
        if flc_freq > 0:
            self._plate_flc_lbl.setText(f"fLC (Diagonal): {flc_freq:.1f} Hz")
            self._plate_flc_lbl.setVisible(True)
        else:
            self._plate_flc_lbl.setVisible(False)
        # Properties (title + L: val  C: val format)
        self._plate_c_long.setText(f"L: {props.c_long_m_s:.0f} m/s")
        self._plate_c_cross.setText(f"C: {props.c_cross_m_s:.0f} m/s")
        self._plate_E_long.setText(f"L: {props.E_long_GPa:.2f} GPa")
        self._plate_E_cross.setText(f"C: {props.E_cross_GPa:.2f} GPa")
        if glc_pa and glc_pa > 0:
            self._plate_glc_val.setText(f"{glc_pa / 1e9:.3f} GPa")
            self._plate_glc_widget.setVisible(True)
        else:
            self._plate_glc_widget.setVisible(False)
        cl = PA.QUALITY_COLORS.get(props.quality_long, "#888888")
        cc = PA.QUALITY_COLORS.get(props.quality_cross, "#888888")
        self._plate_spec_long_value.setText(f"{props.specific_modulus_long:.1f}")
        self._plate_spec_long_value.setStyleSheet(f"color: {cl};")
        self._plate_quality_long.setText(props.quality_long)
        self._plate_quality_long.setStyleSheet(f"color: {cl};")
        self._plate_spec_cross_value.setText(f"{props.specific_modulus_cross:.1f}")
        self._plate_spec_cross_value.setStyleSheet(f"color: {cc};")
        self._plate_quality_cross.setText(props.quality_cross)
        self._plate_quality_cross.setStyleSheet(f"color: {cc};")
        self._plate_rad_long.setText(f"L: {props.radiation_ratio_long:.1f}")
        self._plate_rad_cross.setText(f"C: {props.radiation_ratio_cross:.1f}")
        self._plate_cross_long.setText(f"{props.cross_long_ratio:.3f}")
        self._plate_long_cross.setText(f"{props.long_cross_ratio:.1f}")
        cov = PA.QUALITY_COLORS.get(props.overall_quality, "#888888")
        self._plate_overall_quality.setText(props.overall_quality)
        self._plate_overall_quality.setStyleSheet(f"color: {cov}; font-weight: bold;")
        # Gore Target Thickness
        try:
            _preset_str  = AS.AppSettings.plate_stiffness_preset()
            _preset      = PSP.PlateStiffnessPreset(_preset_str)
            _fvs         = (AS.AppSettings.custom_plate_stiffness()
                            if _preset == PSP.PlateStiffnessPreset.CUSTOM
                            else _preset.value_fvs)
            _body_l      = AS.AppSettings.guitar_body_length()
            _body_w      = AS.AppSettings.guitar_body_width()
            _gore        = PA.calculate_gore_target_thickness(
                props, _body_l, _body_w, _fvs, _preset.value, glc_pa=glc_pa
            )
            if _gore and _gore.thickness_mm > 0:
                self._gore_thickness_value.setText(f"{_gore.thickness_mm:.2f}")
                if glc_pa and glc_pa > 0:
                    self._gore_glc_value.setText(f"{glc_pa / 1e9:.3f} GPa")
                    self._gore_glc_row_w.setVisible(True)
                    self._gore_glc_info.setVisible(False)
                else:
                    self._gore_glc_row_w.setVisible(False)
                    self._gore_glc_info.setText(
                        "\u24d8 GLC assumed 0 \u2014 FLC tap recorded but GLC not computed"
                        if flc_freq > 0 else
                        "\u24d8 GLC assumed 0 \u2014 enable FLC tap for a more accurate result"
                    )
                    self._gore_glc_info.setVisible(True)
                _preset_lbl = (
                    f"f_vs = {int(_fvs)} (custom)"
                    if _preset == PSP.PlateStiffnessPreset.CUSTOM
                    else f"f_vs = {int(_fvs)} ({_preset.value})"
                )
                self._gore_params_lbl.setText(
                    f"Body: {_gore.body_length_mm:.0f} \u00d7 {_gore.body_width_mm:.0f} mm"
                    f"\n{_preset_lbl}"
                )
                self._gore_frame.setVisible(True)
            else:
                self._gore_frame.setVisible(False)
        except Exception:
            self._gore_frame.setVisible(False)
        self._plate_placeholder.setVisible(False)
        self._plate_content.setVisible(True)
        self._brace_section.setVisible(False)
        self._plate_section.setVisible(True)
        self._material_section.setVisible(True)

    def _get_current_dims(self) -> PA.PlateDimensions | None:
        """Return current plate/brace dimensions from AppSettings."""
        mt = self._current_mt()
        if mt.is_brace:
            return PA.PlateDimensions(
                length_mm=AS.AppSettings.brace_length(),
                width_mm=AS.AppSettings.brace_width(),
                thickness_mm=AS.AppSettings.brace_thickness(),
                mass_g=AS.AppSettings.brace_mass(),
            )
        else:
            return PA.PlateDimensions(
                length_mm=AS.AppSettings.plate_length(),
                width_mm=AS.AppSettings.plate_width(),
                thickness_mm=AS.AppSettings.plate_thickness(),
                mass_g=AS.AppSettings.plate_mass(),
            )

    # ================================================================
    # Measurements save / load / export
    # ================================================================

    def _collect_measurement(
        self,
        tap_location: str | None = None,
        notes: str | None = None,
    ) -> TapToneMeasurement:
        """Collect the current held peaks and spectrum into a TapToneMeasurement."""
        import uuid as _uuid
        from datetime import datetime, timezone
        canvas = self.fft_canvas
        model  = self.peak_widget.model
        mt     = self._current_mt()

        # Build ResonantPeak list from the current peaks table
        peaks: list[ResonantPeak] = []
        selected_ids: list[str] = []
        # For guitar: user-assigned mode overrides in Swift format {uuid: mode_string}
        # For plate/brace: use selectedLongitudinalPeakID etc. instead (set below)
        peak_mode_overrides: dict[str, str] = {}
        # Material peak ID tracking (plate/brace only)
        selected_longitudinal_peak_id: str | None = None
        selected_cross_peak_id: str | None = None
        selected_flc_peak_id: str | None = None

        ts = datetime.now(timezone.utc).isoformat()
        for row in range(model.rowCount(QtCore.QModelIndex())):
            idx  = model.index(row, 0)
            freq = model.freq_value(idx)
            mag  = model.magnitude_value(idx)
            q    = model.q_value(idx)
            show = model.show_value(idx)
            mode = model.mode_value(idx)
            peak_id = str(_uuid.uuid4())

            bandwidth = freq / max(q, 0.001) if q else 0.0
            entry = ResonantPeak(
                id=peak_id,
                frequency=freq,
                magnitude=mag,
                quality=q,
                bandwidth=bandwidth,
                timestamp=ts,
                mode_label=mode,
            )
            peaks.append(entry)

            if show == "on":
                selected_ids.append(peak_id)

            if mt.is_guitar:
                # Guitar: record user mode overrides (freq in model.modes = override set)
                if freq in model.modes:
                    peak_mode_overrides[peak_id] = model.modes[freq]
            else:
                # Plate/brace: track which peak was selected for each material mode
                label = model.modes.get(freq, "")
                if label == "Longitudinal":
                    selected_longitudinal_peak_id = peak_id
                elif label == "Cross-grain":
                    selected_cross_peak_id = peak_id
                elif label == "FLC":
                    selected_flc_peak_id = peak_id

        # Annotation offsets — store as [hzOffset, dbOffset] deltas (Swift convention).
        # hzOffset = label_hz - peak_hz; dbOffset positive = downward in screen = lower dB.
        # Default label center in data space = (peak_freq, peak_mag + 14.0).
        _LABEL_OFFSET_DB = 14.0
        freq_to_peak = {p.frequency: p for p in peaks}
        freq_to_id   = {p.frequency: p.id for p in peaks}
        annotation_offsets: dict[str, list[float]] = {}
        for ann_dict in canvas.annotations.annotations:
            ann_freq = ann_dict.get("freq")
            xytext   = ann_dict.get("xytext")
            if ann_freq is not None and xytext and ann_freq in freq_to_id:
                peak = freq_to_peak[ann_freq]
                hz_offset = float(xytext[0]) - peak.frequency
                # dbOffset positive = downward = lower dB; xytext[1] is absolute dB of label center
                db_offset = (peak.magnitude + _LABEL_OFFSET_DB) - float(xytext[1])
                annotation_offsets[freq_to_id[ann_freq]] = [hz_offset, db_offset]

        # Spectrum snapshot — guitar uses spectrumSnapshot; plate/brace use phase snapshots
        spectrum_snapshot: SpectrumSnapshot | None = None
        longitudinal_snapshot: SpectrumSnapshot | None = None
        cross_snapshot: SpectrumSnapshot | None = None
        flc_snapshot: SpectrumSnapshot | None = None
        if hasattr(canvas, "saved_mag_y_db") and np.any(canvas.saved_mag_y_db):
            freqs = canvas.freq.tolist()
            mags  = canvas.saved_mag_y_db.tolist()
            _snap_base = dict(
                frequencies=freqs,
                magnitudes=mags,
                min_freq=float(self.min_spin.value()),
                max_freq=float(self.max_spin.value()),
                min_db=float(self.threshold_slider.value()),
                max_db=float(np.max(canvas.saved_mag_y_db)) + 10.0,
                guitar_type=self.guitar_type_combo.currentText(),
                measurement_type=self.measurement_type_combo.currentText(),
            )
            if mt.is_guitar:
                spectrum_snapshot = SpectrumSnapshot(**_snap_base)
            else:
                # Plate/brace: embed current dimensions in the longitudinal snapshot
                # so they are restored when the measurement is loaded back.
                _dims = self._get_current_dims()
                _pc = canvas.plate_capture
                if mt.is_brace:
                    _l_mags = (
                        _pc.long_mag_db.tolist()
                        if _pc.long_mag_db is not None
                        else mags
                    )
                    longitudinal_snapshot = SpectrumSnapshot(
                        frequencies=freqs,
                        magnitudes=_l_mags,
                        min_freq=float(self.min_spin.value()),
                        max_freq=float(self.max_spin.value()),
                        min_db=float(self.threshold_slider.value()),
                        max_db=float(np.max(_l_mags)) + 10.0,
                        guitar_type=self.guitar_type_combo.currentText(),
                        measurement_type=self.measurement_type_combo.currentText(),
                        brace_length=_dims.length_mm if _dims else None,
                        brace_width=_dims.width_mm if _dims else None,
                        brace_thickness=_dims.thickness_mm if _dims else None,
                        brace_mass=_dims.mass_g if _dims else None,
                    )
                else:
                    _psp_str = AS.AppSettings.plate_stiffness_preset()
                    _plate_dim_kwargs = dict(
                        plate_length=_dims.length_mm if _dims else None,
                        plate_width=_dims.width_mm if _dims else None,
                        plate_thickness=_dims.thickness_mm if _dims else None,
                        plate_mass=_dims.mass_g if _dims else None,
                        plate_stiffness_preset=_psp_str,
                        custom_plate_stiffness=(
                            AS.AppSettings.custom_plate_stiffness()
                            if _psp_str == "Custom" else None
                        ),
                        guitar_body_length=AS.AppSettings.guitar_body_length(),
                        guitar_body_width=AS.AppSettings.guitar_body_width(),
                    )
                    # Longitudinal snapshot uses the mag_db stored per-phase
                    # (falls back to saved_mag_y_db if per-phase data is missing)
                    _l_mags = (
                        _pc.long_mag_db.tolist()
                        if _pc.long_mag_db is not None
                        else mags
                    )
                    longitudinal_snapshot = SpectrumSnapshot(
                        frequencies=freqs,
                        magnitudes=_l_mags,
                        min_freq=float(self.min_spin.value()),
                        max_freq=float(self.max_spin.value()),
                        min_db=float(self.threshold_slider.value()),
                        max_db=float(np.max(_l_mags)) + 10.0,
                        guitar_type=self.guitar_type_combo.currentText(),
                        measurement_type=self.measurement_type_combo.currentText(),
                        **_plate_dim_kwargs,
                    )
                    # Cross-grain snapshot
                    if _pc.cross_mag_db is not None:
                        _c_mags = _pc.cross_mag_db.tolist()
                        cross_snapshot = SpectrumSnapshot(
                            frequencies=freqs,
                            magnitudes=_c_mags,
                            min_freq=float(self.min_spin.value()),
                            max_freq=float(self.max_spin.value()),
                            min_db=float(self.threshold_slider.value()),
                            max_db=float(np.max(_c_mags)) + 10.0,
                            guitar_type=self.guitar_type_combo.currentText(),
                            measurement_type=self.measurement_type_combo.currentText(),
                            **_plate_dim_kwargs,
                        )
                    # FLC snapshot
                    if _pc.flc_mag_db is not None:
                        _flc_mags = _pc.flc_mag_db.tolist()
                        flc_snapshot = SpectrumSnapshot(
                            frequencies=freqs,
                            magnitudes=_flc_mags,
                            min_freq=float(self.min_spin.value()),
                            max_freq=float(self.max_spin.value()),
                            min_db=float(self.threshold_slider.value()),
                            max_db=float(np.max(_flc_mags)) + 10.0,
                            guitar_type=self.guitar_type_combo.currentText(),
                            measurement_type=self.measurement_type_combo.currentText(),
                            **_plate_dim_kwargs,
                        )

        mic_name: str | None = None
        try:
            mic_name = canvas.mic.device_name
        except Exception:
            pass

        return TapToneMeasurement.create(
            peaks=peaks,
            decay_time=self._ring_out_s,
            tap_location=tap_location or None,
            notes=notes or None,
            spectrum_snapshot=spectrum_snapshot,
            longitudinal_snapshot=longitudinal_snapshot,
            cross_snapshot=cross_snapshot,
            flc_snapshot=flc_snapshot,
            selected_peak_ids=selected_ids or None,
            peak_mode_overrides=peak_mode_overrides or None,
            annotation_offsets=annotation_offsets or None,
            tap_detection_threshold=float(self.tap_threshold_slider.value()),
            number_of_taps=self.tap_num_spin.value(),
            peak_threshold=float(self.threshold_slider.value()) if mt.is_guitar else None,
            selected_longitudinal_peak_id=selected_longitudinal_peak_id,
            selected_cross_peak_id=selected_cross_peak_id,
            selected_flc_peak_id=selected_flc_peak_id,
            microphone_name=mic_name,
            measurement_type=self.measurement_type_combo.currentText(),
            guitar_type=self.guitar_type_combo.currentText(),
        )

    def _on_save_measurement(self) -> None:
        """Show save dialog then persist the measurement."""
        dlg = SMD.SaveMeasurementDialog(self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        m = self._collect_measurement(
            tap_location=dlg.tap_location,
            notes=dlg.notes,
        )

        measurements = M.load_all_measurements()
        measurements.append(m)
        try:
            M.save_all_measurements(measurements)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Save Error", f"Could not save measurement:\n{exc}"
            )

    def _on_open_measurements(self) -> None:
        dlg = MD.MeasurementsDialog(self)
        dlg.measurementSelected.connect(self._restore_measurement)
        dlg.comparisonRequested.connect(self._on_comparison_requested)
        dlg.exec()

    def _on_comparison_requested(self, measurements: list) -> None:
        """Load comparison overlays onto the main chart.

        Called when the user presses Compare(N) in the measurements dialog.
        Mirrors the loadComparison() call triggered by the Compare button in Swift's
        MeasurementsListView.
        """
        self.fft_canvas.load_comparison(measurements)

    def _on_comparison_changed(self, is_comparing: bool) -> None:
        """Update UI when comparison overlay state changes.

        Mirrors TapToneAnalysisView+Controls.swift (status bar swap, button states)
        and TapAnalysisResultsView.swift (Comparing N measurements label).
        """
        canvas = self.fft_canvas
        n = canvas.comparison_count

        # ── Status bar: swap normal widgets ↔ comparison info ────────────────
        self._sb_normal_wgt.setVisible(not is_comparing)
        self._sb_compare_wgt.setVisible(is_comparing)
        if is_comparing:
            self._sb_compare_msg.setText(f"Comparing {n} measurements")

        # ── Analysis Results: show placeholder label ↔ peak list ─────────────
        self._comparing_lbl.setVisible(is_comparing)
        self._comparing_lbl.setText(f"Comparing {n} measurements")
        self.peak_widget.setVisible(not is_comparing)
        # Scroll area (plate/brace) also hidden while comparing
        self._material_scroll.setVisible(not is_comparing)
        # Guitar summary (Ring-Out, Tap Ratio) — mirrors
        # `measurementType.isGuitar && analyzer.displayMode != .comparison` in Swift
        self._guitar_summary.setVisible(self._current_mt().is_guitar and not is_comparing)

        # ── display_mode is already set by load_comparison / clear_comparison ──
        # The canvas _on_fft_frame_ready gates on display_mode == COMPARISON to
        # suppress live updates — no need to touch is_measurement_complete here.

        # ── Annotations ───────────────────────────────────────────────────────
        if is_comparing:
            canvas.annotations.hide_annotations()
        else:
            canvas.annotations.show_all_annotations()

        # ── Badge ──────────────────────────────────────────────────────────────
        self._update_measurement_badge()

        # ── Save / Export ──────────────────────────────────────────────────────
        # Export PDF is hidden (not just disabled) during comparison — mirrors
        # `if let exportPDF = onExportPDFReport, analyzer.displayMode != .comparison`
        # in TapAnalysisResultsView.swift.
        # Export Spectrum remains visible and is enabled during comparison.
        if is_comparing:
            self.save_measurement_btn.setEnabled(False)
            self.export_spectrum_btn.setEnabled(True)
            self.export_pdf_btn.setVisible(False)
        else:
            self.save_measurement_btn.setEnabled(self._is_measurement_complete)
            self.export_spectrum_btn.setEnabled(self._is_measurement_complete)
            self.export_pdf_btn.setVisible(True)
            self.export_pdf_btn.setEnabled(self._is_measurement_complete)

        # ── Peak-selection buttons ─────────────────────────────────────────────
        can_select = self._is_measurement_complete and not is_comparing
        self.select_all_btn.setEnabled(can_select)
        self.deselect_all_btn.setEnabled(can_select)
        self.reset_auto_selection_btn.setEnabled(
            can_select and self.peak_widget.model.user_has_modified_peak_selection
        )

        self._update_tap_buttons()

    def _restore_measurement(self, m: TapToneMeasurement) -> None:
        canvas = self.fft_canvas

        # Loading a measurement exits comparison mode and enters frozen mode —
        # mirrors comparisonSpectra = [] + displayMode = .frozen in loadMeasurement() in Swift.
        canvas.clear_comparison()
        if self._is_measurement_complete:
            self.set_measurement_complete(False)
        # Set FROZEN after the set_measurement_complete(False) call — that call invokes
        # analyzer.clear_comparison() which sets _display_mode = LIVE; setting FROZEN
        # here ensures the loaded measurement is displayed correctly.
        canvas.display_mode = DisplayMode.FROZEN

        # Restore display settings
        if m.guitar_type:
            self.guitar_type_combo.setCurrentText(m.guitar_type)
        if m.measurement_type:
            # Swift may save various string forms; normalise via from_string() then
            # map to the three combo values ("Guitar", "Plate", "Brace").
            _mt = MT.MeasurementType.from_string(m.measurement_type)
            _combo_val = "Guitar" if _mt.is_guitar else _mt.short_name
            self.measurement_type_combo.setCurrentText(_combo_val)

        # Restore peaks (built early so _loaded_measurement_peaks is set before
        # update_axis fires, preventing a stale find_peaks call from the spinner signals)
        if m.peaks:
            peaks_array = np.array(
                [[p.frequency, p.magnitude, p.quality] for p in m.peaks],
                dtype=np.float64,
            )
            # Sort by frequency so that range-slicing in _emit_loaded_peaks_at_threshold
            # and update_mode_colors gives only in-range peaks.
            peaks_array = peaks_array[np.argsort(peaks_array[:, 0])]
        else:
            peaks_array = np.zeros((0, 3), dtype=np.float64)

        canvas.saved_peaks = peaks_array
        canvas._loaded_measurement_peaks = peaks_array  # authoritative; used by threshold/range sliders
        canvas.b_peaks_freq = peaks_array[:, 0] if len(peaks_array) > 0 else []
        canvas.peaks_f_min_index = 0
        canvas.peaks_f_max_index = len(peaks_array)

        # Restore spectrum snapshot if available.
        # For guitar: use spectrumSnapshot. For plate/brace: spectrumSnapshot is nil;
        # use longitudinalSnapshot instead — mirrors Swift: longitudinalSnapshot ?? spectrumSnapshot.
        # Block spinner valueChanged signals while setting values to prevent
        # spurious update_axis → find_peaks calls with stale magnitude data.
        _snap = m.spectrum_snapshot or m.longitudinal_snapshot
        if _snap is not None:
            snap = _snap
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes, dtype=np.float64)
            canvas.saved_mag_y_db = mag_arr
            # Keep as float64 — int64 would quantize sub-Hz bins to 0, distorting the plot.
            canvas.freq = freq_arr
            with QtCore.QSignalBlocker(self.min_spin):
                self.min_spin.setValue(int(snap.min_freq))
            with QtCore.QSignalBlocker(self.max_spin):
                self.max_spin.setValue(int(snap.max_freq))
            # Restore dB axis range from snapshot, then update the frequency axis.
            canvas.setYRange(snap.min_db, snap.max_db, padding=0)
            canvas.update_axis(int(snap.min_freq), int(snap.max_freq))
            canvas.set_draw_data(mag_arr, peaks_array)
        else:
            # No snapshot — emit peaks filtered to current range
            canvas._emit_loaded_peaks_at_threshold()

        # Restore ring-out
        self._ring_out_s = m.decay_time
        if m.decay_time is not None:
            self.set_ring_out(m.decay_time)

        # Restore mode overrides and show/hide state
        peak_model = self.peak_widget.model

        _restored_mt = MT.MeasurementType.from_string(m.measurement_type or "")

        # Restore plate/brace dimensions from the snapshot — mirrors Swift's .onReceive
        # handlers that write loadedXxx published properties back to TapDisplaySettings.
        # Updating AppSettings here means the settings panel reflects the loaded dims.
        if not _restored_mt.is_guitar:
            _snap_for_dims = m.longitudinal_snapshot or m.spectrum_snapshot
            if _snap_for_dims is not None:
                if _restored_mt.is_brace:
                    if _snap_for_dims.brace_length    is not None: AS.AppSettings.set_brace_length(_snap_for_dims.brace_length)
                    if _snap_for_dims.brace_width     is not None: AS.AppSettings.set_brace_width(_snap_for_dims.brace_width)
                    if _snap_for_dims.brace_thickness is not None: AS.AppSettings.set_brace_thickness(_snap_for_dims.brace_thickness)
                    if _snap_for_dims.brace_mass      is not None: AS.AppSettings.set_brace_mass(_snap_for_dims.brace_mass)
                else:
                    if _snap_for_dims.plate_length    is not None: AS.AppSettings.set_plate_length(_snap_for_dims.plate_length)
                    if _snap_for_dims.plate_width     is not None: AS.AppSettings.set_plate_width(_snap_for_dims.plate_width)
                    if _snap_for_dims.plate_thickness is not None: AS.AppSettings.set_plate_thickness(_snap_for_dims.plate_thickness)
                    if _snap_for_dims.plate_mass      is not None: AS.AppSettings.set_plate_mass(_snap_for_dims.plate_mass)
                    if _snap_for_dims.plate_stiffness_preset is not None:
                        AS.AppSettings.set_plate_stiffness_preset(_snap_for_dims.plate_stiffness_preset)
                    if _snap_for_dims.custom_plate_stiffness is not None:
                        AS.AppSettings.set_custom_plate_stiffness(_snap_for_dims.custom_plate_stiffness)
                    if _snap_for_dims.guitar_body_length is not None:
                        AS.AppSettings.set_guitar_body_length(_snap_for_dims.guitar_body_length)
                    if _snap_for_dims.guitar_body_width is not None:
                        AS.AppSettings.set_guitar_body_width(_snap_for_dims.guitar_body_width)

        if not _restored_mt.is_guitar:
            # Plate / brace: label peaks by selectedLongitudinalPeakID / selectedCrossPeakID / selectedFlcPeakID
            _id_to_label: dict[str, str] = {}
            if m.selected_longitudinal_peak_id:
                _id_to_label[m.selected_longitudinal_peak_id.upper()] = "Longitudinal"
            if m.selected_cross_peak_id:
                _id_to_label[m.selected_cross_peak_id.upper()] = "Cross-grain"
            if m.selected_flc_peak_id:
                _id_to_label[m.selected_flc_peak_id.upper()] = "FLC"
            peak_model.modes = {}
            for p in m.peaks:
                peak_model.modes[p.frequency] = _id_to_label.get(
                    (p.id or "").upper(), "Peak"
                )
        elif m.peak_mode_overrides:
            # Guitar: manual mode overrides (keyed by UUID in new format)
            id_to_mode = m.peak_mode_overrides
            peak_model.modes = {}
            for p in m.peaks:
                if p.id in id_to_mode:
                    peak_model.modes[p.frequency] = id_to_mode[p.id]
        else:
            peak_model.modes = {}

        # Show/hide selection — mirrors Swift: selectedPeakIDs ?? all peaks
        selected_ids = set(
            m.selected_peak_ids if m.selected_peak_ids is not None
            else [p.id for p in m.peaks]
        )
        peak_model.show = {}
        for p in m.peaks:
            if p.id in selected_ids:
                peak_model.show[p.frequency] = "on"

        # Mark as user-modified so threshold changes carry selections forward by
        # frequency proximity — mirrors Swift: userHasModifiedPeakSelection = true
        peak_model._set_user_modified(True)

        # Restore analysis settings saved with the measurement.
        # Format: Swift saves dBFS (negative); old Python saves internal 0-100 scale (positive).
        # Detect by sign: negative → dBFS directly; non-negative → convert (value - 100).
        if m.tap_detection_threshold is not None:
            val = float(m.tap_detection_threshold)
            db = int(val) if val < 0 else int(val - 100)
            self.tap_threshold_slider.setValue(max(-80, min(-20, db)))
        if m.peak_threshold is not None:
            val = float(m.peak_threshold)
            db = int(val) if val < 0 else int(val - 100)
            self.threshold_slider.setValue(max(-100, min(-20, db)))
        if m.number_of_taps is not None:
            self.tap_num_spin.setValue(m.number_of_taps)

        # Restore annotations
        canvas.annotations.clear_annotations()
        ann_offsets = m.annotation_offsets or {}
        for p in m.peaks:
            freq = p.frequency
            mag  = p.magnitude
            if _restored_mt.is_guitar:
                mode_str = (
                    peak_model.modes.get(freq)
                    or p.mode_label
                    or GM.classify_peak(freq, peak_model.guitar_type)
                )
            else:
                # Plate/brace: use the material mode label set above; never fall back to guitar classifier
                mode_str = peak_model.modes.get(freq, "Peak")
            # ann_offsets stores [hzOffset, dbOffset] in Swift convention.
            # hzOffset: Hz delta from peak; dbOffset positive = downward = lower dB.
            # Convert to absolute label center: (freq + hzOffset, mag + 14.0 - dbOffset).
            _ann_offset = ann_offsets.get(p.id) or ann_offsets.get(p.id.upper())
            if _ann_offset:
                xytext = (freq + _ann_offset[0], mag + 14.0 - _ann_offset[1])
            else:
                xytext = (freq, mag + 14.0)
            html = peak_model.annotation_html(freq, mag, mode_str)
            canvas.annotations.annotations.append(
                {
                    "freq":       freq,
                    "annotation": None,
                    "arrow_line": None,
                    "mag":        mag,
                    "html":       html,
                    "mode_str":   mode_str,
                    "xytext":     xytext,
                }
            )

        # Restore annotation visibility mode — mirrors Swift: annotationVisibilityMode ?? .all
        _mode_name_map = {"all": "All", "selected": "Selected", "none": "None"}
        target_mode = _mode_name_map.get(
            (m.annotation_visibility_mode or "all").lower(), "All"
        )
        target_idx = next(
            (i for i, (name, _) in enumerate(self._ANN_MODES) if name == target_mode),
            self._ann_mode_idx,
        )
        self._ann_mode_idx = target_idx
        self.annotations_btn.setIcon(qta.icon(self._ANN_MODES[target_idx][1]))

        # For plate/brace, restore material peak widget and compute properties
        if not _restored_mt.is_guitar:
            _f_long = 0.0
            _f_cross = 0.0
            _f_flc   = 0.0
            if m.selected_longitudinal_peak_id:
                _uid = m.selected_longitudinal_peak_id.upper()
                _p = next((p for p in m.peaks if (p.id or "").upper() == _uid), None)
                if _p:
                    _f_long = _p.frequency
            if m.selected_cross_peak_id:
                _uid = m.selected_cross_peak_id.upper()
                _p = next((p for p in m.peaks if (p.id or "").upper() == _uid), None)
                if _p:
                    _f_cross = _p.frequency
            if m.selected_flc_peak_id:
                _uid = m.selected_flc_peak_id.upper()
                _p = next((p for p in m.peaks if (p.id or "").upper() == _uid), None)
                if _p:
                    _f_flc = _p.frequency

            # Populate material peak widget with loaded peaks and assignment
            _show_flc = (not _restored_mt.is_brace) and _f_flc > 0
            self._material_peak_widget.set_mode(
                show_cross=not _restored_mt.is_brace,
                show_flc=_show_flc,
            )
            self._material_peak_widget.update_peaks(peaks_array)
            self._material_peak_widget.set_assignment(_f_long, _f_cross, _f_flc)

            if _f_long > 0:
                _dims = self._get_current_dims()
                if _dims and _dims.is_valid():
                    try:
                        if _restored_mt.is_brace:
                            self._populate_brace_section(
                                PA.calculate_brace_properties(_dims, _f_long)
                            )
                        elif _f_cross > 0:
                            _glc = (PA.calculate_glc_from_flc(_dims, _f_flc)
                                    if _f_flc > 0 else None)
                            self._populate_plate_section(
                                PA.calculate_plate_properties(_dims, _f_long, _f_cross),
                                flc_freq=_f_flc,
                                glc_pa=_glc if _glc else None,
                            )
                    except ValueError:
                        pass

        # Update chart title to show the measurement name — mirrors Swift loadedMeasurementName.
        canvas.set_loaded_measurement_name(m.tap_location)

        self.set_measurement_complete(True)

        # Arm the loaded-settings warning AFTER set_measurement_complete so it isn't
        # immediately cleared by that call — mirrors Swift showLoadedSettingsWarning = true
        # being the last statement in loadMeasurement().
        self._loaded_tap_threshold = self.tap_threshold_slider.value()
        self._loaded_tap_num = self.tap_num_spin.value()
        self._show_loaded_settings_warning = True
        self._sb_warning_msg.setText(
            f"Settings from loaded measurement \u2014 Threshold: {self._loaded_tap_threshold} dB"
            f" \u00b7 Taps: {self._loaded_tap_num}"
        )
        self._sb_warning_wgt.setVisible(True)
        self._warn_pulse_t = 0.0
        self._warn_pulse_timer.start()

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
                    _cal = _mc_mod.CalibrationStorage.calibration_for_device(new_name)
                    self.set_calibration_status(_cal.name if _cal else "")
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
        _cal = _mc_mod.CalibrationStorage.calibration_for_device(fallback_name)
        self.set_calibration_status(_cal.name if _cal else "")

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
        try:
            cal = _mc_mod.MicrophoneCalibration.from_path(path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Calibration Error",
                f"Could not parse calibration file:\n{path}\n\n{exc}",
            )
            return
        _mc_mod.CalibrationStorage.save(cal)
        AS.AppSettings.set_calibration_path(os.path.dirname(path))
        dev_name = (
            self.fft_canvas.current_calibration_device()
            or AS.AppSettings.device_name()
        )
        if dev_name:
            _mc_mod.CalibrationStorage.set_calibration_for_device(dev_name, cal.id)
        self.fft_canvas.load_calibration_from_profile(cal)
        self.set_calibration_status(cal.name)

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
                _cal = _mc_mod.CalibrationStorage.calibration_for_device(dev_name)
                self.set_calibration_status(_cal.name if _cal else "")

    # ================================================================
    # Settings dialog
    # ================================================================

    def _show_settings(self) -> None:  # noqa: C901
        """Modal settings dialog matching the Swift TapSettingsView structure."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setMinimumWidth(460)

        # Top-level layout contains a QStackedWidget:
        #   page 0 — settings (scroll area + Cancel/Done buttons)
        #   page 1 — in-panel Quick-Start Guide (back button + QTextBrowser)
        outer = QtWidgets.QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)

        stack = QtWidgets.QStackedWidget()
        outer.addWidget(stack)

        # ── Page 0: Settings ──────────────────────────────────────────────
        settings_page = QtWidgets.QWidget()
        settings_outer = QtWidgets.QVBoxLayout(settings_page)
        settings_outer.setContentsMargins(8, 8, 8, 8)
        settings_outer.setSpacing(8)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(content)
        vbox.setSpacing(8)
        scroll.setWidget(content)
        settings_outer.addWidget(scroll)
        stack.addWidget(settings_page)   # index 0

        # ── Page 1: Quick-Start Guide ─────────────────────────────────────
        import help_dialog as _HD
        help_page = QtWidgets.QWidget()
        help_layout = QtWidgets.QVBoxLayout(help_page)
        help_layout.setContentsMargins(8, 8, 8, 8)
        help_layout.setSpacing(6)
        back_btn = QtWidgets.QPushButton("← Settings")
        back_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        )
        help_layout.addWidget(back_btn)
        help_browser = QtWidgets.QTextBrowser()
        help_browser.setOpenExternalLinks(True)
        help_browser.setHtml(_HD.get_help_html())
        help_layout.addWidget(help_browser)
        stack.addWidget(help_page)       # index 1

        def _show_help_page() -> None:
            stack.setCurrentIndex(1)
            dlg.setWindowTitle("Quick-Start Guide")

        def _show_settings_page() -> None:
            stack.setCurrentIndex(0)
            dlg.setWindowTitle("Settings")

        back_btn.clicked.connect(_show_settings_page)

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

        MEAS_TYPES = [mt.value for mt in MT.MeasurementType]

        # Derive the current unified type from the existing hidden combos
        cur_unified = self._current_mt().value

        meas_type_row = QtWidgets.QHBoxLayout()
        meas_type_row.addWidget(QtWidgets.QLabel("Measurement Type:"))
        meas_type_combo = QtWidgets.QComboBox()
        meas_type_combo.addItems(MEAS_TYPES)
        meas_type_combo.setCurrentText(cur_unified)
        meas_type_combo.setEditable(True)
        meas_type_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed
        )
        meas_type_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        le = meas_type_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        meas_type_row.addWidget(meas_type_combo)
        mg.addLayout(meas_type_row)

        meas_desc_lbl = QtWidgets.QLabel(MT.MeasurementType(cur_unified).description)
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

        mode_ranges_widget = QtWidgets.QWidget()
        _mr_hbox = QtWidgets.QHBoxLayout(mode_ranges_widget)
        _mr_hbox.setContentsMargins(0, 0, 0, 0)
        _mr_hbox.setSpacing(0)

        _mr_left_grid = QtWidgets.QGridLayout()
        _mr_left_grid.setHorizontalSpacing(4)
        _mr_left_grid.setVerticalSpacing(2)
        _mr_right_grid = QtWidgets.QGridLayout()
        _mr_right_grid.setHorizontalSpacing(4)
        _mr_right_grid.setVerticalSpacing(2)

        _mode_name_labels: list[QtWidgets.QLabel] = []
        _mode_range_labels: list[QtWidgets.QLabel] = []
        for _ in range(5):
            nl = QtWidgets.QLabel()
            nl.setFont(small)
            rl = QtWidgets.QLabel()
            rl.setFont(small)
            _mode_name_labels.append(nl)
            _mode_range_labels.append(rl)

        for i, (nl, rl) in enumerate(zip(_mode_name_labels[:3], _mode_range_labels[:3])):
            _mr_left_grid.addWidget(nl, i, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
            _mr_left_grid.addWidget(rl, i, 1, QtCore.Qt.AlignmentFlag.AlignLeft)
        for i, (nl, rl) in enumerate(zip(_mode_name_labels[3:], _mode_range_labels[3:])):
            _mr_right_grid.addWidget(nl, i, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
            _mr_right_grid.addWidget(rl, i, 1, QtCore.Qt.AlignmentFlag.AlignLeft)

        _mr_hbox.addLayout(_mr_left_grid)
        _mr_hbox.addStretch()
        _mr_hbox.addLayout(_mr_right_grid)
        guitar_layout.addWidget(mode_ranges_widget)

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

        def _dim_spinbox(suffix: str, max_val: float = 2000.0,
                         decimals: int = 1) -> QtWidgets.QDoubleSpinBox:
            sb = QtWidgets.QDoubleSpinBox()
            sb.setDecimals(decimals)
            sb.setMinimum(0.01)
            sb.setMaximum(max_val)
            sb.setSuffix(f" {suffix}")
            return sb

        def _dim_row(text: str, widget: QtWidgets.QWidget) -> QtWidgets.QHBoxLayout:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(text))
            row.addStretch()
            widget.setFixedWidth(110)
            row.addWidget(widget)
            return row

        plate_length_spin = _dim_spinbox("mm", 2000.0)
        plate_length_spin.setValue(AS.AppSettings.plate_length())
        plate_width_spin = _dim_spinbox("mm", 1000.0)
        plate_width_spin.setValue(AS.AppSettings.plate_width())
        plate_thick_spin = _dim_spinbox("mm", 50.0, decimals=2)
        plate_thick_spin.setValue(AS.AppSettings.plate_thickness())
        plate_mass_spin = _dim_spinbox("g", 5000.0)
        plate_mass_spin.setValue(AS.AppSettings.plate_mass())

        plate_density_lbl = QtWidgets.QLabel("—")
        plate_density_lbl.setFont(small)
        plate_density_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        plate_layout.addLayout(_dim_row("Length (along grain):", plate_length_spin))
        plate_layout.addLayout(_dim_row("Width (cross grain):", plate_width_spin))
        plate_layout.addLayout(_dim_row("Thickness:", plate_thick_spin))
        plate_layout.addLayout(_dim_row("Mass:", plate_mass_spin))

        _density_row = QtWidgets.QHBoxLayout()
        _density_row.addWidget(QtWidgets.QLabel("Calculated Density:"))
        _density_row.addStretch()
        _density_row.addWidget(plate_density_lbl)
        plate_layout.addLayout(_density_row)

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

        gore_body_len_spin = _dim_spinbox("mm", 1000.0)
        gore_body_len_spin.setValue(AS.AppSettings.guitar_body_length())
        gore_body_wid_spin = _dim_spinbox("mm", 1000.0)
        gore_body_wid_spin.setValue(AS.AppSettings.guitar_body_width())
        plate_layout.addLayout(_dim_row("Body Length (a):", gore_body_len_spin))
        plate_layout.addLayout(_dim_row("Lower Bout Width (b):", gore_body_wid_spin))
        plate_layout.addWidget(_hsep())

        fvs_hdr = QtWidgets.QLabel("Plate Vibrational Stiffness (f_vs)")
        fvs_hdr.setFont(hdr_font)
        plate_layout.addWidget(fvs_hdr)

        PRESET_DISPLAY_NAMES = [p.short_name for p in PSP.PlateStiffnessPreset]
        PRESET_STORAGE_NAMES = [p.value for p in PSP.PlateStiffnessPreset]
        fvs_combo = QtWidgets.QComboBox()
        fvs_combo.addItems(PRESET_DISPLAY_NAMES)
        fvs_combo.setEditable(True)
        _fvs_le = fvs_combo.lineEdit()
        if _fvs_le is not None:
            _fvs_le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            _fvs_le.setReadOnly(True)
        saved_preset = AS.AppSettings.plate_stiffness_preset()
        if saved_preset in PRESET_STORAGE_NAMES:
            fvs_combo.setCurrentIndex(PRESET_STORAGE_NAMES.index(saved_preset))
        fvs_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed
        )
        fvs_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        _panel_type_row = QtWidgets.QHBoxLayout()
        _panel_type_row.addWidget(QtWidgets.QLabel("Panel Type:"))
        _panel_type_row.addStretch()
        _panel_type_row.addWidget(fvs_combo)
        plate_layout.addLayout(_panel_type_row)

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

        brace_length_spin = _dim_spinbox("mm", 1000.0)
        brace_length_spin.setValue(AS.AppSettings.brace_length())
        brace_width_spin = _dim_spinbox("mm", 200.0)
        brace_width_spin.setValue(AS.AppSettings.brace_width())
        brace_thick_spin = _dim_spinbox("mm", 200.0, decimals=2)
        brace_thick_spin.setValue(AS.AppSettings.brace_thickness())
        brace_mass_spin = _dim_spinbox("g", 500.0)
        brace_mass_spin.setValue(AS.AppSettings.brace_mass())

        brace_density_lbl = QtWidgets.QLabel("—")
        brace_density_lbl.setFont(small)
        brace_density_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        brace_layout.addLayout(_dim_row("Length (along grain):", brace_length_spin))
        brace_layout.addLayout(_dim_row("Width (breadth):", brace_width_spin))
        brace_layout.addLayout(_dim_row("Height (tap direction):", brace_thick_spin))

        height_note = QtWidgets.QLabel(
            "Brace height when lying flat — this is the t dimension in the stiffness formula"
        )
        height_note.setFont(small)
        height_note.setWordWrap(True)
        _height_note_row = QtWidgets.QHBoxLayout()
        _height_note_row.addWidget(height_note, stretch=1)
        _height_note_row.addSpacing(110)
        brace_layout.addLayout(_height_note_row)

        brace_layout.addLayout(_dim_row("Mass:", brace_mass_spin))

        _brace_density_row = QtWidgets.QHBoxLayout()
        _brace_density_row.addWidget(QtWidgets.QLabel("Calculated Density:"))
        _brace_density_row.addStretch()
        _brace_density_row.addWidget(brace_density_lbl)
        brace_layout.addLayout(_brace_density_row)

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

        # ---- Measurement type footer (conditional) ----
        _GUITAR_FOOTER = "Select your guitar type for accurate mode classification."
        _PLATE_FOOTER = (
            "Enter the dimensions and mass of your rectangular wood sample. "
            "The app will calculate stiffness, speed of sound, and radiation "
            "ratio from the tap frequencies."
        )
        _is_guitar_initial = MT.MeasurementType(cur_unified).is_guitar
        meas_footer_lbl = QtWidgets.QLabel(
            _GUITAR_FOOTER if _is_guitar_initial else _PLATE_FOOTER
        )
        meas_footer_lbl.setFont(small)
        meas_footer_lbl.setWordWrap(True)
        mg.addWidget(meas_footer_lbl)

        # ---- Mode ranges display ----
        def _update_mode_ranges(unified_type: str) -> None:
            mt_val = MT.MeasurementType(unified_type)
            guitar_type_enum = mt_val.guitar_type
            if guitar_type_enum is None:
                return
            try:
                guitar_type = GT.GuitarType(guitar_type_enum.value)
            except ValueError:
                return
            r = guitar_type.mode_ranges
            entries = [
                ("Air",    f"{int(r.air[0])}–{int(r.air[1])} Hz"),
                ("Top",    f"{int(r.top[0])}–{int(r.top[1])} Hz"),
                ("Back",   f"{int(r.back[0])}–{int(r.back[1])} Hz"),
                ("DP",     f"{int(r.dipole[0])}–{int(r.dipole[1])} Hz"),
                ("Ring",   f"{int(r.ring_mode[0])}–{int(r.ring_mode[1])} Hz"),
            ]
            for i, (nl, rl) in enumerate(zip(_mode_name_labels, _mode_range_labels)):
                if i < len(entries):
                    nl.setText(entries[i][0] + ":")
                    rl.setText(entries[i][1])
                else:
                    nl.setText("")
                    rl.setText("")

        # ---- Show/hide type-specific widgets ----
        def _on_meas_type_changed(unified: str) -> None:
            mt_val = MT.MeasurementType(unified)
            is_guitar = mt_val.is_guitar
            meas_desc_lbl.setText(mt_val.description)
            meas_footer_lbl.setText(_GUITAR_FOOTER if is_guitar else _PLATE_FOOTER)
            guitar_widget.setVisible(is_guitar)
            plate_widget.setVisible(mt_val is MT.MeasurementType.PLATE)
            brace_widget.setVisible(mt_val is MT.MeasurementType.BRACE)
            show_unknown_widget.setEnabled(is_guitar)
            peak_thresh_widget.setEnabled(is_guitar)
            max_peaks_widget.setEnabled(is_guitar)
            if is_guitar:
                _update_mode_ranges(unified)

        meas_type_combo.currentTextChanged.connect(_on_meas_type_changed)

        # =====================================================
        # 2. Display Settings Section
        # =====================================================
        disp_group = QtWidgets.QGroupBox("")
        dg = QtWidgets.QVBoxLayout(disp_group)
        dg.addWidget(_group_header("mdi.chart-line", "Display Settings"))

        def _range_block(
            layout: QtWidgets.QVBoxLayout,
            title: str,
            min_widget: QtWidgets.QWidget,
            max_widget: QtWidgets.QWidget,
            unit: str,
            description: str,
        ) -> None:
            title_lbl = QtWidgets.QLabel(title)
            title_lbl.setFont(hdr_font)
            layout.addWidget(title_lbl)

            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Min"))
            row.addWidget(min_widget)
            row.addWidget(QtWidgets.QLabel("to"))
            row.addWidget(QtWidgets.QLabel("Max"))
            row.addWidget(max_widget)
            row.addWidget(QtWidgets.QLabel(unit))
            row.addStretch()
            layout.addLayout(row)

            desc_lbl = QtWidgets.QLabel(description)
            desc_lbl.setFont(small)
            layout.addWidget(desc_lbl)

        db_min_spin = QtWidgets.QDoubleSpinBox()
        db_min_spin.setRange(-120, 20)
        db_min_spin.setDecimals(1)
        db_min_spin.setSuffix(" dB")
        db_min_spin.setValue(AS.AppSettings.db_min())

        db_max_spin = QtWidgets.QDoubleSpinBox()
        db_max_spin.setRange(-120, 20)
        db_max_spin.setDecimals(1)
        db_max_spin.setSuffix(" dB")
        db_max_spin.setValue(AS.AppSettings.db_max())

        _range_block(
            dg,
            "Frequency Range",
            self.min_spin, self.max_spin,
            "Hz",
            "Frequency range shown in the spectrum chart",
        )
        _range_block(
            dg,
            "Magnitude Range",
            db_min_spin, db_max_spin,
            "dB",
            "Magnitude range shown in the spectrum chart",
        )

        # db range persisted on Apply only

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

        # Show Unknown Modes (guitar only) — first, matching Swift order
        show_unknown_widget = QtWidgets.QWidget()
        su_layout = QtWidgets.QVBoxLayout(show_unknown_widget)
        su_layout.setContentsMargins(0, 4, 0, 0)
        su_layout.setSpacing(2)
        show_unknown_cb = QtWidgets.QCheckBox("Show Unknown Modes")
        show_unknown_cb.setToolTip("Display peaks that don't fall within known mode classification ranges")
        show_unknown_cb.setChecked(AS.AppSettings.show_unknown_modes())
        # show_unknown persisted on Apply only
        unknown_desc = QtWidgets.QLabel("Display peaks that don't fall within known mode ranges")
        unknown_desc.setFont(small)
        su_layout.addWidget(show_unknown_cb)
        su_layout.addWidget(unknown_desc)
        an.addWidget(show_unknown_widget)

        # Analysis Frequency Range — same _range_block pattern as Display
        an_f_min_spin = QtWidgets.QDoubleSpinBox()
        an_f_min_spin.setRange(0, 22050)
        an_f_min_spin.setDecimals(0)
        an_f_min_spin.setSuffix(" Hz")
        an_f_min_spin.setValue(AS.AppSettings.analysis_f_min())

        an_f_max_spin = QtWidgets.QDoubleSpinBox()
        an_f_max_spin.setRange(0, 22050)
        an_f_max_spin.setDecimals(0)
        an_f_max_spin.setSuffix(" Hz")
        an_f_max_spin.setValue(AS.AppSettings.analysis_f_max())

        # analysis range persisted on Apply only

        _range_block(
            an,
            "Analysis Frequency Range",
            an_f_min_spin, an_f_max_spin,
            "Hz",
            "Frequency range used for peak detection",
        )

        # Peak Detection Minimum
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
        # peak_thresh persisted on Apply only
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
            mp_spin.setEnabled(not checked)  # UI only — persisted on Apply

        mp_all_cb.toggled.connect(_on_all_peaks_toggled)
        # mp_spin persisted on Apply only
        an.addWidget(max_peaks_widget)

        # Hysteresis Margin
        hyst_hdr = QtWidgets.QLabel("Hysteresis Margin")
        hyst_hdr.setFont(hdr_font)
        an.addWidget(hyst_hdr)
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
            hyst_readout.setText(f"{val * 0.5:.1f} dB")  # UI only — persisted on Apply

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
        device_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed
        )
        device_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        le = device_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        dev_row.addWidget(device_combo)
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
                    _update_cal_display()  # _on_cal_selected will update status via combo signal

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
        cal_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed
        )
        cal_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        le = cal_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        cal_row.addWidget(cal_combo)
        aud.addLayout(cal_row)

        def _rebuild_cal_combo() -> None:
            cal_combo.blockSignals(True)
            cal_combo.clear()
            cal_combo.addItem("None (Uncalibrated)", userData=None)
            for c in _mc_mod.CalibrationStorage.load_all():
                cal_combo.addItem(c.name, userData=c.id)
            cal_combo.blockSignals(False)

        def _update_cal_display() -> None:
            _rebuild_cal_combo()
            cur_dev = device_combo.currentText()
            active = _mc_mod.CalibrationStorage.calibration_for_device(cur_dev)
            if active:
                for i in range(cal_combo.count()):
                    if cal_combo.itemData(i) == active.id:
                        cal_combo.setCurrentIndex(i)
                        return
            cal_combo.setCurrentIndex(0)

        def _on_cal_selected(index: int) -> None:
            """Activate the selected calibration for the current device."""
            cal_id = cal_combo.itemData(index)
            cur_dev = device_combo.currentText()
            if cal_id:
                cal = next(
                    (c for c in _mc_mod.CalibrationStorage.load_all() if c.id == cal_id),
                    None,
                )
                if cal:
                    _mc_mod.CalibrationStorage.set_calibration_for_device(cur_dev, cal.id)
                    self.fft_canvas.load_calibration_from_profile(cal)
                    self.set_calibration_status(cal.name)
            else:
                _mc_mod.CalibrationStorage.set_calibration_for_device(cur_dev, None)
                self.fft_canvas.clear_calibration()
                self.set_calibration_status("")
            _update_cal_meta()

        cal_combo.currentIndexChanged.connect(_on_cal_selected)
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
            try:
                cal = _mc_mod.MicrophoneCalibration.from_path(path)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(
                    dlg, "Calibration Error",
                    f"Could not parse calibration file:\n{path}\n\n{exc}",
                )
                return
            _mc_mod.CalibrationStorage.save(cal)
            AS.AppSettings.set_calibration_path(os.path.dirname(path))
            dev_name = device_combo.currentText()
            if dev_name:
                _mc_mod.CalibrationStorage.set_calibration_for_device(dev_name, cal.id)
            self.fft_canvas.load_calibration_from_profile(cal)
            self.set_calibration_status(cal.name)
            _update_cal_display()

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
            cal_id = cal_combo.itemData(cal_combo.currentIndex())
            if not cal_id:
                cal_meta_widget.setVisible(False)
                return
            cal = next(
                (c for c in _mc_mod.CalibrationStorage.load_all() if c.id == cal_id), None
            )
            if cal is None:
                cal_meta_widget.setVisible(False)
                return
            if cal.sensitivity_factor is not None:
                cal_meta_sens_lbl.setText(f"Sensitivity: {cal.sensitivity_factor:.2f} dB")
                cal_meta_sens_lbl.setVisible(True)
            else:
                cal_meta_sens_lbl.setVisible(False)
            cal_meta_points_lbl.setText(f"Data points: {len(cal.correction_points)}")
            fr = cal.freq_range
            cal_meta_range_lbl.setText(f"{fr[0]:.0f}–{fr[1]:.0f} Hz" if fr else "")
            cal_meta_widget.setVisible(True)

        _update_cal_meta()

        delete_cal_btn = QtWidgets.QPushButton(
            qta.icon("mdi.trash-can-outline"), "Delete All Calibrations"
        )
        delete_cal_btn.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        )

        def _delete_all_calibrations() -> None:
            n = len(_mc_mod.CalibrationStorage.load_all())
            if n == 0:
                return
            box = QtWidgets.QMessageBox(dlg)
            box.setWindowTitle("Delete All Calibrations?")
            box.setText(
                f"This will permanently delete all {n} saved "
                f"calibration{'s' if n != 1 else ''}. This cannot be undone."
            )
            del_btn = box.addButton(
                "Delete All", QtWidgets.QMessageBox.ButtonRole.DestructiveRole
            )
            box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() != del_btn:
                return
            _mc_mod.CalibrationStorage.delete_all()
            self.fft_canvas.clear_calibration()
            self.set_calibration_status("")
            _update_cal_display()

        delete_cal_btn.clicked.connect(_delete_all_calibrations)
        delete_row = QtWidgets.QHBoxLayout()
        delete_row.addWidget(delete_cal_btn)
        delete_row.addStretch()
        aud.addLayout(delete_row)

        cal_footer = QtWidgets.QLabel(
            "Audio input and calibration changes take effect immediately and are "
            "not affected by Cancel. Calibrations are automatically associated "
            "with each device."
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
        hop_context_lbl.setStyleSheet("color: #007AFF;")  # blue, matches Swift accent

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

        hop_note = QtWidgets.QLabel(
            "Controls the overlap between FFT windows. Higher overlap provides smoother "
            "results but reduces frame rate."
        )
        hop_note.setFont(small)
        hop_note.setWordWrap(True)
        fg.addWidget(hop_note)
        fg.addWidget(hop_context_lbl)

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
        help_btn.clicked.connect(_show_help_page)
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

        # ── Snapshot live main-window state for Cancel revert ─────────────
        # (dialog-local widgets are discarded on Cancel; only live-updated
        #  main-window widgets need explicit restoration)
        _snap_f_min = self.min_spin.value()
        _snap_f_max = self.max_spin.value()
        _snap_meas_t = self.measurement_type_combo.currentText()
        _snap_guitar_t = self.guitar_type_combo.currentText()

        def _apply_settings() -> None:
            # Measurement type → main window
            unified = meas_type_combo.currentText()
            mt_val = MT.MeasurementType(unified)
            self.measurement_type_combo.setCurrentText(
                "Guitar" if mt_val.is_guitar else mt_val.short_name
            )
            gt = mt_val.guitar_type
            if gt is not None:
                self.guitar_type_combo.setCurrentText(gt.value)

            # Display frequency range (min_spin/max_spin already live via _on_fmin/fmax_changed)
            AS.AppSettings.set_f_min(self.min_spin.value(), mt_val)
            AS.AppSettings.set_f_max(self.max_spin.value(), mt_val)

            # Display magnitude range
            AS.AppSettings.set_db_min(db_min_spin.value())
            AS.AppSettings.set_db_max(db_max_spin.value())

            # Analysis frequency range
            AS.AppSettings.set_analysis_f_min(an_f_min_spin.value())
            AS.AppSettings.set_analysis_f_max(an_f_max_spin.value())

            # Show Unknown Modes
            AS.AppSettings.set_show_unknown_modes(show_unknown_cb.isChecked())

            # Peak threshold → AppSettings + main-window slider + graph
            final_db = int(peak_thresh_spin.value())
            AS.AppSettings.set_peak_threshold(float(final_db))
            AS.AppSettings.set_threshold(final_db + 100)
            slider_val = max(-100, min(-20, final_db))
            if self.threshold_slider.value() != slider_val:
                self.threshold_slider.setValue(slider_val)

            # Max peaks
            AS.AppSettings.set_max_peaks(0 if mp_all_cb.isChecked() else mp_spin.value())

            # Hysteresis margin
            hyst_db = hyst_slider.value() * 0.5
            self.fft_canvas.set_hysteresis_margin(hyst_db)
            AS.AppSettings.set_hysteresis_margin(hyst_db)

            # Plate / brace / gore / f_vs dimensions
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

            dlg.accept()

        def _cancel_settings() -> None:
            # Restore main-window frequency range (fires _on_fmin/fmax_changed → canvas + AppSettings)
            self.min_spin.setValue(_snap_f_min)
            self.max_spin.setValue(_snap_f_max)
            # Restore measurement type combos
            self.measurement_type_combo.setCurrentText(_snap_meas_t)
            self.guitar_type_combo.setCurrentText(_snap_guitar_t)
            dlg.reject()

        # ── Apply / Cancel buttons ─────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(_cancel_settings)
        apply_btn = QtWidgets.QPushButton("Done")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(_apply_settings)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(apply_btn)
        settings_outer.addLayout(btn_row)

        # Refresh device and calibration display live while the dialog is open
        self.fft_canvas.devicesChanged.connect(_on_device_list_changed)
        dlg.resize(460, 700)
        dlg.exec()
        self.fft_canvas.devicesChanged.disconnect(_on_device_list_changed)

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
        # Stop the processing thread and wait for it to finish before Qt
        # destroys the widget tree.  Without this, QThread::~QThread() is
        # reached while the thread is still running, which causes Qt to
        # fatal-abort (SIGABRT) during Python's atexit cleanup.
        self.fft_canvas.shutdown()
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

    os.environ["QT_LOGGING_TO_CONSOLE"] = "1"
    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.setWindowIcon(QtGui.QIcon(os.path.join(basedir, "icons/guitar-tap.svg")))
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
