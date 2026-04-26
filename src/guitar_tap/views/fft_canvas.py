""" Samples audio signal and finds the peaks of the guitar tap resonances
"""

from datetime import datetime
from typing import List
import platform

import pyqtgraph as pg
import numpy as np
import sounddevice as sd
import numpy.typing as npt
from PySide6 import QtCore, QtGui, QtWidgets

from views import peak_annotations as fft_a
import models.realtime_fft_analyzer as f_a
from models import guitar_type as gt
from models import guitar_mode as gm
from models import measurement_type as mt_mod
from models import microphone_calibration as _mc_mod
from models.realtime_fft_analyzer import RealtimeFFTAnalyzer
from models.analysis_display_mode import AnalysisDisplayMode
import models.tap_tone_analyzer as td
import models.tap_tone_analyzer as pc
import views.utilities.tap_settings_view as _as
from models.tap_display_settings import TapDisplaySettings as _tds


class _SceneMouseReleaseFilter(QtCore.QObject):
    """Event filter that emits a signal on QGraphicsScene mouse release."""

    released = QtCore.Signal(object)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QtCore.QEvent.Type.GraphicsSceneMouseRelease:
            self.released.emit(event)
        return False


# ── Zoom & Pan help popup ─────────────────────────────────────────────────────

class _ZoomPanPopup(QtWidgets.QFrame):
    """Floating popover listing zoom/pan keyboard+mouse controls.

    Matches the Swift SpectrumView 'Zoom & Pan Controls' popover.
    Uses Qt.Popup so it auto-dismisses when the user clicks outside.
    """

    _ROWS: list[tuple[str, str] | None] = [
        ("Scroll over plot",    "Zoom both axes around cursor"),
        ("Scroll over freq axis", "Zoom frequency only"),
        ("Scroll over mag axis",  "Zoom magnitude only"),
        ("⇧ + Scroll",          "Pan frequency axis"),
        ("⌥ + Scroll",          "Pan magnitude axis"),
        ("⌘ / ⌃ + Scroll",      "Zoom both axes"),
        None,
        ("Drag over plot",      "Pan both axes"),
        ("Drag over freq axis", "Pan frequency only"),
        ("Drag over mag axis",  "Pan magnitude only"),
        ("Right-click",         "Reset axes & labels"),
    ]

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(
            parent,
            QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint,
        )
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(3)

        title = QtWidgets.QLabel("<b>Zoom &amp; Pan Controls</b>")
        layout.addWidget(title)
        layout.addSpacing(2)

        _key_font = QtGui.QFont()
        _key_font.setBold(True)
        _key_font.setPointSize(10)
        _desc_font = QtGui.QFont()
        _desc_font.setPointSize(10)

        for row in self._ROWS:
            if row is None:
                sep = QtWidgets.QFrame()
                sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
                layout.addWidget(sep)
            else:
                key, desc = row
                hl = QtWidgets.QHBoxLayout()
                hl.setSpacing(10)
                hl.setContentsMargins(0, 0, 0, 0)
                key_lbl = QtWidgets.QLabel(key)
                key_lbl.setFont(_key_font)
                key_lbl.setMinimumWidth(130)
                desc_lbl = QtWidgets.QLabel(desc)
                desc_lbl.setFont(_desc_font)
                desc_lbl.setStyleSheet("color: gray;")
                hl.addWidget(key_lbl)
                hl.addWidget(desc_lbl, 1)
                layout.addLayout(hl)

    def show_near(self, global_pos: QtCore.QPoint) -> None:
        """Show the popup with its top-right corner near *global_pos*."""
        self.adjustSize()
        x = global_pos.x() - self.width()
        y = global_pos.y()
        self.move(x, y)
        self.show()


class _PlateCaptureAdapter:
    """Compatibility adapter exposing the old PlateCapture API over the
    new gated-FFT pipeline (material_tap_phase + per-phase spectra).

    Used by tap_tone_analysis_view._update_plate_phase_ui and the save
    snapshot code which still read plate_capture.state / long_mag_db etc.
    """

    from enum import Enum as _Enum

    class State(_Enum):
        IDLE          = "idle"
        WAITING_L     = "waiting_l"
        REVIEWING_L   = "reviewing_l"
        WAITING_C     = "waiting_c"
        REVIEWING_C   = "reviewing_c"
        WAITING_FLC   = "waiting_flc"
        REVIEWING_FLC = "reviewing_flc"
        COMPLETE      = "complete"

    def __init__(self, analyzer):
        self._analyzer = analyzer

    @property
    def state(self) -> "State":
        from models.material_tap_phase import MaterialTapPhase as _MTP
        phase = self._analyzer.material_tap_phase
        if phase == _MTP.COMPLETE:
            return self.State.COMPLETE
        if phase == _MTP.REVIEWING_LONGITUDINAL:
            return self.State.REVIEWING_L
        if phase == _MTP.CAPTURING_CROSS:
            return self.State.WAITING_C
        if phase == _MTP.REVIEWING_CROSS:
            return self.State.REVIEWING_C
        if phase in (_MTP.CAPTURING_FLC, _MTP.WAITING_FOR_FLC_TAP):
            return self.State.WAITING_FLC
        if phase == _MTP.REVIEWING_FLC:
            return self.State.REVIEWING_FLC
        if phase == _MTP.CAPTURING_LONGITUDINAL:
            return self.State.WAITING_L
        return self.State.IDLE  # NOT_STARTED

    @property
    def long_mag_db(self):
        """Return longitudinal spectrum magnitudes as ndarray, or None."""
        import numpy as _np
        spec = self._analyzer.longitudinal_spectrum
        return _np.array(spec[0]) if spec else None

    @property
    def cross_mag_db(self):
        """Return cross-grain spectrum magnitudes as ndarray, or None."""
        import numpy as _np
        spec = self._analyzer.cross_spectrum
        return _np.array(spec[0]) if spec else None

    @property
    def flc_mag_db(self):
        """Return FLC spectrum magnitudes as ndarray, or None."""
        import numpy as _np
        spec = self._analyzer.flc_spectrum
        return _np.array(spec[0]) if spec else None


# pylint: disable=too-many-instance-attributes
class FftCanvas(pg.PlotWidget):
    """Sample the audio stream and display the FFT

    The fft is displayed using background audio capture and callback
    for processing. During the chunk processing the interpolated peaks
    are found.  The threshold used to sample the peaks is the same as the
    threshold used to decide if a new fft is displayed. The
    amplitude of the fft is emitted to the signal passed in the class
    constructor

    After refactoring: FftCanvas is now a thin display widget.  All analysis
    state and logic lives in self.analyzer (TapToneAnalyzer).  FftCanvas owns
    only pyqtgraph rendering objects, Qt event handlers, and view-level signals.
    guitar_tap.py continues to call methods on FftCanvas — those are forwarded
    transparently to self.analyzer.
    """

    hold: bool = False

    peakDeselected: QtCore.Signal = QtCore.Signal()
    peakSelected: QtCore.Signal = QtCore.Signal(float)
    peaksChanged: QtCore.Signal = QtCore.Signal(np.ndarray)
    ampChanged: QtCore.Signal = QtCore.Signal(int)
    averagesChanged: QtCore.Signal = QtCore.Signal(int)
    framerateUpdate: QtCore.Signal = QtCore.Signal(float, float, float)
    newSample: QtCore.Signal = QtCore.Signal(bool)
    tapDetected: QtCore.Signal = QtCore.Signal()
    ringOutMeasured: QtCore.Signal = QtCore.Signal(float)
    tapCountChanged: QtCore.Signal = QtCore.Signal(int, int)  # (captured, total)
    devicesChanged: QtCore.Signal = QtCore.Signal(list)       # new device-name list
    currentDeviceLost: QtCore.Signal = QtCore.Signal(str)     # lost device name
    plateStatusChanged: QtCore.Signal = QtCore.Signal(str)    # plate capture status
    plateAnalysisComplete: QtCore.Signal = QtCore.Signal(float, float, float)  # fL, fC, fFLC
    tapDetectionPaused: QtCore.Signal = QtCore.Signal(bool)   # True=paused
    measurementComplete: QtCore.Signal = QtCore.Signal(bool)  # mirrors Swift @Published var isMeasurementComplete
    statusMessageChanged: QtCore.Signal = QtCore.Signal(str)  # mirrors Swift @Published var statusMessage
    loadedMeasurementNameChanged: QtCore.Signal = QtCore.Signal(object)  # str | None — mirrors Swift @Published var loadedMeasurementName
    playingFileNameChanged: QtCore.Signal = QtCore.Signal(object)        # str | None — mirrors Swift @Published var playingFileName on RealtimeFFTAnalyzer
    showLoadedSettingsWarningChanged: QtCore.Signal = QtCore.Signal(bool)  # mirrors Swift @Published var showLoadedSettingsWarning
    microphoneWarningChanged: QtCore.Signal = QtCore.Signal(object)        # str | None — mirrors Swift @Published var microphoneWarning
    requestDeviceSwitch: QtCore.Signal = QtCore.Signal(object)             # AudioDevice — mirrors Swift fftAnalyzer.setInputDevice(match)
    peakInfoChanged: QtCore.Signal = QtCore.Signal(float, float)  # (peak_hz, peak_db)
    levelChanged: QtCore.Signal = QtCore.Signal(int)              # level 0-100 (dB+100)
    comparisonChanged: QtCore.Signal = QtCore.Signal(bool)         # True=entering, False=leaving
    freqRangeChanged: QtCore.Signal = QtCore.Signal(int, int)      # (fmin, fmax) — pan/zoom

    # Color palette for comparison overlays — mirrors comparisonPalette in TapToneAnalyzer.swift
    _COMPARISON_PALETTE: list[tuple[int, int, int]] = [
        (0,   122, 255),   # blue
        (255, 149,   0),   # orange
        (52,  199,  89),   # green
        (175,  82, 222),   # purple
        (48,  176, 199),   # teal
    ]

    def __init__(
        self,
        fft_size: int,
        sampling_rate: int,
        frange: dict[str, int],
        threshold: int,
    ) -> None:
        super().__init__()

        # Configure plot appearance
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setLabel("left", "FFT Magnitude (dB)")
        self.setLabel("bottom", "Frequency (Hz)")
        self.setTitle("FFT Peaks", color="#333333")
        # Restore persisted dB range — mirrors Swift's @State minDB/maxDB initialized
        # from TapDisplaySettings.minMagnitude / TapDisplaySettings.maxMagnitude.
        import views.utilities.tap_settings_view as _as_init
        self.setYRange(_as_init.AppSettings.db_min(), _as_init.AppSettings.db_max(), padding=0)

        # Enable and configure top axis for note labels
        plot_item = self.getPlotItem()
        plot_item.hideButtons()  # remove the built-in auto-range "A" button
        plot_item.showAxis("top")
        top_axis = plot_item.getAxis("top")
        top_axis.setStyle(showValues=True)
        top_axis.setTicks([[]])

        plot_item.showAxis("right")
        right_axis = plot_item.getAxis("right")
        right_axis.setStyle(showValues=False, tickLength=0)
        right_axis.setWidth(10)

        self.annotations: fft_a.FftAnnotations = fft_a.FftAnnotations(self)

        # Disable pyqtgraph's built-in right-click menu; we provide our own.
        self.getPlotItem().setMenuEnabled(False)

        # threshold_y is the rendering value for the peak threshold line (dB relative to 0).
        # Derived from threshold on construction; kept in sync by set_threshold.
        self.threshold_x: int = sampling_rate // 2
        self.threshold_y: int = threshold - 100

        # Enforce pan/zoom bounds matching Swift's SpectrumView+GestureHandlers limits:
        # frequency 0–5000 Hz (min span 50 Hz), magnitude −120–+20 dB (min span 10 dB).
        self.getPlotItem().vb.setLimits(
            xMin=0, xMax=5000, minXRange=50,
            yMin=-120, yMax=20, minYRange=10,
        )

        # Canvas-local display viewport — tracks the visible frequency range for
        # pan/zoom and peak display.  Separate from analyzer.min_frequency/
        # max_frequency, which mirror Swift TapToneAnalyzer.minFrequency and are
        # the analysis window used by find_peaks (never written by canvas pan/zoom).
        self._minFreq: float = float(frange["f_min"])
        self._maxFreq: float = float(frange["f_max"])
        self.setXRange(frange["f_min"], frange["f_max"], padding=0)

        # Resolve the saved AudioDevice (fingerprint → live index).
        # Mirrors Swift RealtimeFFTAnalyzer selectedInputDevice restore logic.
        from models.audio_device import AudioDevice as _AudioDevice
        _saved_audio_device: _AudioDevice | None = None
        try:
            _all_devs = list(sd.query_devices())
            _saved_fp = _as.AppSettings.audio_device_fingerprint()
            if _saved_fp:
                # Try fingerprint match first (name:sample_rate), then name-only fallback.
                _proto = _AudioDevice.from_fingerprint(_saved_fp)
                if _proto is not None:
                    _saved_audio_device = _proto.resolve(_all_devs)
                if _saved_audio_device is None:
                    # Name-only fallback for settings saved before fingerprints.
                    _saved_name = _as.AppSettings.device_name()
                    for _d in _all_devs:
                        if str(_d["name"]) == _saved_name and _d["max_input_channels"] > 0:
                            _saved_audio_device = _AudioDevice.from_sounddevice_dict(_d)
                            break
        except Exception:
            pass

        # If the saved device wasn't found, fall back to the system default input
        # and persist it so AppSettings reflects reality.
        if _saved_audio_device is None:
            try:
                _def_info = sd.query_devices(kind="input")
                if _def_info is not None:
                    _saved_audio_device = _AudioDevice.from_sounddevice_dict(_def_info)
                    _as.AppSettings.set_audio_device(_saved_audio_device)
            except Exception:
                pass

        # Use the selected device's native sample rate if available.
        # AudioDevice already carries sample_rate so no extra OS query is needed.
        if _saved_audio_device is not None:
            _native_rate = int(_saved_audio_device.sample_rate)
            if _native_rate > 0:
                sampling_rate = _native_rate

        # ── TapToneAnalyzer: the model ─────────────────────────────────────
        # Auto-load calibration profile before constructing the analyzer so we
        # can pass the corrections array in.  Try fingerprint key first, then
        # name-only fallback for profiles saved before fingerprints.
        _initial_calibration = None
        if _saved_audio_device is not None:
            _cal = _mc_mod.CalibrationStorage.calibration_for_device(
                _saved_audio_device.fingerprint
            )
            if _cal is None:
                _cal = _mc_mod.CalibrationStorage.calibration_for_device(
                    _saved_audio_device.name
                )
            if _cal is not None:
                _x = np.arange(0, fft_size // 2 + 1)
                _freq_tmp = _x * sampling_rate // fft_size
                _initial_calibration = _cal.interpolate_to_bins(_freq_tmp)

        guitar_type_str = _as.AppSettings.guitar_type()

        self.analyzer: td.TapToneAnalyzer = td.TapToneAnalyzer()
        self.analyzer.start(
            parent_widget=self,
            sample_rate=sampling_rate,
            fft_size=fft_size,
            audio_device=_saved_audio_device,
            calibration_corrections=_initial_calibration,
        )
        # Wire the analyzer into FftAnnotations so dragged positions are persisted
        # in the model and survive pan/zoom annotation rebuilds.
        self.annotations._analyzer = self.analyzer
        # Display mode is initialised to AnalysisDisplayMode.LIVE in TapToneAnalyzer.__init__.
        # Set initial peak threshold on the analyzer.
        # peak_threshold is stored as dBFS; threshold input is 0-100 scale.
        self.analyzer.peak_threshold = float(threshold - 100)
        # analysis_min_frequency / analysis_max_frequency are initialised from AppSettings
        # in TapToneAnalyzer.__init__ and must not be overwritten with the display viewport.

        # Convenience alias kept for code that still reads self.mic
        self.mic: Microphone = self.analyzer.mic
        # ── Connect analyzer signals → FftCanvas signals (forwarding) ────
        # This allows guitar_tap.py to connect to FftCanvas signals as before.
        self.analyzer.peaksChanged.connect(self.peaksChanged)
        self.analyzer.framerateUpdate.connect(self.framerateUpdate)
        self.analyzer.levelChanged.connect(self.levelChanged)
        self.analyzer.averagesChanged.connect(self.averagesChanged)
        self.analyzer.newSample.connect(self.newSample)
        self.analyzer.tapDetectedSignal.connect(self._on_tap_detected_from_analyzer)
        self.analyzer.tapCountChanged.connect(self.tapCountChanged)
        self.analyzer.ringOutMeasured.connect(self.ringOutMeasured)
        self.analyzer.devicesChanged.connect(self.devicesChanged)
        self.analyzer.currentDeviceLost.connect(self.currentDeviceLost)
        self.analyzer.plateStatusChanged.connect(self.plateStatusChanged)
        self.analyzer.plateAnalysisComplete.connect(self.plateAnalysisComplete)
        self.analyzer.tapDetectionPaused.connect(self.tapDetectionPaused)
        self.analyzer.measurementComplete.connect(self.measurementComplete)
        self.analyzer.statusMessageChanged.connect(self.statusMessageChanged)
        self.analyzer.loadedMeasurementNameChanged.connect(self.loadedMeasurementNameChanged)
        self.analyzer.playingFileNameChanged.connect(self.playingFileNameChanged)
        self.analyzer.showLoadedSettingsWarningChanged.connect(self.showLoadedSettingsWarningChanged)
        self.analyzer.microphoneWarningChanged.connect(self.microphoneWarningChanged)
        self.analyzer.requestDeviceSwitch.connect(self.requestDeviceSwitch)
        self.analyzer.comparisonChanged.connect(self._on_comparison_changed_from_analyzer)
        self.analyzer.materialSpectraChanged.connect(self.load_material_spectra)
        self.analyzer.peakInfoChanged.connect(self.peakInfoChanged)
        # spectrumUpdated drives the spectrum line rendering path.
        # peaksChanged drives the scatter plot — single authoritative source for
        # both the scatter plot and the results panel.
        self.analyzer.spectrumUpdated.connect(self._on_spectrum_updated)
        self.analyzer.peaksChanged.connect(self._on_peaks_changed_scatter)
        # Clear annotations reactively when a new averaged sample is accepted —
        # mirrors Swift's onChange(of: tap.numAverages) rather than inline polling.
        self.analyzer.averagesChanged.connect(self._on_averages_changed)

        # FFT line
        self.fft_line: pg.PlotDataItem = self.plot(
            [], [], pen=pg.mkPen("r", width=1)
        )

        # Peak scatter points
        self.points: pg.ScatterPlotItem = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen(None), brush=pg.mkBrush(30, 100, 200, 200)
        )
        self.selected_point: pg.ScatterPlotItem = pg.ScatterPlotItem(
            size=16, pen=pg.mkPen((180, 0, 0, 220), width=1),
            brush=pg.mkBrush(220, 30, 30, 220), symbol='star',
        )
        self.addItem(self.points)
        self.addItem(self.selected_point)

        self.points.sigClicked.connect(self.point_picked)

        # Threshold lines — use InfiniteLine so labels stay in view when panned
        _peak_y: int = self.threshold_y
        _tap_y: int  = _as.AppSettings.tap_threshold() - 100
        _hyst: float = _as.AppSettings.hysteresis_margin()

        # Label opts: anchors are (x, y) where x=0 left-align, x=1 right-align;
        #             y=0 text below position, y=1 text above position.
        _lbl_opts_peak    = {"position": 0.01, "color": (0, 200, 0),   "anchors": [(0, 1), (0, 1)]}
        _lbl_opts_trigger = {"position": 0.99, "color": (220, 130, 0), "anchors": [(1, 1), (1, 1)]}
        _lbl_opts_reset   = {"position": 0.01, "color": (220, 130, 0), "anchors": [(0, 0), (0, 0)]}
        _dash = QtCore.Qt.PenStyle.DashLine
        _dot  = QtCore.Qt.PenStyle.DotLine

        # Peak-minimum line (green solid) — "Peak: x dB", left, above
        self.line_threshold = pg.InfiniteLine(
            pos=_peak_y, angle=0,
            pen=pg.mkPen("g", width=1),
            label=f"Peak: {_peak_y} dB",
            labelOpts=_lbl_opts_peak,
        )
        self.addItem(self.line_threshold)

        # Tap-trigger line (orange dashed) — "Trigger: x dB", right, above
        self._tap_threshold_y: int = _tap_y
        self._hysteresis_margin: float = _hyst
        self.line_tap_threshold = pg.InfiniteLine(
            pos=_tap_y, angle=0,
            pen=pg.mkPen(pg.mkColor(220, 130, 0), width=1, style=_dash),
            label=f"Trigger: {_tap_y} dB",
            labelOpts=_lbl_opts_trigger,
        )
        self.addItem(self.line_tap_threshold)

        # Hysteresis reset line (orange dotted) — "Reset: x dB", left, below
        self.line_reset_threshold = pg.InfiniteLine(
            pos=_tap_y - _hyst, angle=0,
            pen=pg.mkPen(pg.mkColor(220, 130, 0), width=1, style=_dot),
            label=f"Reset: {_tap_y - _hyst} dB",
            labelOpts=_lbl_opts_reset,
        )
        self.addItem(self.line_reset_threshold)

        # Mode band overlays
        self._mode_band_items: list = []
        self._mode_bands_visible: bool = True

        # Mode color map (freq → RGB) — kept on canvas for rendering
        self._mode_color_map: dict[float, tuple[int, int, int]] = {}

        # Scene event filter to detect end of annotation drag
        self._scene_filter = _SceneMouseReleaseFilter(self)
        self._scene_filter.released.connect(self.annotations.annotation_moved)
        self.scene().installEventFilter(self._scene_filter)

        # Hover cursor readout
        self._cursor_label = pg.TextItem(
            html="", anchor=(0.0, 1.0),
            fill=pg.mkBrush(255, 255, 255, 180),
        )
        self._cursor_label.setZValue(200)
        self.addItem(self._cursor_label)
        self._cursor_label.setVisible(False)

        # Crosshair lines — follow mouse when free, snap to curve when held
        _cross_pen = pg.mkPen((80, 80, 80, 180), width=1)
        self._crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=_cross_pen)
        self._crosshair_h = pg.InfiniteLine(angle=0,  movable=False, pen=_cross_pen)
        self._crosshair_v.setZValue(150)
        self._crosshair_h.setZValue(150)
        self._crosshair_v.setVisible(False)
        self._crosshair_h.setVisible(False)
        self.addItem(self._crosshair_v)
        self.addItem(self._crosshair_h)

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self.getPlotItem().vb.sigXRangeChanged.connect(self._refresh_peaks_for_viewport)

        # Initialise mode bands for the saved guitar type
        self.set_guitar_type_bands(guitar_type_str)

        # Overlay text shown when analyzer is not running
        self._overlay_label = pg.TextItem(
            text="Press Start to begin",
            anchor=(0.5, 0.5),
            color=(120, 120, 120),
        )
        self._overlay_label.setZValue(300)
        font = QtGui.QFont()
        font.setPointSize(18)
        self._overlay_label.setFont(font)
        self.addItem(self._overlay_label)
        # Position the overlay after the view is fully set up
        QtCore.QTimer.singleShot(0, self._center_overlay)

        # ⓘ Info button — upper-right overlay, shows Zoom & Pan help popup
        self._info_btn = QtWidgets.QToolButton(self)
        self._info_btn.setText("ⓘ")
        self._info_btn.setFixedSize(22, 22)
        self._info_btn.setStyleSheet(
            "QToolButton { border: none; background: transparent;"
            " color: rgba(120,120,120,180); font-size: 15px; }"
            "QToolButton:hover { color: rgba(60,60,60,220); }"
        )
        self._info_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._info_btn.setToolTip("Zoom & Pan Controls")
        self._info_btn.clicked.connect(self._show_zoom_help)
        self._zoom_popup = _ZoomPanPopup(self)
        # Defer initial position until the widget has been laid out
        QtCore.QTimer.singleShot(0, self._reposition_info_btn)

        # Comparison overlay state — mirrors comparisonSpectra in TapToneAnalyzer.swift
        self._comparison_curves: list[pg.PlotDataItem] = []
        self._comparison_legend: QtWidgets.QWidget | None = None
        # True when _comparison_curves contains material phase overlays (L/C/FLC)
        # rather than user-loaded comparison files.  When True, fft_line must still
        # be updated so the live waveform is visible underneath the overlays —
        # mirrors Swift SpectrumView always rendering spectrumLineContent.
        self._has_material_spectra: bool = False

        # Last viewport-filtered peaks received via peaksChanged signal.
        # Tracks the emitted slice so point_picked and update_mode_colors
        # don't need to re-derive it from saved_peaks + index fields.
        self._current_peaks: list = []  # list[ResonantPeak]

        # Legacy numpy array of shape (N, 3) — [frequency, magnitude, quality].
        # Used by plate-mode consumers that do column-slice arithmetic.
        # Decoupled from analyzer.current_peaks (list[ResonantPeak]) to avoid
        # corrupting the typed peak list with raw arrays.
        import numpy as _np
        self._saved_peaks_array: "npt.NDArray" = _np.zeros((0, 3), dtype=_np.float64)

        # Start the microphone (always running; processing thread gated by start_analyzer())
        self.mic.start()

        # Connect processing thread signals.  The thread is owned by the mic
        # (RealtimeFFTAnalyzer) and accessed via self.analyzer.mic.proc_thread.
        self._connect_proc_thread_signals()
        # Apply the initial calibration to the thread if one was loaded above.
        self.analyzer.mic.proc_thread.set_calibration(self.analyzer._calibration_corrections)

    # ------------------------------------------------------------------ #
    # Backward-compatibility properties — guitar_tap.py reads these directly
    # ------------------------------------------------------------------ #

    @property
    def display_mode(self) -> AnalysisDisplayMode:
        return self.analyzer.display_mode

    @display_mode.setter
    def display_mode(self, value: AnalysisDisplayMode) -> None:
        self.analyzer.display_mode = value

    @property
    def is_measurement_complete(self) -> bool:
        return self.analyzer.is_measurement_complete

    @is_measurement_complete.setter
    def is_measurement_complete(self, value: bool) -> None:
        self.analyzer.is_measurement_complete = value

    @property
    def saved_peaks(self) -> npt.NDArray:
        return self._saved_peaks_array

    @saved_peaks.setter
    def saved_peaks(self, value) -> None:
        self._saved_peaks_array = value

    @property
    def saved_mag_y_db(self):
        return self.analyzer.frozen_magnitudes

    @saved_mag_y_db.setter
    def saved_mag_y_db(self, value) -> None:
        self.analyzer.frozen_magnitudes = value

    @property
    def plate_capture(self):
        """Compatibility shim: returns an adapter exposing per-phase spectra
        (long_mag_db, cross_mag_db, flc_mag_db) and phase state from the
        gated-FFT pipeline via material_tap_phase."""
        return _PlateCaptureAdapter(self.analyzer)

    @property
    def minFreq(self) -> int:
        return int(self._minFreq)

    @minFreq.setter
    def minFreq(self, value: int) -> None:
        self._minFreq = float(value)

    @property
    def maxFreq(self) -> int:
        return int(self._maxFreq)

    @maxFreq.setter
    def maxFreq(self, value: int) -> None:
        self._maxFreq = float(value)

    @property
    def comparison_labels(self):
        return self.analyzer.comparison_labels

    @comparison_labels.setter
    def comparison_labels(self, value) -> None:
        self.analyzer.comparison_labels = value

    @property
    def freq(self):
        return self.analyzer.freq

    @freq.setter
    def freq(self, value) -> None:
        self.analyzer.freq = value

    @property
    def display_spectrum(self) -> tuple:
        """Return (freqs, mag_db) as a matched pair from a single atomic read.

        Mirrors Swift ``displaySpectrum`` in TapToneAnalysisView+SpectrumViews.swift.
        Reading ``is_measurement_complete`` once here ensures both arrays always
        come from the same source (frozen or live) and therefore always have
        matching lengths.  Callers that read the flag separately for freq and
        mag_db risk receiving mismatched arrays when the flag changes between
        the two reads.
        """
        from models.analysis_display_mode import AnalysisDisplayMode as _ADM
        if self.analyzer.is_measurement_complete:
            return (self.analyzer.frozen_frequencies, self.analyzer.frozen_magnitudes)
        # During a device-change settle, display_mode is FROZEN but
        # is_measurement_complete is False.  Return the frozen arrays directly
        # (empty = blank spectrum during settle).  Mirrors the Swift fix in
        # TapToneAnalysisView+SpectrumViews.swift displaySpectrum.
        if self.analyzer.display_mode == _ADM.FROZEN:
            return (self.analyzer.frozen_frequencies, self.analyzer.frozen_magnitudes)
        return (self.analyzer.freq, None)

    @property
    def _loaded_measurement_peaks(self):
        return self.analyzer.loaded_measurement_peaks

    @_loaded_measurement_peaks.setter
    def _loaded_measurement_peaks(self, value) -> None:
        self.analyzer.loaded_measurement_peaks = value

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Delegate to analyzer — called by guitar_tap.py after loading a measurement."""
        self.analyzer._emit_loaded_peaks_at_threshold()

    # ------------------------------------------------------------------ #
    # Analyzer start / stop
    # ------------------------------------------------------------------ #

    def _center_overlay(self) -> None:
        """Position the overlay label in the centre of the view."""
        vb = self.getPlotItem().vb
        x_range, y_range = vb.viewRange()
        cx = (x_range[0] + x_range[1]) / 2
        cy = (y_range[0] + y_range[1]) / 2
        self._overlay_label.setPos(cx, cy)

    def _connect_proc_thread_signals(self) -> None:
        """Connect proc_thread signals to FftCanvas slots.

        fftFrameReady is connected inside TapToneAnalyzer.start() and
        recreate_proc_thread() — not here.  The analyzer owns that wiring.
        """
        self.analyzer.mic.proc_thread.rmsLevelChanged.connect(self.ampChanged)
        self.analyzer.mic.proc_thread.finished.connect(self._on_proc_thread_finished)

    def _on_proc_thread_finished(self) -> None:
        """Called when the processing thread exits (after stop_analyzer)."""
        pass  # placeholder for future cleanup if needed

    def start_analyzer(self) -> None:
        """Start the processing thread and hide the idle overlay.

        Called on initial startup (thread not yet running).  Delegates all
        model-state reset to analyzer.start_tap_sequence() — mirrors Swift
        where startTapSequence() is a model method that owns
        isMeasurementComplete, capturedTaps, etc.  Canvas is responsible only
        for thread lifecycle and UI overlay.

        For New Tap while the thread is already running, use
        restart_tap_sequence() instead, which keeps the thread alive
        (no audio dropout) — mirrors Swift's AVAudioEngine running continuously.
        """
        self._overlay_label.setVisible(False)
        self.analyzer.start_tap_sequence()
        if self.analyzer.mic.proc_thread.isRunning():
            self.analyzer.mic.proc_thread.stop()
            self.analyzer.mic.proc_thread.wait(500)
            # Recreate thread on the mic (RealtimeFFTAnalyzer owns it) to reset all state.
            self.analyzer.recreate_proc_thread()
            self._connect_proc_thread_signals()
        self.analyzer.mic.proc_thread.reset_state()
        self.analyzer.mic.proc_thread.start()

    def restart_tap_sequence(self) -> None:
        """Begin a new tap sequence while the processing thread is already running.

        Mirrors Swift's New Tap button calling tap.startTapSequence() on a
        continuously-running AVAudioEngine — no audio engine restart occurs.
        In Python the PortAudio stream runs continuously; only the ring buffer
        state is reset (reset_state() is thread-safe) and the analysis state
        machine is restarted via start_tap_sequence().

        If the thread is not running for any reason, falls back to start_analyzer().
        """
        if not self.analyzer.mic.proc_thread.isRunning():
            # Fallback: thread died unexpectedly — do a full restart.
            self.start_analyzer()
            return
        # Reset analysis state (is_measurement_complete = False, is_detecting = True, etc.)
        self.analyzer.start_tap_sequence()
        # Reset ring buffer so stale pre-tap audio doesn't contaminate the new sequence.
        # reset_state() is safe to call on a running thread.
        self.analyzer.mic.proc_thread.reset_state()

    def stop_analyzer(self) -> None:
        """Stop the processing thread and show the idle overlay."""
        self.analyzer.mic.proc_thread.stop()
        self._center_overlay()
        self._overlay_label.setText("Stopped")
        self._overlay_label.setVisible(True)

    def shutdown(self) -> None:
        """Stop the processing thread and wait for it to exit.

        Must be called before the widget is destroyed (e.g. from the main
        window's closeEvent) to prevent Qt from aborting on QThread::~QThread()
        while the thread is still running.
        """
        self.analyzer.mic.proc_thread.stop()
        self.analyzer.mic.proc_thread.wait(2000)

    # ------------------------------------------------------------------ #
    # Guitar mode band overlays
    # ------------------------------------------------------------------ #

    def set_guitar_type_bands(self, guitar_type_str: str) -> None:
        """Rebuild the mode band overlays for the given guitar type."""
        self._remove_mode_bands()
        try:
            guitar_type = gt.GuitarType(guitar_type_str)
        except ValueError:
            return
        from models.tap_display_settings import TapDisplaySettings as _tds
        is_guitar = _tds.measurement_type().is_guitar
        for lo, hi, mode_name, rgba in gm.get_bands(guitar_type):
            r, g, b, _ = rgba
            pen = pg.mkPen((r, g, b), width=1, style=QtCore.Qt.PenStyle.DashLine)
            abbrev = gm.GuitarMode.from_mode_string(mode_name).abbreviation
            lbl_opts = {"position": 0.96, "color": (r, g, b), "anchors": [(0, 1), (0, 1)]}

            lo_line = pg.InfiniteLine(
                pos=lo, angle=90, movable=False, pen=pen,
                label=abbrev, labelOpts=lbl_opts,
            )
            lo_line.setZValue(-10)
            lo_line.setVisible(self._mode_bands_visible and is_guitar)
            self.addItem(lo_line)
            self._mode_band_items.append(lo_line)

            hi_line = pg.InfiniteLine(pos=hi, angle=90, movable=False, pen=pen)
            hi_line.setZValue(-10)
            hi_line.setVisible(self._mode_bands_visible and is_guitar)
            self.addItem(hi_line)
            self._mode_band_items.append(hi_line)

    def _remove_mode_bands(self) -> None:
        for item in self._mode_band_items:
            self.removeItem(item)
        self._mode_band_items.clear()

    def show_mode_bands(self, visible: bool) -> None:
        """Show or hide all mode band overlays.

        Mirrors Swift modeBoundaryContent which is always gated by
        `showModeBoundaries && measurementType.isGuitar` — both conditions
        are re-evaluated on every render.  Python must apply the same joint
        gate here because setVisible(visible) would otherwise re-show bands
        when called while in plate/brace mode.
        """
        from models.tap_display_settings import TapDisplaySettings as _tds
        is_guitar = _tds.measurement_type().is_guitar
        self._mode_bands_visible = visible
        for item in self._mode_band_items:
            item.setVisible(visible and is_guitar)

    # ------------------------------------------------------------------ #
    # Hot-plug device detection (forwarded from analyzer signals)
    # ------------------------------------------------------------------ #

    # Screen-distance threshold (pixels) for locking crosshair to a comparison curve.
    _CURVE_GRAVITY_PX: float = 12.0

    def _on_mouse_moved(self, scene_pos) -> None:
        """Track the cursor: snaps to FFT curve when results are held, free otherwise."""
        vb = self.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(scene_pos):
            self._cursor_label.setVisible(False)
            self._crosshair_v.setVisible(False)
            self._crosshair_h.setVisible(False)
            return
        view_pos = vb.mapSceneToView(scene_pos)
        mouse_freq = float(view_pos.x())
        mouse_db   = float(view_pos.y())

        freq_color = "rgb(220,50,50)"   # default red

        # Material spectra overlays (plate/brace review states) are stored in
        # _comparison_curves even when is_comparing is False.  Snap to them
        # whenever they are present — mirrors Swift resolveSnapState which snaps
        # when isMeasurementComplete || !materialSpectra.isEmpty.
        has_material_curves = bool(self._comparison_curves)

        if (self.is_comparing or (has_material_curves and not self.is_measurement_complete)) and self._comparison_curves:
            # Snap to the nearest comparison/material curve by screen-Y distance (mirrors
            # Swift's nearestSeriesIndex() with curveGravityThreshold = 12 pt).
            best_idx   = getattr(self, "_locked_series_index", 0)
            best_px_dy = float("inf")

            for i, curve in enumerate(self._comparison_curves):
                xdata, ydata = curve.getData()
                if xdata is None or len(xdata) == 0:
                    continue
                bin_idx = int(np.searchsorted(xdata, mouse_freq))
                bin_idx = max(0, min(bin_idx, len(xdata) - 1))
                curve_db = float(ydata[bin_idx])
                # Convert dB difference to screen pixels for apples-to-apples comparison
                curve_scene = vb.mapViewToScene(
                    QtCore.QPointF(float(xdata[bin_idx]), curve_db)
                )
                px_dy = abs(scene_pos.y() - curve_scene.y())
                if px_dy < best_px_dy:
                    best_px_dy = px_dy
                    best_idx   = i

            # Apply hysteresis: only switch curves when outside gravity threshold
            locked = getattr(self, "_locked_series_index", 0)
            if best_px_dy < self._CURVE_GRAVITY_PX or locked >= len(self._comparison_curves):
                self._locked_series_index = best_idx
            locked = self._locked_series_index

            # Re-evaluate display values for the locked curve
            curve = self._comparison_curves[locked]
            xdata, ydata = curve.getData()
            if xdata is not None and len(xdata) > 0:
                bin_idx = int(np.searchsorted(xdata, mouse_freq))
                bin_idx = max(0, min(bin_idx, len(xdata) - 1))
                display_freq = float(xdata[bin_idx])
                display_db   = float(ydata[bin_idx])
            else:
                display_freq = mouse_freq
                display_db   = mouse_db

            r, g, b = self._COMPARISON_PALETTE[locked % len(self._COMPARISON_PALETTE)]
            freq_color = f"rgb({r},{g},{b})"

        elif self.is_measurement_complete and np.any(self.saved_mag_y_db):
            # Snap to nearest FFT bin on the frozen curve.
            # Use frozen_frequencies (not self.freq): a Swift-saved plate measurement has
            # 16 384 bins while the live self.freq has 32 769.  Indexing frozen_magnitudes
            # with an index derived from self.freq would go out of bounds.
            frozen_freq = self.analyzer.frozen_frequencies
            if len(frozen_freq) > 0:
                idx = int(np.searchsorted(frozen_freq, mouse_freq))
                idx = max(0, min(idx, len(frozen_freq) - 1))
                display_freq = float(frozen_freq[idx])
                display_db   = float(self.saved_mag_y_db[idx])
            else:
                display_freq = mouse_freq
                display_db   = mouse_db
        else:
            # Free mouse tracking — no curve snap
            display_freq = mouse_freq
            display_db   = mouse_db

        self._crosshair_v.setPos(display_freq)
        self._crosshair_h.setPos(display_db)
        freq_str = f"{display_freq/1000:.2f} kHz" if display_freq >= 1000 else f"{display_freq:.1f} Hz"
        html = (
            f'<center>'
            f'<b style="color:{freq_color};">{freq_str}</b><br/>'
            f'<span style="color:rgb(130,130,130);">{display_db:.1f} dB</span>'
            f'</center>'
        )
        self._cursor_label.setHtml(html)
        doc = self._cursor_label.textItem.document()
        doc.setTextWidth(-1)
        doc.setTextWidth(doc.idealWidth())
        self._cursor_label.setPos(display_freq, display_db)
        self._crosshair_v.setVisible(True)
        self._crosshair_h.setVisible(True)
        self._cursor_label.setVisible(True)

    # ------------------------------------------------------------------ #
    # Microphone calibration (delegates to analyzer)
    # ------------------------------------------------------------------ #

    def load_calibration(self, path: str) -> bool:
        """Load and pre-interpolate a calibration file onto the FFT bin grid."""
        return self.analyzer.load_calibration(path)

    def load_calibration_from_profile(self, cal: "_mc_mod.MicrophoneCalibration") -> None:
        """Apply a pre-parsed MicrophoneCalibration profile to the FFT pipeline."""
        self.analyzer.load_calibration_from_profile(cal)

    def clear_calibration(self) -> None:
        """Remove the active calibration (no dB correction applied)."""
        self.analyzer.clear_calibration()

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self.analyzer.current_calibration_device()

    # ------------------------------------------------------------------ #
    # Tap detector / sequence control (delegates to analyzer)
    # ------------------------------------------------------------------ #

    def reset_tap_detector(self) -> None:
        """Public wrapper to reset the tap detector state machine."""
        self.analyzer.reset_tap_detector()

    @property
    def chart_title(self) -> str:
        """Compute the chart title, mirroring Swift's chartTitle computed property:
            fft.playingFileName ?? tap.loadedMeasurementName ?? "New"
        """
        playing = getattr(self.analyzer.mic, "playing_file_name", None)
        loaded = getattr(self.analyzer, "loaded_measurement_name", None)
        suffix = playing or loaded or "New"
        return f"FFT Peaks \u2014 {suffix}"

    def set_loaded_measurement_name(self, name: str | None) -> None:
        """Update the chart title to reflect the loaded measurement name.

        Mirrors Swift: chartTitle = fft.playingFileName ?? tap.loadedMeasurementName ?? "New"
        If a file is currently playing its name takes priority over the loaded measurement name.
        """
        self.setTitle(self.chart_title, color="#333333")

    def set_playing_file_name(self, name: str | None) -> None:
        """Update the chart title to reflect the playing file name, or revert to
        the loaded measurement name / 'New' when playback ends.

        Mirrors Swift: chartTitle = fft.playingFileName ?? tap.loadedMeasurementName ?? "New"
        Connected to playingFileNameChanged signal.
        """
        self.setTitle(self.chart_title, color="#333333")

    def start_tap_sequence(self) -> None:
        """Begin a fresh tap sequence: clear any accumulated spectra and restart warmup."""
        self.analyzer.start_tap_sequence()

    def cancel_tap_sequence(self) -> None:
        """Cancel the current tap sequence and restart warmup — matches Swift cancelTapSequence."""
        self.analyzer.cancel_tap_sequence()

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing (1 = immediate freeze)."""
        self.analyzer.set_tap_num(n)

    def set_measurement_type(self, measurement_type) -> None:
        """Switch between Guitar / Plate / Brace analysis modes."""
        self.analyzer.set_measurement_type(measurement_type)
        is_guitar = measurement_type.is_guitar
        # Mode bands and peak threshold line are guitar-only — mirrors Swift's
        # showModeBoundaries && measurementType.isGuitar and isGuitar threshold line guard.
        for item in self._mode_band_items:
            item.setVisible(is_guitar and self._mode_bands_visible)
        self.line_threshold.setVisible(is_guitar and not self.is_comparing)

    def start_plate_analysis(self) -> None:
        """Arm the plate capture state machine for the next tap(s)."""
        self.analyzer.start_plate_analysis()

    def reset_plate_analysis(self) -> None:
        """Abort plate capture and return to idle."""
        self.analyzer.reset_plate_analysis()

    def set_auto_scale(self, enabled: bool) -> None:
        """Enable/disable automatic Y-axis scaling to the spectrum floor."""
        self.analyzer._auto_scale_db = enabled
        if not enabled:
            self.setYRange(-100, 0, padding=0)

    def set_tap_threshold(self, value: int) -> None:
        """Update the tap-detection threshold (0–100 scale)."""
        self._tap_threshold_y = value - 100
        self.analyzer.set_tap_threshold(value)
        self.line_tap_threshold.setPos(self._tap_threshold_y)
        self.line_tap_threshold.label.setText(f"Trigger: {self._tap_threshold_y} dB")
        self._update_reset_line()

    def _update_reset_line(self) -> None:
        """Reposition the hysteresis reset line based on current tap threshold and margin."""
        reset_y = self._tap_threshold_y - self._hysteresis_margin
        self.line_reset_threshold.setPos(reset_y)
        self.line_reset_threshold.label.setText(f"Reset: {reset_y} dB")

    def set_hysteresis_margin(self, value: float) -> None:
        """Update the tap-detection hysteresis margin (in dB, 1.0–10.0)."""
        self._hysteresis_margin = max(1.0, value)
        self.analyzer.set_hysteresis_margin(value)
        self._update_reset_line()

    def pause_tap_detection(self) -> None:
        """Pause the tap detector; spectrum continues to update."""
        self.analyzer.pause_tap_detection()
        # tapDetectionPaused signal is forwarded from analyzer

    def resume_tap_detection(self) -> None:
        """Resume a paused tap detector."""
        self.analyzer.resume_tap_detection()
        # tapDetectionPaused signal is forwarded from analyzer

    def cancel_tap_sequence(self) -> None:
        """Cancel the in-progress multi-tap sequence and rearm for a fresh tap."""
        self.analyzer.cancel_tap_sequence()

    def set_device(self, device) -> None:
        """Switch the audio input to the given AudioDevice and
        auto-load the calibration associated with that device.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:).
        """
        self.analyzer.set_device(device)

    # ------------------------------------------------------------------ #
    # Peak selection (view-level — updates scatter point)
    # ------------------------------------------------------------------ #

    def select_peak(self, freq: float) -> None:
        """Select the peak (scatter point) with the specified frequency"""
        if self.is_measurement_complete:
            row = np.where(self.saved_peaks[:, 0] == freq)
            magdb = self.saved_peaks[row][0][1]
            self.selected_point.setData(x=[freq], y=[magdb])
            self.analyzer.selected_peak = freq

    def deselect_peak(self, _freq: float) -> None:
        """Deselect the peak (scatter point) with the specified frequency"""
        self.selected_point.setData(x=[], y=[])

    def clear_selected_peak(self) -> None:
        """Reset the selected peak."""
        self.analyzer.selected_peak = -1.0

    def point_picked(
        self, scatter: pg.ScatterPlotItem, points: list, ev
    ) -> None:
        """Handle scatter point click: emit peakSelected if within frequency range."""
        if self.is_measurement_complete and len(points) > 0:
            if self.annotations.select_annotation(scatter):
                return
            index0 = points[0].index()
            if self._current_peaks and index0 < len(self._current_peaks):
                freq = float(self._current_peaks[index0].frequency)
                self.peakSelected.emit(freq)

    # ── info button & zoom/pan help ───────────────────────────────────────────

    def _reposition_info_btn(self) -> None:
        btn = getattr(self, "_info_btn", None)
        if btn is None:
            return
        btn.move(self.width() - btn.width() - 4, 4)
        btn.raise_()

    def _reposition_comparison_legend(self) -> None:
        leg = getattr(self, "_comparison_legend", None)
        if leg is None or not leg.isVisible():
            return
        leg.adjustSize()
        # Position inside the plot area — 8px below the viewbox top edge, 12px
        # from the right edge. Mirrors Swift's .padding(.top, 8).padding(.trailing, 12)
        # applied *inside* the chart overlay, so the legend sits within the axes.
        vb = self.getPlotItem().vb
        scene_rect = vb.sceneBoundingRect()
        vb_top  = int(self.mapFromScene(scene_rect.topLeft()).y())
        vb_right = int(self.mapFromScene(scene_rect.topRight()).x())
        x = vb_right - leg.width() - 12
        y = vb_top + 8
        leg.move(x, y)
        leg.raise_()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reposition_info_btn()
        self._reposition_comparison_legend()

    def _show_zoom_help(self) -> None:
        btn_br = self._info_btn.mapToGlobal(
            QtCore.QPoint(self._info_btn.width(), self._info_btn.height())
        )
        self._zoom_popup.show_near(btn_br)

    # ── wheel event with modifier-key bindings ────────────────────────────────

    def wheelEvent(self, ev: QtGui.QWheelEvent) -> None:
        """Scroll-wheel zoom/pan with modifier keys matching Swift SpectrumView.

        No modifier  — pyqtgraph default (zoom around cursor)
        ⇧ Shift      — pan frequency (X) axis
        ⌥ Alt/Option — pan magnitude (Y) axis
        ⌘ Cmd / ⌃ Ctrl — zoom both axes around centre
        """
        mods = ev.modifiers()
        Mod = QtCore.Qt.KeyboardModifier
        vb = self.getViewBox()

        # On macOS, Shift+scroll converts vertical to horizontal scroll,
        # so read whichever axis has a non-zero delta.
        delta = ev.angleDelta().y()
        if delta == 0:
            delta = ev.angleDelta().x()
        if delta == 0:
            ev.accept()
            return

        if mods & Mod.ShiftModifier:
            # Pan X: shift by 10% of current span (limits enforced by setLimits).
            x0, x1 = vb.viewRange()[0]
            shift = (x1 - x0) * 0.10 * (1 if delta > 0 else -1)
            vb.setXRange(x0 + shift, x1 + shift, padding=0)
            self._refresh_peaks_for_viewport()
            ev.accept()

        elif mods & Mod.AltModifier:
            # Pan Y: shift by 10% of current span (limits enforced by setLimits).
            y0, y1 = vb.viewRange()[1]
            shift = (y1 - y0) * 0.10 * (1 if delta > 0 else -1)
            vb.setYRange(y0 + shift, y1 + shift, padding=0)
            ev.accept()

        elif mods & (Mod.ControlModifier | Mod.MetaModifier):
            # Zoom both axes around centre (limits enforced by setLimits).
            factor = 1.15 ** (delta / 120.0)
            x0, x1 = vb.viewRange()[0]
            y0, y1 = vb.viewRange()[1]
            xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
            xh = (x1 - x0) / 2 / factor
            yh = (y1 - y0) / 2 / factor
            vb.setXRange(xc - xh, xc + xh, padding=0)
            vb.setYRange(yc - yh, yc + yh, padding=0)
            self._refresh_peaks_for_viewport()
            ev.accept()

        else:
            super().wheelEvent(ev)

    # ── context menu (replaces pyqtgraph default) ─────────────────────────────

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """Right-click menu matching the Swift SpectrumView context menu."""
        menu = QtWidgets.QMenu(self)

        # ── Reset to Saved (persisted AppSettings values) ─────────────────
        menu.addAction("Reset Both Axes to Saved",    self._reset_both_to_saved)
        menu.addAction("Reset Frequency Axis to Saved", self._reset_freq_to_saved)
        menu.addAction("Reset Magnitude Axis to Saved", self._reset_mag_to_saved)

        menu.addSeparator()

        # ── Reset to Defaults (factory hard-coded values) ─────────────────
        menu.addAction("Reset Both Axes to Defaults",    self._reset_both_to_defaults)
        menu.addAction("Reset Frequency Axis to Defaults", self._reset_freq_to_defaults)
        menu.addAction("Reset Magnitude Axis to Defaults", self._reset_mag_to_defaults)

        menu.addSeparator()

        # ── Reset Labels ──────────────────────────────────────────────────
        act = menu.addAction("Reset Labels", self.annotations.reset_all_positions)
        act.setEnabled(self.annotations.has_moved_annotations)

        menu.exec(event.globalPos())
        event.accept()

    # ── Axis Reset Helpers ────────────────────────────────────────────────────
    #
    # Each helper computes the target axis values then delivers them via
    # _apply_axis_range so all four bounds are applied in one call.
    # Mirrors Swift SpectrumView+GestureHandlers.swift resetBothAxesToDefaults
    # et al., which call onAxisRangeReset(minFreq, maxFreq, minDB, maxDB).

    def _apply_axis_range(
        self, fmin: float, fmax: float, db_min: float, db_max: float
    ) -> None:
        """Apply all four axis bounds atomically.

        Mirrors Swift ``TapToneAnalysisView.applyAxisRange(minFreq:maxFreq:minDB:maxDB:)``.
        All reset helpers delegate here so there is a single application point,
        matching the Swift pattern where ``onAxisRangeReset`` is the sole path
        through which axis resets reach the chart.
        """
        self.update_axis(fmin, fmax)
        self.setYRange(db_min, db_max, padding=0)

    def _reset_freq_to_saved(self) -> None:
        mt = self.analyzer._measurement_type
        _, (db_min, db_max) = self.getPlotItem().vb.viewRange()
        self._apply_axis_range(
            _as.AppSettings.f_min(mt), _as.AppSettings.f_max(mt), db_min, db_max,
        )

    def _reset_mag_to_saved(self) -> None:
        (fmin, fmax), _ = self.getPlotItem().vb.viewRange()
        self._apply_axis_range(
            fmin, fmax, _as.AppSettings.db_min(), _as.AppSettings.db_max(),
        )

    def _reset_both_to_saved(self) -> None:
        self._apply_axis_range(
            _tds.min_frequency(), _tds.max_frequency(),
            _as.AppSettings.db_min(), _as.AppSettings.db_max(),
        )

    def _reset_freq_to_defaults(self) -> None:
        _, (db_min, db_max) = self.getPlotItem().vb.viewRange()
        self._apply_axis_range(
            _tds.default_min_frequency(_tds.measurement_type()),
            _tds.default_max_frequency(_tds.measurement_type()),
            db_min, db_max,
        )

    def _reset_mag_to_defaults(self) -> None:
        (fmin, fmax), _ = self.getPlotItem().vb.viewRange()
        self._apply_axis_range(
            fmin, fmax,
            _as.AppSettings.default_db_min(), _as.AppSettings.default_db_max(),
        )

    def _reset_both_to_defaults(self) -> None:
        mt = self.analyzer._measurement_type
        self._apply_axis_range(
            _as.AppSettings.default_f_min(mt), _as.AppSettings.default_f_max(mt),
            _as.AppSettings.default_db_min(), _as.AppSettings.default_db_max(),
        )

    def update_axis(self, fmin: int, fmax: int, init: bool = False) -> None:
        """Update the x-axis frequency range"""
        if fmin < fmax:
            self._minFreq = float(fmin)
            self._maxFreq = float(fmax)
            self.setXRange(fmin, fmax, padding=0)
            if not init:
                self.analyzer.recalculate_frozen_peaks_if_needed()

    def _refresh_peaks_for_viewport(self, _vb=None, x_range=None) -> None:
        """Re-emit filtered peaks and update the freq-range label whenever the
        viewport x-range changes (pan, zoom, or explicit wheel-scroll gestures).

        Connected to ViewBox.sigXRangeChanged and also called directly from
        wheelEvent after Shift+scroll pan and Ctrl+scroll zoom.
        """
        vb = self.getPlotItem().vb
        x0, x1 = vb.viewRange()[0]
        fmin = int(round(x0))
        fmax = int(round(x1))
        if fmin >= fmax:
            return
        self._minFreq = float(fmin)
        self._maxFreq = float(fmax)
        if self.display_mode != AnalysisDisplayMode.COMPARISON:
            self.analyzer.recalculate_frozen_peaks_if_needed()
        self.freqRangeChanged.emit(fmin, fmax)

    def set_max_average_count(self, max_average_count: int) -> None:
        """Set the number of averages to take"""
        self.analyzer.set_max_average_count(max_average_count)

    def reset_averaging(self) -> None:
        """Reset the number of averages taken to zero."""
        self.analyzer.reset_averaging()

    def set_avg_enable(self, avg_enable: bool) -> None:
        """Flag to enable/disable the averaging"""
        self.analyzer.set_avg_enable(avg_enable)

    # ------------------------------------------------------------------ #
    # Comparison overlay — delegates to analyzer + manages view curves
    # ------------------------------------------------------------------ #

    @property
    def is_comparing(self) -> bool:
        """True when in comparison display mode — mirrors tap.displayMode == .comparison."""
        return self.display_mode == AnalysisDisplayMode.COMPARISON

    @property
    def comparison_count(self) -> int:
        """Number of active comparison overlay curves."""
        return len(self._comparison_curves)

    @staticmethod
    def _comparison_label(m: object) -> str:
        """Short label for the legend — mirrors comparisonLabel(for:) in Swift."""
        loc = getattr(m, "tap_location", None)
        if loc:
            return loc
        ts = getattr(m, "timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}"
        except Exception:
            return ts[:16]

    def load_comparison(self, measurements: list) -> None:
        """Load guitar measurements as comparison overlays.

        Delegates analysis to the analyzer, then creates PlotDataItem view curves.
        """
        self.clear_comparison()

        # Delegate to analyzer — populates _comparison_data / comparison_labels
        self.analyzer.load_comparison(measurements)

        # Render the curves from analyzer state (shared with the restore path).
        self._render_comparison_curves()

        # comparisonChanged (and therefore _on_comparison_changed_from_analyzer)
        # was already emitted by analyzer.load_comparison — visibility and axis
        # ranges are applied there.

    def _render_comparison_curves(self) -> None:
        """Create PlotDataItem curves and legend from analyzer._comparison_data.

        Called both by load_comparison() (live path) and by
        _on_comparison_changed_from_analyzer() when curves are absent (restore path).
        Assumes _comparison_curves is empty; callers must call clear_comparison() first
        if needed.
        """
        for entry in self.analyzer._comparison_data:
            label    = entry["label"]
            color    = entry["color"]
            freq_arr = entry["freqs"]
            mag_arr  = entry["mags"]
            curve = pg.PlotDataItem(
                freq_arr, mag_arr,
                pen=pg.mkPen(color, width=1.5),
                name=label,
            )
            self.addItem(curve)
            self._comparison_curves.append(curve)

        if self._comparison_curves:
            # Legend — horizontal overlay, top-right
            legend = QtWidgets.QWidget(self)
            legend.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            legend.setStyleSheet(
                "background: rgba(240,240,240,210); border-radius: 6px;"
            )
            row = QtWidgets.QHBoxLayout(legend)
            row.setContentsMargins(8, 4, 8, 4)
            row.setSpacing(12)
            for label, (r, g, b) in self.analyzer.comparison_labels:
                swatch = QtWidgets.QLabel()
                swatch.setFixedSize(16, 2)
                swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border-radius: 1px;")
                text = QtWidgets.QLabel(label)
                css_font = "font-size: 10px;"
                text.setStyleSheet(f"color: rgb({r},{g},{b}); {css_font} background: transparent;")
                entry = QtWidgets.QHBoxLayout()
                entry.setSpacing(4)
                entry.addWidget(swatch, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
                entry.addWidget(text,   0, QtCore.Qt.AlignmentFlag.AlignVCenter)
                row.addLayout(entry)
            legend.adjustSize()
            legend.show()
            self._comparison_legend = legend
            self._reposition_comparison_legend()

        # Clear the main spectrum line — only comparison curves should be visible.
        self.fft_line.setData([], [])
        self.points.setData(x=[], y=[])

        self._locked_series_index = 0

    def clear_comparison(self) -> None:
        """Remove all comparison overlay curves — mirrors clearComparison() in Swift."""
        self._locked_series_index = 0
        for curve in self._comparison_curves:
            self.removeItem(curve)
        self._comparison_curves.clear()
        if self._comparison_legend is not None:
            self._comparison_legend.deleteLater()
            self._comparison_legend = None
        self.analyzer.clear_comparison()
        # comparisonChanged (and _on_comparison_changed_from_analyzer) is emitted
        # by analyzer.clear_comparison — visibility is applied there.

    def _on_comparison_changed_from_analyzer(self, is_comparing: bool) -> None:
        """React to comparison mode entering or leaving.

        Applies visibility of peaks and threshold lines (mirrors the isComparing
        checks in TapToneAnalysisView+SpectrumViews.swift), and applies the
        axis ranges from the comparison data when entering comparison mode.

        Also relays the signal outward so external observers can react.
        """
        showing = not is_comparing
        self.points.setVisible(showing)
        self.selected_point.setVisible(showing)
        # Peak threshold line is guitar-only; hide during comparison regardless.
        self.line_threshold.setVisible(showing and self.analyzer._measurement_type.is_guitar)
        self.line_tap_threshold.setVisible(showing)
        self.line_reset_threshold.setVisible(showing)

        if is_comparing:
            # On the restore path (loading a saved comparison record), the analyzer
            # has populated _comparison_data but the canvas has no curves yet.
            # Render them now before updating the axis or emitting outward.
            if not self._comparison_curves and self.analyzer._comparison_data:
                self._render_comparison_curves()

            # Apply axis ranges from the saved snapshot display bounds — mirrors Swift
            # loadComparison(measurements:) which computes the union of each snapshot's
            # minFreq/maxFreq/minDB/maxDB and publishes it via setLoadedAxisRange.
            #
            # Do NOT derive ranges from np.min/max of the raw frequency/magnitude arrays:
            # that gives the full FFT extent (e.g. 0–5000 Hz) rather than the display
            # window that was active when each measurement was captured.
            snaps = self.analyzer.loaded_comparison_snapshots()
            if snaps:
                min_freq = int(min(s.min_freq for s in snaps))
                max_freq = int(max(s.max_freq for s in snaps))
                min_db   = float(min(s.min_db   for s in snaps))
                max_db   = float(max(s.max_db   for s in snaps))
                self.update_axis(min_freq, max_freq)
                self.setYRange(min_db, max_db, padding=0)

        self.comparisonChanged.emit(is_comparing)

    def set_measurement_complete(self, is_measurement_complete: bool) -> None:
        """Update canvas-side UI for frozen/live state.

        Called by the view in response to the measurementComplete signal from the
        model.  Does NOT call analyzer.set_measurement_complete — the model is the
        source of truth and already emitted the signal that triggered this call.
        """
        if not is_measurement_complete:
            self.selected_point.setData(x=[], y=[])
            self.clear_selected_peak()
            # clear_comparison was already called by analyzer.set_measurement_complete
            # but we need to clear the view curves too
            self._clear_comparison_view()
            # Reset the Y range to the full live view so the ambient noise floor
            # is visible.  The loaded-measurement range (set by setYRange in
            # _restore_measurement) is appropriate for frozen display but typically
            # too narrow to show quiet live audio.
            self.setYRange(-100, 0, padding=0)

    def _clear_comparison_view(self) -> None:
        """Remove comparison view curves (called when returning to live mode)."""
        self._locked_series_index = 0
        for curve in self._comparison_curves:
            self.removeItem(curve)
        self._comparison_curves.clear()
        self._has_material_spectra = False
        if self._comparison_legend is not None:
            self._comparison_legend.deleteLater()
            self._comparison_legend = None

    def load_material_spectra(
        self,
        spectra: "list[tuple[str, tuple[int,int,int], list, list]]",
    ) -> None:
        """Display per-phase plate/brace spectra as overlaid colored curves.

        Mirrors Swift's materialSpectra computed property in
        TapToneAnalysisView+SpectrumViews.swift, which builds the L/C/FLC overlay
        from tap.longitudinalSpectrum / crossSpectrum / flcSpectrum.

        Each entry in `spectra` is (label, (r,g,b), freq_list, mag_list).
        Reuses the _comparison_curves / legend infrastructure so the display is
        identical to the comparison overlay but driven by phase snapshots.
        The live fft_line remains visible underneath the overlays — mirrors Swift's
        spectrumLineContent always being rendered with materialSpectraContent on top.
        """
        import numpy as np

        # Clear any existing curves/legend first.
        self._clear_comparison_view()

        if not spectra:
            return

        self._has_material_spectra = True

        # Clear the live fft_line immediately so the stale waveform from just
        # before the phase transition does not persist as a red ghost underneath
        # the phase overlay curves.  set_draw_data() will keep it cleared while
        # is_reviewing is True (it skips the setData call), but we must clear it
        # here on the transition because set_draw_data() may not be called again
        # until the next FFT frame arrives.
        # Mirrors Swift SpectrumView: spectrumLineContent is excluded from the
        # chart entirely when isReviewingMaterialPhase is true.
        if self.analyzer.material_tap_phase.is_reviewing:
            self.fft_line.setData([], [])

        for label, (r, g, b), freq_list, mag_list in spectra:
            freq_arr = np.array(freq_list, dtype=np.float64)
            mag_arr  = np.array(mag_list,  dtype=np.float64)
            curve = pg.PlotDataItem(
                freq_arr, mag_arr,
                pen=pg.mkPen((r, g, b), width=2),
                name=label,
            )
            self.addItem(curve)
            self._comparison_curves.append(curve)

        # Build legend — mirrors load_comparison legend layout.
        legend = QtWidgets.QWidget(self)
        legend.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        legend.setStyleSheet(
            "background: rgba(240,240,240,210); border-radius: 6px;"
        )
        row = QtWidgets.QHBoxLayout(legend)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(12)
        for label, (r, g, b), _f, _m in spectra:
            swatch = QtWidgets.QLabel()
            swatch.setFixedSize(16, 2)
            swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border-radius: 1px;")
            text = QtWidgets.QLabel(label)
            text.setStyleSheet(
                f"color: rgb({r},{g},{b}); font-size: 10px; background: transparent;"
            )
            entry = QtWidgets.QHBoxLayout()
            entry.setSpacing(4)
            entry.addWidget(swatch, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            entry.addWidget(text,   0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            row.addLayout(entry)
        legend.adjustSize()
        legend.show()
        self._comparison_legend = legend
        self._reposition_comparison_legend()

        # fft_line is cleared above when entering a review phase (mirrors Swift hiding
        # spectrumLineContent when isReviewingMaterialPhase is true).  During capture
        # phases (not reviewing) the live waveform remains visible so the user can
        # see the spectrum as they prepare to tap.

    def setMinFreq(self, minFreq: int) -> None:
        """As it says"""
        self.update_axis(minFreq, self.maxFreq)

    def setMaxFreq(self, maxFreq: int) -> None:
        """As it says"""
        self.update_axis(self.minFreq, maxFreq)

    def set_threshold(self, threshold: int) -> None:
        """Set the threshold used to limit both the triggering of a sample
        and the threshold on finding peaks. The threshold value is always 0 to 100.
        """
        self.analyzer.peak_threshold = float(threshold - 100)

        self.threshold_x = self.analyzer.mic.rate // 2
        self.threshold_y = threshold - 100

        self.line_threshold.setPos(self.threshold_y)
        self.line_threshold.label.setText(f"Peak: {self.threshold_y} dB")

        self.analyzer.recalculate_frozen_peaks_if_needed()

        self.selected_point.setData(x=[], y=[])
        self.peakDeselected.emit()
        if self._current_peaks and self.analyzer.selected_peak > 0:
            if self.analyzer.selected_peak in [p.frequency for p in self._current_peaks]:
                self.peakSelected.emit(self.analyzer.selected_peak)

    def _peak_brushes(self, freqs) -> list:
        """Return a list of QBrush objects, one per peak, coloured by mode."""
        brushes = []
        for f in freqs:
            r, g, b = self._mode_color_map.get(float(f), (30, 100, 200))
            brushes.append(pg.mkBrush(r, g, b, 200))
        return brushes

    def update_mode_colors(self, color_map: dict) -> None:
        """Update the per-peak mode colour map and redraw scatter points."""
        self._mode_color_map = color_map
        if self._current_peaks:
            freqs = [p.frequency for p in self._current_peaks]
            mags  = [p.magnitude for p in self._current_peaks]
            self.points.setData(
                x=freqs, y=mags,
                brush=self._peak_brushes(freqs),
            )

    def _on_peaks_changed_scatter(self, peaks) -> None:
        """Update the scatter plot whenever the analyzer emits peaksChanged.

        This is the single authoritative path for updating peak scatter points.
        Connected to analyzer.peaksChanged so both the scatter plot and the
        results panel (also connected to peaksChanged) are always in sync —
        mirrors how Swift's SpectrumView.allPeaksInRange reactively re-filters
        currentPeaks on every render rather than keeping a separate state.

        In guitar mode, unknown-mode peaks are excluded when show_unknown_modes
        is False, mirroring Swift's SpectrumView.allPeaksInRange filter.
        """
        if peaks:
            # Filter unknown peaks in guitar mode when the setting is off
            mt = _as.AppSettings.measurement_type()
            if mt.is_guitar and not _as.AppSettings.show_unknown_modes():
                guitar_type_str = _as.AppSettings.guitar_type()
                try:
                    guitar_type = gt.GuitarType(guitar_type_str)
                except ValueError:
                    guitar_type = gt.GuitarType.CLASSICAL
                peaks = [p for p in peaks if gm.GuitarMode.is_known(p.frequency, guitar_type)]
            self._current_peaks = peaks
            freqs = [p.frequency for p in peaks]
            mags  = [p.magnitude for p in peaks]
            self.points.setData(x=freqs, y=mags, brush=self._peak_brushes(freqs))
        else:
            self._current_peaks = []
            self.points.setData(x=[], y=[])

    def set_draw_data(self, mag_db, freqs=None) -> None:
        """Update the spectrum line and auto-scale the Y axis if enabled.

        The scatter plot is driven separately via _on_peaks_changed_scatter,
        which is connected to analyzer.peaksChanged.

        Args:
            mag_db: Magnitude data (dB) to render.
            freqs:  Frequency axis array matched to *mag_db*.  When supplied,
                    ``freqs`` and ``mag_db`` are guaranteed to come from the
                    same atomic snapshot (frozen or live), preventing mismatched
                    array lengths during mode transitions.  Falls back to
                    ``self.freq`` for legacy callers.
        """
        freq_axis = freqs if freqs is not None else self.freq
        # Suppress fft_line (live waveform) in two cases:
        # 1. User comparison mode (user-loaded files) — only overlay curves shown.
        # 2. Material phase review (REVIEWING_L/C/FLC) — only frozen phase overlays
        #    and peak annotations should be visible, no live waveform underneath.
        # Mirrors Swift SpectrumView.baseChart: spectrumLineContent is hidden when
        # isReviewingMaterialPhase is true.
        is_user_comparison = bool(self._comparison_curves) and not self._has_material_spectra
        is_reviewing = (
            self._has_material_spectra
            and self.analyzer.material_tap_phase.is_reviewing
        )
        if not is_user_comparison and not is_reviewing:
            if np.any(mag_db):
                self.fft_line.setData(freq_axis, mag_db)
            elif mag_db is not None and len(mag_db) == 0:
                # Blank spectrum during device-change settle — clear the line.
                self.fft_line.setData([], [])
        if self.analyzer._auto_scale_db and np.any(mag_db):
            valid = mag_db[(mag_db > -100) & (mag_db < 20)]
            if valid.size:
                min_mag = float(np.min(valid))
                max_mag = float(np.max(valid))
                sig_range = max_mag - min_mag
                padding = max(10.0, sig_range * 0.1)
                new_min = max(-120.0, min_mag - padding)
                new_max = min(20.0, max_mag + padding)
                if new_max - new_min < 20.0:
                    center = (new_min + new_max) / 2.0
                    new_min, new_max = center - 10.0, center + 10.0
                self.setYRange(new_min, new_max, padding=0)

    def process_averages(self, mag_y) -> None:
        """For the specified magnitude find the average with all the saved magnitudes.

        Delegates to analyzer.process_averages.  Annotation clearing is handled
        reactively via _on_averages_changed, connected to analyzer.averagesChanged.
        """
        self.analyzer.process_averages(mag_y)

    # ── find_peaks: thin wrapper that delegates to analyzer ───────────────────

    def find_peaks(self, mag_y_db):
        """Delegate peak finding to the analyzer.

        Returns (triggered, peaks) for call sites that need the return value.
        The analyzer emits peaksChanged, which is forwarded to FftCanvas.peaksChanged.
        """
        return self.analyzer.find_peaks(mag_y_db, list(self.analyzer.freq))

    # ------------------------------------------------------------------ #
    # FFT frame handler (called from proc_thread signal)
    # ------------------------------------------------------------------ #

    def _on_fft_frame_ready(
        self,
        mag_y_db: npt.NDArray[np.float64],
        mag_y: npt.NDArray[np.float32],
        fft_peak_amp: int,
        rms_amp: int,
        fps: float,
        sample_dt: float,
        processing_dt: float,
    ) -> None:
        """Receive a processed FFT frame from proc_thread (main thread slot).

        Delegates analysis to the TapToneAnalyzer, which calls detect_tap() and
        emits spectrumUpdated (connected to _on_spectrum_updated) for rendering.
        """
        self.analyzer.on_fft_frame(
            mag_y_db, mag_y, fft_peak_amp, rms_amp, fps, sample_dt, processing_dt
        )

    def _on_spectrum_updated(self, freqs, mag_y_db) -> None:
        """Receive spectrum data from the analyzer and update the view.

        Connected to TapToneAnalyzer.spectrumUpdated.  Updates the spectrum
        line only; the scatter plot is driven by _on_peaks_changed_scatter
        via the peaksChanged signal.

        ``freqs`` and ``mag_y_db`` are always emitted together as a matched
        pair (see TapToneAnalyzer.spectrumUpdated emit sites), so passing
        ``freqs`` through to set_draw_data ensures the two arrays are always
        consistent — mirroring the Swift displaySpectrum atomic-read pattern.
        """
        self.set_draw_data(mag_y_db, freqs=freqs)

    def _on_averages_changed(self, _count: int) -> None:
        """Clear annotations when a new averaged sample is accepted.

        Connected to analyzer.averagesChanged — mirrors Swift's onChange(of: tap.numAverages).
        Replaces the inline prev_averages != num_averages polling that was in process_averages.
        """
        self.annotations.clear_annotations()

    def _on_tap_detected_from_analyzer(self) -> None:
        """Relay analyzer.tapDetectedSignal → FftCanvas.tapDetected (hold trigger)."""
        # Update the spectrum line with the averaged result.
        # The scatter plot is updated automatically via peaksChanged →
        # _on_peaks_changed_scatter, which fires during tap capture.
        # Use display_spectrum to read freq and mag_db atomically — mirrors
        # the Swift displaySpectrum pattern so both arrays always match.
        if self.display_mode != AnalysisDisplayMode.COMPARISON:
            freqs, mag_db = self.display_spectrum
            if mag_db is not None:
                self.set_draw_data(mag_db, freqs=freqs)
        self.tapDetected.emit()
