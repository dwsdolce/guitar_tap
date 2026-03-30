""" Samples audio signal and finds the peaks of the guitar tap resonances
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List
import queue
import threading
import time
import platform

import pyqtgraph as pg
import numpy as np
import sounddevice as sd
import numpy.typing as npt
from scipy.signal import get_window
from PyQt6 import QtCore, QtGui, QtWidgets

import fft_annotations as fft_a
import freq_anal as f_a
import guitar_type as gt
import guitar_modes as gm
import microphone
import tap_detector as td
import plate_capture as pc
import measurement_type as mt_mod
import app_settings as _as


@dataclass
class FftData:
    """Data used to drive the FFT calculations"""

    def __init__(self, sample_freq: int = 44100, m_t: int = 15001) -> None:
        self.sample_freq = sample_freq
        self.m_t = m_t

        # self.window_fcn = get_window('blackman', self.m_t)
        self.window_fcn = get_window("boxcar", self.m_t)
        self.n_f: int = int(2 ** (np.ceil(np.log2(self.m_t))))
        self.h_n_f: int = self.n_f // 2


class _SceneMouseReleaseFilter(QtCore.QObject):
    """Event filter that emits a signal on QGraphicsScene mouse release."""

    released = QtCore.pyqtSignal(object)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QtCore.QEvent.Type.GraphicsSceneMouseRelease:
            self.released.emit(event)
        return False


class FftProcessingThread(QtCore.QThread):
    """Audio processing thread — all DSP runs here, off the main/GUI thread.

    Drains mic.queue chunk-by-chunk, maintains the ring buffer, runs the
    tap detector and decay tracker, computes the FFT, and emits results to
    the main thread via Qt signals.
    """

    # (mag_y_db, mag_y, tap_fired, tap_amp, fps, sample_dt, processing_dt)
    fftFrameReady: QtCore.pyqtSignal = QtCore.pyqtSignal(
        np.ndarray, np.ndarray, bool, int, float, float, float
    )
    # per-chunk RMS (plate/brace) or per-FFT peak (guitar), 0-100 scale
    rmsLevelChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    # ring-out time in seconds, relayed from DecayTracker
    ringOutMeasured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    # (captured, total) — not emitted here; kept in FftCanvas._do_capture_tap
    tapCountChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)

    def __init__(
        self,
        mic: "microphone.Microphone",
        fft_data: "FftData",
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._mic = mic
        self._fft_data = fft_data
        self._stop_event = threading.Event()

        # Ring buffer state
        self._audio_ring: npt.NDArray[np.float32] = np.zeros(
            fft_data.m_t, dtype=np.float32
        )
        self._ring_fill: int = 0
        self._samples_since_last_fft: int = 0

        # Tap / decay state
        import app_settings as _as
        self._tap_detector = td.TapDetector(
            tap_threshold=_as.AppSettings.tap_threshold(),
            hysteresis_margin=_as.AppSettings.hysteresis_margin(),
            mode=td.TapDetector.MODE_GUITAR,
            parent=self,
        )
        self._decay_tracker = td.DecayTracker(parent=self)

        # tapDetected fires from within run() (background thread) — use
        # DirectConnection so _tap_pending is set synchronously in the same thread.
        self._tap_detector.tapDetected.connect(
            self._on_tap_detected, QtCore.Qt.ConnectionType.DirectConnection
        )
        # ringOutMeasured fires from the background thread; relay via QueuedConnection.
        self._decay_tracker.ringOutMeasured.connect(
            self.ringOutMeasured, QtCore.Qt.ConnectionType.QueuedConnection
        )

        self._tap_pending: bool = False
        self._last_detector_amp: int = 0

        # Settings protected by a lock (written from main thread, read from run())
        self._settings_lock = threading.Lock()
        self._is_measurement_complete: bool = False
        self._is_guitar: bool = True
        self._calibration: npt.NDArray | None = None

    # ------------------------------------------------------------------ #
    # Internal slot — called from run() via DirectConnection
    # ------------------------------------------------------------------ #

    def _on_tap_detected(self) -> None:
        self._tap_pending = True
        self._decay_tracker.start(self._last_detector_amp)

    # ------------------------------------------------------------------ #
    # QThread.run() — the processing loop
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        lastupdate = time.time()
        while not self._stop_event.is_set():
            try:
                chunk = self._mic.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Snapshot mutable settings
            with self._settings_lock:
                is_frozen = self._is_measurement_complete
                is_guitar = self._is_guitar
                calibration = self._calibration

            enter_now = time.time()
            n = len(chunk)
            self._audio_ring = np.concatenate(
                [self._audio_ring[n:], chunk[:n].astype(np.float32)]
            )
            self._ring_fill = min(self._ring_fill + n, self._fft_data.m_t)
            self._samples_since_last_fft += n

            # Per-chunk RMS level
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            level_db = 20.0 * np.log10(max(rms, 1e-10))
            rms_amp = int(level_db + 100.0)

            if not is_guitar:
                self._last_detector_amp = rms_amp
                self.rmsLevelChanged.emit(rms_amp)
                if not is_frozen:
                    self._tap_detector.update(rms_amp)
                self._decay_tracker.update(rms_amp)

            if self._samples_since_last_fft < self._fft_data.m_t:
                continue
            self._samples_since_last_fft -= self._fft_data.m_t

            sample_dt = enter_now - lastupdate
            lastupdate = enter_now

            mag_y_db, mag_y = f_a.dft_anal(
                self._audio_ring, self._fft_data.window_fcn, self._fft_data.n_f
            )
            if calibration is not None:
                mag_y_db = mag_y_db + calibration

            if is_guitar:
                fft_peak_amp = int(np.max(mag_y_db) + 100.0)
                self._last_detector_amp = fft_peak_amp
                self.rmsLevelChanged.emit(fft_peak_amp)
                if not is_frozen:
                    self._tap_detector.update(fft_peak_amp)
                self._decay_tracker.update(fft_peak_amp)

            tap_fired = self._tap_pending and not is_frozen
            if self._tap_pending and is_frozen:
                print(
                    f"TAP_DEBUG [run] tap_pending=True but is_measurement_complete=True → tap suppressed"
                )
            if tap_fired:
                print(
                    f"TAP_DEBUG [run] tap_fired=True → forwarding to _do_capture_tap"
                )
                self._tap_pending = False

            exit_now = time.time()
            processing_dt = exit_now - enter_now
            fps = 1.0 / max(sample_dt, 1e-12)

            self.fftFrameReady.emit(
                mag_y_db, mag_y, tap_fired, self._last_detector_amp,
                fps, sample_dt, processing_dt,
            )

    # ------------------------------------------------------------------ #
    # Public API — safe to call from main thread
    # ------------------------------------------------------------------ #

    def stop(self) -> None:
        """Signal the run() loop to exit."""
        self._stop_event.set()

    def reset_state(self) -> None:
        """Reset ring buffer and tap detector; call before start()."""
        self._audio_ring = np.zeros(self._fft_data.m_t, dtype=np.float32)
        self._ring_fill = 0
        self._samples_since_last_fft = 0
        self._tap_pending = False
        self._last_detector_amp = 0
        self._stop_event.clear()
        self._tap_detector.reset()

    def set_measurement_complete(self, value: bool) -> None:
        with self._settings_lock:
            self._is_measurement_complete = value

    def set_measurement_type(self, is_guitar: bool) -> None:
        with self._settings_lock:
            self._is_guitar = is_guitar
        mode = td.TapDetector.MODE_GUITAR if is_guitar else td.TapDetector.MODE_PLATE_BRACE
        self._tap_detector.set_mode(mode)

    def set_calibration(self, arr: npt.NDArray | None) -> None:
        with self._settings_lock:
            self._calibration = arr

    def set_tap_threshold(self, value: int) -> None:
        self._tap_detector.set_tap_threshold(value)

    def set_hysteresis_margin(self, value: float) -> None:
        self._tap_detector.set_hysteresis_margin(value)

    def pause_tap_detection(self) -> None:
        self._tap_detector.pause()

    def resume_tap_detection(self) -> None:
        self._tap_detector.resume()

    def reset_tap_detector(self) -> None:
        self._tap_detector.reset()

    def cancel_tap_sequence_in_thread(self) -> None:
        self._tap_pending = False
        self._tap_detector.cancel()


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


# pylint: disable=too-many-instance-attributes
class FftCanvas(pg.PlotWidget):
    """Sample the audio stream and display the FFT

    The fft is displayed using background audio capture and callback
    for processing. During the chunk processing the interpolated peaks
    are found.  The threshold used to sample the peaks is the same as the
    threshold used to decide if a new fft is displayed. The
    amplitude of the fft is emitted to the signal passed in the class
    constructor
    """

    hold: bool = False

    peakDeselected: QtCore.pyqtSignal = QtCore.pyqtSignal()
    peakSelected: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    peaksChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(np.ndarray)
    ampChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    averagesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    framerateUpdate: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)
    newSample: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    tapDetected: QtCore.pyqtSignal = QtCore.pyqtSignal()
    ringOutMeasured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    tapCountChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)  # (captured, total)
    devicesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(list)       # new device-name list
    currentDeviceLost: QtCore.pyqtSignal = QtCore.pyqtSignal(str)     # lost device name
    _devicesRefreshed: QtCore.pyqtSignal = QtCore.pyqtSignal()         # internal: thread → main
    plateStatusChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(str)    # plate capture status
    plateAnalysisComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float)  # fL, fC
    tapDetectionPaused: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)   # True=paused
    peakInfoChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float)  # (peak_hz, peak_db)
    levelChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)              # level 0-100 (dB+100)
    comparisonChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)         # True=entering, False=leaving
    freqRangeChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)      # (fmin, fmax) — pan/zoom

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
        window_length: int,
        sampling_rate: int,
        frange: dict[str, int],
        threshold: int,
    ) -> None:
        super().__init__()

        self.is_measurement_complete: bool = False

        # Configure plot appearance
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setLabel("left", "FFT Magnitude (dB)")
        self.setLabel("bottom", "Frequency (Hz)")
        self.setTitle("FFT Peaks")
        self.setYRange(-100, 0, padding=0)

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

        self.avg_enable: bool = False

        self.fft_data: FftData = FftData(sampling_rate, window_length)

        self.threshold: int = threshold

        # Set threshold value for drawing threshold line
        self.threshold_x: int = self.fft_data.sample_freq // 2
        self.threshold_y: int = self.threshold - 100

        self.update_axis(frange["f_min"], frange["f_max"], True)

        # Open the audio stream — resolve saved device name to an index
        import app_settings as _as
        saved_device_index: int | None = None
        saved_device_name: str = ""
        try:
            saved_name = _as.AppSettings.device_name()
            if saved_name:
                for dev in sd.query_devices():
                    if dev["name"] == saved_name and dev["max_input_channels"] > 0:
                        saved_device_index = dev["index"]
                        saved_device_name = saved_name
                        break
        except Exception:
            pass

        # If the saved device wasn't found, resolve the actual default input device
        # so that AppSettings and _calibration_device_name reflect reality.
        if not saved_device_name:
            try:
                default_info = sd.query_devices(kind="input")
                if default_info is not None:
                    saved_device_name = str(default_info["name"])
                    _as.AppSettings.set_device_name(saved_device_name)
            except Exception:
                pass

        self._devicesRefreshed.connect(self._on_devices_refreshed)
        self.mic: microphone.Microphone = microphone.Microphone(
            self, rate=self.fft_data.sample_freq, chunksize=4096,
            device_index=saved_device_index,
            on_devices_changed=self._devicesRefreshed.emit,  # no-arg, thread-safe
        )

        # Calibration is auto-loaded below, after self.freq is initialised.

        # FFT line
        self.fft_line: pg.PlotDataItem = self.plot(
            [], [], pen=pg.mkPen("b", width=1)
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

        x_axis: npt.NDArray[np.int64] = np.arange(0, self.fft_data.h_n_f + 1)
        self.freq: npt.NDArray[np.int64] = (
            x_axis * self.fft_data.sample_freq // (self.fft_data.n_f)
        )

        # Microphone calibration corrections (dB per bin, or None)
        self._calibration_corrections: npt.NDArray[np.float64] | None = None
        self._calibration_device_name: str = saved_device_name

        # Auto-load the calibration profile stored for this device
        if saved_device_name:
            import mic_calibration as _mc
            _cal = _mc.CalibrationStorage.calibration_for_device(saved_device_name)
            if _cal is not None:
                self._calibration_corrections = _cal.interpolate_to_bins(self.freq)

        # Auto-scale dB
        self._auto_scale_db: bool = False

        # Saved waveform data for drawing
        self.saved_mag_y_db: npt.NDArray[np.float64] = []
        self.saved_peaks: npt.NDArray[np.float64] = np.zeros((0, 3))  # freq, mag, Q
        self.b_peaks_freq: npt.NDArray[np.float64] = []
        # When a measurement is loaded from file these are the authoritative peaks.
        # set_threshold / update_axis filter this array instead of re-analysing the
        # spectrum, so peaks can never be permanently lost by sliding the threshold.
        # Cleared when the display is unfrozen (returning to live capture).
        self._loaded_measurement_peaks: npt.NDArray[np.float64] | None = None
        self.selected_peak: float = 0.0
        self._mode_color_map: dict[float, tuple[int, int, int]] = {}  # freq → RGB

        # Saved peak information
        self.peaks_f_min_index: int = 0
        self.peaks_f_max_index: int = 0

        # Saved averaging data
        self.max_average_count: int = 1
        self.mag_y_sum: List[float] = []
        self.num_averages = 0

        # Tap-level accumulator (main thread only)
        self._tap_num: int = 1           # number of taps to accumulate
        self._tap_spectra: list[npt.NDArray[np.float64]] = []

        # Plate / brace analysis state machine
        self._measurement_type: mt_mod.MeasurementType = mt_mod.MeasurementType.CLASSICAL
        self._plate_capture = pc.PlateCapture(
            sample_freq=self.fft_data.sample_freq,
            n_f=self.fft_data.n_f,
            parent=self,
        )
        self._plate_capture.stateChanged.connect(self.plateStatusChanged)
        self._plate_capture.analysisComplete.connect(self.plateAnalysisComplete)
        # Snapshot of the most recent linear spectrum for plate HPS
        self._current_mag_y: npt.NDArray[np.float32] = np.array([])

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

        # Guitar type — updated by set_guitar_type_bands(); used for peak deduplication
        self._guitar_type: gt.GuitarType = gt.GuitarType.CLASSICAL

        # Initialise mode bands for the saved guitar type
        self.set_guitar_type_bands(_as.AppSettings.guitar_type())

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
        self.comparison_labels: list[tuple[str, tuple[int, int, int]]] = []
        self._comparison_legend: pg.LegendItem | None = None

        # Start the microphone (always running; processing thread gated by start_analyzer())
        self.mic.start()

        # Processing thread — created here, started by start_analyzer()
        self._proc_thread = FftProcessingThread(self.mic, self.fft_data, parent=self)
        self._connect_proc_thread_signals()
        # Apply the initial calibration to the thread if one was loaded above
        self._proc_thread.set_calibration(self._calibration_corrections)

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
        """Connect FftProcessingThread signals to FftCanvas slots."""
        self._proc_thread.fftFrameReady.connect(self._on_fft_frame_ready)
        self._proc_thread.rmsLevelChanged.connect(self.ampChanged)
        self._proc_thread.ringOutMeasured.connect(self.ringOutMeasured)
        self._proc_thread.finished.connect(self._on_proc_thread_finished)

    def _on_proc_thread_finished(self) -> None:
        """Called when the processing thread exits (after stop_analyzer)."""
        pass  # placeholder for future cleanup if needed

    def start_analyzer(self) -> None:
        """Start the processing thread and hide the idle overlay."""
        self._overlay_label.setVisible(False)
        self.set_measurement_complete(False)
        if self._proc_thread.isRunning():
            self._proc_thread.stop()
            self._proc_thread.wait(500)
            # Recreate thread to reset all state
            self._proc_thread = FftProcessingThread(self.mic, self.fft_data, parent=self)
            self._connect_proc_thread_signals()
            self._proc_thread.set_calibration(self._calibration_corrections)
            self._proc_thread.set_measurement_type(self._measurement_type.is_guitar)
        self._tap_spectra.clear()
        self._proc_thread.reset_state()
        self._proc_thread.start()

    def stop_analyzer(self) -> None:
        """Stop the processing thread and show the idle overlay."""
        self._proc_thread.stop()
        self._center_overlay()
        self._overlay_label.setText("Stopped")
        self._overlay_label.setVisible(True)

    def shutdown(self) -> None:
        """Stop the processing thread and wait for it to exit.

        Must be called before the widget is destroyed (e.g. from the main
        window's closeEvent) to prevent Qt from aborting on QThread::~QThread()
        while the thread is still running.
        """
        self._proc_thread.stop()
        self._proc_thread.wait(2000)

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
        self._guitar_type = guitar_type
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
            lo_line.setVisible(self._mode_bands_visible)
            self.addItem(lo_line)
            self._mode_band_items.append(lo_line)

            hi_line = pg.InfiniteLine(pos=hi, angle=90, movable=False, pen=pen)
            hi_line.setZValue(-10)
            hi_line.setVisible(self._mode_bands_visible)
            self.addItem(hi_line)
            self._mode_band_items.append(hi_line)

    def _remove_mode_bands(self) -> None:
        for item in self._mode_band_items:
            self.removeItem(item)
        self._mode_band_items.clear()

    def show_mode_bands(self, visible: bool) -> None:
        """Show or hide all mode band overlays."""
        self._mode_bands_visible = visible
        for item in self._mode_band_items:
            item.setVisible(visible)

    # ------------------------------------------------------------------ #
    # Hot-plug device detection
    # ------------------------------------------------------------------ #

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

        if self.is_measurement_complete and np.any(self.saved_mag_y_db):
            # Snap to nearest FFT bin on the frozen curve
            idx = int(np.searchsorted(self.freq, mouse_freq))
            idx = max(0, min(idx, len(self.freq) - 1))
            display_freq = float(self.freq[idx])
            display_db   = float(self.saved_mag_y_db[idx])
        else:
            # Free mouse tracking — no curve snap
            display_freq = mouse_freq
            display_db   = mouse_db

        self._crosshair_v.setPos(display_freq)
        self._crosshair_h.setPos(display_db)
        freq_str = f"{display_freq/1000:.2f} kHz" if display_freq >= 1000 else f"{display_freq:.1f} Hz"
        html = (
            f'<center>'
            f'<b style="color:rgb(220,50,50);">{freq_str}</b><br/>'
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

    def _on_devices_refreshed(self) -> None:
        """Handle a hot-plug event from Microphone (always on main thread).

        PortAudio caches its device list at Pa_Initialize() time, so we must
        reinitialize it before calling sd.query_devices() to get accurate data.
        reinitialize_portaudio() stops the stream, reinits PortAudio, and
        attempts to restart on the same device — all safely on the main thread.
        """
        self.mic.reinitialize_portaudio()

        try:
            names: list[str] = sorted(
                str(d["name"]) for d in sd.query_devices() if d["max_input_channels"] > 0
            )
        except Exception:
            names = []

        self.devicesChanged.emit(names)

        # Check if the active device has disappeared
        if (
            self._calibration_device_name
            and self._calibration_device_name not in names
        ):
            self.currentDeviceLost.emit(self._calibration_device_name)

    # ------------------------------------------------------------------ #
    # Microphone calibration
    # ------------------------------------------------------------------ #

    def load_calibration(self, path: str) -> bool:
        """Load and pre-interpolate a calibration file onto the FFT bin grid.

        Returns True on success; False (and leaves existing calibration intact)
        on parse error.
        """
        import mic_calibration as mc
        try:
            cal_data = mc.parse_cal_file(path)
            self._calibration_corrections = mc.interpolate_to_bins(cal_data, self.freq)
            if hasattr(self, "_proc_thread"):
                self._proc_thread.set_calibration(self._calibration_corrections)
            return True
        except Exception:
            return False

    def load_calibration_from_profile(self, cal: "mic_calibration.MicrophoneCalibration") -> None:
        """Apply a pre-parsed MicrophoneCalibration profile to the FFT pipeline."""
        import mic_calibration
        self._calibration_corrections = cal.interpolate_to_bins(self.freq)
        if hasattr(self, "_proc_thread"):
            self._proc_thread.set_calibration(self._calibration_corrections)

    def clear_calibration(self) -> None:
        """Remove the active calibration (no dB correction applied)."""
        self._calibration_corrections = None
        if hasattr(self, "_proc_thread"):
            self._proc_thread.set_calibration(None)

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self._calibration_device_name

    # ------------------------------------------------------------------ #

    def reset_tap_detector(self) -> None:
        """Public wrapper to reset the tap detector state machine."""
        self._proc_thread.reset_tap_detector()

    def start_tap_sequence(self) -> None:
        """Begin a fresh tap sequence: clear any accumulated spectra and restart warmup."""
        self._tap_spectra.clear()
        self._proc_thread.reset_tap_detector()   # enters WARMUP → prevents false immediate trigger
        self.tapCountChanged.emit(0, self._tap_num)

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing (1 = immediate freeze)."""
        self._tap_num = max(1, n)
        self._tap_spectra.clear()

    def _do_capture_tap(self, mag_y_db: npt.NDArray[np.float64], tap_amp: int) -> None:
        """Capture one tap spectrum; called from _on_fft_frame_ready() when tap_fired is True."""
        print(
            f"TAP_DEBUG [handleTapDetection] ENTERED | "
            f"tap_amp={tap_amp} is_guitar={self._proc_thread._is_guitar} "
            f"captured_so_far={len(self._tap_spectra)} numberOfTaps={self._tap_num}"
        )
        if not np.any(mag_y_db):
            print("TAP_DEBUG [handleTapDetection] SKIPPED — mag_y_db is all zeros")
            return
        self._tap_spectra.append(mag_y_db.copy())
        captured = len(self._tap_spectra)
        print(
            f"TAP_DEBUG [handleTapDetection] GUITAR TAP STORED | "
            f"currentTapCount={captured} numberOfTaps={self._tap_num} "
            f"tapProgress={captured/max(self._tap_num,1):.2f}"
        )
        self.tapCountChanged.emit(captured, self._tap_num)

        if captured >= self._tap_num:
            # Power-average all captured spectra (dB → linear → mean → dB).
            stacked = np.stack(self._tap_spectra)
            avg_db = 10.0 * np.log10(np.mean(np.power(10.0, stacked / 10.0), axis=0))
            self.saved_mag_y_db = avg_db
            _, peaks = self.find_peaks(avg_db)
            self.set_draw_data(avg_db, peaks)
            self._tap_spectra.clear()
            self.tapDetected.emit()   # now trigger hold
        else:
            # More taps needed — rearm the detector without holding
            self._proc_thread.reset_tap_detector()

    def _on_tap_for_plate(self) -> None:
        """Forward tap events to the plate capture state machine when active."""
        if self._plate_capture.is_active and len(self._current_mag_y) > 0:
            self._plate_capture.on_tap(self._current_mag_y)

    def set_measurement_type(self, measurement_type: mt_mod.MeasurementType | str) -> None:
        """Switch between Guitar / Plate / Brace analysis modes."""
        if isinstance(measurement_type, str):
            measurement_type = mt_mod.MeasurementType.from_combo_values(
                measurement_type, ""
            )
        self._measurement_type = measurement_type
        self._proc_thread.set_measurement_type(measurement_type.is_guitar)

    def start_plate_analysis(self) -> None:
        """Arm the plate capture state machine for the next tap(s)."""
        self._plate_capture.start(is_brace=self._measurement_type.is_brace)

    def reset_plate_analysis(self) -> None:
        """Abort plate capture and return to idle."""
        self._plate_capture.reset()

    def set_auto_scale(self, enabled: bool) -> None:
        """Enable/disable automatic Y-axis scaling to the spectrum floor."""
        self._auto_scale_db = enabled
        if not enabled:
            self.setYRange(-100, 0, padding=0)

    def set_tap_threshold(self, value: int) -> None:
        """Update the tap-detection threshold (0–100 scale)."""
        self._tap_threshold_y = value - 100
        self._proc_thread.set_tap_threshold(value)
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
        self._proc_thread.set_hysteresis_margin(value)
        self._update_reset_line()

    def pause_tap_detection(self) -> None:
        """Pause the tap detector; spectrum continues to update."""
        self._proc_thread.pause_tap_detection()
        self.tapDetectionPaused.emit(True)

    def resume_tap_detection(self) -> None:
        """Resume a paused tap detector."""
        self._proc_thread.resume_tap_detection()
        self.tapDetectionPaused.emit(False)

    def cancel_tap_sequence(self) -> None:
        """Cancel the in-progress multi-tap sequence and rearm for a fresh tap."""
        self._tap_spectra.clear()
        self._proc_thread.cancel_tap_sequence_in_thread()
        self.tapCountChanged.emit(0, self._tap_num)

    def set_device(self, device_index: int) -> None:
        """Switch the audio input to the given sounddevice index and
        auto-load the calibration associated with that device."""
        self.mic.set_device(device_index)
        import app_settings as _as
        try:
            dev_name = str(sd.query_devices(device_index)["name"])  # type: ignore[index]
        except Exception:
            dev_name = ""
        self._calibration_device_name = dev_name
        cal_path = _as.AppSettings.calibration_for_device(dev_name)
        if cal_path:
            self.load_calibration(cal_path)   # also calls _proc_thread.set_calibration
        else:
            self.clear_calibration()          # also calls _proc_thread.set_calibration

    def select_peak(self, freq: float) -> None:
        """Select the peak (scatter point) with the specified frequency"""
        if self.is_measurement_complete:
            row = np.where(self.saved_peaks[:, 0] == freq)
            magdb = self.saved_peaks[row][0][1]
            self.selected_point.setData(x=[freq], y=[magdb])
            self.selected_peak = freq

    def deselect_peak(self, _freq: float) -> None:
        """Deselect the peak (scatter point) with the specified frequency"""
        self.selected_point.setData(x=[], y=[])

    def clear_selected_peak(self) -> None:
        """Reset the selected peak."""
        self.selected_peak = -1.0

    def point_picked(
        self, scatter: pg.ScatterPlotItem, points: list, ev
    ) -> None:
        """Handle scatter point click: emit peakSelected if within frequency range."""
        if self.is_measurement_complete and len(points) > 0:
            if self.annotations.select_annotation(scatter):
                return
            index0 = points[0].index()
            if self.peaks_f_min_index <= index0 < self.peaks_f_max_index:
                if np.any(self.saved_peaks):
                    freq = self.saved_peaks[index0][0]
                    self.peakSelected.emit(freq)

    # ── info button & zoom/pan help ───────────────────────────────────────────

    def _reposition_info_btn(self) -> None:
        btn = getattr(self, "_info_btn", None)
        if btn is None:
            return
        btn.move(self.width() - btn.width() - 4, 4)
        btn.raise_()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reposition_info_btn()

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
            # Pan X: scroll up / right → higher frequencies
            x0, x1 = vb.viewRange()[0]
            shift = (x1 - x0) * 0.10 * (1 if delta > 0 else -1)
            vb.setXRange(x0 + shift, x1 + shift, padding=0)
            self._refresh_peaks_for_viewport()
            ev.accept()

        elif mods & Mod.AltModifier:
            # Pan Y: scroll up → up (higher magnitude)
            y0, y1 = vb.viewRange()[1]
            shift = (y1 - y0) * 0.10 * (1 if delta > 0 else -1)
            vb.setYRange(y0 + shift, y1 + shift, padding=0)
            ev.accept()

        elif mods & (Mod.ControlModifier | Mod.MetaModifier):
            # Zoom both axes around centre
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

    def _reset_freq_to_saved(self) -> None:
        mt = self._measurement_type
        self.update_axis(_as.AppSettings.f_min(mt), _as.AppSettings.f_max(mt))

    def _reset_mag_to_saved(self) -> None:
        self.setYRange(_as.AppSettings.db_min(), _as.AppSettings.db_max(), padding=0)

    def _reset_both_to_saved(self) -> None:
        self._reset_freq_to_saved()
        self._reset_mag_to_saved()

    def _reset_freq_to_defaults(self) -> None:
        mt = self._measurement_type
        self.update_axis(_as.AppSettings.default_f_min(mt), _as.AppSettings.default_f_max(mt))

    def _reset_mag_to_defaults(self) -> None:
        self.setYRange(_as.AppSettings.default_db_min(), _as.AppSettings.default_db_max(), padding=0)

    def _reset_both_to_defaults(self) -> None:
        self._reset_freq_to_defaults()
        self._reset_mag_to_defaults()

    def update_axis(self, fmin: int, fmax: int, init: bool = False) -> None:
        """Update the x-axis frequency range"""
        if fmin < fmax:
            self.fmin = fmin
            self.fmax = fmax
            self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
            self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq

            self.setXRange(fmin, fmax, padding=0)
            if not init:
                if self._loaded_measurement_peaks is not None:
                    self._emit_loaded_peaks_at_threshold()
                else:
                    self.find_peaks(self.saved_mag_y_db)

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
        self.fmin = fmin
        self.fmax = fmax
        self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
        self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq
        if self._loaded_measurement_peaks is not None:
            self._emit_loaded_peaks_at_threshold()
        else:
            self.find_peaks(self.saved_mag_y_db)
        self.freqRangeChanged.emit(fmin, fmax)

    def set_max_average_count(self, max_average_count: int) -> None:
        """Set the number of averages to take"""
        self.max_average_count = max_average_count

    def reset_averaging(self) -> None:
        """Reset the number of averages taken to zero."""
        self.num_averages = 0

    def set_avg_enable(self, avg_enable: bool) -> None:
        """Flag to enable/disable the averaging"""
        self.avg_enable = avg_enable

    # ------------------------------------------------------------------ #
    # Comparison overlay — mirrors loadComparison / clearComparison in
    # TapToneAnalyzer+MeasurementManagement.swift
    # ------------------------------------------------------------------ #

    @property
    def is_comparing(self) -> bool:
        """True when comparison overlay curves are active — mirrors !comparisonSpectra.isEmpty."""
        return bool(self._comparison_curves)

    @staticmethod
    def _comparison_label(m: object) -> str:
        """Short label for the legend — mirrors comparisonLabel(for:) in Swift."""
        loc = getattr(m, "tap_location", None)
        if loc:
            return loc
        ts = getattr(m, "timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%b %-d %H:%M")
        except Exception:
            return ts[:16]

    def load_comparison(self, measurements: list) -> None:
        """Load guitar measurements as comparison overlays.

        Mirrors loadComparison(measurements:) in TapToneAnalyzer+MeasurementManagement.swift:
        - Filters to measurements that have a spectrum_snapshot.
        - Assigns a colour from _COMPARISON_PALETTE (cycles if >5 measurements).
        - Adds one PlotDataItem curve per measurement, with a legend entry.
        - Updates the axis ranges to the union of all snapshot display ranges.
        """
        self.clear_comparison()

        with_snapshots = [m for m in measurements if m.spectrum_snapshot is not None]
        for idx, m in enumerate(with_snapshots):
            snap = m.spectrum_snapshot
            color = self._COMPARISON_PALETTE[idx % len(self._COMPARISON_PALETTE)]
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes,  dtype=np.float64)
            label = self._comparison_label(m)
            curve = pg.PlotDataItem(
                freq_arr, mag_arr,
                pen=pg.mkPen(color, width=1.5),
                name=label,
            )
            self.addItem(curve)
            self._comparison_curves.append(curve)
            self.comparison_labels.append((label, color))

        if with_snapshots:
            # Legend — anchored top-right of the plot area
            self._comparison_legend = pg.LegendItem(offset=(-10, 10))
            self._comparison_legend.setParentItem(self.getPlotItem())
            for curve, (label, _) in zip(self._comparison_curves, self.comparison_labels):
                self._comparison_legend.addItem(curve, label)

            # Broadcast the union of all snapshot axis ranges —
            # mirrors the loadedMinFreq / loadedMaxFreq / loadedMinDB / loadedMaxDB
            # updates in Swift's loadComparison(measurements:).
            snaps = [m.spectrum_snapshot for m in with_snapshots]
            min_freq = int(min(s.min_freq for s in snaps))
            max_freq = int(max(s.max_freq for s in snaps))
            min_db   = float(min(s.min_db for s in snaps))
            max_db   = float(max(s.max_db for s in snaps))
            self.update_axis(min_freq, max_freq)
            self.setYRange(min_db, max_db, padding=0)

        self._set_comparison_visibility()
        self.comparisonChanged.emit(self.is_comparing)

    def clear_comparison(self) -> None:
        """Remove all comparison overlay curves — mirrors clearComparison() in Swift."""
        was_comparing = self.is_comparing
        for curve in self._comparison_curves:
            self.removeItem(curve)
        self._comparison_curves.clear()
        self.comparison_labels.clear()
        if self._comparison_legend is not None:
            self._comparison_legend.scene().removeItem(self._comparison_legend)
            self._comparison_legend = None
        if was_comparing:
            self._set_comparison_visibility()
            self.comparisonChanged.emit(False)

    def _set_comparison_visibility(self) -> None:
        """Show/hide peaks and threshold lines based on comparison state.

        Mirrors the isComparing checks in TapToneAnalysisView+SpectrumViews.swift:
            peaks: isComparing ? nil : tap.currentPeaks
            thresholdLines: isComparing ? [] : thresholds
        """
        showing = not self.is_comparing
        self.points.setVisible(showing)
        self.selected_point.setVisible(showing)
        self.line_threshold.setVisible(showing)
        self.line_tap_threshold.setVisible(showing)
        self.line_reset_threshold.setVisible(showing)

    def set_measurement_complete(self, is_measurement_complete: bool) -> None:
        """Flag to enable/disable the holding of peaks."""
        self.is_measurement_complete = is_measurement_complete
        self._proc_thread.set_measurement_complete(is_measurement_complete)
        if not is_measurement_complete:
            self.selected_point.setData(x=[], y=[])
            self.clear_selected_peak()
            self._tap_spectra.clear()
            self._loaded_measurement_peaks = None
            # Starting a new tap sequence always clears any active comparison overlay —
            # mirrors self.comparisonSpectra = [] in startTapSequence() in Swift.
            self.clear_comparison()

    def set_fmin(self, fmin: int) -> None:
        """As it says"""
        self.update_axis(fmin, self.fmax)

    def set_fmax(self, fmax: int) -> None:
        """As it says"""
        self.update_axis(self.fmin, fmax)

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter the loaded-measurement peaks by the current threshold and
        fmin/fmax, then emit peaksChanged.  Used instead of re-running the full
        spectrum analysis when a measurement has been loaded from file — mirrors
        Swift's recalculateFrozenPeaksIfNeeded fast-path.
        """
        assert self._loaded_measurement_peaks is not None
        threshold_db = self.threshold - 100
        peaks: npt.NDArray[np.float64] = self._loaded_measurement_peaks[
            self._loaded_measurement_peaks[:, 1] >= threshold_db
        ]

        empty: npt.NDArray[np.float64] = np.zeros((0, 3))
        if peaks.shape[0] == 0:
            self.saved_peaks = empty
            self.b_peaks_freq = np.array([], dtype=np.float64)
            self.peaksChanged.emit(empty)
            return

        self.saved_peaks = peaks
        peaks_freq: npt.NDArray[np.float64] = peaks[:, 0]

        b_indices = np.nonzero((peaks_freq < self.fmax) & (peaks_freq > self.fmin))
        if len(b_indices[0]) > 0:
            self.peaks_f_min_index = int(b_indices[0][0])
            self.peaks_f_max_index = int(b_indices[0][-1]) + 1
            self.b_peaks_freq = peaks_freq[self.peaks_f_min_index:self.peaks_f_max_index]
            self.peaksChanged.emit(peaks[self.peaks_f_min_index:self.peaks_f_max_index])
        else:
            self.peaks_f_min_index = 0
            self.peaks_f_max_index = 0
            self.b_peaks_freq = np.array([], dtype=np.float64)
            self.peaksChanged.emit(empty)

    def set_threshold(self, threshold: int) -> None:
        """Set the threshold used to limit both the triggering of a sample
        and the threshold on finding peaks. The threshold value is always 0 to 100.
        """
        self.threshold = threshold

        self.threshold_x = self.fft_data.sample_freq // 2
        self.threshold_y = self.threshold - 100

        self.line_threshold.setPos(self.threshold_y)
        self.line_threshold.label.setText(f"Peak: {self.threshold_y} dB")

        if self._loaded_measurement_peaks is not None:
            self._emit_loaded_peaks_at_threshold()
        else:
            self.find_peaks(self.saved_mag_y_db)

        self.selected_point.setData(x=[], y=[])
        self.peakDeselected.emit()
        if np.any(self.b_peaks_freq):
            if self.selected_peak > 0:
                peak_index = np.where(self.b_peaks_freq == self.selected_peak)
                if len(peak_index[0]):
                    self.peakSelected.emit(self.selected_peak)

    def _apply_mode_priority(self, peaks: np.ndarray) -> np.ndarray:
        """Apply mode-priority selection and 2 Hz deduplication.

        Mirrors the updated Swift findPeaks pass-1 algorithm:

        1. Scan modes in ascending frequency order using a lastClaimedFrequency
           cursor.  Each mode only considers peaks strictly above the previous
           mode's claimed frequency, preventing two modes from claiming the same
           physical peak (critical in the Top/Back overlap zone ~190-230 Hz).
           A per-claim 2 Hz duplicate check also discards a candidate that is
           within 2 Hz of an already-claimed peak.
        2. Deduplicate ALL remaining peaks at 2 Hz (descending magnitude) —
           mirrors Swift's removeDuplicatePeaks, allowing multiple peaks per
           mode range provided they are >2 Hz apart.
        3. Restore any guaranteed peaks consumed in step 2 so each mode always
           has a slot in the output.
        4. Sort by frequency ascending for consistent table display.
        """
        if peaks.shape[0] == 0:
            return peaks

        freqs = peaks[:, 0]
        mags  = peaks[:, 1]

        # Pass 1 — sequential scan with lastClaimedFrequency cursor.
        # Modes are visited in ascending lower-bound order so the cursor advances
        # monotonically, matching the new Swift findPeaks pass-1 logic.
        known_modes = sorted(
            [gm.GuitarMode.AIR, gm.GuitarMode.TOP, gm.GuitarMode.BACK,
             gm.GuitarMode.DIPOLE, gm.GuitarMode.RING_MODE, gm.GuitarMode.UPPER_MODES],
            key=lambda m: m.mode_range(self._guitar_type)[0],
        )
        guaranteed: set[int] = set()
        last_claimed_freq: float = -1.0

        for mode in known_modes:
            lo, hi = mode.mode_range(self._guitar_type)
            # Only consider peaks above the last claimed frequency (cursor)
            candidates = np.where(
                (freqs >= lo) & (freqs <= hi) & (freqs > last_claimed_freq)
            )[0]
            if candidates.size == 0:
                continue
            best = int(candidates[np.argmax(mags[candidates])])
            # Post-claim 2 Hz duplicate check — discard if too close to an
            # already-claimed peak from an earlier mode
            if any(abs(freqs[best] - freqs[g]) < 2.0 for g in guaranteed):
                continue
            guaranteed.add(best)
            last_claimed_freq = float(freqs[best])

        # Pass 2 — deduplicate ALL peaks at 2 Hz (descending magnitude).
        used = np.zeros(len(freqs), dtype=bool)
        kept: list[int] = []
        for i in np.argsort(-mags):
            idx = int(i)
            if not used[idx]:
                kept.append(idx)
                used |= np.abs(freqs - freqs[idx]) < 2.0

        # Pass 3 — restore guaranteed peaks consumed by a stronger neighbour
        kept_set = set(kept)
        for g_idx in guaranteed:
            if g_idx not in kept_set:
                kept.append(g_idx)

        return peaks[sorted(kept, key=lambda i: freqs[i])]

    def find_peaks(self, mag_y_db):
        """For the specified magnitude in db:
        1. detect the peaks that are above the user specified threshold
        2. interpolate each peak using parabolic interpolation
        3. If there are peaks above the user specified threshold then
           from the resulting list of peaks find those that are within the
           user specified min/max frequency range and emit a signal that
           the peaks have changed.
        4. If there are no peaks in the frequency range then emit a signal
           with an empty list of peaks.
        5. If there were no peaks within the threshold then emit
           a peaks changed with the saved set of peaks.
        """
        if not np.any(mag_y_db):
            return False, self.saved_peaks

        ploc = f_a.peak_detection(mag_y_db, self.threshold - 100)
        iploc, peaks_mag = f_a.peak_interp(mag_y_db, ploc)

        peaks_freq = (iploc * self.fft_data.sample_freq) / float(self.fft_data.n_f)

        if peaks_mag.size > 0:
            max_peaks_mag = np.max(peaks_mag)
            q_values = f_a.peak_q_factor(
                mag_y_db, ploc, iploc, peaks_mag,
                self.fft_data.sample_freq, self.fft_data.n_f,
            )
            peaks = np.column_stack((peaks_freq, peaks_mag, q_values))
            # Two-pass mode-priority + 2 Hz deduplication (mirrors Swift findPeaks)
            peaks = self._apply_mode_priority(peaks)
            if peaks.shape[0] > 0:
                peaks_freq = peaks[:, 0]
                max_peaks_mag = np.max(peaks[:, 1])
            else:
                peaks_freq = np.array([])
                max_peaks_mag = -100
        else:
            max_peaks_mag = -100
            peaks = np.zeros((0, 3))

        if max_peaks_mag > (self.threshold - 100):
            self.saved_mag_y_db = mag_y_db
            self.saved_peaks = peaks
            triggered = True

            self.peaks_f_min_index = 0
            self.peaks_f_max_index = 0
            b_peaks_f_indices = np.nonzero(
                (peaks_freq < self.fmax) & (peaks_freq > self.fmin)
            )
            if len(b_peaks_f_indices[0]) > 0:
                self.peaks_f_min_index = b_peaks_f_indices[0][0]
                self.peaks_f_max_index = b_peaks_f_indices[0][-1] + 1

            if self.peaks_f_max_index > 0:
                self.b_peaks_freq = peaks_freq[
                    self.peaks_f_min_index : self.peaks_f_max_index
                ]
                peaks_data = peaks[self.peaks_f_min_index : self.peaks_f_max_index]
                self.peaksChanged.emit(peaks_data)
            else:
                self.b_peaks_freq = []
                self.peaksChanged.emit(np.zeros((0, 3)))
        else:
            self.saved_peaks = np.zeros((0, 3))
            self.peaksChanged.emit(self.saved_peaks)
            triggered = False

        return triggered, peaks

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
        if self.saved_peaks.size > 0 and self.peaks_f_max_index > 0:
            peaks_data = self.saved_peaks[self.peaks_f_min_index:self.peaks_f_max_index]
            self.points.setData(
                x=peaks_data[:, 0], y=peaks_data[:, 1],
                brush=self._peak_brushes(peaks_data[:, 0]),
            )

    def set_draw_data(self, mag_db, peaks) -> None:
        """Set the data for each of the plot objects used in update_fft"""
        if np.any(mag_db):
            self.fft_line.setData(self.freq, mag_db)
        if hasattr(peaks, "size") and peaks.size > 0:
            self.points.setData(
                x=peaks[:, 0], y=peaks[:, 1],
                brush=self._peak_brushes(peaks[:, 0]),
            )
        else:
            self.points.setData(x=[], y=[])
        if self._auto_scale_db and np.any(mag_db):
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
        """For the specified magnitude find the average with all the saved magnitudes."""
        if self.num_averages < self.max_average_count:
            if self.num_averages > 0:
                mag_y_sum = self.mag_y_sum + mag_y
            else:
                mag_y_sum = mag_y
            num_averages = self.num_averages + 1

            avg_mag_y = mag_y_sum / num_averages

            avg_mag_y[avg_mag_y < np.finfo(float).eps] = np.finfo(float).eps

            avg_mag_y_db = 20 * np.log10(avg_mag_y)

            avg_amplitude = np.max(avg_mag_y_db) + 100
            if avg_amplitude > self.threshold:
                triggered, avg_peaks = self.find_peaks(avg_mag_y_db)
                if triggered:
                    self.newSample.emit(self.is_measurement_complete)
                    self.annotations.clear_annotations()
                    self.set_draw_data(avg_mag_y_db, avg_peaks)

                    self.mag_y_sum = mag_y_sum
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))

                    self.saved_mag_y_db = avg_mag_y_db
                    self.saved_peaks = avg_peaks

        self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)

    def _on_fft_frame_ready(
        self,
        mag_y_db: npt.NDArray[np.float64],
        mag_y: npt.NDArray[np.float32],
        tap_fired: bool,
        tap_amp: int,
        fps: float,
        sample_dt: float,
        processing_dt: float,
    ) -> None:
        """Receive a processed FFT frame from FftProcessingThread (main thread slot).

        Replaces the old update_fft() / QTimer path.  All DSP is already done
        in the thread; this method updates the display and handles tap capture.
        """
        self._current_mag_y = mag_y  # snapshot for plate capture HPS

        if tap_fired:
            self._do_capture_tap(mag_y_db, tap_amp)
            self._on_tap_for_plate()

        # Update display
        if self.is_measurement_complete:
            self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)
        else:
            _, peaks = self.find_peaks(mag_y_db)
            self.set_draw_data(mag_y_db, peaks)

        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))
        self.levelChanged.emit(tap_amp)
        peak_idx = int(np.argmax(mag_y_db))
        if peak_idx < len(self.freq):
            self.peakInfoChanged.emit(float(self.freq[peak_idx]), float(mag_y_db[peak_idx]))
