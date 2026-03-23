""" Samples audio signal and finds the peaks of the guitar tap resonances
"""

from dataclasses import dataclass
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
        self._is_frozen: bool = False
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
                is_frozen = self._is_frozen
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
            if tap_fired:
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

    def set_frozen(self, value: bool) -> None:
        with self._settings_lock:
            self._is_frozen = value

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

    def __init__(
        self,
        window_length: int,
        sampling_rate: int,
        frange: dict[str, int],
        threshold: int,
    ) -> None:
        super().__init__()

        self.is_frozen: bool = False

        # Configure plot appearance
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setLabel("left", "FFT Magnitude (dB)")
        self.setLabel("bottom", "Frequency (Hz)")
        self.setTitle("FFT Peaks")
        self.setYRange(-100, 0, padding=0)

        # Enable and configure top axis for note labels
        plot_item = self.getPlotItem()
        plot_item.showAxis("top")
        top_axis = plot_item.getAxis("top")
        top_axis.setStyle(showValues=True)
        top_axis.setTicks([[]])

        plot_item.showAxis("right")
        right_axis = plot_item.getAxis("right")
        right_axis.setStyle(showValues=False, tickLength=0)
        right_axis.setWidth(10)

        self.annotations: fft_a.FftAnnotations = fft_a.FftAnnotations(self)

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

        # Auto-load calibration for the starting device
        self._calibration_device_name = saved_device_name
        if saved_device_name:
            cal_path = _as.AppSettings.calibration_for_device(saved_device_name)
            if cal_path:
                self.load_calibration(cal_path)

        # FFT line
        self.fft_line: pg.PlotDataItem = self.plot(
            [], [], pen=pg.mkPen("b", width=1)
        )

        # Peak scatter points
        self.points: pg.ScatterPlotItem = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen(None), brush=pg.mkBrush(30, 100, 200, 200)
        )
        self.selected_point: pg.ScatterPlotItem = pg.ScatterPlotItem(
            size=10, pen=pg.mkPen(None), brush=pg.mkBrush(220, 30, 30, 220)
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
        _lbl_opts_peak    = {"position": 0.04, "color": (0, 200, 0),   "anchors": [(0, 1), (0, 1)]}
        _lbl_opts_trigger = {"position": 0.96, "color": (220, 130, 0), "anchors": [(1, 1), (1, 1)]}
        _lbl_opts_reset   = {"position": 0.04, "color": (220, 130, 0), "anchors": [(0, 0), (0, 0)]}
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
        self._calibration_device_name: str = ""

        # Auto-scale dB
        self._auto_scale_db: bool = False

        # Saved waveform data for drawing
        self.saved_mag_y_db: npt.NDArray[np.float64] = []
        self.saved_peaks: npt.NDArray[np.float64] = np.zeros((0, 3))  # freq, mag, Q
        self.b_peaks_freq: npt.NDArray[np.float64] = []
        self.selected_peak: float = 0.0

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
            text="", anchor=(0.0, 1.0), color=(60, 60, 60),
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
        self.set_frozen(False)
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

        if self.is_frozen and np.any(self.saved_mag_y_db):
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
        self._cursor_label.setText(f"{display_freq:.1f} Hz  {display_db:.1f} dB")
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
        if not np.any(mag_y_db):
            return
        self._tap_spectra.append(mag_y_db.copy())
        captured = len(self._tap_spectra)
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
        """Arm the plate capture state machine for the next two taps."""
        self._plate_capture.start()

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
        if self.is_frozen:
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
        if self.is_frozen and len(points) > 0:
            if self.annotations.select_annotation(scatter):
                return
            index0 = points[0].index()
            if self.peaks_f_min_index <= index0 < self.peaks_f_max_index:
                if np.any(self.saved_peaks):
                    freq = self.saved_peaks[index0][0]
                    self.peakSelected.emit(freq)

    def update_axis(self, fmin: int, fmax: int, init: bool = False) -> None:
        """Update the x-axis frequency range"""
        if fmin < fmax:
            self.fmin = fmin
            self.fmax = fmax
            self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
            self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq

            self.setXRange(fmin, fmax, padding=0)
            if not init:
                self.find_peaks(self.saved_mag_y_db)

    def set_max_average_count(self, max_average_count: int) -> None:
        """Set the number of averages to take"""
        self.max_average_count = max_average_count

    def reset_averaging(self) -> None:
        """Reset the number of averages taken to zero."""
        self.num_averages = 0

    def set_avg_enable(self, avg_enable: bool) -> None:
        """Flag to enable/disable the averaging"""
        self.avg_enable = avg_enable

    def set_frozen(self, is_frozen: bool) -> None:
        """Flag to enable/disable the holding of peaks."""
        self.is_frozen = is_frozen
        self._proc_thread.set_frozen(is_frozen)
        if not is_frozen:
            self.selected_point.setData(x=[], y=[])
            self.clear_selected_peak()
            self._tap_spectra.clear()

    def set_fmin(self, fmin: int) -> None:
        """As it says"""
        self.update_axis(fmin, self.fmax)

    def set_fmax(self, fmax: int) -> None:
        """As it says"""
        self.update_axis(self.fmin, fmax)

    def set_threshold(self, threshold: int) -> None:
        """Set the threshold used to limit both the triggering of a sample
        and the threshold on finding peaks. The threshold value is always 0 to 100.
        """
        self.threshold = threshold

        self.threshold_x = self.fft_data.sample_freq // 2
        self.threshold_y = self.threshold - 100

        self.line_threshold.setPos(self.threshold_y)
        self.line_threshold.label.setText(f"Peak: {self.threshold_y} dB")

        self.find_peaks(self.saved_mag_y_db)

        self.selected_point.setData(x=[], y=[])
        self.peakDeselected.emit()
        if np.any(self.b_peaks_freq):
            if self.selected_peak > 0:
                peak_index = np.where(self.b_peaks_freq == self.selected_peak)
                if len(peak_index[0]):
                    self.peakSelected.emit(self.selected_peak)

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

    def set_draw_data(self, mag_db, peaks) -> None:
        """Set the data for each of the plot objects used in update_fft"""
        if np.any(mag_db):
            self.fft_line.setData(self.freq, mag_db)
        if hasattr(peaks, "size") and peaks.size > 0:
            self.points.setData(x=peaks[:, 0], y=peaks[:, 1])
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
                    self.newSample.emit(self.is_frozen)
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
        if self.is_frozen:
            self.set_draw_data(self.saved_mag_y_db, self.saved_peaks)
        else:
            _, peaks = self.find_peaks(mag_y_db)
            self.set_draw_data(mag_y_db, peaks)

        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))
