"""
Main window class for Guitar Tap.

Mirrors Swift's TapToneAnalysisView.swift — the root view / main window that
hosts the spectrum canvas, controls toolbar, analysis results panel, and
status bar.

The class is split across several mixin-style logical sections (matching Swift
+Extension files); the full split into separate mixin files is pending.
"""

import os

import numpy as np
import sounddevice as sd
from PySide6 import QtWidgets, QtGui, QtCore

import views.fft_canvas as fft_c
from models.analysis_display_mode import AnalysisDisplayMode
from models.annotation_visibility_mode import AnnotationVisibilityMode
import views.shared.peak_card_widget as PT
import views.utilities.tap_settings_view as AS
from models.tap_display_settings import TapDisplaySettings as TDS
import views.tap_analysis_results_view as M
from views.exportable_spectrum_chart import make_exportable_spectrum_view
from models import TapToneMeasurement, ResonantPeak
from models import plate_stiffness_preset as PSP
from models import guitar_type as GT
from models import measurement_type as MT
from models import microphone_calibration as _mc_mod
import views.measurements.measurements_list_view as MD
import views.save_measurement_sheet as SMD
import models.material_properties as PA
import views.help_view as HD
import views.utilities.gt_images as gt_i
import views.fft_analysis_metrics_view as FMV
from views.shared.loading_overlay import LoadingOverlay
from views.comparison_results_view import ComparisonResultsView
import qtawesome as qta

# Package root: src/guitar_tap/views/ → src/guitar_tap/
basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))



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
    """Plate/brace peak list with L/C/FLC mode indicators.

    Mirrors Swift's MaterialPeakRowView rows inside peaksAndModesSection.
    Each row shows: star toggle | frequency | magnitude | L badge | [C] | [FLC]
    The L/C/FLC badges are display-only — they show which peak was auto-identified
    for each phase. Assignment is driven entirely by the analyzer; Redo is the
    only way to change it.
    """

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

    # ── public API ──────────────────────────────────────────────────────

    def set_mode(self, show_cross: bool, show_flc: bool) -> None:
        self._show_cross = show_cross
        self._show_flc   = show_flc
        self._rebuild_rows()

    def update_peaks(self, peaks) -> None:
        """Refresh from a list[ResonantPeak]."""
        if peaks and not isinstance(peaks, np.ndarray):
            self._peaks = [(float(p.frequency), float(p.magnitude)) for p in peaks]
        elif isinstance(peaks, np.ndarray) and peaks.ndim == 2 and peaks.shape[0] > 0:
            # Fallback for direct ndarray calls (e.g. load path).
            self._peaks = [(float(peaks[i, 0]), float(peaks[i, 1]))
                           for i in range(peaks.shape[0])]
        else:
            self._peaks = []
        existing = {f for f, _ in self._peaks}
        if self._long_freq  not in existing: self._long_freq  = 0.0
        if self._cross_freq not in existing: self._cross_freq = 0.0
        if self._flc_freq   not in existing: self._flc_freq   = 0.0
        # Only the identified (auto-selected) peaks are selected — mirrors Swift
        # MaterialPeakRowView where isSelected reflects selectedPeakIDs which contains
        # only the dominant peak(s) set by phase-completion handlers.
        self._selected = {f for f in (self._long_freq, self._cross_freq, self._flc_freq) if f > 0.0}
        self._rebuild_rows()

    def set_assignment(self, long_freq: float, cross_freq: float = 0.0,
                       flc_freq: float = 0.0) -> None:
        self._long_freq  = long_freq
        self._cross_freq = cross_freq
        self._flc_freq   = flc_freq
        # Keep selected set in sync with identified peaks.
        self._selected = {f for f in (self._long_freq, self._cross_freq, self._flc_freq) if f > 0.0}
        self._rebuild_rows()

    def long_freq(self)  -> float: return self._long_freq
    def cross_freq(self) -> float: return self._cross_freq
    def flc_freq(self)   -> float: return self._flc_freq

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

        # Star indicator — display-only, mirrors Swift MaterialPeakRowView which renders
        # a plain Image(systemName:) with no onToggleSelection callback in plate/brace mode.
        is_sel = freq in self._selected
        star = QtWidgets.QLabel("★" if is_sel else "☆")
        star.setFixedSize(24, 24)
        star.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        star_color = "rgb(30,120,255)" if is_sel else "rgb(160,160,160)"
        star_fnt = QtGui.QFont()
        star_fnt.setPointSize(14)
        star.setFont(star_fnt)
        star.setStyleSheet(f"color: {star_color};")
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

        # L badge (always shown) — display-only, shows auto-identified peak
        is_l = (freq == self._long_freq)
        hl.addWidget(self._mode_btn("L", is_l, "#1976D2"))

        # C badge (plate only)
        if self._show_cross:
            is_c = (freq == self._cross_freq)
            hl.addWidget(self._mode_btn("C", is_c, "#E65100"))

        # FLC badge (plate + FLC only)
        if self._show_flc:
            is_flc = (freq == self._flc_freq)
            hl.addWidget(self._mode_btn("FLC", is_flc, "#7B1FA2", width=42))

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

class MaterialInstructionsWidget(QtWidgets.QWidget):
    """Process instructions shown at the bottom of the material scroll view.

    Mirrors Swift plateProcessInstructionsSection / braceProcessInstructionsSection,
    which appear after the plate/brace properties section (not after peaks).
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._show_cross: bool = True
        self._show_flc:   bool = False

        il = QtWidgets.QVBoxLayout(self)
        il.setContentsMargins(0, 4, 0, 0)
        il.setSpacing(4)

        _bold9 = QtGui.QFont()
        _bold9.setPointSize(9)
        _bold9.setBold(True)
        self._instr_title = QtWidgets.QLabel()
        self._instr_title.setFont(_bold9)
        il.addWidget(self._instr_title)

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

        self._rebuild()

    def set_mode(self, show_cross: bool, show_flc: bool) -> None:
        self._show_cross = show_cross
        self._show_flc   = show_flc
        self._rebuild()

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

    def _rebuild(self) -> None:
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
        self._help_dialog: HD.HelpDialog | None = None
        self._metrics_dialog: FMV.FFTAnalysisMetricsView | None = None
        self.avg_enable_saved: bool = False
        self._loaded_resonant_peaks: list = []  # ResonantPeak objects from last loaded measurement
        self._loaded_measurement = None          # full TapToneMeasurement, used for export filtering
        # Mirrors Swift's @State var tapLocation/notes on TapToneAnalysisView.
        # Live text the user types before saving; cleared after save; read by export PDF.
        self._tap_location: str = ""
        self._notes: str = ""

        from _version import __version_string__
        self.setWindowTitle(f"Guitar Tap {__version_string__}")

        # Menu bar
        #
        # The Python app is cross-platform (Windows/Linux primary, macOS also supported).
        # Qt renders the menu bar inside the window on Windows and Linux.  On macOS,
        # Qt moves it to the top-of-screen system menu bar automatically — no platform
        # guards are needed in code.
        #
        # Certain QAction MenuRole values cause Qt to relocate actions on macOS:
        #   AboutRole       → placed as first item in the system Application menu
        #   PreferencesRole → placed after About in the system Application menu
        # On Windows/Linux these roles are ignored and the actions stay in the menu
        # where they were added, so the GuitarTap menu is always visible there.
        #
        # The Swift app (macOS/iOS only) uses SwiftUI CommandGroup to build its menus.
        # Python ↔ Swift menu correspondence (Python is primary; Swift is macOS-native twin):
        #   GuitarTap menu: About Guitar Tap… ↔  .appInfo CommandGroup (system-provided)
        #                   Settings… (Ctrl+,) ↔  CommandGroup(after: .appInfo) Settings… (⌘,)
        #   File menu:      Close (Ctrl+W)     ↔  standard Window-scene Close item (⌘W)
        #                   Save Measurement…  ↔  CommandGroup(after: .saveItem) Save… (⌘S)
        #                   Export Spectrum…   ↔  Export Spectrum Image… (⌘E)
        #                   Export PDF…        ↔  Export PDF Report… (⇧⌘E)
        #   View menu:      Auto dB (Ctrl+0)   ↔  CommandGroup(after: .sidebar) Auto dB (⌘0)
        #                   Cycle Annotations  ↔  Cycle Annotations (⌘`)
        #                   Show Metrics       ↔  Show Metrics (⌘M)
        #                   Show Measurements  ↔  Show Measurements (⌘L)
        #   Help menu:      Guitar Tap Help (F1) ↔  CommandGroup(replacing: .help) (⌘?)

        import sys as _sys
        mb = self.menuBar()

        # ── Menu structure by platform ────────────────────────────────────────
        #
        # macOS:
        #   App menu (auto):  About Guitar Tap…  /  Settings… (⌘,)  /  Quit
        #                     Qt moves AboutRole + PreferencesRole here automatically.
        #   File:             Close (⌘W)  |  Save  |  Export…  /  Export PDF…
        #   View:             Auto dB  /  Cycle Annotations  |  Show Metrics  /  Show Measurements
        #   Help:             Guitar Tap Help
        #
        # Windows:
        #   File:             Save  |  Export…  /  Export PDF…  |  Settings…  |  Exit
        #   View:             (same as macOS)
        #   Help:             Guitar Tap Help  |  About Guitar Tap…
        #
        # Linux:
        #   File:             Save  |  Export…  /  Export PDF…  |  Settings…  |  Quit
        #   View:             (same as macOS)
        #   Help:             Guitar Tap Help  |  About Guitar Tap…
        # ─────────────────────────────────────────────────────────────────────

        # macOS only: GuitarTap app menu — Qt automatically moves AboutRole and
        # PreferencesRole into the system Application menu and hides this menu.
        if _sys.platform == "darwin":
            app_menu = mb.addMenu("GuitarTap")
            about_action_mac = QtGui.QAction("About Guitar Tap…", self)
            about_action_mac.setMenuRole(QtGui.QAction.MenuRole.AboutRole)
            about_action_mac.triggered.connect(self._show_about)
            app_menu.addAction(about_action_mac)
            settings_action_mac = QtGui.QAction("Settings…", self)
            settings_action_mac.setShortcut(QtGui.QKeySequence("Ctrl+,"))
            settings_action_mac.setMenuRole(QtGui.QAction.MenuRole.PreferencesRole)
            settings_action_mac.triggered.connect(self._show_settings)
            app_menu.addAction(settings_action_mac)

        # -- File menu --
        file_menu = mb.addMenu("File")

        if _sys.platform == "darwin":
            # macOS: "Close" mirrors the standard Window-scene Close item (⌘W).
            close_action = QtGui.QAction("Close", self)
            close_action.setShortcut(QtGui.QKeySequence.StandardKey.Close)
            close_action.triggered.connect(self.close)
            file_menu.addAction(close_action)
            file_menu.addSeparator()

        play_file_action = QtGui.QAction("Play Audio File…", self)
        play_file_action.setShortcut(QtGui.QKeySequence("Ctrl+Alt+O"))
        play_file_action.triggered.connect(self._open_audio_file)
        file_menu.addAction(play_file_action)

        file_menu.addSeparator()

        self._menu_save_action = QtGui.QAction("Save Measurement…", self)
        self._menu_save_action.setShortcut(QtGui.QKeySequence.StandardKey.Save)
        self._menu_save_action.setEnabled(False)
        self._menu_save_action.triggered.connect(self._on_save_measurement)
        file_menu.addAction(self._menu_save_action)

        file_menu.addSeparator()

        self._menu_export_spectrum_action = QtGui.QAction("Export Spectrum Image…", self)
        self._menu_export_spectrum_action.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        self._menu_export_spectrum_action.setEnabled(False)
        self._menu_export_spectrum_action.triggered.connect(self._on_export_spectrum)
        file_menu.addAction(self._menu_export_spectrum_action)

        self._menu_export_pdf_action = QtGui.QAction("Export PDF Report…", self)
        self._menu_export_pdf_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+E"))
        self._menu_export_pdf_action.setEnabled(False)
        self._menu_export_pdf_action.triggered.connect(self._on_export_pdf)
        file_menu.addAction(self._menu_export_pdf_action)

        if _sys.platform != "darwin":
            # Windows/Linux: Settings in File menu (standard placement on these platforms).
            file_menu.addSeparator()
            settings_action = QtGui.QAction("Settings…", self)
            settings_action.setShortcut(QtGui.QKeySequence("Ctrl+,"))
            settings_action.triggered.connect(self._show_settings)
            file_menu.addAction(settings_action)
            # Exit (Windows) / Quit (Linux) at the very bottom of File menu.
            file_menu.addSeparator()
            exit_label = "Exit" if _sys.platform == "win32" else "Quit"
            exit_action = QtGui.QAction(exit_label, self)
            exit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
            exit_action.triggered.connect(self.close)
            file_menu.addAction(exit_action)

        # -- View menu --
        view_menu = mb.addMenu("View")

        self._menu_auto_db_action = QtGui.QAction("Auto dB", self)
        self._menu_auto_db_action.setShortcut(QtGui.QKeySequence("Ctrl+0"))
        self._menu_auto_db_action.setCheckable(True)
        self._menu_auto_db_action.triggered.connect(self._on_menu_auto_db)
        view_menu.addAction(self._menu_auto_db_action)

        cycle_ann_action = QtGui.QAction("Cycle Annotations", self)
        cycle_ann_action.setShortcut(QtGui.QKeySequence("Ctrl+`"))
        cycle_ann_action.triggered.connect(self._on_cycle_annotation_mode)
        view_menu.addAction(cycle_ann_action)

        view_menu.addSeparator()

        show_metrics_action = QtGui.QAction("Show Metrics", self)
        show_metrics_action.setShortcut(QtGui.QKeySequence("Ctrl+M"))
        show_metrics_action.triggered.connect(self._show_metrics)
        view_menu.addAction(show_metrics_action)

        show_measurements_action = QtGui.QAction("Show Measurements", self)
        show_measurements_action.setShortcut(QtGui.QKeySequence("Ctrl+L"))
        show_measurements_action.triggered.connect(self._on_open_measurements)
        view_menu.addAction(show_measurements_action)

        # -- Help menu --
        help_menu = mb.addMenu("Help")
        help_action = QtGui.QAction("Guitar Tap Help", self)
        help_action.setShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.HelpContents))
        help_action.setMenuRole(QtGui.QAction.MenuRole.NoRole)
        help_action.triggered.connect(self._show_help)
        help_menu.addAction(help_action)

        if _sys.platform != "darwin":
            # Windows/Linux: About belongs in the Help menu (standard placement).
            help_menu.addSeparator()
            about_action = QtGui.QAction("About Guitar Tap…", self)
            about_action.triggered.connect(self._show_about)
            help_menu.addAction(about_action)

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
            "fft_size": 4 * 16384,
        }
        f_range: dict[str, int] = {
            "f_min": AS.AppSettings.f_min(),
            "f_max": AS.AppSettings.f_max(),
        }

        # Build FftCanvas first — everything else references it
        self.fft_canvas = fft_c.FftCanvas(
            fft_settings["fft_size"],
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

        # Left: canvas + material instructions panel (below graph, plate/brace only)
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

        # Loading overlay — covers the central widget during slow export operations.
        # Mirrors Swift LoadingOverlay placed via .overlay on the root content view.
        self._loading_overlay = LoadingOverlay(main_widget)

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

        self._play_file_btn = QtWidgets.QPushButton(
            qta.icon("fa5s.file-audio"), "Play File\u2026"
        )
        self._play_file_btn.setToolTip(
            "Feed an audio file through the analysis pipeline\n"
            "(WAV, AIFF, FLAC \u2014 same pipeline as microphone, for cross-platform comparison)"
        )
        self._play_file_btn.clicked.connect(self._open_audio_file)
        hl.addWidget(self._play_file_btn)

        hl.addSpacing(4)

        self.auto_db_btn = QtWidgets.QToolButton()
        self.auto_db_btn.setIcon(qta.icon("mdi.swap-vertical-circle-outline"))
        self.auto_db_btn.setIconSize(QtCore.QSize(18, 18))
        self.auto_db_btn.setText("Auto dB")
        self.auto_db_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.auto_db_btn.setStyleSheet(
            "QToolButton { border: none; }"
            "QToolButton:checked { border: none; color: palette(button-text); }"
        )
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
        _saved_mode = TDS.annotation_visibility_mode()
        _saved_idx = next(
            (i for i, mode in enumerate(self._ANN_MODES) if mode == _saved_mode), 0
        )
        self._ann_mode_idx: int = _saved_idx
        self.annotations_btn.setIcon(qta.icon(self._ANN_MODES[_saved_idx].icon_name))
        self.annotations_btn.setToolTip(
            f"Annotation visibility: {_saved_mode.label}\n"
            "Click to cycle: Selected → None → All"
        )
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
        self.tap_num_spin.setToolTip("Number of taps to accumulate and average")
        self.tap_num_spin.setMaximumWidth(60)
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
        self.threshold_slider, self.peak_min_readout, self.peak_min_reset_btn = \
            _db_slider_group(
                "Peak Min:", -100, -20, peak_min_val, 40,
                "Minimum magnitude a spectral peak must have to be reported\n"
                "(shown as green line on the spectrum)",
            )
        self.peak_min_reset_btn.clicked.connect(lambda: self.threshold_slider.setValue(-60))

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

        # Comparison mode grid — replaces peak list while comparing.
        # Shows Air / Top / Back frequencies per spectrum (mirrors Swift ComparisonResultsView).
        self._comparison_results_view = ComparisonResultsView()
        self._comparison_results_view.setVisible(False)
        vbox.addWidget(self._comparison_results_view, stretch=1)

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

        # ── Gore Target Thickness box (shown immediately after peaks — key result) ──
        # Mirrors Swift: goreThicknessSectionView is placed BEFORE platePropertiesSection.
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

        # Separator between gore box and plate properties (mirrors Swift Divider).
        # Hidden when gore is hidden so there's no double-separator.
        self._gore_sep = _hsep()
        self._gore_sep.setVisible(False)
        ps_vbox.addWidget(self._gore_sep)

        # ── Plate Properties section (mirrors Swift platePropertiesSection) ──

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

        ms_vbox.addWidget(self._plate_section)

        self._brace_section.setVisible(False)
        self._plate_section.setVisible(False)
        self._material_section.setVisible(False)

        # ── Wrap _material_peak_widget + _material_section in a scroll area ──
        # Process instructions — shown after plate/brace properties (mirrors Swift layout:
        # plateProcessInstructionsSection / braceProcessInstructionsSection appear at the
        # bottom of the scroll view, after goreThicknessSectionView and platePropertiesSection).
        self._material_instr_widget = MaterialInstructionsWidget()

        _mat_container = QtWidgets.QWidget()
        _mat_vbox = QtWidgets.QVBoxLayout(_mat_container)
        _mat_vbox.setContentsMargins(0, 0, 0, 0)
        _mat_vbox.setSpacing(8)
        _mat_vbox.addWidget(self._material_peak_widget)
        _mat_vbox.addWidget(self._material_section)
        _mat_vbox.addWidget(_hsep())
        _mat_vbox.addWidget(self._material_instr_widget)
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


        return panel

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
        _frozen_txt = QtWidgets.QLabel("Complete")
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
        # Wide enough to fit "Phase 1/2 · Tap 3/5" when numberOfTaps > 1.
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

        Mirrors Swift's materialInstructionsView (GroupBox layout):
          Row 1: [dot] [shortStatus]  [Spacer]  [Phase N/M]
          Divider
          Row 2: [icon]  [title]
                         [description]
        """
        frame = QtWidgets.QFrame()
        frame.setObjectName("material_instr_panel")
        frame.setStyleSheet(
            "#material_instr_panel { border-top: 1px solid palette(mid); }"
        )
        vl = QtWidgets.QVBoxLayout(frame)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(4)

        # ── GroupBox title — mirrors Swift GroupBox("Plate Measurement") label ──
        _title_font = QtGui.QFont()
        _title_font.setPointSize(9)
        _title_font.setBold(True)
        self._mip_group_title_lbl = QtWidgets.QLabel("Plate Measurement")
        self._mip_group_title_lbl.setFont(_title_font)
        self._mip_group_title_lbl.setStyleSheet("color: palette(shadow);")
        vl.addWidget(self._mip_group_title_lbl)

        # ── Row 1: dot + shortStatus + spacer + step counter ────────────
        row1 = QtWidgets.QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        # Phase colour dot
        self._mip_dot = QtWidgets.QLabel()
        self._mip_dot.setFixedSize(10, 10)
        self._mip_dot.setStyleSheet(
            "QLabel { background-color: gray; border-radius: 5px; }"
        )
        row1.addWidget(self._mip_dot, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        # Short status text — e.g. "L tap...", "Review L" (colored like the dot)
        _bold9 = QtGui.QFont()
        _bold9.setPointSize(9)
        _bold9.setBold(True)
        self._mip_short_status_lbl = QtWidgets.QLabel("Ready")
        self._mip_short_status_lbl.setFont(_bold9)
        self._mip_short_status_lbl.setStyleSheet("color: gray;")
        row1.addWidget(self._mip_short_status_lbl)

        row1.addStretch(1)

        # Phase counter on the right — e.g. "Phase 1/3", "✓" (secondary color)
        _sm9 = QtGui.QFont()
        _sm9.setPointSize(9)
        self._mip_step_lbl = QtWidgets.QLabel("")
        self._mip_step_lbl.setFont(_sm9)
        self._mip_step_lbl.setStyleSheet("color: palette(shadow);")
        self._mip_step_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._mip_step_lbl.setMinimumWidth(70)
        row1.addWidget(self._mip_step_lbl)

        vl.addLayout(row1)

        # ── Divider ──────────────────────────────────────────────────────
        div = QtWidgets.QFrame()
        div.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        div.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        vl.addWidget(div)

        # ── Row 2: icon + (title / description) ─────────────────────────
        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(10)

        # Phase icon (qtawesome SF-symbol equivalent)
        self._mip_icon_lbl = QtWidgets.QLabel()
        self._mip_icon_lbl.setFixedSize(30, 30)
        self._mip_icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self._mip_icon_lbl, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        # Title + description stacked
        txt = QtWidgets.QVBoxLayout()
        txt.setContentsMargins(0, 0, 0, 0)
        txt.setSpacing(2)

        _med9 = QtGui.QFont()
        _med9.setPointSize(9)
        self._mip_title_lbl = QtWidgets.QLabel("Press New Tap to begin")
        self._mip_title_lbl.setFont(_med9)
        txt.addWidget(self._mip_title_lbl)

        _cap9 = QtGui.QFont()
        _cap9.setPointSize(9)
        self._mip_body_lbl = QtWidgets.QLabel(
            "Press 'New Tap' to start the plate measurement."
        )
        self._mip_body_lbl.setFont(_cap9)
        self._mip_body_lbl.setStyleSheet("color: palette(shadow);")
        self._mip_body_lbl.setWordWrap(True)
        txt.addWidget(self._mip_body_lbl)

        row2.addLayout(txt, stretch=1)
        vl.addLayout(row2)

        frame.setVisible(False)  # Shown when plate/brace type is selected
        return frame

    def _show_metrics(self) -> None:
        """Non-modal dialog showing live FFT diagnostics.

        Mirrors Swift ``TapToneAnalysisView`` Metrics toolbar button action —
        presents ``FFTAnalysisMetricsView`` as a non-modal sheet.
        """
        if self._metrics_dialog and self._metrics_dialog.isVisible():
            self._metrics_dialog.raise_()
            self._metrics_dialog.activateWindow()
            return

        self._metrics_dialog = FMV.FFTAnalysisMetricsView(self.fft_canvas, parent=self)
        self._metrics_dialog.destroyed.connect(lambda: setattr(self, "_metrics_dialog", None))
        self._metrics_dialog.show()

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

        canvas.plateStatusChanged.connect(self._on_plate_status_changed)
        canvas.plateAnalysisComplete.connect(self._on_plate_analysis_complete)

        # Peaks table ← canvas
        # peaksChanged carries ALL peaks (mirrors Swift currentPeaks).
        # _on_peaks_changed_results applies the viewport filter (fmin/fmax) before
        # forwarding to the widget — matching Swift sortedPeaksWithModes in TapAnalysisResultsView.
        self._current_peaks_all = None  # cache of last all-peaks array
        canvas.peaksChanged.connect(self._on_peaks_changed_results)
        canvas.peaksChanged.connect(self._on_peaks_changed_ratios)
        canvas.peaksChanged.connect(self._material_peak_widget.update_peaks)
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
        canvas.statusMessageChanged.connect(self._on_status_message_changed)
        # Mirrors Swift @Published var isMeasurementComplete driving view updates reactively.
        canvas.measurementComplete.connect(self.set_measurement_complete)
        # Mirrors Swift SpectrumView body reading tap.loadedMeasurementName ?? "New" reactively.
        canvas.loadedMeasurementNameChanged.connect(canvas.set_loaded_measurement_name)
        # Mirrors Swift chartTitle = fft.playingFileName ?? tap.loadedMeasurementName ?? "New".
        canvas.playingFileNameChanged.connect(canvas.set_playing_file_name)
        # Mirrors Swift .tint(fft.isPlayingFile ? .orange : .blue) on the Play File button.
        # playingFileNameChanged fires with the filename when file playback starts and None
        # when it ends — dedicated signal, no guard needed.
        canvas.playingFileNameChanged.connect(self._on_playing_file_changed)
        # Mirrors Swift .onChange(of: tap.showLoadedSettingsWarning) driving banner animation.
        canvas.showLoadedSettingsWarningChanged.connect(self._on_loaded_settings_warning_changed)
        # Mirrors Swift fftAnalyzer.setInputDevice(match) called inside loadMeasurement().
        canvas.requestDeviceSwitch.connect(self._on_request_device_switch)
        # Mirrors Swift @Published var microphoneWarning driving alert sheet.
        canvas.microphoneWarningChanged.connect(self._on_microphone_warning_changed)
        canvas.ringOutMeasured.connect(self.set_ring_out)
        canvas.ringOutMeasured.connect(self._on_ring_out_measured)
        canvas.tapCountChanged.connect(self.set_tap_count)
        canvas.devicesChanged.connect(self._on_devices_changed)
        canvas.currentDeviceLost.connect(self._on_device_lost)
        try:
            from models.audio_device import filter_input_devices as _filt
            self._known_input_device_names: set[str] = {
                str(d["name"]) for d in _filt(list(sd.query_devices()))
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

        saved_mt = AS.AppSettings.measurement_type()
        # Persist the resolved measurement type so QSettings is always in sync with
        # TapDisplaySettings — mirrors Swift where TapDisplaySettings.measurementType
        # is written once from UserDefaults/defaults on init.
        AS.AppSettings.set_measurement_type(saved_mt)

        saved_gt = AS.AppSettings.guitar_type()
        canvas.set_guitar_type_bands(saved_gt)
        self._update_measurement_badge()
        self.reset_auto_selection_btn.setVisible(TDS.measurement_type().is_guitar)

        self.set_measurement_complete(False)

        # Seed the model's annotation_mode so the live FFT path respects the saved setting
        self._apply_annotation_mode(self._ANN_MODES[self._ann_mode_idx])

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
        # Mirror Swift exactly:
        #   tap.isDetecting && (isPlate || tap.currentTapCount > 0)
        # isDetecting becomes False at the approve/redo step — hiding the count during review.
        mt = TDS.measurement_type()
        is_detecting = self.fft_canvas.analyzer.is_detecting
        is_plate_or_brace = not mt.is_guitar
        show = is_detecting and (is_plate_or_brace or captured > 0)
        # For plate with numberOfTaps > 1 the tap counter is embedded in the phase label
        # (mirrors Swift "Phase N/total · Tap p/q"), so hide the standalone tap count label.
        embed_in_phase = show and not mt.is_brace and not mt.is_guitar and total > 1
        if show:
            pct = int(min(captured, total) * 100 / max(total, 1))  # clamp — mirrors Swift min(1.0, ...)
            self._sb_progress.setValue(pct)
            if not embed_in_phase:
                self._sb_tap_count.setText(f"{captured}/{total}")
        self._sb_progress.setVisible(show)
        self._sb_tap_count.setVisible(show and not embed_in_phase)
        # Refresh the phase label text to embed the updated tap count (when visible on plate).
        if self._sb_plate_step_lbl.isVisible() and embed_in_phase:
            self._update_plate_phase_ui()
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
        if self._is_running and not TDS.measurement_type().is_guitar:
            self._sb_avg_lbl.setText(f"{amp - 100.0:.1f} dB")

    def _on_peak_info(self, peak_hz: float, peak_db: float) -> None:
        if self._is_running:
            # Guitar mode: show FFT peak magnitude — mirrors Swift fft.peakMagnitude
            # Plate/brace: _sb_avg_lbl is updated in _on_level_changed (displayLevelDB)
            if TDS.measurement_type().is_guitar:
                self._sb_avg_lbl.setText(f"{peak_db:.1f} dB")
            self._sb_peak_lbl.setText(f"Peak: {peak_db:.1f} dB @ {peak_hz:.1f} Hz")

    def _sb_update_frozen_state(self, frozen: bool) -> None:
        if frozen:
            self._sb_tap_dot.setStyleSheet("color: green;")
            self._sb_tap_msg.setText("Tap Detected!")
            self._sb_tap_msg.setStyleSheet("color: green;")
            # Mirrors Swift: phase/tap count labels are guarded by tap.isDetecting.
            # When frozen, isDetecting is false → labels are hidden.
            self._sb_tap_count.setVisible(False)
            self._sb_plate_step_lbl.setVisible(False)
        else:
            self._sb_tap_dot.setStyleSheet("color: rgba(128,128,128,77);")
            self._sb_tap_msg.setText("Waiting for tap…")
            self._sb_tap_msg.setStyleSheet("color: gray;")

    def _on_menu_auto_db(self, checked: bool) -> None:
        """Toggle Auto dB from the View menu; keeps the toolbar button in sync."""
        self.auto_db_btn.setChecked(checked)

    def _on_auto_db_toggled(self, enabled: bool) -> None:
        if enabled:
            self.auto_db_btn.setIcon(qta.icon("mdi.swap-vertical-circle", color="#27ae60"))
        else:
            self.auto_db_btn.setIcon(qta.icon("mdi.swap-vertical-circle-outline"))
        # Keep the View menu checkmark in sync with the toolbar button state.
        self._menu_auto_db_action.setChecked(enabled)

    def _on_framerate_update(
        self, framerate: float, _sampletime: float, processingtime: float
    ) -> None:
        """Handle a frame-rate update from the FFT processing thread.

        Mirrors Swift's @ObservedObject auto-refresh of FFTAnalysisMetricsView —
        forwards live metrics to the dialog when it is open, and updates the
        results-panel status indicator regardless.
        """
        # Forward to FFTAnalysisMetricsView (mirrors SwiftUI @ObservedObject re-render)
        if self._metrics_dialog and self._metrics_dialog.isVisible():
            self._metrics_dialog.update_metrics(
                framerate=framerate,
                processing_time=processingtime,
                is_running=self._is_running,
                peaks=self.fft_canvas.saved_peaks,
            )

        # Update the results-panel running / stopped status indicator
        if self._is_running:
            self._results_status_dot.setStyleSheet("color: green;")
            self._results_status_lbl.setStyleSheet("color: palette(text);")
            self._results_status_lbl.setText("Analyzing")
        else:
            self._results_status_dot.setStyleSheet("color: gray;")
            self._results_status_lbl.setStyleSheet("color: gray;")
            self._results_status_lbl.setText("Stopped")

    def update_tap_tone_ratio(self, ratio: "float | None") -> None:
        """Update the tap-tone ratio display from a pre-computed ratio.

        Mirrors TapAnalysisResultsView.swift:550,620.
        """
        if ratio is not None:
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
        gt_text = TDS.measurement_type().guitar_type.value if TDS.measurement_type().guitar_type else ""
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
        # loadedMeasurementName is cleared by start_tap_sequence() / reset(), not here.
        # showLoadedSettingsWarning is cleared by the model via showLoadedSettingsWarningChanged signal.

        # Refresh status label colour immediately so that any status message emitted
        # *before* measurementComplete(True) (e.g. "Loaded measurement (frozen)...")
        # is displayed in orange.  Mirrors Swift's batched objectWillChange: by the
        # time SwiftUI re-renders Text(tap.statusMessage) the isDetecting flag is
        # already updated, so the foregroundColor(.orange) modifier sees the correct
        # state.  In Python the signal order is serial, so we refresh here.
        self._sb_detect_msg.setStyleSheet("color: orange;" if checked else "")

        self.peak_widget.data_held(checked)
        mt = TDS.measurement_type()
        if not mt.is_guitar:
            self._material_section.setVisible(checked)
        if checked:
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
            self._menu_save_action.setEnabled(True)
            self._menu_export_spectrum_action.setEnabled(True)
            self._menu_export_pdf_action.setEnabled(True)
            self.select_all_btn.setEnabled(mt.is_guitar)
            self.deselect_all_btn.setEnabled(mt.is_guitar)
            self.reset_auto_selection_btn.setEnabled(
                mt.is_guitar and self.peak_widget.model.user_has_modified_peak_selection
            )
        else:
            self.avg_enable.setEnabled(True)
            self.save_measurement_btn.setEnabled(False)
            self.export_spectrum_btn.setEnabled(False)
            self.export_pdf_btn.setEnabled(False)
            self._menu_save_action.setEnabled(False)
            self._menu_export_spectrum_action.setEnabled(False)
            self._menu_export_pdf_action.setEnabled(False)
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
    def _on_peaks_changed_results(self, peaks: object) -> None:
        """Filter all peaks to the current viewport and forward to the results panel.

        Mirrors Swift TapAnalysisResultsView.sortedPeaksWithModes which filters
        analyzer.currentPeaks by minFreq/maxFreq at display time.
        """
        self._current_peaks_all = peaks if isinstance(peaks, list) else []

        # Rule 5a: propagate selection state when peaks change on a frozen measurement.
        #
        # Swift's applyFrozenPeakState() writes selectedPeakIDs which SwiftUI
        # propagates automatically to every view. In Python, _apply_frozen_peak_state()
        # writes analyzer.selected_peak_frequencies but the peaksChanged signal chain
        # (→ _on_peaks_changed_results → update_data_with_modes) never touches
        # peak_widget.model.selected_frequencies.
        #
        # _restore_measurement sets selected_frequencies directly *before* emitting
        # peaks and calls set_measurement_complete(True) *after*, so
        # _is_measurement_complete is False during restore — the guard below correctly
        # skips that path (restore already handled it).
        #
        # Guitar-live path: _is_measurement_complete is False until _on_tap_detected
        # calls set_measurement_complete(True) then auto_select_peaks_by_mode() —
        # also skipped by the guard.
        #
        # Mirrors Swift: applyFrozenPeakState sets selectedPeakIDs which propagates to
        # all views automatically via @Published.
        # For guitar mode, only propagate selection when measurement is complete.
        # For plate/brace, propagate on every peaksChanged so that only the
        # identified peak's star is filled during capture and review phases —
        # mirrors Swift where selectedPeakIDs (managed by phase-completion handlers)
        # drives the star display at all times.
        analyzer = self.fft_canvas.analyzer
        if self._is_measurement_complete or not TDS.measurement_type().is_guitar:
            if not TDS.measurement_type().is_guitar:
                # For plate/brace: build selected_frequencies from all identified peaks.
                # During a live measurement use the analyzer's in-memory peak objects
                # (L/C/FLC as available).  During a loaded/frozen measurement those
                # objects are None, so fall back to the restored selected_frequencies
                # already set by _restore_measurement — do not overwrite it.
                az = self.fft_canvas.analyzer
                live_freqs = {
                    p.frequency
                    for p in (az.selected_longitudinal_peak, az.selected_cross_peak, az.selected_flc_peak)
                    if p is not None
                }
                if live_freqs:
                    self.peak_widget.model.selected_frequencies = live_freqs
                # else: frozen/loaded measurement — _restore_measurement already set
                # selected_frequencies from selected*PeakID; leave it untouched.
            else:
                sel_freqs = getattr(analyzer, "selected_peak_frequencies", None)
                if sel_freqs is not None:
                    self.peak_widget.model.selected_frequencies = set(sel_freqs)

        # Push plate/brace phase peak IDs to the model on every peaksChanged so
        # annotations label the identified peak immediately — mirrors Swift's
        # @Published effectiveLongitudinalPeakID auto-propagation.
        az = self.fft_canvas.analyzer
        if not TDS.measurement_type().is_guitar:
            pm = self.peak_widget.model
            pm.selected_longitudinal_peak_id = az.effective_longitudinal_peak_id
            pm.selected_cross_peak_id        = az.effective_cross_peak_id
            pm.selected_flc_peak_id          = az.effective_flc_peak_id

        self._refresh_results_peaks()

    def _refresh_results_peaks(self) -> None:
        """Re-apply the viewport filter and pair each peak with its mode.

        Mirrors Swift TapAnalysisResultsView.sortedPeaksWithModes (line 276–291)
        which filters analyzer.currentPeaks by [minFreq, maxFreq] then maps each
        peak through analyzer.peakMode(for:) to produce (peak, mode) tuples.
        The pre-classified tuples are passed to update_data_with_modes so the
        model installs the analyzer's identifiedModes directly without re-running
        classify_all.

        Swift sortedPeaksWithModes:
          measurementType.isGuitar
              ? (peak.frequency >= minFreq && peak.frequency <= maxFreq)
              : true    // plate/brace: never filter by display range
        """
        peaks = self._current_peaks_all
        if not peaks:
            self.peak_widget.update_data_with_modes([])
            return
        fmin = self.fft_canvas.minFreq
        fmax = self.fft_canvas.maxFreq
        analyzer = self.fft_canvas.analyzer
        from models.guitar_mode import GuitarMode
        mt = TDS.measurement_type()
        show_unknown = AS.AppSettings.show_unknown_modes()
        # Mirrors Swift: plate/brace bypasses the frequency range filter (`: true`).
        # Guitar mode filters to the displayed viewport.
        peaks_with_modes = [
            (p, analyzer.peak_mode(p))
            for p in peaks
            if not mt.is_guitar or (fmin <= p.frequency <= fmax)
        ]
        if mt.is_guitar and not show_unknown:
            peaks_with_modes = [
                (p, m) for p, m in peaks_with_modes
                if m != GuitarMode.UNKNOWN
            ]
        self.peak_widget.update_data_with_modes(peaks_with_modes)

        # For plate/brace: mirror Swift's live reactive MaterialPeakRowView binding:
        #   isLongitudinal: effectiveLongitudinalPeakID == item.peak.id
        # Swift re-evaluates this on every body render. Python must call
        # set_assignment whenever peaks change so the L/C/FLC buttons stay
        # in sync — _on_plate_analysis_complete only fires after all phases
        # complete, so intermediate phases need this path.
        if not mt.is_guitar:
            long_id  = analyzer.effective_longitudinal_peak_id
            cross_id = analyzer.effective_cross_peak_id
            flc_id   = analyzer.effective_flc_peak_id
            # Resolve UUIDs to frequencies via the current peak list.
            peak_by_id = {p.id: p for p in peaks}
            long_freq  = float(peak_by_id[long_id].frequency)  if long_id  and long_id  in peak_by_id else 0.0
            cross_freq = float(peak_by_id[cross_id].frequency) if cross_id and cross_id in peak_by_id else 0.0
            flc_freq   = float(peak_by_id[flc_id].frequency)   if flc_id   and flc_id   in peak_by_id else 0.0
            self._material_peak_widget.set_assignment(long_freq, cross_freq,
                                                      flc_freq=flc_freq)

    def _on_canvas_freq_range_changed(self, fmin: int, fmax: int) -> None:
        """Update freq label and re-filter the results panel when viewport changes."""
        self.freq_range_label.setText(f"Showing {fmin} – {fmax} Hz")
        self._refresh_results_peaks()

    def _update_freq_range_label(self) -> None:
        self.freq_range_label.setText(
            f"Showing {self.fft_canvas.minFreq} – {self.fft_canvas.maxFreq} Hz"
        )

    # ================================================================
    # Annotation visibility cycling
    # ================================================================

    # (mode, icon_name) — order defines the cycle; matches Swift: selected→all→none
    _ANN_MODES: tuple[AnnotationVisibilityMode, ...] = (
        AnnotationVisibilityMode.SELECTED,
        AnnotationVisibilityMode.NONE,
        AnnotationVisibilityMode.ALL,
    )

    def _on_cycle_annotation_mode(self) -> None:
        self._ann_mode_idx = (self._ann_mode_idx + 1) % len(self._ANN_MODES)
        next_mode = self._ANN_MODES[self._ann_mode_idx]
        self.annotations_btn.setIcon(qta.icon(next_mode.icon_name))
        self.annotations_btn.setToolTip(
            f"Annotation visibility: {next_mode.label}\n"
            "Click to cycle: Selected → None → All"
        )
        TDS.set_annotation_visibility_mode(next_mode)
        self._apply_annotation_mode(next_mode)

    def _apply_annotation_mode(self, mode: AnnotationVisibilityMode) -> None:
        """Set the annotation visibility mode.

        Setting annotation_mode on the model is reactive: its property setter
        calls update_data() which re-emits exactly the right annotation signals
        for the current peaks and mode — mirroring Swift where changing
        annotationVisibilityMode (a @Published property) automatically
        re-evaluates the visiblePeaks computed property.
        """
        self.peak_widget.model.annotation_mode = mode

    # ================================================================
    # Threshold / hysteresis
    # ================================================================

    def _on_threshold_changed(self, db_val: int) -> None:
        self.fft_canvas.set_threshold(db_val + 100)
        AS.AppSettings.set_threshold(db_val + 100)
        AS.AppSettings.set_peak_threshold(float(db_val))  # keep single source of truth in sync — mirrors Swift peakThreshold didSet
        self.peak_min_readout.setText(f"{db_val} dB")

    def _on_loaded_settings_warning_changed(self, active: bool) -> None:
        """Show or hide the loaded-settings warning banner.

        Connected to canvas.showLoadedSettingsWarningChanged — mirrors Swift
        .onChange(of: tap.showLoadedSettingsWarning) driving banner animation.
        """
        if active:
            analyzer = self.fft_canvas.analyzer
            threshold_db = int(analyzer.loaded_tap_detection_threshold) if analyzer.loaded_tap_detection_threshold is not None else "?"
            num_taps = analyzer.loaded_number_of_taps if analyzer.loaded_number_of_taps is not None else "?"
            self._sb_warning_msg.setText(
                f"Settings from loaded measurement — Threshold: {threshold_db} dB"
                f" · Taps: {num_taps}"
            )
            self._sb_warning_wgt.setVisible(True)
            self._warn_pulse_t = 0.0
            self._warn_pulse_timer.start()
        else:
            self._warn_pulse_timer.stop()
            self._warn_opacity_effect.setOpacity(1.0)
            self._sb_warning_wgt.setVisible(False)

    def _on_request_device_switch(self, device) -> None:
        """Switch to the device emitted by the model after loading a measurement.

        Connected to canvas.requestDeviceSwitch — mirrors Swift
        fftAnalyzer.setInputDevice(match) called inside loadMeasurement().
        """
        canvas = self.fft_canvas
        canvas.set_device(device)
        AS.AppSettings.set_audio_device(device)
        self.device_status_lbl.setText(device.name)

    def _on_microphone_warning_changed(self, warning: "str | None") -> None:
        """Display or clear the mic-not-connected warning.

        Connected to canvas.microphoneWarningChanged — mirrors Swift
        @Published var microphoneWarning driving an alert sheet.
        """
        if warning is None:
            return
        if getattr(self, "_suppress_mic_warning", False):
            self._pending_mic_warning = warning
        else:
            from PySide6 import QtWidgets
            QtWidgets.QMessageBox.warning(self, "Microphone Not Connected", warning)

    def _on_tap_threshold_changed(self, db_val: int) -> None:
        self.fft_canvas.set_tap_threshold(db_val + 100)
        AS.AppSettings.set_tap_threshold(db_val + 100)
        self.tap_threshold_readout.setText(f"{db_val} dB")

    def _on_tap_num_changed(self, n: int) -> None:
        self.fft_canvas.set_tap_num(n)
        # Update the cached total so _plate_step_label() uses the new denominator.
        # In Swift this is reactive: numberOfTaps @Published causes Text(phaseLabel)
        # to re-evaluate automatically. In Python we must update _tap_count_total and
        # refresh the phase label manually whenever the spinner value changes.
        self._tap_count_total = n
        if self._sb_plate_step_lbl.isVisible():
            self._update_plate_phase_ui()

    # ================================================================
    # Tap button state
    # ================================================================

    def _is_in_review_phase(self) -> bool:
        """Return True when the analyzer is paused at a per-phase review state.

        Mirrors Swift TapToneAnalysisView.isInReviewPhase.
        """
        from models.material_tap_phase import MaterialTapPhase as _MTP
        phase = self.fft_canvas.analyzer.material_tap_phase
        return phase in (
            _MTP.REVIEWING_LONGITUDINAL,
            _MTP.REVIEWING_CROSS,
            _MTP.REVIEWING_FLC,
        ) and not TDS.measurement_type().is_guitar

    def _update_tap_buttons(self) -> None:
        """Refresh enabled/disabled state of New Tap, Pause, Cancel, and tap count spinner."""
        tap_num = self.tap_num_spin.value()
        mt = TDS.measurement_type()

        # Mirrors Swift: .disabled(tap.currentTapCount > 0 && !tap.isMeasurementComplete)
        # Lock the tap count spinner once any tap has been detected in the current sequence,
        # so the total can't change mid-measurement. Re-enables when measurement completes.
        self.tap_num_spin.setEnabled(
            not (self._tap_count_captured > 0 and not self._is_measurement_complete)
        )
        is_plate = not mt.is_guitar
        # Mirrors Swift isDetecting: False when paused (pauseTapDetection sets isDetecting=false)
        is_detecting = self._is_running and not self._is_measurement_complete and not self._is_paused
        is_comparing = self.fft_canvas.is_comparing
        in_review = self._is_in_review_phase()

        if in_review:
            # Review phase: New Tap always available (start over), Accept and Redo enabled.
            # Mirrors Swift: newTapButtonDisabled always False for plate/brace,
            # pauseResumeButtonEnabled / cancelButtonEnabled return True in review.
            self.new_tap_btn.setEnabled(self._is_running)
            self.pause_tap_btn.setEnabled(True)
            self.cancel_tap_btn.setEnabled(True)

            # Relabel Pause → Accept with green tint.
            # Mirrors Swift: .tint(isInReviewPhase ? .green : nil)
            self.pause_tap_btn.setText("Accept")
            self.pause_tap_btn.setIcon(qta.icon("fa5.check-circle", color="green"))
            self.pause_tap_btn.setStyleSheet("color: green;")

            # Relabel Cancel → Redo <phase> with orange foreground.
            # Mirrors Swift: .foregroundStyle(cancelButtonEnabled ? .orange : .gray)
            from models.material_tap_phase import MaterialTapPhase as _MTP
            phase = self.fft_canvas.analyzer.material_tap_phase
            redo_labels = {
                _MTP.REVIEWING_LONGITUDINAL: "Redo L",
                _MTP.REVIEWING_CROSS:        "Redo C",
                _MTP.REVIEWING_FLC:          "Redo FLC",
            }
            self.cancel_tap_btn.setText(redo_labels.get(phase, "Redo"))
            self.cancel_tap_btn.setIcon(qta.icon("fa5s.undo", color="orange"))
            self.cancel_tap_btn.setStyleSheet("color: orange;")
        else:
            # Normal (non-review) state — restore standard labels first.
            if self._is_paused:
                self.pause_tap_btn.setText("Resume")
                self.pause_tap_btn.setIcon(qta.icon("fa5.play-circle"))
            else:
                self.pause_tap_btn.setText("Pause")
                self.pause_tap_btn.setIcon(qta.icon("fa5.pause-circle"))
            self.pause_tap_btn.setStyleSheet("")
            self.cancel_tap_btn.setText("Cancel")

            # New Tap: always enabled for plate/brace when running or when a
            # measurement is loaded (complete state); for guitar it requires a
            # complete or comparison state.
            # Mirrors Swift newTapButtonDisabled: disabled only when fft.isRunning
            # is false (audio not yet started) AND no measurement has been loaded.
            # In the Python app _is_running is False when a measurement is loaded
            # before the analyzer is started, so we treat _is_measurement_complete
            # as an additional "ready" condition — the user can always start a new
            # tap from a loaded/frozen measurement even before starting audio.
            if is_plate:
                self.new_tap_btn.setEnabled(
                    self._is_running or self._is_measurement_complete or is_comparing
                )
            else:
                self.new_tap_btn.setEnabled(
                    self._is_measurement_complete or is_comparing
                )

            self.pause_tap_btn.setEnabled(is_detecting or self._is_paused)

            # Mirrors Swift cancelButtonEnabled:
            #   plate/brace: True whenever isDetecting (cancel = abort the sequence)
            #   guitar: True only in multi-tap mode before all taps captured
            if is_plate:
                cancel_enabled = is_detecting
            else:
                cancel_enabled = (
                    is_detecting and tap_num > 1
                    and 0 < self._tap_count_captured < tap_num
                )
            self.cancel_tap_btn.setEnabled(cancel_enabled)
            # Mirrors Swift: .foregroundStyle(cancelButtonEnabled ? .orange : .gray)
            self.cancel_tap_btn.setStyleSheet(
                "color: orange;" if cancel_enabled else "color: gray;"
            )
            if cancel_enabled:
                self.cancel_tap_btn.setIcon(qta.icon("fa5.times-circle", color="orange"))
            else:
                self.cancel_tap_btn.setIcon(qta.icon("fa5.times-circle"))

    # ================================================================
    # Pause / Cancel tap detection
    # ================================================================

    def _on_pause_tap(self) -> None:
        if self._is_in_review_phase():
            # In review mode the Pause button acts as Accept.
            self.fft_canvas.analyzer.accept_current_phase()
        elif self._is_paused:
            self.fft_canvas.resume_tap_detection()
        else:
            self.fft_canvas.pause_tap_detection()

    def _on_cancel_tap(self) -> None:
        if self._is_in_review_phase():
            # In review mode the Cancel button acts as Redo.
            self.fft_canvas.analyzer.redo_current_phase()
            self._update_tap_buttons()
            return
        self._is_paused = False
        self.fft_canvas.cancel_tap_sequence()
        self._tap_count_captured = 0
        self._update_tap_buttons()

    def _on_tap_detection_paused(self, paused: bool) -> None:
        self._is_paused = paused
        self._update_tap_buttons()

    # ================================================================
    # Start / Stop
    # ================================================================

    def _start_analyzer(self) -> None:
        self._is_running = True
        self.set_running(True)
        self.fft_canvas.start_analyzer()

    def _open_audio_file(self) -> None:
        """Open a file picker and feed the chosen audio file through the FFT pipeline.

        Uses the same audio-processing queue as the microphone so the FFT, tap
        detection, and peak analysis are completely unchanged.  This allows
        apples-to-apples comparison between platforms using the same recording.

        Mirrors Swift TapToneAnalysisView+Actions.openAudioFile(_:) / openWAVFile().
        """
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Audio File",
            "",
            "Audio files (*.wav *.aif *.aiff *.flac *.ogg);;All files (*)",
        )
        if not path:
            return

        analyzer = self.fft_canvas.analyzer

        try:
            # Start the processing thread if it isn't running yet (first use).
            if not analyzer.mic.proc_thread.isRunning():
                self.fft_canvas.start_analyzer()
            else:
                # Thread already running — reset ring-buffer state for the new source.
                analyzer.mic.proc_thread.reset_state()

            # Mirrors Swift openAudioFile(_:) which calls:
            #   1. fft.startFromFile(url, completion:) — start engine, recompute freq bins
            #   2. tapToneAnalyzer.startTapSequence(skipWarmup: true) — arm tap detection
            # The completion closure in Swift releases security-scoped resource access;
            # here we use it to emit playingFileNameChanged(None) and restore the title.
            def _on_finished() -> None:
                analyzer.playingFileNameChanged.emit(None)

            analyzer.start_from_file(path, on_finished=_on_finished)

            # Emit the playing filename so chartTitle updates reactively.
            # Mirrors Swift: fft.playingFileName (@Published) drives chartTitle computed var.
            analyzer.playingFileNameChanged.emit(analyzer.mic.playing_file_name)

            # Arm tap detection with warmup skipped — the audio source is deterministic
            # so there is no mic startup noise, and the tap may appear in the first 0.5 s.
            # Mirrors Swift: tapToneAnalyzer.startTapSequence(skipWarmup: true)
            analyzer.start_tap_sequence(skip_warmup=True)

            self._is_running = True
            self.set_running(True)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Could not play audio file", str(exc)
            )

    def _on_playing_file_changed(self, name: "str | None") -> None:
        """Tint the Play File button orange while a file is playing, blue otherwise.

        Mirrors Swift .tint(fft.isPlayingFile ? .orange : .blue) on the Play File buttons.
        Connected to canvas.playingFileNameChanged, which fires with the filename when
        file playback starts and with None when it ends — no guard needed since this
        signal is dedicated to file-playback state (unlike loadedMeasurementNameChanged).
        """
        self._play_file_btn.setStyleSheet("color: orange;" if name is not None else "")

    # ================================================================
    # Tap events
    # ================================================================

    def _on_status_message_changed(self, msg: str) -> None:
        """Reflect analyzer.status_message in the status bar label.

        Connected to canvas.statusMessageChanged, which forwards
        analyzer.statusMessageChanged (mirrors Swift Text(tap.statusMessage)
        re-rendering whenever the @Published var statusMessage changes).

        Mirrors Swift: .foregroundColor(tap.isDetecting ? .primary : .orange)
        During review phases isDetecting is False → orange.
        """
        self._sb_detect_msg.setText(msg)
        # Mirrors Swift: .foregroundColor(tap.isDetecting ? .primary : .orange)
        # isDetecting is False when: in a review phase, paused, or measurement complete (frozen).
        in_review = self._is_in_review_phase()
        is_not_detecting = in_review or self._is_paused or self._is_measurement_complete
        self._sb_detect_msg.setStyleSheet(
            "color: orange;" if is_not_detecting else ""
        )

    def _on_tap_detected(self) -> None:
        """Update the status dot when a tap fires.

        Selection is handled in the model layer: both _finish_capture (single-tap)
        and _finish_guitar_tap_sequence (multi-tap) set selected_peak_ids and
        selected_peak_frequencies before emitting peaksChanged, so
        _on_peaks_changed_results already propagates the selection to
        peak_widget.model.selected_frequencies. Mirrors Swift where
        processMultipleTaps() sets selectedPeakIDs synchronously before any
        @Published notifications propagate.
        """
        # Status message is set by the model via statusMessageChanged → _on_status_message_changed.
        self._sb_detect_dot.setStyleSheet("color: orange;")

    def _on_new_tap(self) -> None:
        """Begin a new tap sequence, clearing any in-progress accumulated spectra.

        Mirrors Swift New Tap button action: tap.startTapSequence().
        startTapSequence() sets isMeasurementComplete = false, clears captured
        taps, resets material phase state for plate/brace, and emits measurementComplete(False).
        In Python, start_analyzer() calls analyzer.start_tap_sequence() and also
        restarts the audio processing thread (equivalent to Swift's AVAudioEngine restart
        that occurs when startTapSequence re-arms the audio pipeline).
        """
        # Exit comparison mode first — required when _is_measurement_complete is False
        # (e.g. user entered comparison from live-detecting state).
        if self.fft_canvas.is_comparing:
            self.fft_canvas.clear_comparison()
        self._is_paused = False
        # Clear loaded measurement state — mirrors Swift loadMeasurement clearing
        # currentPeaks/selectedPeakIDs when a new tap begins, ensuring _on_export_pdf
        # reads live analyzer state rather than stale loaded-measurement data.
        self._loaded_resonant_peaks = []
        self._loaded_measurement = None
        self._tap_count_captured = 0
        self._sb_tap_count.setVisible(False)
        self._sb_progress.setVisible(False)
        # restart_tap_sequence() calls analyzer.start_tap_sequence() (sets
        # is_measurement_complete = False, emits measurementComplete(False)) and
        # resets the ring buffer state — without stopping the processing thread.
        # This mirrors Swift's New Tap button calling tap.startTapSequence() on a
        # continuously-running AVAudioEngine (no engine restart on New Tap in Swift).
        # For plate/brace, start_tap_sequence() already transitions material_tap_phase
        # to CAPTURING_LONGITUDINAL — no separate start_plate_analysis() call needed.
        self.fft_canvas.restart_tap_sequence()

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
            self.peak_widget.model.auto_select_peaks_by_mode()
        except Exception:
            pass

    def _on_user_modified_selection_changed(self, modified: bool) -> None:
        self.reset_auto_selection_btn.setEnabled(
            modified and self._is_measurement_complete
        )

    # ================================================================
    # Peaks / ratios
    # ================================================================

    def _on_peaks_changed_ratios(self, peaks: object) -> None:
        if not isinstance(peaks, list) or not peaks:
            return
        # Delegate to the analyzer — mirrors TapAnalysisResultsView.swift:550,620.
        ratio = self.fft_canvas.analyzer.calculate_tap_tone_ratio()
        self.update_tap_tone_ratio(ratio)

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

    def _apply_measurement_type_to_ui(self) -> None:
        """Update all UI elements that depend on the current measurement type.

        This is the load-path equivalent of Swift's .onReceive(tap.$loadedMeasurementType)
        handler — it propagates a measurement-type change to every bound control and
        widget WITHOUT restarting the tap sequence.  Called from both the load path
        (_on_loaded_measurement_type) and the settings-apply path
        (_on_measurement_type_changed), mirroring how Swift separates the two concerns.
        """
        mt = TDS.measurement_type()
        AS.AppSettings.set_measurement_type(mt)
        self.fft_canvas.set_measurement_type(mt)
        # Load the persisted axis range for the newly selected measurement type.
        # Swift initialises @State minFreq/maxFreq from TapDisplaySettings.minFrequency
        # (a per-type stored value) at startup; when the type changes the stored value
        # for the new type is the right range to show (e.g. 20–200 Hz for plate, falling
        # back to the factory default if never explicitly saved by the user).
        self.fft_canvas._reset_both_to_saved()
        self.reset_auto_selection_btn.setVisible(mt.is_guitar)
        self.threshold_slider.setEnabled(mt.is_guitar)
        self.peak_min_readout.setEnabled(mt.is_guitar)
        self.peak_min_reset_btn.setEnabled(mt.is_guitar)
        self.peak_widget.set_is_guitar(mt.is_guitar)
        self._guitar_summary.setVisible(mt.is_guitar)
        self._material_section.setVisible(not mt.is_guitar and self._is_measurement_complete)
        # Toggle peak list: guitar → PeakListWidget; plate/brace → MaterialPeakListWidget
        self.peak_widget.setVisible(mt.is_guitar)
        self._material_scroll.setVisible(not mt.is_guitar)
        self._material_instr_panel.setVisible(not mt.is_guitar)
        if mt.is_guitar:
            gt = mt.guitar_type
            if gt is not None:
                self.fft_canvas.set_guitar_type_bands(gt.value)
        else:
            show_flc = (not mt.is_brace) and AS.AppSettings.measure_flc()
            self._material_peak_widget.set_mode(
                show_cross=not mt.is_brace,
                show_flc=show_flc,
            )
            self._material_instr_widget.set_mode(
                show_cross=not mt.is_brace,
                show_flc=show_flc,
            )
            self._mat_title.setText(
                "Brace Properties" if mt.is_brace else "Plate Properties"
            )
            self._update_plate_phase_ui()   # Reset panel to IDLE/COMPLETE state for type
        self._update_measurement_badge()

    def _on_loaded_measurement_type(self, _: str) -> None:
        """Handle a measurement-type change that originated from loading a saved measurement.

        Mirrors Swift's .onReceive(tap.$loadedMeasurementType) handler: updates all
        bound controls and widgets for the new type but does NOT restart the tap
        sequence — the loaded measurement state must be preserved.
        """
        self._apply_measurement_type_to_ui()

    def _on_measurement_type_changed(self, _: str) -> None:
        """Handle a measurement-type change that originated from the settings UI.

        Mirrors Swift's onApply?(measurementChanged) callback in TapSettingsView:
        updates the UI for the new type AND restarts the tap sequence so the next
        tap starts from a clean state.  Only restarts when the analyzer is running
        (i.e. not during app initialisation).
        """
        self._apply_measurement_type_to_ui()
        # Mirrors Swift onApply: if measurementChanged { startTapSequence() }
        # restart_tap_sequence() resets is_measurement_complete → False (via
        # measurementComplete signal), clears peaks/spectra, and seeds the noise floor —
        # so the next tap starts clean regardless of which type was active before.
        # Only do this when the analyzer thread is running (i.e. app is live, not init).
        if self._is_running:
            self.fft_canvas.restart_tap_sequence()

    def _update_measurement_badge(self) -> None:
        """Refresh the badge in the Analysis Results panel.

        Shows 'Comparison' with a purple tint in comparison mode (mirrors
        analyzer.displayMode == .comparison check in TapAnalysisResultsView.swift),
        otherwise shows the measurement type short name with blue/orange tint.
        """
        if self.fft_canvas.display_mode == AnalysisDisplayMode.COMPARISON:
            self.measurement_type_badge.setText("Comparison")
            self.measurement_type_badge.setStyleSheet(
                "background: rgba(160,32,240,0.20); border-radius: 4px; padding: 1px 6px;"
            )
            return
        mt = TDS.measurement_type()
        self.measurement_type_badge.setText(mt.short_name)
        self.measurement_type_badge.setStyleSheet(
            "background: rgba(0,100,255,0.15); border-radius: 4px; padding: 1px 6px;"
            if mt.is_guitar else
            "background: rgba(255,140,0,0.20); border-radius: 4px; padding: 1px 6px;"
        )

    def _on_plate_status_changed(self, status: str) -> None:
        """Update instructions panel, status bar, and buttons for plate/brace capture progress."""
        from models.material_tap_phase import MaterialTapPhase as _MTP

        self._update_plate_phase_ui(status)
        self._update_tap_buttons()

        # Push the current phase selection IDs to the peaks model so the annotations
        # label the identified peak (e.g. "Longitudinal") rather than the generic "Peak".
        # Mirrors Swift: effectiveLongitudinalPeakID is a @Published-chain computed property
        # that SwiftUI propagates automatically; Python requires an explicit push here.
        az = self.fft_canvas.analyzer
        phase = az.material_tap_phase
        in_review = phase in (_MTP.REVIEWING_LONGITUDINAL, _MTP.REVIEWING_CROSS, _MTP.REVIEWING_FLC)
        if in_review:
            pm = self.peak_widget.model
            pm.selected_longitudinal_peak_id = az.effective_longitudinal_peak_id
            pm.selected_cross_peak_id        = az.effective_cross_peak_id
            pm.selected_flc_peak_id          = az.effective_flc_peak_id
            # Populate selected_frequencies so show_value_bool() returns True for all
            # identified peaks — mirrors Swift selectedPeakIDs which includes all
            # resolved L/C/FLC peaks in the annotation visibility filter.
            pm.selected_frequencies = {
                p.frequency
                for p in (az.selected_longitudinal_peak, az.selected_cross_peak, az.selected_flc_peak)
                if p is not None
            }
            pm.refresh_annotations()

    def _plate_step_label(self, phase_step: int, total: int) -> str:
        """Return the status bar phase label, appending tap count when numberOfTaps > 1 on plate.

        Mirrors Swift:
          tap.numberOfTaps > 1
            ? "Phase N/total · Tap p/q"
            : "Phase N/total"
        For brace there is no per-phase tap averaging display (single phase), so
        the bare "Phase N/M" string is returned regardless of tap count.
        """
        base = f"Phase\u00a0{phase_step}/{total}"
        mt = TDS.measurement_type()
        tap_num = self._tap_count_total
        if not mt.is_brace and tap_num > 1:
            # Mirrors Swift: max(0, tap.currentTapCount - (materialPhaseStep - 1) * tap.numberOfTaps)
            tap_in_phase = max(0, self._tap_count_captured - (phase_step - 1) * tap_num)
            return f"{base}\u00a0\u00b7\u00a0Tap\u00a0{tap_in_phase}/{tap_num}"
        return base

    def _update_plate_phase_ui(self, status: str = "") -> None:
        """Sync the material instructions panel and status bar to the current PlateCapture state.

        Called on every PlateCapture.stateChanged emission and on measurement type change.
        """
        mt = TDS.measurement_type()
        pc = self.fft_canvas.plate_capture
        state = pc.state
        State = type(pc).State

        is_brace = mt.is_brace
        measure_flc = (not is_brace) and AS.AppSettings.measure_flc()
        total = 1 if is_brace else (3 if measure_flc else 2)

        # Update GroupBox title — mirrors Swift GroupBox("Brace Measurement" / "Plate Measurement")
        self._mip_group_title_lbl.setText(
            "Brace Measurement" if is_brace else "Plate Measurement"
        )

        # ── Instructions panel ──────────────────────────────────────────
        # Each state sets: dot color, shortStatus text+color, step label,
        # icon (qtawesome equiv of SF Symbol), title, and body description.
        # Mirrors Swift materialInstructionsView computed properties.

        if state == State.IDLE:
            color_hex  = "gray"
            short_status = "Ready"
            step_text  = f"Phase\u00a01/{total}"  # Swift: materialPhaseStep returns 1 for notStarted
            icon_name  = "fa5s.hand-point-up"
            title      = "Press \u2018New Tap\u2019 to Begin"
            tap_word   = "three-tap" if measure_flc else "two-tap"
            body       = (
                "Press \u2018New Tap\u2019 to begin the brace fL measurement."
                if is_brace else
                f"Press \u2018New Tap\u2019 to begin the {tap_word} plate measurement process."
            )
            self._sb_plate_step_lbl.setVisible(False)

        elif state == State.WAITING_L:
            color_hex  = "#1976D2"
            short_status = "L tap..."
            step_text  = f"Phase\u00a01/{total}"
            icon_name  = "fa5s.wave-square"
            title      = (
                "Step 1: Longitudinal (fL) Mode" if is_brace
                else "Step 1: Longitudinal (L) Mode"
            )
            body       = (
                "Hold brace at 22% from one end along the length. Tap center."
                if is_brace else
                "Hold plate at 22% from one end along the length, near one long edge "
                "(not at the width node). Tap center."
            )
            self._sb_plate_step_lbl.setText(self._plate_step_label(1, total))
            self._sb_plate_step_lbl.setVisible(True)

        elif state == State.REVIEWING_L:
            color_hex  = "#1976D2"
            short_status = "Review L"
            step_text  = f"Phase\u00a01/{total}"
            icon_name  = "fa5.check-circle"
            title      = "Review L Tap \u2014 Accept or Redo"
            body       = (
                "L tap captured. Review the spectrum \u2014 press Accept to continue "
                "to the C tap, or Redo to re-capture."
            )
            # Mirrors Swift: step label only shown when isDetecting (hidden during review)
            self._sb_plate_step_lbl.setVisible(False)

        elif state == State.WAITING_C:
            color_hex  = "#E65100"
            short_status = "C tap..."
            step_text  = f"Phase\u00a02/{total}"
            icon_name  = "fa5s.wave-square"
            title      = "Step 2: Cross-grain (C) Mode"
            body       = (
                "Hold plate at 22% from one end along the width, near one short edge "
                "(not at the length node). Tap center."
            )
            self._sb_plate_step_lbl.setText(self._plate_step_label(2, total))
            self._sb_plate_step_lbl.setVisible(True)

        elif state == State.REVIEWING_C:
            color_hex  = "#E65100"
            short_status = "Review C"
            step_text  = f"Phase\u00a02/{total}"
            icon_name  = "fa5.check-circle"
            title      = "Review C Tap \u2014 Accept or Redo"
            body       = (
                "C tap captured. Review the spectrum \u2014 press Accept to continue, "
                "or Redo to re-capture."
            )
            # Mirrors Swift: step label only shown when isDetecting (hidden during review)
            self._sb_plate_step_lbl.setVisible(False)

        elif state == State.WAITING_FLC:
            color_hex  = "#7B1FA2"
            step_text  = f"Phase\u00a03/{total}"
            self._sb_plate_step_lbl.setText(self._plate_step_label(3, total))
            self._sb_plate_step_lbl.setVisible(True)
            # WAITING_FLC covers two Swift sub-states; distinguish via underlying MTP phase.
            mtp = self.fft_canvas.analyzer.material_tap_phase
            from models.material_tap_phase import MaterialTapPhase as _MTPLocal
            if mtp == _MTPLocal.CAPTURING_FLC:
                # Swift capturingFlc: actively capturing the FLC tap
                short_status = "FLC tap..."
                icon_name    = "fa5s.wave-square"
                title        = "Step 3: FLC (Diagonal) Mode"
                body         = (
                    "Hold plate at the midpoint of one long edge. Tap near the opposite corner "
                    "(~22% from both the end and the side). Measures shear stiffness."
                )
            else:
                # Swift waitingForFlcTap: C captured, user repositioning for FLC
                short_status = "Tap for FLC"
                icon_name    = "fa5s.sync-alt"
                title        = "C Captured \u2014 Prepare for Step 3"
                body         = (
                    "Cross-grain mode captured! Now hold plate at the midpoint of one long edge. "
                    "Tap near the opposite corner (~22% from both sides) for FLC."
                )

        elif state == State.REVIEWING_FLC:
            color_hex  = "#7B1FA2"
            short_status = "Review FLC"
            step_text  = f"Phase\u00a03/{total}"
            icon_name  = "fa5.check-circle"
            title      = "Review FLC Tap \u2014 Accept or Redo"
            body       = (
                "FLC tap captured. Review the spectrum \u2014 press Accept to complete "
                "the measurement, or Redo to re-capture."
            )
            # Mirrors Swift: step label only shown when isDetecting (hidden during review)
            self._sb_plate_step_lbl.setVisible(False)

        else:  # COMPLETE
            color_hex  = "#388E3C"
            short_status = "Done"
            last_step  = total if measure_flc else (1 if is_brace else 2)
            step_text  = f"Phase\u00a0{last_step}/{total}"
            icon_name  = "fa5s.check-circle"
            title      = "Measurement Complete"
            if is_brace:
                body = (
                    "fL captured! Review the fL (blue) peak selection in the Results panel. "
                    "Adjust if the auto-selection isn\u2019t correct."
                )
            else:
                flc_part = ", and FLC (purple)" if measure_flc else ""
                body = (
                    f"All modes captured! Review the L (blue), C (orange){flc_part} peak "
                    "selections in the Results panel. Adjust if the auto-selection isn\u2019t correct."
                )
            self._sb_plate_step_lbl.setVisible(False)

        # Apply dot color
        self._mip_dot.setStyleSheet(
            f"QLabel {{ background-color: {color_hex}; border-radius: 5px; }}"
        )

        # Apply shortStatus text + matching color
        self._mip_short_status_lbl.setText(short_status)
        self._mip_short_status_lbl.setStyleSheet(f"color: {color_hex};")

        # Apply phase counter label (secondary color, "Phase N/M" format).
        # Hidden for brace (total == 1) — one phase only, label is redundant.
        self._mip_step_lbl.setText(step_text)
        self._mip_step_lbl.setVisible(total > 1)

        # Apply phase icon (qtawesome equivalent of SF Symbol name)
        try:
            icon_px = qta.icon(icon_name, color=color_hex).pixmap(24, 24)
            self._mip_icon_lbl.setPixmap(icon_px)
        except Exception:
            self._mip_icon_lbl.clear()

        # Apply title and body description
        self._mip_title_lbl.setText(title)
        self._mip_body_lbl.setText(body)

        # ── Status bar detect message (left side) ───────────────────────
        # Mirrors Swift: Text(tap.statusMessage).foregroundColor(tap.isDetecting ? .primary : .orange)
        # During REVIEWING phases isDetecting is False, so the message is orange.
        if status:
            self._sb_detect_msg.setText(status)
            in_review = state in (State.REVIEWING_L, State.REVIEWING_C, State.REVIEWING_FLC)
            self._sb_detect_msg.setStyleSheet(
                "color: orange;" if in_review else ""
            )

    def _on_plate_analysis_complete(self, f_long: float, f_cross: float, f_flc: float) -> None:
        """Auto-compute material properties and display in results panel."""
        mt = TDS.measurement_type()
        dims = self._get_current_dims()
        if dims is None or not dims.is_valid():
            QtWidgets.QMessageBox.warning(
                self, "Missing Dimensions",
                "Plate/brace dimensions are required.\n"
                "Please enter them in Settings → Measurement Type.",
            )
            return
        # The plateAnalysisComplete signal carries the exact selected peak frequencies
        # from the model's selected_longitudinal_peak / selected_cross_peak /
        # selected_flc_peak. Use them directly — mirrors Swift passing
        # effectiveLongitudinalPeakID == item.peak.id to MaterialPeakRowView.
        actual_long  = f_long  if f_long  > 0 else 0.0
        actual_cross = f_cross if (f_cross > 0 and not mt.is_brace) else 0.0
        actual_flc   = f_flc   if (f_flc   > 0 and not mt.is_brace) else 0.0

        # Update material peak widget with auto-assigned frequencies.
        # set_assignment highlights the L/C/FLC buttons on the matching peak rows —
        # equivalent to Swift MaterialPeakRowView(isLongitudinal: effectiveID == peak.id).
        self._material_peak_widget.set_assignment(actual_long, actual_cross,
                                                   flc_freq=actual_flc)

        # Populate selected_frequencies with the assigned peak frequencies so that
        # annotation mode "Selected" shows labels for the L/C/FLC peaks.
        # Mirrors Swift selectedPeakIDs = Set(resolvedPlatePeaks().map { $0.id })
        # set at the end of each gated-FFT phase in TapToneAnalyzer+SpectrumCapture.swift.
        assigned = {f for f in (actual_long, actual_cross, actual_flc) if f > 0}
        self.peak_widget.model.selected_frequencies = assigned

        # Pass the selected peak IDs (UUID strings) to the model so mode_value() can
        # resolve "Longitudinal" / "Cross-grain" / "FLC" labels by direct ID comparison.
        # Mirrors Swift modeLabel in DraggablePeakAnnotation which checks
        # peak.id == selectedLongitudinalPeakID / selectedCrossPeakID / selectedFlcPeakID.
        az = self.fft_canvas.analyzer
        self.peak_widget.model.selected_longitudinal_peak_id = az.effective_longitudinal_peak_id
        self.peak_widget.model.selected_cross_peak_id        = az.effective_cross_peak_id
        self.peak_widget.model.selected_flc_peak_id         = az.effective_flc_peak_id

        self.peak_widget.model.refresh_annotations()

        try:
            if mt.is_brace:
                self._populate_brace_section(PA.calculate_brace_properties(dims, f_long))
            else:
                self._populate_plate_section(
                    PA.calculate_plate_properties(
                        dims, f_long, f_cross,
                        f_flc_hz=actual_flc if actual_flc > 0 else None,
                    ),
                )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Calculation Error", str(exc))
            return

        self.set_measurement_complete(True)


    def _populate_brace_section(self, props: PA.BraceProperties) -> None:
        """Fill the brace material properties sub-section and make it visible."""
        self._brace_subtitle.setText(f"Longitudinal (fL): {props.f_long:.1f} Hz")
        self._brace_c_long.setText(f"{props.c_long_m_s:.0f} m/s")
        self._brace_E_long.setText(f"{props.youngsModulusLongGPa:.2f} GPa")
        color = PA.WoodQuality(props.quality).color
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

    def _populate_plate_section(self, props: PA.PlateProperties) -> None:
        """Fill the plate material properties sub-section and make it visible.

        All frequencies and G_LC are read from props directly — mirrors Swift where
        PlateProperties carries f_flc and exposes goreShearModulus as a computed property.
        """
        # Frequencies — one per line (mirrors Swift reading props.fundamentalFrequency*)
        self._plate_fl_lbl.setText(f"fL (Longitudinal): {props.f_long:.1f} Hz")
        self._plate_fc_lbl.setText(f"fC (Cross-grain): {props.f_cross:.1f} Hz")
        if props.f_flc is not None and props.f_flc > 0:
            self._plate_flc_lbl.setText(f"fLC (Diagonal): {props.f_flc:.1f} Hz")
            self._plate_flc_lbl.setVisible(True)
        else:
            self._plate_flc_lbl.setVisible(False)
        # Properties (title + L: val  C: val format)
        self._plate_c_long.setText(f"L: {props.c_long_m_s:.0f} m/s")
        self._plate_c_cross.setText(f"C: {props.c_cross_m_s:.0f} m/s")
        self._plate_E_long.setText(f"L: {props.youngsModulusLongGPa:.2f} GPa")
        self._plate_E_cross.setText(f"C: {props.youngsModulusCrossGPa:.2f} GPa")
        # G_LC from props.gore_shear_modulus (mirrors Swift props.goreShearModulus)
        glc_pa = props.gore_shear_modulus
        if glc_pa is not None and glc_pa > 0:
            self._plate_glc_val.setText(f"{glc_pa / 1e9:.3f} GPa")
            self._plate_glc_widget.setVisible(True)
        else:
            self._plate_glc_widget.setVisible(False)
        cl = PA.WoodQuality(props.quality_long).color
        cc = PA.WoodQuality(props.quality_cross).color
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
        cov = PA.WoodQuality(props.overall_quality).color
        self._plate_overall_quality.setText(props.overall_quality)
        self._plate_overall_quality.setStyleSheet(f"color: {cov}; font-weight: bold;")
        # Gore Target Thickness
        try:
            _fvs         = TDS.plate_stiffness()
            _body_l      = TDS.guitar_body_length()
            _body_w      = TDS.guitar_body_width()
            try:
                _preset = PSP.PlateStiffnessPreset(AS.AppSettings.plate_stiffness_preset())
            except (ValueError, KeyError):
                _preset = PSP.PlateStiffnessPreset.STEEL_STRING_TOP
            # Mirrors Swift: props.goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:)
            _thickness_mm = PA.calculate_gore_target_thickness(
                props, _body_l, _body_w, _fvs
            )
            if _thickness_mm is not None and _thickness_mm > 0:
                self._gore_thickness_value.setText(f"{_thickness_mm:.2f}")
                if glc_pa is not None and glc_pa > 0:
                    self._gore_glc_value.setText(f"{glc_pa / 1e9:.3f} GPa")
                    self._gore_glc_row_w.setVisible(True)
                    self._gore_glc_info.setVisible(False)
                else:
                    self._gore_glc_row_w.setVisible(False)
                    self._gore_glc_info.setText(
                        "\u24d8 GLC assumed 0 \u2014 enable FLC tap for a more accurate result"
                    )
                    self._gore_glc_info.setVisible(True)
                _preset_lbl = (
                    f"f_vs = {int(_fvs)} (custom)"
                    if _preset == PSP.PlateStiffnessPreset.CUSTOM
                    else f"f_vs = {int(_fvs)} ({_preset.value})"  # .value returns the human-readable label string
                )
                self._gore_params_lbl.setText(
                    f"Body: {_body_l:.0f} \u00d7 {_body_w:.0f} mm"
                    f"\n{_preset_lbl}"
                )
                self._gore_frame.setVisible(True)
                self._gore_sep.setVisible(True)
            else:
                self._gore_frame.setVisible(False)
                self._gore_sep.setVisible(False)
        except Exception:
            self._gore_frame.setVisible(False)
            self._gore_sep.setVisible(False)
        self._plate_placeholder.setVisible(False)
        self._plate_content.setVisible(True)
        self._brace_section.setVisible(False)
        self._plate_section.setVisible(True)
        self._material_section.setVisible(True)

    def _get_current_dims(self) -> PA.PlateDimensions | None:
        """Return current plate/brace dimensions from TapDisplaySettings."""
        mt = TDS.measurement_type()
        if mt.is_brace:
            return PA.PlateDimensions(
                length_mm=TDS.brace_length(),
                width_mm=TDS.brace_width(),
                thickness_mm=TDS.brace_thickness(),
                mass_g=TDS.brace_mass(),
            )
        else:
            return PA.PlateDimensions(
                length_mm=TDS.plate_length(),
                width_mm=TDS.plate_width(),
                thickness_mm=TDS.plate_thickness(),
                mass_g=TDS.plate_mass(),
            )

    # ================================================================
    # Measurements save / load / export
    # ================================================================

    def save_measurement(
        self,
        tap_location: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Collect view-side state and delegate to the model to save a measurement.

        Mirrors Swift ``TapToneAnalysisView+Actions.saveMeasurement()``:
        reads the visible axis range (view @State), reads device identity,
        reads effective peak role IDs from the analyzer, then calls
        ``analyzer.save_measurement(...)`` directly.  The model builds all
        ``SpectrumSnapshot`` objects internally from its own state.
        """
        canvas = self.fft_canvas
        analyzer = canvas.analyzer
        mt = TDS.measurement_type()

        # ── Axis range — view @State, mirrors Swift minFreq/maxFreq/minDB/maxDB ──
        min_freq_val = float(canvas.minFreq)
        max_freq_val = float(canvas.maxFreq)
        try:
            _, _y_range = canvas.getPlotItem().getViewBox().viewRange()
            min_db_val = float(_y_range[0])
            max_db_val = float(_y_range[1])
        except Exception:
            min_db_val = float(self.threshold_slider.value())
            max_db_val = 0.0

        # ── Device identity — mirrors Swift fft.selectedInputDevice?.name / fft.selectedInputDevice?.uid ──
        # Use the currently selected input device (not the calibration-time device name).
        _sel_dev = getattr(getattr(analyzer, "mic", None), "selected_input_device", None)
        mic_name: str | None = getattr(_sel_dev, "name", None) or None
        mic_uid: str | None = getattr(_sel_dev, "fingerprint", None) or None
        cal_name: str | None = getattr(analyzer, "_active_calibration_name", None) or None

        # ── Plate/brace peak role selections — mirrors Swift tap.effectiveLongitudinalPeakID ──
        selected_longitudinal_peak_id = analyzer.effective_longitudinal_peak_id if not mt.is_guitar else None
        selected_cross_peak_id        = analyzer.effective_cross_peak_id        if mt.is_plate  else None
        selected_flc_peak_id          = analyzer.effective_flc_peak_id          if mt.is_plate  else None

        analyzer.save_measurement(
            tap_location=tap_location or None,
            notes=notes or None,
            include_spectrum=True,
            selected_longitudinal_peak_id=selected_longitudinal_peak_id,
            selected_cross_peak_id=selected_cross_peak_id,
            selected_flc_peak_id=selected_flc_peak_id,
            microphone_name=mic_name,
            microphone_uid=mic_uid,
            calibration_name=cal_name,
            min_freq=min_freq_val,
            max_freq=max_freq_val,
            min_db=min_db_val,
            max_db=max_db_val,
        )

    def _on_save_measurement(self) -> None:
        """Show save dialog then persist the measurement.

        In comparison mode, routes to save_comparison() instead of save_measurement().
        Mirrors Swift: Save Comparison button calls saveComparison(tapLocation:notes:)
        when displayMode == .comparison (TapToneAnalysisView+Export.swift).

        For normal measurements mirrors Swift: the Save sheet receives tapLocation/notes
        as @Binding so it edits the view's live state directly.  Here we pre-populate
        the dialog from self._tap_location / self._notes and write back on accept, then
        clear them — exactly as Swift clears tapLocation = "" / notes = "" after
        saveMeasurement().
        """
        is_comparing = self.fft_canvas.is_comparing

        dlg = SMD.SaveMeasurementDialog(self)
        # Pre-populate from live state (mirrors Swift @Binding to the view's @State vars)
        dlg.set_tap_location(self._tap_location)
        dlg.set_notes(self._notes)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        # Write back into live state before saving (mirrors Swift binding update)
        self._tap_location = dlg.tap_location
        self._notes = dlg.notes

        if is_comparing:
            # Route to save_comparison() — mirrors Swift saveComparison(tapLocation:notes:).
            try:
                self.fft_canvas.analyzer.save_comparison(
                    tap_location=self._tap_location or None,
                    notes=self._notes or None,
                )
            except OSError as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Save Error", f"Could not save comparison:\n{exc}"
                )
        else:
            try:
                self.save_measurement(
                    tap_location=self._tap_location,
                    notes=self._notes,
                )
            except OSError as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Save Error", f"Could not save measurement:\n{exc}"
                )

        # Clear after saving — mirrors Swift: tapLocation = ""; notes = ""
        self._tap_location = ""
        self._notes = ""

    def _on_open_measurements(self) -> None:
        dlg = MD.MeasurementsDialog(self.fft_canvas.analyzer, self)
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

        # ── Analysis Results: show comparison grid ↔ peak list ───────────────
        if is_comparing:
            # Populate the Air/Top/Back grid from current comparison data.
            self._comparison_results_view.set_comparison_data(
                self.fft_canvas.analyzer._comparison_data
            )
            # Set the right panel minimum width from the table's actual column
            # widths now that set_comparison_data() has called
            # resizeColumnToContents(0) to fit the real label content.
            _tbl = self._comparison_results_view._table
            _label_col_w = _tbl.columnWidth(0)
            _fixed_cols_w = sum(_tbl.columnWidth(c) for c in range(1, 4))
            _frame = _tbl.frameWidth() * 2
            _panel_margins = self._right_panel.layout().contentsMargins()
            _panel_h_margins = _panel_margins.left() + _panel_margins.right()
            self._right_panel.setMinimumWidth(
                _label_col_w + _fixed_cols_w + _frame + _panel_h_margins
            )
        else:
            self._right_panel.setMinimumWidth(0)
        self._comparison_results_view.setVisible(is_comparing)
        self.peak_widget.setVisible(not is_comparing)
        # Scroll area (plate/brace) also hidden while comparing
        self._material_scroll.setVisible(not is_comparing)
        # Peak selection buttons hidden when there are no peaks to act on —
        # mirrors Swift `if !sortedPeaksWithModes.isEmpty` which evaluates to
        # empty during comparison (and also when no measurement has been made).
        _has_peaks = not is_comparing and self.peak_widget.model.rowCount(QtCore.QModelIndex()) > 0
        self.select_all_btn.setVisible(_has_peaks)
        self.deselect_all_btn.setVisible(_has_peaks)
        self.reset_auto_selection_btn.setVisible(
            _has_peaks and TDS.measurement_type().is_guitar
        )
        # Guitar summary (Ring-Out, Tap Ratio) — mirrors
        # `measurementType.isGuitar && analyzer.displayMode != .comparison` in Swift
        self._guitar_summary.setVisible(TDS.measurement_type().is_guitar and not is_comparing)

        # ── display_mode is already set by load_comparison / clear_comparison ──
        # The canvas _on_fft_frame_ready gates on display_mode == COMPARISON to
        # suppress live updates — no need to touch is_measurement_complete here.

        # ── Annotations ───────────────────────────────────────────────────────
        if is_comparing:
            canvas.annotations.hide_annotations()
        else:
            self.peak_widget.model.refresh_annotations()

        # ── Badge ──────────────────────────────────────────────────────────────
        self._update_measurement_badge()

        # ── Save / Export ──────────────────────────────────────────────────────
        # Export PDF is hidden (not just disabled) during comparison — mirrors
        # `if let exportPDF = onExportPDFReport, analyzer.displayMode != .comparison`
        # in TapAnalysisResultsView.swift.
        # Export Spectrum remains visible and is enabled during comparison.
        if is_comparing:
            # Save is enabled in comparison mode — routes to save_comparison().
            # Mirrors Swift: Save Comparison button visible when displayMode == .comparison.
            self.save_measurement_btn.setEnabled(True)
            self.export_spectrum_btn.setEnabled(True)
            self.export_pdf_btn.setVisible(True)
            self.export_pdf_btn.setEnabled(True)
            self._menu_save_action.setEnabled(True)
            self._menu_export_spectrum_action.setEnabled(True)
            self._menu_export_pdf_action.setEnabled(True)
        else:
            self.save_measurement_btn.setEnabled(self._is_measurement_complete)
            self.export_spectrum_btn.setEnabled(self._is_measurement_complete)
            self.export_pdf_btn.setVisible(True)
            self.export_pdf_btn.setEnabled(self._is_measurement_complete)
            self._menu_save_action.setEnabled(self._is_measurement_complete)
            self._menu_export_spectrum_action.setEnabled(self._is_measurement_complete)
            self._menu_export_pdf_action.setEnabled(self._is_measurement_complete)

        # ── Peak-selection buttons ─────────────────────────────────────────────
        can_select = self._is_measurement_complete and not is_comparing and TDS.measurement_type().is_guitar
        self.select_all_btn.setEnabled(can_select)
        self.deselect_all_btn.setEnabled(can_select)
        self.reset_auto_selection_btn.setEnabled(
            can_select and self.peak_widget.model.user_has_modified_peak_selection
        )

        self._update_tap_buttons()

    def _restore_measurement(self, m: TapToneMeasurement) -> None:
        canvas = self.fft_canvas
        analyzer = canvas.analyzer

        # ── Clear stale view-side tap count before model changes state ────────
        self._tap_count_captured = 0
        self._sb_tap_count.setVisible(False)
        if self._is_measurement_complete:
            # Temporarily un-complete so set_measurement_complete(True) at the
            # end fires its signal properly — view-side guard only.
            self._is_measurement_complete = False

        # ── Delegate all model-state restoration to the model ─────────────────
        # Mirrors Swift: TapToneAnalyzer.loadMeasurement(_:) is a model method.
        # load_measurement() sets peaks, spectra, selections, annotation offsets,
        # analysis settings, detection flags, AppSettings (the Python equivalent
        # of Swift's loaded* @Published + .onReceive → TapDisplaySettings writes),
        # and emits measurementComplete(True) + the status message.
        analyzer.load_measurement(m)

        # ── Store view-side references used by export / peak model ────────────
        self._loaded_resonant_peaks = list(m.peaks) if m.peaks else []
        self._loaded_measurement = m

        _restored_mt = MT.MeasurementType.from_string(m.measurement_type or "")

        # ── Propagate measurement type to TapDisplaySettings ──────────────────
        # AppSettings was already updated by load_measurement(); call
        # _on_loaded_measurement_type to propagate the loaded type to the UI —
        # mirrors Swift .onReceive(tap.$loadedMeasurementType) which updates the
        # bound picker without restarting the tap sequence.
        if m.measurement_type:
            _mt = MT.MeasurementType.from_string(m.measurement_type)
            AS.AppSettings.set_measurement_type(_mt)
            self._on_loaded_measurement_type(_mt.short_name)

        # ── Sync canvas saved_peaks array (used for scatter-plot drawing) ─────
        if m.peaks:
            peaks_array = np.array(
                [[p.frequency, p.magnitude, p.quality] for p in m.peaks],
                dtype=np.float64,
            )
            peaks_array = peaks_array[np.argsort(peaks_array[:, 0])]
        else:
            peaks_array = np.zeros((0, 3), dtype=np.float64)
        canvas.saved_peaks = peaks_array
        # canvas._loaded_measurement_peaks mirrors analyzer.loaded_measurement_peaks
        # (already set by load_measurement) — keep in sync for threshold slider use.
        canvas._loaded_measurement_peaks = analyzer.loaded_measurement_peaks or []

        # ── Update peak_model view state ──────────────────────────────────────
        peak_model = self.peak_widget.model

        if not _restored_mt.is_guitar:
            _plate_selected_ids: set[str] = set()
            for _pid in (
                m.selected_longitudinal_peak_id,
                m.selected_cross_peak_id,
                m.selected_flc_peak_id,
            ):
                if _pid:
                    _plate_selected_ids.add(_pid.upper())
            peak_model.selected_frequencies = {
                p.frequency for p in m.peaks
                if (p.id or "").upper() in _plate_selected_ids
            }
            peak_model.selected_longitudinal_peak_id = m.selected_longitudinal_peak_id
            peak_model.selected_cross_peak_id        = m.selected_cross_peak_id
            peak_model.selected_flc_peak_id          = m.selected_flc_peak_id
        else:
            selected_ids = set(
                m.selected_peak_ids if m.selected_peak_ids is not None
                else [p.id for p in m.peaks]
            )
            peak_model.selected_frequencies = {
                p.frequency for p in m.peaks if p.id in selected_ids
            }
        peak_model.is_live = False

        # ── Restore peak mode labels into peak_model.modes ────────────────────
        if not _restored_mt.is_guitar:
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
            peak_model.modes = {}
            for p in m.peaks:
                if p.id in m.peak_mode_overrides:
                    peak_model.modes[p.frequency] = m.peak_mode_overrides[p.id]
        else:
            peak_model.modes = {}

        peak_model._set_user_modified(True)

        # ── Restore annotation visibility mode into peak_model ────────────────
        target_mode = analyzer.annotation_visibility_mode
        target_idx = next(
            (i for i, mode in enumerate(self._ANN_MODES) if mode == target_mode),
            self._ann_mode_idx,
        )
        self._ann_mode_idx = target_idx
        self.annotations_btn.setIcon(qta.icon(self._ANN_MODES[target_idx].icon_name))
        # Set annotation mode directly on the private attribute so the public setter's
        # no-op guard and premature update_data call are both bypassed.
        peak_model._annotation_mode = target_mode

        # ── Draw spectrum on canvas ───────────────────────────────────────────
        _snap = m.spectrum_snapshot or m.longitudinal_snapshot
        if _snap is not None:
            snap = _snap
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes, dtype=np.float64)
            # set_frozen_spectrum keeps frozen_frequencies and frozen_magnitudes in
            # sync.  For plate/brace measurements load_measurement() clears
            # frozen_frequencies (plate mode doesn't use the combined frozen
            # spectrum for model purposes), so we must re-populate it here so
            # that the canvas crosshair snap (_on_mouse_moved) has a matching
            # freq array to index into.
            analyzer.set_frozen_spectrum(freq_arr, mag_arr)
            canvas.setYRange(snap.min_db, snap.max_db, padding=0)
            canvas.update_axis(int(snap.min_freq), int(snap.max_freq))
            canvas.set_draw_data(mag_arr, freqs=freq_arr)

            # For plate/brace: build material-spectra list for canvas display.
            # The per-phase spectra were already restored onto the analyzer by
            # load_measurement(); read them back to build the canvas overlay list.
            if not _restored_mt.is_guitar:
                _phase_spectra: list = []
                if m.longitudinal_snapshot is not None:
                    ls = m.longitudinal_snapshot
                    _phase_spectra.append(("Longitudinal (L)", (0, 122, 255),
                                           list(ls.frequencies), list(ls.magnitudes)))
                if _restored_mt.is_plate and m.cross_snapshot is not None:
                    cs = m.cross_snapshot
                    _phase_spectra.append(("Cross-grain (C)", (255, 149, 0),
                                           list(cs.frequencies), list(cs.magnitudes)))
                if _restored_mt.is_plate and m.flc_snapshot is not None:
                    fs = m.flc_snapshot
                    _phase_spectra.append(("FLC", (175, 82, 222),
                                           list(fs.frequencies), list(fs.magnitudes)))
                canvas.analyzer.set_material_spectra(_phase_spectra)
        else:
            canvas._emit_loaded_peaks_at_threshold()

        # ── Restore ring-out widget ───────────────────────────────────────────
        self._ring_out_s = m.decay_time
        if m.decay_time is not None:
            self.set_ring_out(m.decay_time)

        # ── Restore analysis settings sliders/spinners ────────────────────────
        # load_measurement() already wrote the model attrs; read them back to
        # drive the Qt widgets — mirrors Swift .onReceive on loaded* properties.
        self.tap_threshold_slider.setValue(int(analyzer.tap_detection_threshold))
        self.threshold_slider.setValue(int(analyzer.peak_threshold))
        self.tap_num_spin.setValue(analyzer.number_of_taps)

        # ── Configure material peak widget columns ────────────────────────────
        if not _restored_mt.is_guitar:
            _f_flc = analyzer.selected_flc_peak.frequency if analyzer.selected_flc_peak else 0.0
            _show_flc = (not _restored_mt.is_brace) and _f_flc > 0
            self._material_peak_widget.set_mode(
                show_cross=not _restored_mt.is_brace,
                show_flc=_show_flc,
            )
            self._material_instr_widget.set_mode(
                show_cross=not _restored_mt.is_brace,
                show_flc=_show_flc,
            )

        canvas._emit_loaded_peaks_at_threshold()

        # ── Compute and display material properties (plate/brace) ─────────────
        if not _restored_mt.is_guitar:
            _f_long  = analyzer.selected_longitudinal_peak.frequency if analyzer.selected_longitudinal_peak else 0.0
            _f_cross = analyzer.selected_cross_peak.frequency        if analyzer.selected_cross_peak        else 0.0
            _f_flc   = analyzer.selected_flc_peak.frequency          if analyzer.selected_flc_peak          else 0.0
            if _f_long > 0:
                _dims = self._get_current_dims()
                if _dims and _dims.is_valid():
                    try:
                        if _restored_mt.is_brace:
                            self._populate_brace_section(
                                PA.calculate_brace_properties(_dims, _f_long)
                            )
                        elif _f_cross > 0:
                            self._populate_plate_section(
                                PA.calculate_plate_properties(
                                    _dims, _f_long, _f_cross,
                                    f_flc_hz=_f_flc if _f_flc > 0 else None,
                                ),
                            )
                    except ValueError:
                        pass

        # ── Chart title ───────────────────────────────────────────────────────
        # loadedMeasurementNameChanged signal emitted by _load_measurement_body()
        # drives canvas.set_loaded_measurement_name() reactively — no explicit call needed.
        self._tap_location = ""
        self._notes = ""

        # ── Auto-select the recorded microphone ───────────────────────────────
        # Handled reactively: _load_measurement_body() emits requestDeviceSwitch
        # (drives _on_request_device_switch) and microphoneWarningChanged
        # (drives _on_microphone_warning_changed).  No view-side logic needed here.

        # ── Advance plate/brace phase UI to COMPLETE ──────────────────────────
        # load_measurement() already set material_tap_phase = COMPLETE on the model.
        _mt_now = TDS.measurement_type()
        if not _mt_now.is_guitar:
            self._update_plate_phase_ui()

        # ── Finalise view-side measurement-complete state ─────────────────────
        # Handled reactively: _load_measurement_body() emits measurementComplete(True)
        # as its last action (after all state is restored), which drives
        # set_measurement_complete() via the canvas.measurementComplete signal connection.

    def _on_export_spectrum(self) -> None:
        import time as _time

        # Build a suggested filename that mirrors Swift's base_filename pattern
        # (e.g. "spectrum-1775190435.png").
        suggested_name = f"spectrum-{int(_time.time())}.png"
        suggested_path = os.path.join(M.last_export_dir(), suggested_name)

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Spectrum",
            suggested_path,
            "PNG images (*.png)",
        )
        if not path:
            return
        if not path.endswith(".png"):
            path += ".png"
        M.update_export_dir(path)

        self._loading_overlay.show_message("Exporting spectrum…")
        try:
            canvas = self.fft_canvas

            # ── Comparison mode: render overlay chart from _comparison_data ───
            if canvas.is_comparing:
                from views.exportable_spectrum_chart import make_exportable_spectrum_view as _mev
                analyzer = canvas.analyzer
                comparison_spectra = []
                for entry in analyzer._comparison_data:
                    r, g, b = entry["color"]
                    comparison_spectra.append({
                        "frequencies": list(entry["freqs"]),
                        "magnitudes":  list(entry["mags"]),
                        "color": (r, g, b),
                        "label": entry["label"],
                    })
                snaps = [e["snapshot"] for e in analyzer._comparison_data if e.get("snapshot")]
                min_freq = float(min(s.min_freq for s in snaps)) if snaps else 50.0
                max_freq = float(max(s.max_freq for s in snaps)) if snaps else 1000.0
                min_db   = float(min(s.min_db   for s in snaps)) if snaps else -100.0
                max_db   = float(max(s.max_db   for s in snaps)) if snaps else 0.0
                _loc = (analyzer.loaded_measurement_name or self._tap_location or "").strip()
                chart_title = f"Comparison \u2014 {_loc}" if _loc else "Comparison"
                from datetime import datetime, timezone
                date_label = datetime.now(timezone.utc).isoformat()
                png_bytes = _mev(
                    frequencies=[], magnitudes=[],
                    min_freq=min_freq, max_freq=max_freq,
                    min_db=min_db, max_db=max_db,
                    peaks=[],
                    material_spectra=comparison_spectra if comparison_spectra else None,
                    chart_title=chart_title,
                    date_label=date_label,
                )
                with open(path, "wb") as f:
                    f.write(png_bytes)
                return

            # ── Single-spectrum path ──────────────────────────────────────────
            saved_freq = canvas.analyzer.frozen_frequencies
            freqs = saved_freq.tolist() if hasattr(saved_freq, "tolist") else list(saved_freq)
            mags  = (canvas.saved_mag_y_db.tolist()
                     if hasattr(canvas.saved_mag_y_db, "tolist")
                     else list(canvas.saved_mag_y_db))

            mt = TDS.measurement_type()
            is_guitar = mt.is_guitar

            from datetime import datetime, timezone
            date_label = datetime.now(timezone.utc).isoformat()

            peaks_list: list = []
            # Selection/visibility parameters from the loaded measurement (if any).
            _sel_long_id = None
            _sel_cross_id = None
            _sel_flc_id = None
            _mode_overrides: dict = {}
            _annotation_positions: dict = {}
            try:
                # Prefer the stored ResonantPeak objects (have full pitch data).
                # Apply annotationVisibilityMode / selectedPeakIDs filtering
                # exactly as render_spectrum_image_for_measurement does.
                if self._loaded_resonant_peaks and self._loaded_measurement is not None:
                    m_exp = self._loaded_measurement
                    all_peaks = self._loaded_resonant_peaks
                    visibility_mode = AnnotationVisibilityMode.from_string(
                        m_exp.annotation_visibility_mode or "all"
                    )
                    selected_ids = set(
                        m_exp.selected_peak_ids or [p.id for p in all_peaks]
                    )
                    if visibility_mode == AnnotationVisibilityMode.SELECTED:
                        peaks_list = [p for p in all_peaks if p.id in selected_ids]
                    elif visibility_mode == AnnotationVisibilityMode.NONE:
                        peaks_list = []
                    else:
                        peaks_list = list(all_peaks)
                    _sel_long_id = m_exp.selected_longitudinal_peak_id
                    _sel_cross_id = m_exp.selected_cross_peak_id
                    _sel_flc_id = m_exp.selected_flc_peak_id
                    _mode_overrides = m_exp.peak_mode_overrides or {}
                    # Always read annotation positions from the live analyzer state —
                    # mirrors Swift createExportableSpectrumView() which always passes
                    # tap.peakAnnotationOffsets (populated by loadMeasurement or by dragging).
                    # _restore_measurement populates peak_annotation_offsets from the
                    # measurement's saved offsets, so this is the single source of truth.
                    # Pass as absolute data-space positions (annotation_positions) so the
                    # export renderer can place cards precisely without a baseline-mismatch
                    # between the live canvas default (14 dB above peak) and the export
                    # chart default (ANNOT_OFFS_Y px above peak).
                    _freq_to_id = {p.frequency: p.id for p in all_peaks}
                    _annotation_positions: dict = {}
                    for _freq, (_lx, _ly) in canvas.analyzer.peak_annotation_offsets.items():
                        _pid = _freq_to_id.get(_freq)
                        if _pid:
                            _annotation_positions[_pid] = [float(_lx), float(_ly)]
                elif self._loaded_resonant_peaks:
                    peaks_list = list(self._loaded_resonant_peaks)
                else:
                    # Mirror Swift createExportableSpectrumView(): read live analyzer state.
                    # tap.visiblePeaks → currentPeaks filtered by annotation visibility mode.
                    _az = canvas.analyzer
                    peaks_list = list(_az.current_peaks)
                    _sel_long_id  = _az.effective_longitudinal_peak_id
                    _sel_cross_id = _az.effective_cross_peak_id
                    _sel_flc_id   = _az.effective_flc_peak_id
                    _mode_overrides = dict(_az.peak_mode_overrides)
                    for _pid, (_lx, _ly) in _az.peak_annotation_offsets.items():
                        _annotation_positions[_pid] = [float(_lx), float(_ly)]
            except Exception:
                pass

            _gt = TDS.measurement_type().guitar_type
            gt_str = _gt.value if _gt else None

            # Mirrors Swift chartTitle computed property:
            # fft.playingFileName ?? tap.loadedMeasurementName ?? "New"
            chart_title = canvas.chart_title

            # Read the actual Y axis range from the ViewBox — mirrors Swift's
            # minDB/maxDB which come from the chart's current axis domain.
            try:
                _, y_range = canvas.getPlotItem().getViewBox().viewRange()
                export_min_db = float(y_range[0])
                export_max_db = float(y_range[1])
            except Exception:
                export_min_db = float(self.threshold_slider.value())
                export_max_db = float(max(mags)) + 10.0 if mags else 0.0

            # Build material_spectra — mirrors Swift's materialSpectra computed property
            # (TapToneAnalysisView+SpectrumViews.swift), which reads tap.longitudinalSpectrum,
            # tap.crossSpectrum, tap.flcSpectrum for both live and loaded measurements.
            # For loaded measurements: snapshots come from _loaded_measurement.
            # For live measurements: spectra come from analyzer._material_spectra
            # (set by set_material_spectra() at capture completion).
            _material_spectra = None
            if not is_guitar:
                _ms: list = []
                if self._loaded_measurement is not None:
                    m_exp = self._loaded_measurement
                    if m_exp.longitudinal_snapshot is not None:
                        ls = m_exp.longitudinal_snapshot
                        _ms.append({"frequencies": list(ls.frequencies), "magnitudes": list(ls.magnitudes),
                                    "color": "blue", "label": "Longitudinal (L)"})
                    if m_exp.cross_snapshot is not None:
                        cs = m_exp.cross_snapshot
                        _ms.append({"frequencies": list(cs.frequencies), "magnitudes": list(cs.magnitudes),
                                    "color": "orange", "label": "Cross-grain (C)"})
                    if m_exp.flc_snapshot is not None:
                        fs = m_exp.flc_snapshot
                        _ms.append({"frequencies": list(fs.frequencies), "magnitudes": list(fs.magnitudes),
                                    "color": "purple", "label": "FLC"})
                else:
                    # Live measurement: read per-phase spectra from the analyzer.
                    # _material_spectra is a list of (label, (r,g,b), freqs, mags) tuples.
                    _COLOR_NAMES = {
                        (0, 122, 255): "blue",
                        (255, 149, 0): "orange",
                        (175, 82, 222): "purple",
                    }
                    for _label, _rgb, _mfreqs, _mmags in getattr(canvas.analyzer, "_material_spectra", []):
                        _color = _COLOR_NAMES.get(tuple(_rgb), "blue")
                        _ms.append({"frequencies": list(_mfreqs), "magnitudes": list(_mmags),
                                    "color": _color, "label": _label})
                if _ms:
                    _material_spectra = _ms

            # Mirrors Swift TapToneAnalysisView+Export.createExportableSpectrumView()
            # calling makeExportableSpectrumView(...) directly.
            png_bytes = make_exportable_spectrum_view(
                frequencies=freqs,
                magnitudes=mags,
                min_freq=float(canvas.minFreq),
                max_freq=float(canvas.maxFreq),
                min_db=export_min_db,
                max_db=export_max_db,
                peaks=peaks_list,
                annotation_positions=_annotation_positions,
                measurement_type_str=mt.value if not is_guitar else None,
                selected_longitudinal_peak_id=_sel_long_id,
                selected_cross_peak_id=_sel_cross_id,
                selected_flc_peak_id=_sel_flc_id,
                mode_overrides=_mode_overrides,
                material_spectra=_material_spectra,
                guitar_type_str=gt_str,
                date_label=date_label,
                chart_title=chart_title,
            )
            with open(path, "wb") as f:
                f.write(png_bytes)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Failed", str(exc))
        finally:
            self._loading_overlay.hide()

    def _on_export_pdf(self) -> None:
        import time as _time

        # In comparison mode route to the comparison PDF export path.
        # Mirrors Swift exportComparisonPDFReport() called when displayMode == .comparison.
        if self.fft_canvas.is_comparing:
            self._on_export_comparison_pdf()
            return

        suggested_name = f"report-{int(_time.time())}.pdf"
        suggested_path = os.path.join(M.last_export_dir(), suggested_name)

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            suggested_path,
            "PDF files (*.pdf)",
        )
        if not path:
            return
        if not path.endswith(".pdf"):
            path += ".pdf"
        M.update_export_dir(path)

        self._loading_overlay.show_message("Generating PDF report…")
        try:
            # Mirrors Swift exportPDFReport() which reads live analyzer state
            # directly — no TapToneMeasurement is constructed at any point.
            canvas   = self.fft_canvas
            analyzer = canvas.analyzer
            mt       = TDS.measurement_type()
            is_guitar = mt.is_guitar

            # ── tapLocation / notes — mirrors Swift: tapLocation.isEmpty ? nil : tapLocation ──
            loc = self._tap_location if self._tap_location else None
            if loc is None and self._loaded_measurement is not None:
                loc = self._loaded_measurement.tap_location or None
            notes_val = self._notes if self._notes else None

            # ── Frequency / dB range from visible axis — mirrors Swift minFreq/maxFreq ────────
            min_freq_val = float(canvas.minFreq)
            max_freq_val = float(canvas.maxFreq)
            try:
                _, y_range = canvas.getPlotItem().getViewBox().viewRange()
                min_db_val = float(y_range[0])
                max_db_val = float(y_range[1])
            except Exception:
                min_db_val = float(self.threshold_slider.value())
                max_db_val = 0.0

            # ── Peaks — use stored ResonantPeak objects when available, fall back to live analyzer ─
            all_peaks: list = []
            sel_long_id  = None
            sel_cross_id = None
            sel_flc_id   = None
            mode_overrides: dict = {}
            annotation_positions: dict = {}
            selected_ids: set = set()

            if self._loaded_resonant_peaks and self._loaded_measurement is not None:
                m_exp = self._loaded_measurement
                all_peaks = list(self._loaded_resonant_peaks)
                selected_ids = set(
                    m_exp.selected_peak_ids or [p.id for p in all_peaks]
                )
                sel_long_id  = m_exp.selected_longitudinal_peak_id
                sel_cross_id = m_exp.selected_cross_peak_id
                sel_flc_id   = m_exp.selected_flc_peak_id
                mode_overrides = m_exp.peak_mode_overrides or {}
                # peak_annotation_offsets is keyed by peak_id (UUID string), not frequency.
                for _pid, (_lx, _ly) in analyzer.peak_annotation_offsets.items():
                    annotation_positions[_pid] = [float(_lx), float(_ly)]
            else:
                # Mirror Swift: read tap.currentPeaks and tap.selectedPeakIDs directly
                # from the live analyzer — do NOT reconstruct peaks from the table model.
                all_peaks = list(analyzer.current_peaks)
                selected_ids = set(analyzer.selected_peak_ids)
                sel_long_id  = analyzer.effective_longitudinal_peak_id
                sel_cross_id = analyzer.effective_cross_peak_id
                sel_flc_id   = analyzer.effective_flc_peak_id
                mode_overrides = dict(analyzer.peak_mode_overrides)
                # peak_annotation_offsets is keyed by peak_id (UUID string), not frequency.
                for _pid, (_lx, _ly) in analyzer.peak_annotation_offsets.items():
                    annotation_positions[_pid] = [float(_lx), float(_ly)]

            # Mirror Swift: rangeFilteredPeaks = tap.currentPeaks.filter { freq in range }
            range_peaks = [p for p in all_peaks
                           if min_freq_val <= p.frequency <= max_freq_val]
            if not selected_ids:
                selected_ids = {p.id for p in range_peaks}

            # ── Peak modes from live identifiedModes — mirrors Swift peakModes ───────────────
            peak_modes = {
                entry["peak"].id: entry["mode"]
                for entry in analyzer.identified_modes
                if "peak" in entry and "mode" in entry
            }

            # ── Material properties — mirrors Swift plate/brace derivation ────────────────────
            plate_props = None
            brace_props = None
            if mt == MT.MeasurementType.PLATE:
                long_peak  = next((p for p in all_peaks if p.id == sel_long_id),  None)
                cross_peak = next((p for p in all_peaks if p.id == sel_cross_id), None)
                flc_peak   = next((p for p in all_peaks if p.id == sel_flc_id),   None) if sel_flc_id else None
                if long_peak and cross_peak:
                    dims = PA.MaterialDimensions(
                        length_mm=TDS.plate_length(),
                        width_mm=TDS.plate_width(),
                        thickness_mm=TDS.plate_thickness(),
                        mass_g=TDS.plate_mass(),
                    )
                    if dims.is_valid():
                        try:
                            plate_props = PA.calculate_plate_properties(
                                dims, long_peak.frequency, cross_peak.frequency,
                                f_flc_hz=flc_peak.frequency if flc_peak else None,
                            )
                        except Exception:
                            pass
            elif mt == MT.MeasurementType.BRACE:
                long_peak = next((p for p in all_peaks if p.id == sel_long_id), None)
                if long_peak:
                    dims = PA.MaterialDimensions(
                        length_mm=TDS.brace_length(),
                        width_mm=TDS.brace_width(),
                        thickness_mm=TDS.brace_thickness(),
                        mass_g=TDS.brace_mass(),
                    )
                    if dims.is_valid():
                        try:
                            brace_props = PA.calculate_brace_properties(dims, long_peak.frequency)
                        except Exception:
                            pass

            # ── Gore / plate stiffness — mirrors Swift's TapDisplaySettings reads ─────────────
            from views.utilities.tap_settings_view import AppSettings as _AppSettings
            _preset_str = _AppSettings.plate_stiffness_preset()
            try:
                _preset = PSP.PlateStiffnessPreset(_preset_str)
            except ValueError:
                _preset = PSP.PlateStiffnessPreset.STEEL_STRING_TOP
            if _preset == PSP.PlateStiffnessPreset.CUSTOM:
                plate_stiffness = TDS.custom_plate_stiffness()
            else:
                plate_stiffness = _preset.stiffness

            # ── Render spectrum PNG — mirrors Swift createExportableSpectrumView() ─────────────
            saved_freq = analyzer.frozen_frequencies
            freqs = saved_freq.tolist() if hasattr(saved_freq, "tolist") else list(saved_freq)
            mags  = (canvas.saved_mag_y_db.tolist()
                     if hasattr(canvas.saved_mag_y_db, "tolist")
                     else list(canvas.saved_mag_y_db))

            # Use the live annotation visibility mode from the view's cycle index.
            # analyzer.annotation_visibility_mode is only set at init and is not updated
            # when the user cycles the annotation button — _ann_mode_idx is authoritative.
            visibility_mode = self._ANN_MODES[self._ann_mode_idx]
            if visibility_mode == AnnotationVisibilityMode.SELECTED:
                vis_peaks = [p for p in all_peaks if p.id in selected_ids]
            elif visibility_mode == AnnotationVisibilityMode.NONE:
                vis_peaks = []
            else:
                vis_peaks = list(all_peaks)

            # Build material_spectra — mirrors Swift's materialSpectra computed property
            # (TapToneAnalysisView+SpectrumViews.swift), which reads tap.longitudinalSpectrum,
            # tap.crossSpectrum, tap.flcSpectrum for both live and loaded measurements.
            _material_spectra = None
            if not is_guitar:
                _ms: list = []
                if self._loaded_measurement is not None:
                    m_exp = self._loaded_measurement
                    if m_exp.longitudinal_snapshot is not None:
                        ls = m_exp.longitudinal_snapshot
                        _ms.append({"frequencies": list(ls.frequencies), "magnitudes": list(ls.magnitudes),
                                    "color": "blue", "label": "Longitudinal (L)"})
                    if m_exp.cross_snapshot is not None:
                        cs = m_exp.cross_snapshot
                        _ms.append({"frequencies": list(cs.frequencies), "magnitudes": list(cs.magnitudes),
                                    "color": "orange", "label": "Cross-grain (C)"})
                    if m_exp.flc_snapshot is not None:
                        fs = m_exp.flc_snapshot
                        _ms.append({"frequencies": list(fs.frequencies), "magnitudes": list(fs.magnitudes),
                                    "color": "purple", "label": "FLC"})
                else:
                    # Live measurement: read per-phase spectra from the analyzer.
                    _COLOR_NAMES = {
                        (0, 122, 255): "blue",
                        (255, 149, 0): "orange",
                        (175, 82, 222): "purple",
                    }
                    for _label, _rgb, _mfreqs, _mmags in getattr(analyzer, "_material_spectra", []):
                        _color = _COLOR_NAMES.get(tuple(_rgb), "blue")
                        _ms.append({"frequencies": list(_mfreqs), "magnitudes": list(_mmags),
                                    "color": _color, "label": _label})
                if _ms:
                    _material_spectra = _ms

            _gt = TDS.measurement_type().guitar_type
            gt_str = _gt.value if _gt else None

            # Mirrors Swift chartTitle computed property:
            # fft.playingFileName ?? tap.loadedMeasurementName ?? "New"
            chart_title = canvas.chart_title

            from datetime import datetime, timezone as _tz
            # Mirrors Swift: tap.sourceMeasurementTimestamp ?? Date()
            # Use the original capture time when a saved measurement is loaded;
            # fall back to now for a live (unsaved) capture.
            _src_ts = getattr(analyzer, "source_measurement_timestamp", None)
            if _src_ts is not None:
                try:
                    date_label = datetime.fromisoformat(_src_ts).isoformat()
                except Exception:
                    date_label = datetime.now(_tz.utc).isoformat()
            else:
                date_label = datetime.now(_tz.utc).isoformat()

            # ── Device identity — mirrors Swift fft.selectedInputDevice?.name (WI-31) ──────────
            # Use the currently selected input device, not the calibration-time device name.
            _sel_dev = getattr(getattr(analyzer, "mic", None), "selected_input_device", None)
            mic_name: str | None = getattr(_sel_dev, "name", None) or None

            # ── Active calibration name — mirrors Swift fft.activeCalibration?.name (WI-30) ──
            # Use _active_calibration_name which is set by both manual selection and
            # device-specific auto-load (via load_calibration_from_profile).
            _active_cal_name: str | None = getattr(analyzer, "_active_calibration_name", None) or None

            # Mirror Swift createExportableSpectrumView(): always call make_exportable_spectrum_view.
            # For plate/brace, frozenFrequencies is intentionally empty — the spectrum renders
            # via material_spectra (per-phase overlays). Swift has no "if freqs and mags" guard.
            png_data: bytes | None = None
            if freqs or _material_spectra:
                try:
                    png_data = make_exportable_spectrum_view(
                        frequencies=freqs, magnitudes=mags,
                        min_freq=min_freq_val, max_freq=max_freq_val,
                        min_db=min_db_val,    max_db=max_db_val,
                        peaks=vis_peaks,
                        annotation_positions=annotation_positions,
                        measurement_type_str=mt.value if not is_guitar else None,
                        selected_longitudinal_peak_id=sel_long_id,
                        selected_cross_peak_id=sel_cross_id,
                        selected_flc_peak_id=sel_flc_id,
                        mode_overrides=mode_overrides,
                        peak_modes=peak_modes,
                        material_spectra=_material_spectra,
                        guitar_type_str=gt_str,
                        date_label=date_label,
                        chart_title=chart_title,
                    )
                except Exception:
                    pass

            # ── Build PDFReportData directly — mirrors Swift PDFReportData(...) init ─────────
            report_data = M.PDFReportData(
                timestamp=date_label,
                tap_location=loc,
                notes=notes_val,
                measurement_type_str=mt.value,
                guitar_type_str=gt_str or TDS.guitar_type(),
                microphone_name=mic_name,
                calibration_name=_active_cal_name,
                min_freq=min_freq_val,
                max_freq=max_freq_val,
                peaks=range_peaks,
                selected_peak_ids=selected_ids,
                peak_modes=peak_modes,
                peak_mode_overrides=mode_overrides,
                selected_longitudinal_peak_id=sel_long_id,
                selected_cross_peak_id=sel_cross_id,
                selected_flc_peak_id=sel_flc_id,
                decay_time=getattr(analyzer, "current_decay_time", None),
                tap_tone_ratio=analyzer.calculate_tap_tone_ratio(),
                plate_properties=plate_props,
                brace_properties=brace_props,
                guitar_body_length=TDS.guitar_body_length(),
                guitar_body_width=TDS.guitar_body_width(),
                plate_stiffness=plate_stiffness,
                plate_stiffness_preset_str=_preset_str,
                spectrum_image_data=png_data,
            )

            M.export_pdf(report_data, path)
            # Success is silent — mirrors Swift MeasurementFileExporter.
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export Error", f"Could not export PDF:\n{exc}"
            )
        finally:
            self._loading_overlay.hide()

    def _on_export_comparison_pdf(self) -> None:
        """Export a comparison PDF report from the live comparison state.

        Renders the current comparison overlay chart to PNG, builds
        ComparisonPDFReportData from the live _comparison_data, then calls
        export_comparison_pdf() to write the PDF.

        Mirrors Swift exportComparisonPDFReport() in TapToneAnalysisView+Export.swift.
        """
        import time as _time

        # Mirrors Swift: let label = tap.loadedMeasurementName ?? tapLocation
        # basename is "report-<ts>" when label is empty, else "<label>-<ts>".
        _label = (self.fft_canvas.analyzer.loaded_measurement_name or self._tap_location or "").strip()
        suggested_name = (
            (_label.replace(" ", "-").replace("/", "-").lower() + f"-{int(_time.time())}.pdf")
            if _label
            else f"report-{int(_time.time())}.pdf"
        )
        suggested_path = os.path.join(M.last_export_dir(), suggested_name)

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Comparison PDF Report",
            suggested_path,
            "PDF files (*.pdf)",
        )
        if not path:
            return
        if not path.endswith(".pdf"):
            path += ".pdf"
        M.update_export_dir(path)

        self._loading_overlay.show_message("Generating comparison PDF report…")
        try:
            canvas   = self.fft_canvas
            analyzer = canvas.analyzer

            # Render the comparison overlay chart image from live comparison data.
            from views.exportable_spectrum_chart import make_exportable_spectrum_view
            import numpy as np
            comparison_spectra = []
            for entry in analyzer._comparison_data:
                r, g, b = entry["color"]
                comparison_spectra.append({
                    "frequencies": list(entry["freqs"]),
                    "magnitudes":  list(entry["mags"]),
                    "color": (r, g, b),
                    "label": entry["label"],
                })

            snaps = [e["snapshot"] for e in analyzer._comparison_data if e.get("snapshot")]
            min_freq = float(min(s.min_freq for s in snaps)) if snaps else 50.0
            max_freq = float(max(s.max_freq for s in snaps)) if snaps else 1000.0
            min_db   = float(min(s.min_db   for s in snaps)) if snaps else -100.0
            max_db   = float(max(s.max_db   for s in snaps)) if snaps else 0.0

            loc = self._tap_location or None
            if loc is None and analyzer.loaded_measurement_name:
                loc = analyzer.loaded_measurement_name
            chart_title = f"Comparison — {loc}" if loc else "Comparison"

            png_data = make_exportable_spectrum_view(
                frequencies=[], magnitudes=[],
                min_freq=min_freq, max_freq=max_freq,
                min_db=min_db,     max_db=max_db,
                peaks=[],
                material_spectra=comparison_spectra if comparison_spectra else None,
                chart_title=chart_title,
            )

            # Build mode_frequencies list from live _comparison_data.
            from models.guitar_mode import GuitarMode
            from models.tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin

            mode_frequencies = []
            for entry in analyzer._comparison_data:
                mode_freqs = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
                    entry.get("peaks", []), entry.get("guitar_type")
                )
                r, g, b = entry["color"]
                mode_frequencies.append((
                    entry["label"],
                    (r, g, b),
                    mode_freqs.get(GuitarMode.AIR),
                    mode_freqs.get(GuitarMode.TOP),
                    mode_freqs.get(GuitarMode.BACK),
                ))

            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).isoformat()

            report_data = M.ComparisonPDFReportData(
                timestamp=timestamp,
                comparison_label=loc,
                notes=self._notes or None,
                spectrum_image_data=png_data,
                entries=[],   # entries not needed for live export (no saved ComparisonEntry objects)
                mode_frequencies=mode_frequencies,
            )

            M.export_comparison_pdf(report_data, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export Error", f"Could not export comparison PDF:\n{exc}"
            )
        finally:
            self._loading_overlay.hide()

    # ================================================================
    # Device management
    # ================================================================

    def _on_devices_changed(self, device_names: list[str]) -> None:
        """Sync the UI after the model has processed a hot-plug event.

        The model (_on_devices_refreshed) already called set_device() on the
        newly-selected device via mic.load_available_input_devices() +
        auto-selection logic. We read the already-selected device from the
        model rather than re-implementing the selection here.
        """
        new_names = set(device_names)
        added = new_names - self._known_input_device_names
        self._known_input_device_names = new_names

        if not added:
            return

        # Read the device the model already selected — do not call set_device() again.
        selected = getattr(self.fft_canvas.analyzer, "mic", None)
        selected = getattr(selected, "selected_input_device", None) if selected else None

        if selected is not None and selected.name in added:
            self.device_status_lbl.setText(selected.name)
            AS.AppSettings.set_audio_device(selected)
            _cal = _mc_mod.CalibrationStorage.calibration_for_device(selected.fingerprint)
            if _cal is None:
                _cal = _mc_mod.CalibrationStorage.calibration_for_device(selected.name)
            self.set_calibration_status(_cal.name if _cal else "")

    def _on_device_lost(self, device_name: str) -> None:
        """Active device disconnected — sync the UI to the model's already-chosen fallback.

        The model (_on_devices_refreshed) already called _auto_select_on_hotplug()
        via load_available_input_devices(), which falls back to built-in or first
        available, and then called set_device() on the fallback. We just read the
        model's selection and update the UI labels.
        """
        selected = getattr(self.fft_canvas.analyzer, "mic", None)
        selected = getattr(selected, "selected_input_device", None) if selected else None

        if selected is None:
            self.device_status_lbl.setText("⚠ No audio input device available")
            return

        self.device_status_lbl.setText(selected.name)
        AS.AppSettings.set_audio_device(selected)
        _cal = _mc_mod.CalibrationStorage.calibration_for_device(selected.fingerprint)
        if _cal is None:
            _cal = _mc_mod.CalibrationStorage.calibration_for_device(selected.name)
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
        import views.help_view as _HD
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

        # Read the current measurement type from TapDisplaySettings (single source of truth)
        cur_unified = TDS.measurement_type().value

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

        def _dim_field(unit: str, value: float) -> QtWidgets.QLineEdit:
            """Text field for a dimension value — mirrors Swift TextField bound to a String."""
            tf = QtWidgets.QLineEdit(str(value))
            tf.setFixedWidth(80)
            tf.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            tf.setPlaceholderText(unit)
            return tf

        def _dim_row(text: str, widget: QtWidgets.QWidget,
                     unit: str = "") -> QtWidgets.QHBoxLayout:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(text))
            row.addStretch()
            row.addWidget(widget)
            if unit:
                row.addWidget(QtWidgets.QLabel(unit))
            return row

        plate_length_field = _dim_field("mm", TDS.plate_length())
        plate_width_field = _dim_field("mm", TDS.plate_width())
        plate_thick_field = _dim_field("mm", TDS.plate_thickness())
        plate_mass_field = _dim_field("g", TDS.plate_mass())

        plate_density_lbl = QtWidgets.QLabel("—")
        plate_density_lbl.setFont(small)
        plate_density_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        plate_layout.addLayout(_dim_row("Length (along grain):", plate_length_field, "mm"))
        plate_layout.addLayout(_dim_row("Width (cross grain):", plate_width_field, "mm"))
        plate_layout.addLayout(_dim_row("Thickness:", plate_thick_field, "mm"))
        plate_layout.addLayout(_dim_row("Mass:", plate_mass_field, "g"))

        _density_row = QtWidgets.QHBoxLayout()
        _density_row.addWidget(QtWidgets.QLabel("Calculated Density:"))
        _density_row.addStretch()
        _density_row.addWidget(plate_density_lbl)
        plate_layout.addLayout(_density_row)

        def _update_plate_density() -> None:
            try:
                L = float(plate_length_field.text())
                W = float(plate_width_field.text())
                T = float(plate_thick_field.text())
                m = float(plate_mass_field.text())
            except ValueError:
                plate_density_lbl.setText("—")
                return
            if L > 0 and W > 0 and T > 0 and m > 0:
                density = m / ((L / 10) * (W / 10) * (T / 10))
                plate_density_lbl.setText(f"{density:.3f} g/cm³")
            else:
                plate_density_lbl.setText("—")

        plate_length_field.textChanged.connect(lambda _: _update_plate_density())
        plate_width_field.textChanged.connect(lambda _: _update_plate_density())
        plate_thick_field.textChanged.connect(lambda _: _update_plate_density())
        plate_mass_field.textChanged.connect(lambda _: _update_plate_density())
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

        gore_body_len_field = _dim_field("mm", TDS.guitar_body_length())
        gore_body_wid_field = _dim_field("mm", TDS.guitar_body_width())
        plate_layout.addLayout(_dim_row("Body Length (a):", gore_body_len_field, "mm"))
        plate_layout.addLayout(_dim_row("Lower Bout Width (b):", gore_body_wid_field, "mm"))
        plate_layout.addWidget(_hsep())

        fvs_hdr = QtWidgets.QLabel("Plate Vibrational Stiffness (f_vs)")
        fvs_hdr.setFont(hdr_font)
        plate_layout.addWidget(fvs_hdr)

        PRESET_DISPLAY_NAMES = [p.short_name for p in PSP.PlateStiffnessPreset]
        PRESET_STORAGE_NAMES = [p._value_ for p in PSP.PlateStiffnessPreset]
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
        custom_fvs_field = QtWidgets.QLineEdit(str(TDS.custom_plate_stiffness()))
        custom_fvs_field.setFixedWidth(80)
        custom_fvs_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        custom_fvs_row.addWidget(custom_fvs_field)
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

        brace_length_field = _dim_field("mm", TDS.brace_length())
        brace_width_field = _dim_field("mm", TDS.brace_width())
        brace_thick_field = _dim_field("mm", TDS.brace_thickness())
        brace_mass_field = _dim_field("g", TDS.brace_mass())

        brace_density_lbl = QtWidgets.QLabel("—")
        brace_density_lbl.setFont(small)
        brace_density_lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )

        brace_layout.addLayout(_dim_row("Length (along grain):", brace_length_field, "mm"))
        brace_layout.addLayout(_dim_row("Width (breadth):", brace_width_field, "mm"))
        brace_layout.addLayout(_dim_row("Height (tap direction):", brace_thick_field, "mm"))

        height_note = QtWidgets.QLabel(
            "Brace height when lying flat — this is the t dimension in the stiffness formula"
        )
        height_note.setFont(small)
        height_note.setWordWrap(True)
        brace_layout.addWidget(height_note)

        brace_layout.addLayout(_dim_row("Mass:", brace_mass_field, "g"))

        _brace_density_row = QtWidgets.QHBoxLayout()
        _brace_density_row.addWidget(QtWidgets.QLabel("Calculated Density:"))
        _brace_density_row.addStretch()
        _brace_density_row.addWidget(brace_density_lbl)
        brace_layout.addLayout(_brace_density_row)

        def _update_brace_density() -> None:
            try:
                L = float(brace_length_field.text())
                W = float(brace_width_field.text())
                T = float(brace_thick_field.text())
                m = float(brace_mass_field.text())
            except ValueError:
                brace_density_lbl.setText("—")
                return
            if L > 0 and W > 0 and T > 0 and m > 0:
                density = m / ((L / 10) * (W / 10) * (T / 10))
                brace_density_lbl.setText(f"{density:.3f} g/cm³")
            else:
                brace_density_lbl.setText("—")

        brace_length_field.textChanged.connect(lambda _: _update_brace_density())
        brace_width_field.textChanged.connect(lambda _: _update_brace_density())
        brace_thick_field.textChanged.connect(lambda _: _update_brace_density())
        brace_mass_field.textChanged.connect(lambda _: _update_brace_density())
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
            # Reload the frequency text fields from the stored values for the newly
            # selected type so the Display Settings section shows the correct range.
            # Mirrors Swift TapSettingsView+Sections.swift onChange(of: selectedMeasurementType)
            # which sets minFreqInput/maxFreqInput string state without touching the axis.
            disp_f_min_field.setText(str(AS.AppSettings.f_min(mt_val)))
            disp_f_max_field.setText(str(AS.AppSettings.f_max(mt_val)))

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

        # Local staging text fields — mirrors Swift's @State String vars
        # minFreqInput / maxFreqInput / minDBInput / maxDBInput.
        # Values are only applied to the graph when Done is pressed (_apply_settings),
        # not live as the user types, matching Swift TapSettingsView behaviour.
        _tf_width = 70

        disp_f_min_field = QtWidgets.QLineEdit(
            str(int(AS.AppSettings.f_min(self.fft_canvas.analyzer._measurement_type)))
        )
        disp_f_min_field.setFixedWidth(_tf_width)
        disp_f_min_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        disp_f_max_field = QtWidgets.QLineEdit(
            str(int(AS.AppSettings.f_max(self.fft_canvas.analyzer._measurement_type)))
        )
        disp_f_max_field.setFixedWidth(_tf_width)
        disp_f_max_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        disp_db_min_field = QtWidgets.QLineEdit(
            f"{AS.AppSettings.db_min():.1f}"
        )
        disp_db_min_field.setFixedWidth(_tf_width)
        disp_db_min_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        disp_db_max_field = QtWidgets.QLineEdit(
            f"{AS.AppSettings.db_max():.1f}"
        )
        disp_db_max_field.setFixedWidth(_tf_width)
        disp_db_max_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        _range_block(
            dg,
            "Frequency Range",
            disp_f_min_field, disp_f_max_field,
            "Hz",
            "Frequency range shown in the spectrum chart",
        )
        _range_block(
            dg,
            "Magnitude Range",
            disp_db_min_field, disp_db_max_field,
            "dB",
            "Magnitude range shown in the spectrum chart",
        )

        # All display range values applied on Done only (see _apply_settings)

        save_view_btn = QtWidgets.QPushButton("Save Current View")
        save_view_btn.setToolTip("Persist the current pan/zoom state as the default view")

        def _save_current_view() -> None:
            vb = self.fft_canvas.getPlotItem().vb
            x_range, y_range = vb.viewRange()
            meas_t = TDS.measurement_type()
            AS.AppSettings.set_f_min(int(x_range[0]), meas_t)
            AS.AppSettings.set_f_max(int(x_range[1]), meas_t)
            AS.AppSettings.set_db_min(y_range[0])
            AS.AppSettings.set_db_max(y_range[1])
            disp_f_min_field.setText(str(int(x_range[0])))
            disp_f_max_field.setText(str(int(x_range[1])))
            disp_db_min_field.setText(f"{y_range[0]:.1f}")
            disp_db_max_field.setText(f"{y_range[1]:.1f}")

        save_view_btn.clicked.connect(_save_current_view)
        dg.addWidget(save_view_btn)

        reset_disp_btn = QtWidgets.QPushButton("Reset to Defaults")
        reset_disp_btn.setToolTip("Restore factory display settings for the current measurement type")

        def _reset_display_defaults() -> None:
            # Delegate to AppSettings → TapDisplaySettings (single source of truth).
            # Mirrors Swift TapSettingsView resetDisplaySettingsToDefaults() which
            # calls TapDisplaySettings.defaultMinFrequency(for:) / defaultMaxFrequency(for:).
            mt_val = MT.MeasurementType(meas_type_combo.currentText())
            disp_f_min_field.setText(str(AS.AppSettings.default_f_min(mt_val)))
            disp_f_max_field.setText(str(AS.AppSettings.default_f_max(mt_val)))
            disp_db_min_field.setText(f"{AS.AppSettings.default_db_min():.1f}")
            disp_db_max_field.setText(f"{AS.AppSettings.default_db_max():.1f}")

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

        # Analysis Frequency Range — text fields matching Swift TextField bound to analysisMinFreqInput
        an_f_min_field = QtWidgets.QLineEdit(str(int(AS.AppSettings.analysis_f_min())))
        an_f_min_field.setFixedWidth(_tf_width)
        an_f_min_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        an_f_max_field = QtWidgets.QLineEdit(str(int(AS.AppSettings.analysis_f_max())))
        an_f_max_field.setFixedWidth(_tf_width)
        an_f_max_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        # analysis range persisted on Apply only

        _range_block(
            an,
            "Analysis Frequency Range",
            an_f_min_field, an_f_max_field,
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
        peak_thresh_field = QtWidgets.QLineEdit(f"{AS.AppSettings.peak_threshold():.0f}")
        peak_thresh_field.setFixedWidth(_tf_width)
        peak_thresh_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        pt_row.addWidget(peak_thresh_field)
        pt_row.addWidget(QtWidgets.QLabel("dB"))
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
        mp_field = QtWidgets.QLineEdit(str(saved_max_peaks if saved_max_peaks > 0 else 10))
        mp_field.setFixedWidth(_tf_width)
        mp_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        mp_field.setEnabled(saved_max_peaks != 0)
        mp_row.addWidget(mp_field)
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
            mp_field.setEnabled(not checked)  # UI only — persisted on Apply

        mp_all_cb.toggled.connect(_on_all_peaks_toggled)
        # mp_field persisted on Apply only
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
            an_f_min_field.setText("30")
            an_f_max_field.setText("2000")
            peak_thresh_field.setText("-60")
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
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        device_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        device_combo.setMaximumWidth(300)
        le = device_combo.lineEdit()
        if le is not None:
            le.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            le.setReadOnly(True)
        dev_row.addWidget(device_combo)
        aud.addLayout(dev_row)

        from models.audio_device import AudioDevice as _AudioDevice
        from models.audio_device import filter_input_devices as _filter_inputs
        input_devices: list[_AudioDevice] = []
        try:
            default_input = sd.query_devices(kind="input")
            for dev in _filter_inputs(list(sd.query_devices())):
                input_devices.append(_AudioDevice.from_sounddevice_dict(dev))
        except Exception:
            pass

        saved_fp = AS.AppSettings.audio_device_fingerprint()
        saved_name = AS.AppSettings.device_name()
        current_dev_idx = -1
        for list_idx, audio_dev in enumerate(input_devices):
            device_combo.addItem(audio_dev.name)
            if audio_dev.fingerprint == saved_fp or (
                current_dev_idx < 0 and audio_dev.name == saved_name
            ):
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
                sr_val.setText(f"{input_devices[combo_idx].sample_rate:.0f} Hz")
            else:
                sr_val.setText("")

        _update_sr_lbl(device_combo.currentIndex())
        device_combo.currentIndexChanged.connect(_update_sr_lbl)

        def _on_device_selected(combo_idx: int) -> None:
            if 0 <= combo_idx < len(input_devices):
                audio_dev = input_devices[combo_idx]
                if audio_dev.fingerprint != AS.AppSettings.audio_device_fingerprint():
                    self.fft_canvas.set_device(audio_dev)
                    AS.AppSettings.set_audio_device(audio_dev)
                    self.device_status_lbl.setText(audio_dev.name)
                    _update_cal_display()

        device_combo.currentIndexChanged.connect(_on_device_selected)

        def _rebuild_device_combo(_: list[str]) -> None:
            """Refresh the device combo when sounddevice reports a change."""
            nonlocal input_devices
            try:
                new_devices: list[_AudioDevice] = [
                    _AudioDevice.from_sounddevice_dict(dev)
                    for dev in _filter_inputs(list(sd.query_devices()))
                ]
            except Exception:
                return
            input_devices = new_devices
            saved_fp = AS.AppSettings.audio_device_fingerprint()
            saved_name = AS.AppSettings.device_name()
            device_combo.blockSignals(True)
            device_combo.clear()
            restore_idx = -1
            for list_idx, audio_dev in enumerate(input_devices):
                device_combo.addItem(audio_dev.name)
                if audio_dev.fingerprint == saved_fp or (
                    restore_idx < 0 and audio_dev.name == saved_name
                ):
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
            cal_combo.blockSignals(True)
            try:
                if active:
                    for i in range(cal_combo.count()):
                        if cal_combo.itemData(i) == active.id:
                            cal_combo.setCurrentIndex(i)
                            return
                cal_combo.setCurrentIndex(0)
            finally:
                cal_combo.blockSignals(False)

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
            _update_cal_display()

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
        # 5. About & Help Section
        # =====================================================
        about_group = QtWidgets.QGroupBox("")
        ab = QtWidgets.QVBoxLayout(about_group)
        ab.addWidget(_group_header("mdi.information", "About & Help"))

        from _version import __version_string__
        ver_row = QtWidgets.QHBoxLayout()
        ver_lbl = QtWidgets.QLabel("Version")
        ver_val = QtWidgets.QLabel(__version_string__)
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
        # Advanced (collapsible: Display, Analysis), aboutSection
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

        # Advanced collapsible content (Display, Analysis)
        adv_content = QtWidgets.QWidget()
        adv_cl = QtWidgets.QVBoxLayout(adv_content)
        adv_cl.setContentsMargins(0, 0, 0, 0)
        adv_cl.setSpacing(8)
        adv_cl.addWidget(disp_group)
        adv_cl.addWidget(analysis_group)
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


        def _apply_settings() -> None:
            # Measurement type → main window
            unified = meas_type_combo.currentText()
            mt_val = MT.MeasurementType(unified)

            # Cancel any in-progress plate/brace measurement if the measurement type
            # or the FLC setting changes — mirrors Swift onApply(didChangeType:) which
            # calls cancelTapSequence() when the new type differs.
            _current_mt = TDS.measurement_type()
            _current_flc = AS.AppSettings.measure_flc()
            _type_changed = (mt_val != _current_mt)
            _flc_changed = (measure_flc_cb.isChecked() != _current_flc)
            _needs_restart = (_type_changed or _flc_changed) and not _current_mt.is_guitar and self._is_running
            if _needs_restart:
                self._is_paused = False
                self.fft_canvas.cancel_tap_sequence()
                self._tap_count_captured = 0

            # Apply measurement type to TapDisplaySettings — mirrors Swift where
            # selectedMeasurementType (local @State) is written to TapDisplaySettings
            # only when applySettings() is called, never during dialog interaction.
            AS.AppSettings.set_measurement_type(mt_val)

            # Display frequency range — parse the staging text fields and apply to the
            # canvas + toolbar spinners, mirroring Swift applySettings() which validates
            # minFreqInput/maxFreqInput Strings and writes through the @Binding to the chart.
            try:
                new_f_min = int(float(disp_f_min_field.text()))
                new_f_max = int(float(disp_f_max_field.text()))
            except ValueError:
                new_f_min = int(AS.AppSettings.f_min(mt_val))
                new_f_max = int(AS.AppSettings.f_max(mt_val))
            new_f_min, new_f_max = min(new_f_min, new_f_max - 1), max(new_f_min + 1, new_f_max)
            AS.AppSettings.set_f_min(new_f_min, mt_val)
            AS.AppSettings.set_f_max(new_f_max, mt_val)
            # Update the staging fields to show the validated (possibly clamped) values
            disp_f_min_field.setText(str(new_f_min))
            disp_f_max_field.setText(str(new_f_max))
            self.fft_canvas.update_axis(new_f_min, new_f_max)
            self._update_freq_range_label()

            # Display magnitude range — parse, persist, and apply to canvas.
            try:
                new_db_min = float(disp_db_min_field.text())
                new_db_max = float(disp_db_max_field.text())
            except ValueError:
                new_db_min = AS.AppSettings.db_min()
                new_db_max = AS.AppSettings.db_max()
            new_db_min, new_db_max = min(new_db_min, new_db_max - 1), max(new_db_min + 1, new_db_max)
            AS.AppSettings.set_db_min(new_db_min)
            AS.AppSettings.set_db_max(new_db_max)
            disp_db_min_field.setText(f"{new_db_min:.1f}")
            disp_db_max_field.setText(f"{new_db_max:.1f}")
            self.fft_canvas.setYRange(new_db_min, new_db_max, padding=0)

            # Analysis frequency range — parse text fields, mirrors Swift applySettings()
            # validating analysisMinFreqInput/analysisMaxFreqInput Strings.
            try:
                new_an_f_min = float(an_f_min_field.text())
                new_an_f_max = float(an_f_max_field.text())
            except ValueError:
                new_an_f_min = AS.AppSettings.analysis_f_min()
                new_an_f_max = AS.AppSettings.analysis_f_max()
            new_an_f_min = max(0.0, min(new_an_f_min, new_an_f_max - 1))
            new_an_f_max = max(new_an_f_min + 1, new_an_f_max)
            AS.AppSettings.set_analysis_f_min(new_an_f_min)
            AS.AppSettings.set_analysis_f_max(new_an_f_max)
            an_f_min_field.setText(str(int(new_an_f_min)))
            an_f_max_field.setText(str(int(new_an_f_max)))
            # Apply immediately to analyzer — mirrors Swift's @Published didSet on
            # minFrequency/maxFrequency which makes the new analysis window active at once.
            self.fft_canvas.analyzer.min_frequency = new_an_f_min
            self.fft_canvas.analyzer.max_frequency = new_an_f_max

            # Show Unknown Modes — save and immediately refresh chart + results panel.
            # Unlike Swift where computed properties re-read the setting on every render,
            # Python requires an explicit re-emission of peaksChanged to push the new
            # filtered list through _on_peaks_changed_scatter and _on_peaks_changed_results.
            AS.AppSettings.set_show_unknown_modes(show_unknown_cb.isChecked())
            self.fft_canvas.analyzer.peaksChanged.emit(
                list(self.fft_canvas.analyzer.current_peaks)
            )

            # Peak threshold → AppSettings + main-window slider + graph
            try:
                final_db = int(float(peak_thresh_field.text()))
            except ValueError:
                final_db = int(AS.AppSettings.peak_threshold())
            final_db = max(-120, min(0, final_db))
            peak_thresh_field.setText(str(final_db))
            AS.AppSettings.set_peak_threshold(float(final_db))
            AS.AppSettings.set_threshold(final_db + 100)
            slider_val = max(-100, min(-20, final_db))
            if self.threshold_slider.value() != slider_val:
                self.threshold_slider.setValue(slider_val)

            # Max peaks
            try:
                _mp_val = int(mp_field.text())
            except ValueError:
                _mp_val = 10
            new_max_peaks = 0 if mp_all_cb.isChecked() else max(1, _mp_val)
            AS.AppSettings.set_max_peaks(new_max_peaks)
            # Apply immediately to analyzer, mirroring Swift's @Published didSet on maxPeaks.
            self.fft_canvas.analyzer.max_peaks = new_max_peaks

            # Recalculate peaks with the new analysis window and max_peaks, mirroring
            # Swift's recalculateFrozenPeaksIfNeeded() calls in applySettings().
            self.fft_canvas.analyzer.recalculate_frozen_peaks_if_needed()

            # Hysteresis margin
            hyst_db = hyst_slider.value() * 0.5
            self.fft_canvas.set_hysteresis_margin(hyst_db)
            AS.AppSettings.set_hysteresis_margin(hyst_db)

            # Plate / brace / gore / f_vs dimensions — parse text fields, mirrors Swift
            # applySettings() which parses plateLengthInput etc. with Float(input) ?? 0.
            def _pf(field: QtWidgets.QLineEdit, fallback: float) -> float:
                try:
                    v = float(field.text())
                    return v if v > 0 else fallback
                except ValueError:
                    return fallback

            AS.AppSettings.set_plate_length(_pf(plate_length_field, TDS.plate_length()))
            AS.AppSettings.set_plate_width(_pf(plate_width_field, TDS.plate_width()))
            AS.AppSettings.set_plate_thickness(_pf(plate_thick_field, TDS.plate_thickness()))
            AS.AppSettings.set_plate_mass(_pf(plate_mass_field, TDS.plate_mass()))
            AS.AppSettings.set_measure_flc(measure_flc_cb.isChecked())
            AS.AppSettings.set_guitar_body_length(_pf(gore_body_len_field, TDS.guitar_body_length()))
            AS.AppSettings.set_guitar_body_width(_pf(gore_body_wid_field, TDS.guitar_body_width()))
            fvs_idx = fvs_combo.currentIndex()
            AS.AppSettings.set_plate_stiffness_preset(
                PRESET_STORAGE_NAMES[fvs_idx] if 0 <= fvs_idx < len(PRESET_STORAGE_NAMES) else "Steel String Top"
            )
            AS.AppSettings.set_custom_plate_stiffness(_pf(custom_fvs_field, TDS.custom_plate_stiffness()))
            AS.AppSettings.set_brace_length(_pf(brace_length_field, TDS.brace_length()))
            AS.AppSettings.set_brace_width(_pf(brace_width_field, TDS.brace_width()))
            AS.AppSettings.set_brace_thickness(_pf(brace_thick_field, TDS.brace_thickness()))
            AS.AppSettings.set_brace_mass(_pf(brace_mass_field, TDS.brace_mass()))

            # Fire _on_measurement_type_changed exactly once after all settings are
            # persisted — mirrors Swift's onApply?(measurementChanged) callback which
            # runs after applySettings() completes.
            if _type_changed or _flc_changed:
                self._on_measurement_type_changed(mt_val.short_name)

            # Restart the plate/brace capture state machine after all settings are
            # saved so the new phase count (2 vs 3) is immediately active.
            # Mirrors Swift: onApply?(measurementChanged) → startTapSequence().
            if _needs_restart and not mt_val.is_guitar:
                self.fft_canvas.start_plate_analysis()

            # If a brace/plate measurement is active, recalculate material properties
            # using the freshly saved dimensions.
            #
            # Mirrors Swift: applySettings() → onApply?() → reclassifyPeaks() →
            # identifiedModes @Published → SwiftUI re-evaluates calculatedBraceProperties
            # (computed property that reads TapDisplaySettings + effectiveLongitudinalPeakID).
            #
            # Python has no reactive computed properties, so we mirror the Swift computed
            # property directly: read effective peak IDs from the analyzer, look up peak
            # objects from the phase-specific lists (live) or current_peaks (restored),
            # read fresh dimensions from AppSettings, then repopulate the section.
            if (mt_val is MT.MeasurementType.BRACE or mt_val is MT.MeasurementType.PLATE) \
                    and self._is_measurement_complete:
                _az = self.fft_canvas.analyzer
                _long_id = _az.effective_longitudinal_peak_id
                if _long_id:
                    # Mirrors Swift: search longitudinalPeaks first (live), then
                    # sortedPeaksWithModes / currentPeaks (saved measurement).
                    _long_peak = (
                        next((p for p in _az.longitudinal_peaks if p.id == _long_id), None)
                        or next((p for p in _az.current_peaks if p.id == _long_id), None)
                    )
                    if _long_peak:
                        _dims = self._get_current_dims()
                        if _dims and _dims.is_valid():
                            try:
                                if mt_val is MT.MeasurementType.BRACE:
                                    self._populate_brace_section(
                                        PA.calculate_brace_properties(
                                            _dims, _long_peak.frequency
                                        )
                                    )
                                else:
                                    _cross_id = _az.effective_cross_peak_id
                                    _cross_peak = (
                                        next((p for p in _az.cross_peaks if p.id == _cross_id), None)
                                        or next((p for p in _az.current_peaks if p.id == _cross_id), None)
                                    ) if _cross_id else None
                                    _flc_id = _az.effective_flc_peak_id
                                    _flc_peak = (
                                        next((p for p in _az.flc_peaks if p.id == _flc_id), None)
                                        or next((p for p in _az.current_peaks if p.id == _flc_id), None)
                                    ) if _flc_id else None
                                    if _cross_peak:
                                        self._populate_plate_section(
                                            PA.calculate_plate_properties(
                                                _dims,
                                                _long_peak.frequency,
                                                _cross_peak.frequency,
                                                f_flc_hz=_flc_peak.frequency if _flc_peak else None,
                                            )
                                        )
                            except ValueError:
                                pass

            dlg.accept()

        def _cancel_settings() -> None:
            # Mirrors Swift Cancel → dismiss() with no side-effects.
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
        dlg.resize(max(dlg.sizeHint().width(), 460), 700)
        dlg.exec()
        self.fft_canvas.devicesChanged.disconnect(_on_device_list_changed)

        # Re-hide the reparented widgets
        self.num_averages.setParent(None)  # type: ignore[call-overload]
        self.avg_enable.setParent(None)  # type: ignore[call-overload]
        self.avg_completed.setParent(None)  # type: ignore[call-overload]
        self.avg_done.setParent(None)  # type: ignore[call-overload]
        self.avg_restart.setParent(None)  # type: ignore[call-overload]

    # ================================================================
    # Help
    # ================================================================

    def _show_about(self) -> None:
        from _version import __version_string__
        QtWidgets.QMessageBox.about(
            self,
            "About Guitar Tap",
            "<b>Guitar Tap</b><br>"
            f"Version {__version_string__}<br><br>"
            "An acoustic analysis tool for guitar makers.<br><br>"
            "Tap-tone analysis using real-time FFT to identify "
            "resonant frequencies of guitar top and back plates.<br><br>"
            "Copyright © 2026 David W. Smith dba Dolce Sfogato",
        )

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


