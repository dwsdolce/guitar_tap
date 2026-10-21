# @parity view/spectrum-chart
""" Samples audio signal and finds the peaks of the guitar tap resonances
"""


import html
import math

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

import guitar_tap.models.tap_tone_analyzer as td
import guitar_tap.views.utilities.tap_settings_view as _as
from guitar_tap.models import field_precision as fp
from guitar_tap.models import guitar_mode as gm
from guitar_tap.views.utilities import axis_tick_generator as atg
from guitar_tap.views.utilities import chart_style
from guitar_tap.views.utilities.magnitude_axis import MagnitudeAxis
from guitar_tap.views.utilities import palette
from guitar_tap.models import guitar_type as gt
from guitar_tap.models import microphone_calibration as _mc_mod
from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode
from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
from guitar_tap.utilities.logging import gt_log
from guitar_tap.views import chart_help, chart_menu
from guitar_tap.views import peak_annotations as fft_a
from guitar_tap.views.utilities.extensions import formatted_as_frequency



from guitar_tap.models import display_range as dr  # noqa: E402


class _SceneMouseReleaseFilter(QtCore.QObject):
    """Event filter that emits a signal on QGraphicsScene mouse release."""

    released = QtCore.Signal(object)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QtCore.QEvent.Type.GraphicsSceneMouseRelease:
            self.released.emit(event)
        return False


# ── Zoom & Pan help popup ─────────────────────────────────────────────────────

class _ZoomPanPopup(QtWidgets.QFrame):
    """The chart's help, below its ⓘ: the lines that work on the device in use (chart_help), each "gesture: effect"
    with the effect in text.secondary, groups divided by a line. It scrolls when the screen is too short to show it
    whole. Uses Qt.Popup so it closes on a click outside. Mirrors Swift's ChartHelpView."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(
            parent,
            QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint,
        )
        palette.surface(self, palette.Role.BACKGROUND_PANEL, outlined=True)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

    def _content(self) -> QtWidgets.QWidget:
        """The help's lines, built when it opens — in the current scheme's roles."""
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(4)
        title = QtWidgets.QLabel(chart_help.TITLE)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        layout.addSpacing(2)
        line_font = QtGui.QFont()
        line_font.setPointSize(11)
        secondary = palette.qss(palette.Role.TEXT_SECONDARY)
        for index, group in enumerate(chart_help.shown(chart_help.current())):
            if index:
                layout.addWidget(palette.divider())
            for gesture, effect in group:
                line = QtWidgets.QLabel(f'{html.escape(gesture)}<span style="color: {secondary}">: '
                                        f'{html.escape(effect)}</span>')
                line.setFont(line_font)
                layout.addWidget(line)
        return content

    def show_near(self, global_pos: QtCore.QPoint) -> None:
        """Show the help below the ⓘ, its top-right corner at *global_pos*, no taller than the screen allows."""
        self._scroll.setWidget(self._content())
        content = self._scroll.widget()
        content.adjustSize()
        screen = QtGui.QGuiApplication.screenAt(global_pos) or QtGui.QGuiApplication.primaryScreen()
        room = screen.availableGeometry().bottom() - global_pos.y() - 8
        height = min(content.sizeHint().height(), max(room, 120))
        self.resize(content.sizeHint().width() + self._scroll.verticalScrollBar().sizeHint().width(), height)
        self.move(global_pos.x() - self.width(), global_pos.y())
        self.show()


class _ChipLabel(pg.InfLineLabel):
    """A line's label on a rounded chip — Swift's annotation with `.padding(.horizontal, x)`,
    `.padding(.vertical, y)`, a background and `.cornerRadius(corner)`."""

    def __init__(self, line: pg.InfiniteLine, text: str, padding: tuple[float, float], corner: float,
                 **opts) -> None:
        self._pad_x, self._pad_y = padding
        self._corner = corner
        super().__init__(line, text=text, **opts)
        self.textItem.document().setDocumentMargin(0)
        self.updateTextPos()

    def _chip_rect(self) -> QtCore.QRectF:
        return self.textItem.boundingRect().adjusted(-self._pad_x, -self._pad_y, self._pad_x, self._pad_y)

    def boundingRect(self) -> QtCore.QRectF:
        return self.textItem.mapRectToParent(self._chip_rect())

    def updateTextPos(self) -> None:
        # The chip's padding is outside the text: anchor the padded chip, not the text.
        r = self._chip_rect()
        tl = QtCore.QPointF(r.left() + r.width() * self.anchor.x(), r.top() + r.height() * self.anchor.y())
        self.textItem.setPos(-tl)

    def paint(self, p, *args) -> None:
        # TextItem fills a square box: hand it no fill (it still keeps its transform), then draw the
        # rounded chip under the text.
        fill = self.fill
        self.fill = QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)
        super().paint(p, *args)
        self.fill = fill
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.drawRoundedRect(self.textItem.mapRectToParent(self._chip_rect()), self._corner, self._corner)


class _ModeChip(_ChipLabel):
    """A guitar mode's name at the lower line of its range, as Swift's mode-boundary annotation: a chip
    centred on the line just inside the plot's top (`.annotation(position: .top, overflowResolution:
    .fit(to: .plot))`), kept inside the plot at either side — caption2 semibold in the mode's colour,
    padded 4 / 2, on the mode's colour at 15 %, corner 4."""

    def __init__(self, line: pg.InfiniteLine, text: str, rgb: tuple[int, int, int]) -> None:
        super().__init__(line, text, (4.0, 2.0), 4.0, position=1.0, anchors=[(0.5, 0), (0.5, 0)],
                         color=rgb, fill=QtGui.QColor(*rgb, round(255 * palette.opacity(palette.Opacity.MODE_CHIP_FILL))))
        font = QtGui.QFont()
        font.setPointSizeF(10)
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        self.setFont(font)
        self.updateTextPos()

    def updatePosition(self) -> None:
        super().updatePosition()
        vb = self.getViewBox()
        if vb is None:
            return
        (x0, x1), _ = vb.viewRange()
        width_px = vb.width()
        if x1 <= x0 or width_px <= 0:
            return
        # Only a line inside the chart's range is labelled, as Swift's visibleModeBoundaries. Shown and
        # hidden by its opacity: a visibility change here would re-enter this update.
        inside = x0 <= self.line.value() <= x1
        if self.opacity() != (1.0 if inside else 0.0):
            self.setOpacity(1.0 if inside else 0.0)
        if not inside:
            return
        # Keep the chip inside the plot: near a side, slide it along rather than centre it.
        w = self._chip_rect().width()
        x_px = (self.line.value() - x0) / (x1 - x0) * width_px
        left = min(max(x_px - w / 2, 0.0), max(width_px - w, 0.0))
        self.setAnchor(((x_px - left) / w if w > 0 else 0.5, 0))


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
        from guitar_tap.models.material_tap_phase import MaterialTapPhase as _MTP
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

# Core Audio's 'iost' (kAUStartIO): the I/O unit could not start — typically for a moment while a
# Continuity Audio device connects or disconnects.
_K_AU_START_IO = 1937010544


def _is_io_start_race(exc: BaseException) -> bool:
    """Whether a start failed with Core Audio's transient kAUStartIO, which PortAudio reports as an
    unanticipated host error carrying the OSStatus. Mirrors Swift's check of the error code."""
    info = exc.args[2] if len(getattr(exc, "args", ())) > 2 else None
    return isinstance(info, tuple) and len(info) > 1 and info[1] == _K_AU_START_IO


def _engine_start_error_message(exc: BaseException) -> str:
    """The "Audio Engine Error" text for a start that failed. As Swift's engineStartError."""
    code = exc.args[1] if len(exc.args) > 1 else -1
    return (f"The audio engine could not start (error {code}). Try switching the audio input "
            f"device in Settings, or restart the app.\n\n"
            f"Details: {exc.args[0] if exc.args else exc}")

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

    peaksChanged: QtCore.Signal = QtCore.Signal(np.ndarray)
    currentDecayTimeChanged: QtCore.Signal = QtCore.Signal(object)  # ring-out seconds, or None
    tapCountChanged: QtCore.Signal = QtCore.Signal(int, int)  # (captured, total)
    detectionStateChanged: QtCore.Signal = QtCore.Signal(object)  # new DetectionState
    readyForDetectionChanged: QtCore.Signal = QtCore.Signal(bool)  # engine ready for detection
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
    inputDeviceSwitched: QtCore.Signal = QtCore.Signal(object)             # AudioDevice — relays TapToneAnalyzer.inputDeviceSwitched
    inputDeviceOpenFailed: QtCore.Signal = QtCore.Signal(str)              # message — relays TapToneAnalyzer.inputDeviceOpenFailed
    dumpFolderUnreachable: QtCore.Signal = QtCore.Signal()                 # relays TapToneAnalyzer.dumpFolderUnreachable
    captureRecordingHeld: QtCore.Signal = QtCore.Signal()                  # relays TapToneAnalyzer.captureRecordingHeld
    captureAudioSavedChanged: QtCore.Signal = QtCore.Signal(object)        # file name or None — relays TapToneAnalyzer.captureAudioSavedChanged
    measurementLoadStarting: QtCore.Signal = QtCore.Signal()               # relays TapToneAnalyzer.measurementLoadStarting
    # A start that failed after its retry — the window shows it as an "Audio Engine Error".
    engineStartFailedMessage: QtCore.Signal = QtCore.Signal(str)
    measurementLoaded: QtCore.Signal = QtCore.Signal(object)               # relays TapToneAnalyzer.measurementLoaded
    comparisonChanged: QtCore.Signal = QtCore.Signal(bool)         # True=entering, False=leaving
    freqRangeChanged: QtCore.Signal = QtCore.Signal(float, float)  # (fmin, fmax) — pan/zoom

    def __init__(
        self,
        sampling_rate: int,
        frange: dict[str, int],
        threshold: int,
    ) -> None:
        super().__init__(axisItems={"left": MagnitudeAxis("left")})

        # Configure plot appearance
        # Colours come from the palette's chart roles in _apply_scheme (end of __init__ and on every
        # scheme change); grid alpha 1 so the grid is chart.grid exactly.
        self.showGrid(x=True, y=True, alpha=1.0)
        self._title_text = "FFT Peaks"
        # Restore persisted dB range — mirrors Swift's @State minDB/maxDB initialized
        # from TapDisplaySettings.minMagnitude / TapDisplaySettings.maxMagnitude.
        import guitar_tap.views.utilities.tap_settings_view as _as_init
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

        # Pan/zoom within the chart's limits (display_range — the same as Settings' validation and the
        # widening). The minimum span is checked on zoom gestures, as in Swift.
        vb = self.getPlotItem().vb
        vb.setLimits(xMin=dr.MIN_FREQUENCY_HZ, xMax=dr.MAX_FREQUENCY_HZ,
                     yMin=dr.MIN_MAGNITUDE_DB, yMax=dr.MAX_MAGNITUDE_DB)
        def _scale_by_within_limits(s=None, center=None, x=None, y=None):
            """pyqtgraph's zoom (wheel, drag, axis scroll) as Swift's: each axis by
            display_range.zoomed_range — about the gesture's centre, within the chart's limits, a
            step that would leave the span narrower than the minimum refused (Swift
            applyFrequencyZoom / applyMagnitudeZoom). pyqtgraph's factor is the new span over the
            old."""
            if s is not None:
                sx, sy = (s, s) if not isinstance(s, (list, tuple)) else (s[0], s[1])
            else:
                sx, sy = x, y
            (x0, x1), (y0, y1) = vb.viewRange()
            c = pg.Point(center) if center is not None else pg.Point((x0 + x1) / 2, (y0 + y1) / 2)
            cx, cy = c.x(), c.y()
            if sx is not None and sx > 0:
                r = dr.zoomed_range(x0, x1, cx, 1 / sx, dr.MIN_FREQUENCY_HZ, dr.MAX_FREQUENCY_HZ,
                                    dr.MIN_FREQUENCY_SPAN_HZ)
                if r is not None:
                    vb.setXRange(*r, padding=0)
            if sy is not None and sy > 0:
                r = dr.zoomed_range(y0, y1, cy, 1 / sy, dr.MIN_MAGNITUDE_DB, dr.MAX_MAGNITUDE_DB,
                                    dr.MIN_MAGNITUDE_SPAN_DB)
                if r is not None:
                    vb.setYRange(*r, padding=0)

        vb.scaleBy = _scale_by_within_limits

        # Canvas-local display viewport — tracks the visible frequency range for
        # pan/zoom and peak display.  Separate from analyzer.min_frequency/
        # max_frequency, which mirror Swift TapToneAnalyzer.minFrequency and are
        # the analysis window used by find_peaks (never written by canvas pan/zoom).
        self._minFreq: float = float(frange["f_min"])
        # The range a loaded measurement put on the chart (as widened onto its peaks), while the chart is
        # still showing it; None when no load is in view. Mirrors Swift's loadedChartRange.
        self._loaded_chart_range = None
        self._maxFreq: float = float(frange["f_max"])
        self.setXRange(frange["f_min"], frange["f_max"], padding=0)

        guitar_type_str = _as.AppSettings.guitar_type()

        # Create the FFT engine first, then pass it to TapToneAnalyzer.
        # Mirrors Swift: view creates RealtimeFFTAnalyzer, then passes it to
        # TapToneAnalyzer(fftAnalyzer:) so signals wire at construction time.
        # The engine selects the input device — the saved choice when it is present, else the
        # system default, else the first — and opens its stream at that device's rate.
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer as _Mic
        _mic = _Mic(
            self,
            rate=sampling_rate,
            chunksize=1024,
            on_devices_changed=None,       # wired by attach_to_view() below
        )

        self.analyzer: td.TapToneAnalyzer = td.TapToneAnalyzer(fft_analyzer=_mic)
        # The engine applied the selected device's calibration when it selected the device.
        # The Qt wiring that needs this widget; the engine starts with start_analyzer().
        self.analyzer.attach_to_view(self)
        # Wire the analyzer into FftAnnotations so dragged positions are persisted
        # in the model and survive pan/zoom annotation rebuilds.
        self.annotations._analyzer = self.analyzer
        # Display mode is initialised to AnalysisDisplayMode.LIVE in TapToneAnalyzer.__init__.
        # Set initial peak threshold on the analyzer.
        # peak_min_threshold is stored as dBFS; threshold input is 0-100 scale.
        self.analyzer.peak_min_threshold = float(threshold - 100)
        # analysis_min_frequency / analysis_max_frequency are initialised from AppSettings
        # in TapToneAnalyzer.__init__ and must not be overwritten with the display viewport.

        # Convenience alias kept for code that still reads self.mic
        self.mic: Microphone = self.analyzer.mic
        # ── Connect analyzer signals → FftCanvas signals (forwarding) ────
        # This allows guitar_tap.py to connect to FftCanvas signals as before.
        self.analyzer.peaksChanged.connect(self.peaksChanged)
        self.analyzer.tapCountChanged.connect(self.tapCountChanged)
        self.analyzer.detectionStateChanged.connect(self.detectionStateChanged)
        self.analyzer.readyForDetectionChanged.connect(self.readyForDetectionChanged)
        self.analyzer.currentDecayTimeChanged.connect(self.currentDecayTimeChanged)
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
        self.analyzer.inputDeviceSwitched.connect(self.inputDeviceSwitched)
        self.analyzer.inputDeviceOpenFailed.connect(self.inputDeviceOpenFailed)
        self.analyzer.dumpFolderUnreachable.connect(self.dumpFolderUnreachable)
        self.analyzer.captureRecordingHeld.connect(self.captureRecordingHeld)
        self.analyzer.captureAudioSavedChanged.connect(self.captureAudioSavedChanged)
        self.analyzer.measurementLoadStarting.connect(self.measurementLoadStarting)
        # The placeholder follows the engine: hidden while it runs; "Audio input unavailable" when
        # the permission is refused, a start failed or the recovery's restarts failed, as Swift's.
        thread = self.analyzer.mic.proc_thread
        thread.runningChanged.connect(self._update_overlay)
        thread.microphonePermissionDeniedChanged.connect(self._update_overlay)
        thread.inputCouldNotStartChanged.connect(self._update_overlay)
        thread.inputCouldNotRestartChanged.connect(self._update_overlay)
        self.analyzer.measurementLoaded.connect(self.measurementLoaded)
        self.analyzer.comparisonChanged.connect(self._on_comparison_changed_from_analyzer)
        self.analyzer.loadedAxisRangeChanged.connect(self._on_loaded_axis_range_changed)
        self.analyzer.materialSpectraChanged.connect(self.load_material_spectra)
        # The spectrum line: drawn on every frame from the engine's live frame (_on_live_frame), and
        # when the analyzer's own spectrum changes (spectrumUpdated). peaksChanged drives the scatter
        # plot — single authoritative source for both the scatter plot and the results panel.
        self.analyzer.mic.frame.frameChanged.connect(self._on_live_frame)
        self.analyzer.spectrumUpdated.connect(self._on_spectrum_updated)
        self.analyzer.peaksChanged.connect(self._on_peaks_changed_scatter)
        self.analyzer.highlightedPeakChanged.connect(lambda _id: self._draw_highlight())

        # FFT line
        self.fft_line: pg.PlotDataItem = self.plot(
            [], [], pen=pg.mkPen(None), antialias=True
        )

        # Peak scatter points
        self.points: pg.ScatterPlotItem = pg.ScatterPlotItem(
            size=chart_style.diameter(chart_style.SCREEN.dot_area), pen=pg.mkPen(None),
            antialias=True
        )
        self.selected_point: pg.ScatterPlotItem = pg.ScatterPlotItem(
            size=chart_style.diameter(chart_style.SCREEN.highlighted_dot_area), pen=pg.mkPen(None),
            symbol='star', antialias=True,
        )
        self.addItem(self.points)
        self.addItem(self.selected_point)

        self.points.sigClicked.connect(self.point_picked)

        # Threshold lines — use InfiniteLine so labels stay in view when panned
        _peak_y: int = self.threshold_y
        _tap_y: int  = _as.AppSettings.tap_threshold() - 100

        # Label opts: anchors are (x, y) where x=0 left-align, x=1 right-align;
        #             y=0 text below position, y=1 text above position.
        # Right-aligned, above the line, at the right edge — matches Swift's .trailing/.top.
        _lbl_opts_peak = {"position": 0.99, "anchors": [(1, 1), (1, 1)]}

        # Peak-minimum line (green dashed) — "Peak: x dB", right, above, on a chip of
        # chart.readout.background, padded 6 / 2, corner 4 (matches Swift's thresholdLinesContent RuleMark:
        # green, width 1.5, dash [8, 3], label .top/.trailing).
        self.line_threshold = pg.InfiniteLine(pos=_peak_y, angle=0, pen=pg.mkPen(None))
        self.line_threshold.label = _ChipLabel(
            self.line_threshold, f"Peak: {_peak_y} dB", (6.0, 2.0), 4.0, **_lbl_opts_peak)
        self.addItem(self.line_threshold)

        # Tap-trigger / Reset lines removed — the threshold now compares
        # against the time-domain RMS level, not against the FFT magnitude
        # axis shown on this chart.  Drawing a horizontal line at the
        # threshold dB value here was actively misleading because the
        # captured FFT peaks regularly sit ~30 dB below the threshold even
        # for clean taps.  The threshold's input-level relationship is now
        # shown directly on the ThresholdSlider widget (level meter +
        # peak-hold dot + clipping zone).
        # State kept so set_tap_threshold remains well-defined for the
        # analyzer-side mirror, even though no chart element reflects it.
        self._tap_threshold_y: int = _tap_y

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
        )
        self._cursor_label.setZValue(200)
        self.addItem(self._cursor_label)
        self._cursor_label.setVisible(False)

        # Crosshair lines — follow mouse when free, snap to curve when held
        self._crosshair_v = pg.InfiniteLine(angle=90, movable=False)
        self._crosshair_h = pg.InfiniteLine(angle=0,  movable=False)
        self._crosshair_v.setZValue(150)
        self._crosshair_h.setZValue(150)
        self._crosshair_v.setVisible(False)
        self._crosshair_h.setVisible(False)
        self.addItem(self._crosshair_v)
        self.addItem(self._crosshair_h)

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self.getPlotItem().vb.sigXRangeChanged.connect(self._refresh_peaks_for_viewport)
        # The axis ticks — and so the grid lines — are Swift's, recomputed when the view moves.
        self.getPlotItem().vb.sigRangeChanged.connect(lambda *_: self._update_ticks())

        # Initialise mode bands for the saved guitar type
        self.set_guitar_type_bands(guitar_type_str)

        # The placeholder shown while the engine is not running: the waveform image over
        # "Starting...", or why the input is unavailable. Mirrors Swift's chart overlay.
        self._overlay = QtWidgets.QWidget(self)
        self._overlay.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay_layout = QtWidgets.QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(4)
        overlay_icon = QtWidgets.QLabel()
        overlay_icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        palette.set_icon(overlay_icon, "mdi.waveform", palette.Role.TEXT_SECONDARY, 48)
        overlay_layout.addWidget(overlay_icon)
        self._overlay_label = QtWidgets.QLabel("Starting...")
        self._overlay_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        caption = QtGui.QFont()
        caption.setPointSize(12)
        self._overlay_label.setFont(caption)
        palette.tag(self._overlay_label, color=palette.Role.TEXT_SECONDARY)
        overlay_layout.addWidget(self._overlay_label)
        # Position the overlay after the view is fully set up
        QtCore.QTimer.singleShot(0, self._center_overlay)

        # ⓘ Info button — upper-right overlay, shows Zoom & Pan help popup
        self._info_btn = QtWidgets.QToolButton(self)
        palette.tag(self._info_btn, icon=True)
        palette.set_icon(self._info_btn, "mdi.information-outline", palette.Role.TEXT_SECONDARY)  # Swift info.circle
        self._info_btn.setIconSize(QtCore.QSize(15, 15))
        self._info_btn.setFixedSize(22, 22)
        self._info_btn.setToolTip("Zoom & Pan Controls")
        self._info_btn.clicked.connect(self._show_zoom_help)
        self._zoom_popup = _ZoomPanPopup(self)

        # ⋯ — the chart menu, the same as a right-click; Swift's and the web's ⋯ in the chart's upper-right.
        self._options_btn = QtWidgets.QToolButton(self)
        palette.tag(self._options_btn, icon=True)
        palette.set_icon(self._options_btn, "mdi.dots-horizontal-circle-outline",  # Swift ellipsis.circle
                         palette.Role.TEXT_SECONDARY)
        self._options_btn.setIconSize(QtCore.QSize(15, 15))
        self._options_btn.setFixedSize(22, 22)
        self._options_btn.setToolTip("Chart options")
        self._options_btn.clicked.connect(self._show_chart_options)

        # Defer initial position until the widget has been laid out
        QtCore.QTimer.singleShot(0, self._reposition_info_btn)

        # Comparison overlay state — mirrors comparisonSpectra in TapToneAnalyzer.swift
        self._comparison_curves: list[pg.PlotDataItem] = []
        # Each comparison / material curve's colour: a palette role (drawn in the current scheme) or
        # a stored (r, g, b), in the same order as _comparison_curves.
        self._comparison_curve_colors: list = []
        self._comparison_legend: QtWidgets.QWidget | None = None
        # True when _comparison_curves contains material phase overlays (L/C/FLC)
        # rather than user-loaded comparison files.  When True, fft_line must still
        # be updated so the live waveform is visible underneath the overlays —
        # mirrors Swift SpectrumView always rendering spectrumLineContent.
        self._has_material_spectra: bool = False

        # Last viewport-filtered peaks received via peaksChanged signal.
        # Tracks the emitted slice so point_picked and update_mode_colors
        # don't need to re-derive it from saved_peaks + index fields.
        self._all_peaks_in_range: list = []  # list[ResonantPeak]

        # Legacy numpy array of shape (N, 3) — [frequency, magnitude, quality].
        # Used by plate-mode consumers that do column-slice arithmetic.
        # Decoupled from analyzer.peaks_above_peak_min (list[ResonantPeak]) to avoid
        # corrupting the typed peak list with raw arrays.
        import numpy as _np
        self._saved_peaks_array: "npt.NDArray" = _np.zeros((0, 3), dtype=_np.float64)

        # A start that fails — no input device, or one that cannot be opened — leaves the app running
        # without one, and the window reports it as Swift's view does (its engineStartError →
        # "Audio Engine Error"). Set by start_analyzer().
        self.engine_start_error: str | None = None

        # Draw in the scheme the app is drawn in, and again on every change of it.
        self._apply_scheme()
        palette.notifier().scheme_changed.connect(self._on_scheme_changed)

    # ------------------------------------------------------------------ #
    # Colour scheme
    # ------------------------------------------------------------------ #

    @staticmethod
    def _curve_rgb(color) -> tuple[int, int, int]:
        """A comparison / material curve's colour: its role in the current scheme, or its stored
        rgb."""
        return palette.rgb(color) if isinstance(color, palette.Role) else tuple(color)

    def _on_scheme_changed(self, _scheme) -> None:
        self._apply_scheme()

    def _apply_scheme(self) -> None:
        """Take every chart colour from its role in the current scheme. Mirrors Swift's chart, whose
        palette colours resolve in the scheme they are drawn in."""
        self.setBackground(palette.color(palette.Role.CHART_BACKGROUND))
        plot = self.getPlotItem()
        style = chart_style.SCREEN
        plot.vb.setBorder(chart_style.pen(palette.color(palette.Role.CHART_BORDER), 1))
        for name in ("left", "bottom"):
            axis = plot.getAxis(name)
            axis.setPen(chart_style.pen(palette.color(palette.Role.CHART_GRID), style.grid_width))
            axis.setTextPen(pg.mkPen(palette.color(palette.Role.CHART_AXIS)))
        # The top and right axes draw no values, only a line along the plot's border: in the border's role.
        for name in ("top", "right"):
            plot.getAxis(name).setPen(chart_style.pen(palette.color(palette.Role.CHART_BORDER), 1))
        axis_color = palette.qss(palette.Role.CHART_AXIS)
        self.setLabel("left", "FFT Magnitude (dB)", color=axis_color)
        self.setLabel("bottom", "Frequency (Hz)", color=axis_color)
        self.setTitle(self._title_text, color=palette.qss(palette.Role.CHART_TITLE))
        self.fft_line.setPen(
            chart_style.pen(palette.color(palette.Role.CHART_SPECTRUM), style.spectrum_width))
        highlighted = palette.color(palette.Role.CHART_HIGHLIGHTED_PEAK)
        self.selected_point.setPen(pg.mkPen(highlighted, width=1))
        self.selected_point.setBrush(pg.mkBrush(highlighted))
        peak_min = palette.color(palette.Role.CHART_PEAK_MIN)
        self.line_threshold.setPen(chart_style.pen(
            peak_min, style.peak_min_width, style.peak_min_dash, style.peak_min_opacity))
        self.line_threshold.label.setColor(peak_min)
        self.line_threshold.label.fill = pg.mkBrush(palette.color(palette.Role.CHART_READOUT_BACKGROUND))
        self.line_threshold.label.update()
        self._cursor_label.fill = pg.mkBrush(palette.color(palette.Role.CHART_READOUT_BACKGROUND))
        self._cursor_label.update()
        crosshair = chart_style.pen(
            palette.color(palette.Role.CHART_CROSSHAIR_LINE),
            style.crosshair_width, style.crosshair_dash)
        self._crosshair_v.setPen(crosshair)
        self._crosshair_h.setPen(crosshair)
        if getattr(self, "_bands_guitar_type", None):
            self.set_guitar_type_bands(self._bands_guitar_type)
        for curve, color in zip(self._comparison_curves, self._comparison_curve_colors):
            curve.setPen(chart_style.pen(self._curve_rgb(color), style.overlay_width))
        if self._comparison_legend is not None:
            self._build_comparison_legend(self._comparison_legend_labels, font_size=10)
        self._update_ticks()

    def _update_ticks(self) -> None:
        """Set both axes' ticks — and so the grid lines, one per tick — to Swift's: the
        frequency ticks of generateTicks (8 at most) labelled by format_tick_labels, and a
        magnitude tick every magnitude_stride dB. Mirrors Swift SpectrumView's xAxisContent /
        yAxisContent."""
        plot = self.getPlotItem()
        (x_min, x_max), (y_min, y_max) = plot.vb.viewRange()
        visible = [t for t in atg.generate_ticks(x_min, x_max, max_ticks=8) if x_min <= t <= x_max]
        labels = atg.format_tick_labels(visible)
        plot.getAxis("bottom").setTicks([[(t, labels[t]) for t in visible]])
        stride = chart_style.SCREEN.magnitude_stride or atg.magnitude_stride(y_max - y_min)
        first = math.ceil(y_min / stride)
        last = math.floor(y_max / stride)
        plot.getAxis("left").setTicks(
            [[(k * stride, f"{k * stride:g}") for k in range(first, last + 1)]])
        # pyqtgraph's grid is drawn by all four axes; only the bottom and left carry the ticks.
        plot.getAxis("top").setGrid(False)
        plot.getAxis("right").setGrid(False)

    def _build_comparison_legend(self, labels: list[str], font_size: int) -> None:
        """The horizontal legend over the top-right of the plot: one swatch and label per
        comparison / material curve, in the curve's colour, on the readout background."""
        if self._comparison_legend is not None:
            self._comparison_legend.deleteLater()
        legend = QtWidgets.QWidget(self)
        legend.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        legend.setStyleSheet(
            f"background: {palette.qss(palette.Role.CHART_READOUT_BACKGROUND)}; border-radius: 6px;"
        )
        row = QtWidgets.QHBoxLayout(legend)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(12)
        for label, color in zip(labels, self._comparison_curve_colors):
            r, g, b = self._curve_rgb(color)
            swatch = QtWidgets.QLabel()
            swatch.setFixedSize(16, 2)
            swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border-radius: 1px;")
            text = QtWidgets.QLabel(label)
            text.setStyleSheet(
                f"color: rgb({r},{g},{b}); font-size: {font_size}px; background: transparent;"
            )
            entry = QtWidgets.QHBoxLayout()
            entry.setSpacing(4)
            entry.addWidget(swatch, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            entry.addWidget(text,   0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            row.addLayout(entry)
        legend.adjustSize()
        legend.show()
        self._comparison_legend = legend
        self._comparison_legend_labels = list(labels)
        self._reposition_comparison_legend()

    # ------------------------------------------------------------------ #
    # Backward-compatibility properties — guitar_tap.py reads these directly
    # ------------------------------------------------------------------ #

    @property
    def display_mode(self) -> AnalysisDisplayMode:
        """Current spectrum display mode (delegates to the analyzer)."""
        return self.analyzer.display_mode

    @display_mode.setter
    def display_mode(self, value: AnalysisDisplayMode) -> None:
        self.analyzer.display_mode = value

    @property
    def is_measurement_complete(self) -> bool:
        """Whether a measurement is frozen/complete (delegates to the analyzer)."""
        return self.analyzer.is_measurement_complete

    @is_measurement_complete.setter
    def is_measurement_complete(self, value: bool) -> None:
        self.analyzer.is_measurement_complete = value

    @property
    def saved_peaks(self) -> npt.NDArray:
        """The frozen measurement's saved peak array."""
        return self._saved_peaks_array

    @saved_peaks.setter
    def saved_peaks(self, value) -> None:
        self._saved_peaks_array = value

    @property
    def saved_mag_y_db(self):
        """The frozen measurement's magnitude spectrum, in dB."""
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
    def minFreq(self) -> float:
        """Display x-axis minimum frequency, in Hz."""
        return self._minFreq

    @minFreq.setter
    def minFreq(self, value: float) -> None:
        self._minFreq = float(value)

    @property
    def maxFreq(self) -> float:
        """Display x-axis maximum frequency, in Hz."""
        return self._maxFreq

    @maxFreq.setter
    def maxFreq(self, value: float) -> None:
        self._maxFreq = float(value)

    @property
    def comparison_labels(self):
        """Labels for the active comparison overlays (delegates to the analyzer)."""
        return self.analyzer.comparison_labels

    @comparison_labels.setter
    def comparison_labels(self, value) -> None:
        self.analyzer.comparison_labels = value

    @property
    def freq(self):
        """Current live FFT frequency bins (delegates to the analyzer)."""
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
        if self.analyzer.is_measurement_complete:
            return (self.analyzer.frozen_frequencies, self.analyzer.frozen_magnitudes)
        # A device/route change is settling — show nothing. The settle says so directly, through
        # is_settling, and leaves the frozen arrays alone. Mirrors Swift displaySpectrum.
        if self.analyzer.is_settling:
            return (None, None)
        return (self.analyzer.freq, None)

    # ------------------------------------------------------------------ #
    # Analyzer start / stop
    # ------------------------------------------------------------------ #

    def _center_overlay(self) -> None:
        """Centre the not-running placeholder on the chart, as Swift's overlay."""
        if not hasattr(self, "_overlay"):
            return  # a resize while the canvas is still being built
        self._overlay.adjustSize()
        self._overlay.move((self.width() - self._overlay.width()) // 2,
                           (self.height() - self._overlay.height()) // 2)
        self._overlay.raise_()

    def _update_overlay(self, *_args) -> None:
        """Show the not-running placeholder from the engine's state."""
        mic = self.analyzer.mic
        self._overlay_label.setText(mic.not_running_message)
        self._overlay.setVisible(not mic.is_running)
        self._center_overlay()

    def start_analyzer(self) -> None:
        """Start the analyzer and hide the idle overlay.

        Called at startup, on the first file playback if the processing thread has not started yet, and
        from restart_tap_sequence if it has died. ``analyzer.start()`` starts what is not running (the
        thread, the stream), anchors the warm-up and schedules the guarded auto-start, which leaves a
        sequence already under way alone. A failure to open the input is recorded in
        ``engine_start_error`` for the window to report.

        For New Tap while the thread is already running, use
        restart_tap_sequence() instead, which keeps the thread alive
        (no audio dropout) — mirrors Swift's AVAudioEngine running continuously.
        """
        # The analyzer starts the engine (the processing thread and the stream, each if not running),
        # anchors the warm-up and schedules the guarded auto-start, as Swift's view calls
        # tapToneAnalyzer.start().
        try:
            self.analyzer.start()
        except Exception as exc:  # noqa: BLE001 — any start failure is reported, never fatal
            from guitar_tap.models.realtime_fft_analyzer_engine_control import is_permission_error
            if is_permission_error(exc):
                # The engine has raised its permission flag; the window shows that alert.
                gt_log(f"❌ Audio engine could not start: {exc}")
                return
            if _is_io_start_race(exc):
                # kAUStartIO ('iost') — a transient Core Audio I/O start failure, typically a
                # Continuity Audio device connecting or disconnecting at the same moment. Retry once
                # after a short settle; report only if the retry fails too. As Swift's view does.
                gt_log("⚠️ kAUStartIO race detected — retrying engine start in 1 s")
                QtCore.QTimer.singleShot(1000, self._retry_start_after_io_race)
                return
            self.engine_start_error = _engine_start_error_message(exc)
            gt_log(f"❌ Audio engine could not start: {exc}")

    def _retry_start_after_io_race(self) -> None:
        """The one retry after a kAUStartIO failure; a second failure is reported."""
        try:
            self.analyzer.start()
            gt_log("✅ Engine started successfully on kAUStartIO retry")
        except Exception as exc:  # noqa: BLE001 — reported, never fatal
            gt_log(f"❌ Engine start retry failed: {exc}")
            from guitar_tap.models.realtime_fft_analyzer_engine_control import is_permission_error
            if not is_permission_error(exc):
                self.engine_start_error = _engine_start_error_message(exc)
                self.engineStartFailedMessage.emit(self.engine_start_error)

    def restart_tap_sequence(self) -> None:
        """Request a new tap sequence while the processing thread is already running.

        Mirrors Swift's New Tap button calling tap.requestStartTapSequence() on a
        continuously-running AVAudioEngine — no audio engine restart occurs.
        In Python the PortAudio stream runs continuously; only the ring buffer
        state is reset (reset_state() is thread-safe) once the analyzer arms.
        If the analyzer does not arm (the dump folder is unreachable), nothing changes.
        """
        # Stops file playback, checks the dump folder, and arms (is_measurement_complete = False,
        # is_detecting = True, etc.).
        if self.analyzer.request_start_tap_sequence():
            self._reset_audio_for_new_sequence()

    def start_tap_sequence(self) -> None:
        """Arm a new tap sequence without the dump-folder check — Swift's direct
        tap.startTapSequence()."""
        self.analyzer.start_tap_sequence()
        self._reset_audio_for_new_sequence()

    def _reset_audio_for_new_sequence(self) -> None:
        """After arming: reset the ring buffer, or start the processing thread if it has died."""
        if not self.analyzer.mic.proc_thread.isRunning():
            # Fallback: thread died unexpectedly — do a full restart.
            self.start_analyzer()
            return
        # Reset ring buffer so stale pre-tap audio doesn't contaminate the new sequence.
        # reset_state() is safe to call on a running thread.
        self.analyzer.mic.proc_thread.reset_state()

    def shutdown(self) -> None:
        """Stop the audio stream and processing thread and wait for it to exit.

        Must be called before the widget is destroyed (e.g. from the main
        window's closeEvent) to prevent Qt from aborting on QThread::~QThread()
        while the thread is still running.

        Stops the PortAudio stream (and hot-plug monitor + watchdog) FIRST so
        that no native audio-callback thread is still live when __main__ calls
        os._exit().  os._exit() (used to bypass sounddevice's atexit
        Pa_Terminate, which deadlocks on macOS) kills the process immediately;
        if the InputStream callback thread is still running at that point, the
        OS tears its memory away mid-callback and the process crashes with an
        access violation on exit (observed on Windows).  mic.close() aborts the
        stream on a daemon thread with a bounded timeout, so it is safe on
        macOS too.
        """
        mic = self.analyzer.mic
        mic.stop_buffer_watchdog()
        mic.close()
        mic.proc_thread.stop()
        mic.proc_thread.wait(2000)

    # ------------------------------------------------------------------ #
    # Guitar mode band overlays
    # ------------------------------------------------------------------ #

    def set_guitar_type_bands(self, guitar_type_str: str) -> None:
        """Rebuild the mode band overlays for the given guitar type."""
        self._bands_guitar_type = guitar_type_str
        self._remove_mode_bands()
        try:
            guitar_type = gt.GuitarType(guitar_type_str)
        except ValueError:
            return
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        is_guitar = _tds.measurement_type().is_guitar
        for lo, hi, mode_name in gm.get_bands(guitar_type):
            r, g, b = palette.rgb(palette.mode_role(gm.GuitarMode.from_display_name(mode_name)))
            style = chart_style.SCREEN
            pen = chart_style.pen(
                (r, g, b), style.mode_boundary_width, style.mode_boundary_dash,
                style.mode_boundary_opacity)
            abbrev = gm.GuitarMode.from_display_name(mode_name).abbreviation

            lo_line = pg.InfiniteLine(pos=lo, angle=90, movable=False, pen=pen)
            lo_line.setZValue(-10)
            lo_line.setVisible(self._mode_bands_shown(is_guitar))
            self.addItem(lo_line)
            self._mode_band_items.append(lo_line)

            # The label is drawn over the curves and dots, under the peak labels, as Swift's
            # annotation: it rides an undrawn line of its own above them, the dashed line staying behind.
            chip_line = pg.InfiniteLine(pos=lo, angle=90, movable=False, pen=pg.mkPen(None))
            chip_line.label = _ModeChip(chip_line, abbrev, (r, g, b))
            chip_line.setZValue(fft_a.MODE_LABEL_Z)
            chip_line.setVisible(self._mode_bands_shown(is_guitar))
            self.addItem(chip_line)
            self._mode_band_items.append(chip_line)

            hi_line = pg.InfiniteLine(pos=hi, angle=90, movable=False, pen=pen)
            hi_line.setZValue(-10)
            hi_line.setVisible(self._mode_bands_shown(is_guitar))
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
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as _tds
        is_guitar = _tds.measurement_type().is_guitar
        self._mode_bands_visible = visible
        for item in self._mode_band_items:
            item.setVisible(self._mode_bands_shown(is_guitar))

    def _mode_bands_shown(self, is_guitar: bool) -> bool:
        """The mode bands show for a guitar when the analyzer has the chart draw them (not for a
        comparison of saved measurements) — Swift's ``showModeBoundaries: tap.showsModeBoundaries``
        with ``measurementType.isGuitar``."""
        return self._mode_bands_visible and is_guitar and self.analyzer.shows_mode_boundaries

    # ------------------------------------------------------------------ #
    # Hot-plug device detection (forwarded from analyzer signals)
    # ------------------------------------------------------------------ #

    # Screen-distance threshold (pixels) for locking crosshair to a comparison curve.
    _CURVE_GRAVITY_PX: float = 12.0

    def _pointer_cursor(self, scene_pos) -> QtCore.Qt.CursorShape:
        """Swift's cursors over the chart: the open hand over a peak label (the closed hand while dragging one, which
        the label holds itself), the crosshair over the plot, left-right over the frequency axis, up-down over the
        magnitude axis, the arrow elsewhere."""
        Shape = QtCore.Qt.CursorShape
        if any(isinstance(item, fft_a.DraggableTextItem) and item.isVisible()
               for item in self.scene().items(scene_pos)):
            return Shape.OpenHandCursor
        return {"plot": Shape.CrossCursor, "xAxis": Shape.SizeHorCursor,
                "yAxis": Shape.SizeVerCursor}.get(self._pointer_region(scene_pos), Shape.ArrowCursor)

    def _pointer_region(self, scene_pos) -> str:
        """Where a point is on the chart — "plot", "xAxis" (the frequency axis), "yAxis" (the magnitude axis) or
        "outside". Mirrors Swift pointerRegion(at:plotFrame:)."""
        plot = self.getPlotItem()
        if plot.vb.sceneBoundingRect().contains(scene_pos):
            return "plot"
        # An axis's layout cell, not its drawn area, which takes in its grid lines across the plot.
        if plot.mapRectToScene(plot.getAxis("bottom").geometry()).contains(scene_pos):
            return "xAxis"
        if plot.mapRectToScene(plot.getAxis("left").geometry()).contains(scene_pos):
            return "yAxis"
        return "outside"

    def _on_mouse_moved(self, scene_pos) -> None:
        """Track the cursor: snaps to FFT curve when results are held, free otherwise."""
        shape = self._pointer_cursor(scene_pos)
        if self.viewport().cursor().shape() != shape:
            self.viewport().setCursor(shape)
        vb = self.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(scene_pos):
            self._cursor_label.setVisible(False)
            self._crosshair_v.setVisible(False)
            self._crosshair_h.setVisible(False)
            return
        view_pos = vb.mapSceneToView(scene_pos)
        mouse_freq = float(view_pos.x())
        mouse_db   = float(view_pos.y())

        freq_color = palette.qss(palette.Role.CHART_CROSSHAIR_FREQUENCY)

        # Material spectra overlays (plate/brace review states) are stored in
        # _comparison_curves even when is_comparing is False.  Snap to them
        # whenever they are present — mirrors Swift resolveSnapState which snaps
        # when isMeasurementComplete || !materialSpectra.isEmpty.
        has_material_curves = bool(self._comparison_curves)

        if self.is_comparing or has_material_curves:
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

            r, g, b = self._curve_rgb(self._comparison_curve_colors[locked])
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
        freq_str = formatted_as_frequency(display_freq)
        html = (
            f'<center>'
            f'<b style="color:{freq_color};">{freq_str}</b><br/>'
            f'<span style="color:{palette.qss(palette.Role.CHART_AXIS)};">'
            f'{fp.string(display_db, fp.PEAK_MAGNITUDE_DB)} dB</span>'
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

    def choose_calibration(self, cal: "_mc_mod.MicrophoneCalibration | None") -> None:
        """Apply and save the user's calibration choice (None: none) for the selected device — the
        engine's active calibration, as Swift's Settings assigns fftAnalyzer.activeCalibration."""
        self.analyzer.mic.set_active_calibration(cal)

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self.analyzer.current_calibration_device()

    # ------------------------------------------------------------------ #
    # Tap detector / sequence control (delegates to analyzer)
    # ------------------------------------------------------------------ #

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
        self._title_text = self.chart_title
        self.setTitle(self._title_text, color=palette.qss(palette.Role.CHART_TITLE))

    def set_playing_file_name(self, name: str | None) -> None:
        """Update the chart title to reflect the playing file name, or revert to
        the loaded measurement name / 'New' when playback ends.

        Mirrors Swift: chartTitle = fft.playingFileName ?? tap.loadedMeasurementName ?? "New"
        Connected to playingFileNameChanged signal.
        """
        self._title_text = self.chart_title
        self.setTitle(self._title_text, color=palette.qss(palette.Role.CHART_TITLE))

    def cancel_tap_sequence(self) -> None:
        """Cancel the current tap sequence and restart warmup — matches Swift cancelTapSequence."""
        self.analyzer.cancel_tap_sequence()

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing (1 = immediate freeze)."""
        self.analyzer.set_tap_num(n)

    def apply_measurement_type(self, measurement_type) -> None:
        """Show the chart for a measurement type — the guitar-only mode bands and threshold line.
        The type itself is the model's (the saved setting)."""
        is_guitar = measurement_type.is_guitar
        # Mode bands and peak threshold line are guitar-only — mirrors Swift's
        # showModeBoundaries && measurementType.isGuitar and isGuitar threshold line guard.
        for item in self._mode_band_items:
            item.setVisible(self._mode_bands_shown(is_guitar))
        self.line_threshold.setVisible(is_guitar and not self.is_comparing)
        # Clear stale guitar mode colours when switching to plate/brace so
        # _peak_brushes doesn't use leftover guitar colours on new peaks.
        if not is_guitar:
            self._mode_color_map = {}

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
        """Update the tap-detection threshold (0–100 scale).

        The chart no longer renders a Trigger / Reset line — feedback for
        the threshold lives in the ThresholdSlider's level meter instead.
        We still cache _tap_threshold_y for any downstream consumer.
        """
        self._tap_threshold_y = value - 100
        self.analyzer.set_tap_threshold(value)

    def pause_tap_detection(self) -> None:
        """Pause the tap detector; spectrum continues to update."""
        self.analyzer.pause_tap_detection()
        # tapDetectionPaused signal is forwarded from analyzer

    def resume_tap_detection(self) -> None:
        """Resume a paused tap detector."""
        self.analyzer.resume_tap_detection()
        # tapDetectionPaused signal is forwarded from analyzer

    def set_device(self, device) -> None:
        """Switch the audio input to the given AudioDevice and
        auto-load the calibration associated with that device.

        Mirrors Swift RealtimeFFTAnalyzer.setInputDevice(_:).
        """
        self.analyzer.set_device(device)

    # ------------------------------------------------------------------ #
    # The highlighted peak (the model's highlighted_peak_id)
    # ------------------------------------------------------------------ #

    def _draw_highlight(self) -> None:
        """Draw the star on the highlighted peak's dot — the model's ``highlighted_peak_id``, among the
        dots shown. A highlight whose peak is not shown (another measurement's, or hidden) draws
        nothing. Mirrors Swift's chart drawing from ``highlightedPeakID``."""
        peak_id = self.analyzer.highlighted_peak_id
        peak = next((p for p in self._all_peaks_in_range if p.id == peak_id), None) if peak_id else None
        if peak is None:
            self.selected_point.setData(x=[], y=[])
        else:
            self.selected_point.setData(x=[peak.frequency], y=[peak.magnitude])

    def point_picked(
        self, scatter: pg.ScatterPlotItem, points: list, ev
    ) -> None:
        """A click on a peak's dot toggles the model's highlighted peak (Swift's dot tap)."""
        if self.is_measurement_complete and len(points) > 0:
            if self.annotations.select_annotation(scatter):
                return
            index0 = points[0].index()
            if self._all_peaks_in_range and index0 < len(self._all_peaks_in_range):
                self.analyzer.toggle_highlighted_peak(self._all_peaks_in_range[index0].id)

    # ── info button & zoom/pan help ───────────────────────────────────────────

    def _reposition_info_btn(self) -> None:
        btn = getattr(self, "_info_btn", None)
        if btn is None:
            return
        btn.move(self.width() - btn.width() - 4, 4)
        btn.raise_()
        opts = getattr(self, "_options_btn", None)
        if opts is not None:
            opts.move(btn.x() - opts.width() - 2, 4)
            opts.raise_()

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
        """Reposition the placeholder, the info button and the comparison legend when the canvas
        resizes."""
        super().resizeEvent(event)
        self._center_overlay()
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

        No modifier  — pyqtgraph default by region (zoom around cursor; over an axis that axis only);
                       outside the plot and its axes, pan magnitude
        ⇧ Shift      — pan frequency (X) axis
        ⌥ Alt/Option — pan magnitude (Y) axis
        ⌘ Cmd / ⌃ Ctrl — zoom both axes around the cursor
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
            # Pan X: shift by 10% of current span, within the chart's limits (Swift handlePan).
            x0, x1 = vb.viewRange()[0]
            shift = (x1 - x0) * 0.10 * (1 if delta > 0 else -1)
            vb.setXRange(*dr.panned_range(x0, x1, shift, dr.MIN_FREQUENCY_HZ, dr.MAX_FREQUENCY_HZ),
                         padding=0)
            self._refresh_peaks_for_viewport()
            ev.accept()

        elif mods & Mod.AltModifier:
            # Pan Y: shift by 10% of current span, within the chart's limits (Swift handlePan).
            y0, y1 = vb.viewRange()[1]
            shift = (y1 - y0) * 0.10 * (1 if delta > 0 else -1)
            vb.setYRange(*dr.panned_range(y0, y1, shift, dr.MIN_MAGNITUDE_DB, dr.MAX_MAGNITUDE_DB),
                         padding=0)
            ev.accept()

        elif mods & (Mod.ControlModifier | Mod.MetaModifier):
            # Zoom both axes around the cursor, as Swift's handleZoom.
            self._zoom_axes(1.15 ** (delta / 120.0), self.mapToScene(ev.position().toPoint()))
            ev.accept()

        elif self._pointer_region(self.mapToScene(ev.position().toPoint())) == "outside":
            # Outside the plot and its axes: pan the magnitude axis, as Swift's.
            y0, y1 = vb.viewRange()[1]
            shift = (y1 - y0) * 0.10 * (1 if delta > 0 else -1)
            vb.setYRange(*dr.panned_range(y0, y1, shift, dr.MIN_MAGNITUDE_DB, dr.MAX_MAGNITUDE_DB),
                         padding=0)
            ev.accept()

        else:
            super().wheelEvent(ev)

    def _zoom_axes(self, factor: float, scene_pos, freq: bool = True, mag: bool = True) -> None:
        """One zoom step (*factor* > 1 zooms in) of the frequency and / or magnitude axis about the point under
        *scene_pos* — the view's centre when that point is outside the plot. A step that would leave a span narrower
        than the minimum is refused for that axis, as in Swift."""
        vb = self.getPlotItem().vb
        (x0, x1), (y0, y1) = vb.viewRange()
        if vb.sceneBoundingRect().contains(scene_pos):
            point = vb.mapSceneToView(scene_pos)
            ax, ay = float(point.x()), float(point.y())
        else:
            ax, ay = (x0 + x1) / 2, (y0 + y1) / 2
        if freq:
            rx = dr.zoomed_range(x0, x1, ax, factor, dr.MIN_FREQUENCY_HZ, dr.MAX_FREQUENCY_HZ,
                                 dr.MIN_FREQUENCY_SPAN_HZ)
            if rx is not None:
                vb.setXRange(*rx, padding=0)
        if mag:
            ry = dr.zoomed_range(y0, y1, ay, factor, dr.MIN_MAGNITUDE_DB, dr.MAX_MAGNITUDE_DB,
                                 dr.MIN_MAGNITUDE_SPAN_DB)
            if ry is not None:
                vb.setYRange(*ry, padding=0)
        self._refresh_peaks_for_viewport()

    def viewportEvent(self, ev: QtCore.QEvent) -> bool:
        """A trackpad pinch (macOS) zooms by where it starts, as Swift's: over the plot both axes, over the frequency
        axis frequency only, over the magnitude axis magnitude only. On Windows and Linux a pinch arrives as
        Ctrl + Scroll instead."""
        if ev.type() == QtCore.QEvent.Type.NativeGesture:
            kind = ev.gestureType()
            Gesture = QtCore.Qt.NativeGestureType
            scene_pos = self.mapToScene(ev.position().toPoint())
            if kind == Gesture.BeginNativeGesture:
                self._pinch_region = self._pointer_region(scene_pos)
            elif kind == Gesture.ZoomNativeGesture:
                region = getattr(self, "_pinch_region", "plot")
                self._zoom_axes(1.0 + ev.value(), scene_pos, freq=region != "yAxis", mag=region != "xAxis")
                return True
        return super().viewportEvent(ev)

    # ── context menu (replaces pyqtgraph default) ─────────────────────────────

    def _build_reset_menu(self) -> QtWidgets.QMenu:
        """The chart reset / options menu, shared by right-click and the ⋯ button."""
        menu = QtWidgets.QMenu(self)
        handlers = {
            "resetBothToSaved": self._reset_both_to_saved,
            "resetFrequencyToSaved": self._reset_freq_to_saved,
            "resetMagnitudeToSaved": self._reset_mag_to_saved,
            "resetBothToDefaults": self._reset_both_to_defaults,
            "resetFrequencyToDefaults": self._reset_freq_to_defaults,
            "resetMagnitudeToDefaults": self._reset_mag_to_defaults,
            "resetLabels": self.annotations.reset_all_positions,
        }
        for i, group in enumerate(chart_menu.GROUPS):
            if i:
                menu.addSeparator()
            for entry in group:
                act = palette.add_menu_item(menu, f"mdi.{entry.mdi}", entry.title, handlers[entry.action])
                if entry.action == "resetLabels":
                    act.setEnabled(self.annotations.has_moved_annotations)
        return menu

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """Right-click menu matching the Swift SpectrumView context menu."""
        self._build_reset_menu().exec(event.globalPos())
        event.accept()

    def _show_chart_options(self) -> None:
        """Open the reset/options menu under the ⋯ button (same items as right-click)."""
        btn = self._options_btn
        self._build_reset_menu().exec(btn.mapToGlobal(btn.rect().bottomLeft()))

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

    def update_axis(self, fmin: float, fmax: float) -> None:
        """Set the x-axis frequency range. A display change only: the peaks are not re-detected, as
        Swift's applyAxisRange."""
        if fmin < fmax:
            self._minFreq = float(fmin)
            self._maxFreq = float(fmax)
            self.setXRange(fmin, fmax, padding=0)

    def _refresh_peaks_for_viewport(self, _vb=None, x_range=None) -> None:
        """Re-emit the existing peaks and update the freq-range label whenever the
        viewport x-range changes (pan, zoom, or explicit wheel-scroll gestures).

        Connected to ViewBox.sigXRangeChanged and also called directly from
        wheelEvent after Shift+scroll pan and Ctrl+scroll zoom.

        Panning/zooming is a DISPLAY change: it re-filters what is shown, it does not
        re-analyse.  So this re-emits ``peaks_above_peak_min`` unchanged and lets the range-dependent
        consumers of ``peaksChanged`` (the scatter, results panel, ratios, material widget)
        re-filter themselves against the new ``_minFreq``/``_maxFreq``.

        It deliberately does NOT call ``recalculate_frozen_peaks_if_needed()``.  That is a
        RE-ANALYSIS, and on the live/frozen path it re-runs ``find_peaks`` and mints NEW peak
        UUIDs, after which ``_apply_frozen_peak_state`` has to re-match annotation offsets, mode
        overrides and selection back onto the new ids by frequency (±5 Hz).  Doing that on every
        pan/zoom frame is pure waste — the analysis window (``min_frequency``/``max_frequency``)
        is independent of the canvas viewport, so detection cannot change — and it needlessly
        churns identity in the state we most want stable while the user is inspecting a result.
        Swift calls its equivalent from exactly two places, the ``peakMinThreshold`` observer and
        an explicit Re-analyze; never from zoom or pan.
        """
        vb = self.getPlotItem().vb
        fmin, fmax = (float(v) for v in vb.viewRange()[0])
        if fmin >= fmax:
            return
        self._minFreq = fmin
        self._maxFreq = fmax
        # The peaks the chart marks — none while comparing — as Swift's view reads tap.chartPeaks.
        chart_peaks = self.analyzer.chart_peaks
        if chart_peaks is not None:
            self.analyzer.peaksChanged.emit(chart_peaks)
        self.freqRangeChanged.emit(fmin, fmax)

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
        loc = getattr(m, "measurement_name", None)
        if loc:
            return loc
        from guitar_tap.utilities.date_format import format_display_datetime_compact
        return format_display_datetime_compact(getattr(m, "timestamp", ""))

    def load_comparison(self, measurements: list) -> None:
        """Load guitar measurements as comparison overlays.

        Delegates analysis to the analyzer, then creates PlotDataItem view curves.
        """
        # Remove only the canvas curves — do NOT call analyzer.clear_comparison() here,
        # because it emits comparisonChanged(False).  The model's load_comparison() resets
        # showing_multi_tap_comparison and tap_entries directly (mirroring Swift),
        # then emits a single coherent comparisonChanged(True).
        self._clear_comparison_curves()

        # Delegate to analyzer — resets multi-tap state, populates _comparison_data /
        # comparison_labels, and emits comparisonChanged(True).
        # Mirrors Swift loadComparison(measurements:).
        #
        # _on_comparison_changed_from_analyzer fires during this call; it detects that
        # _comparison_curves is empty and calls _render_comparison_curves() there.
        # We must NOT call _render_comparison_curves() again after this returns, or
        # we get duplicate curves.
        self.analyzer.load_comparison(measurements)

    def _render_comparison_curves(self) -> None:
        """Create PlotDataItem curves and legend from analyzer._comparison_data.

        Called both by load_comparison() (live path) and by
        _on_comparison_changed_from_analyzer() when curves are absent (restore path).
        Assumes _comparison_curves is empty; callers must call _clear_comparison_curves()
        first if needed.
        """
        for entry in self.analyzer._comparison_data:
            label    = entry["label"]
            color    = entry.get("role", entry["color"])
            freq_arr = entry["freqs"]
            mag_arr  = entry["mags"]
            curve = pg.PlotDataItem(
                freq_arr, mag_arr,
                pen=chart_style.pen(self._curve_rgb(color), chart_style.SCREEN.overlay_width),
                name=label, antialias=True,
            )
            self.addItem(curve)
            self._comparison_curves.append(curve)
            self._comparison_curve_colors.append(color)

        if self._comparison_curves:
            self._build_comparison_legend(
                [entry["label"] for entry in self.analyzer._comparison_data], font_size=10)

        # Clear the main spectrum line — only comparison curves should be visible.
        self.fft_line.setData([], [])
        self.points.setData(x=[], y=[])

        self._locked_series_index = 0

    def _clear_comparison_curves(self) -> None:
        """Remove canvas-side comparison curves and legend without touching model state.

        Used by load_comparison() so it can clear old curves without emitting
        comparisonChanged(False) — the model's load_comparison() resets its own
        state and emits a single comparisonChanged(True).
        """
        self._locked_series_index = 0
        for curve in self._comparison_curves:
            self.removeItem(curve)
        self._comparison_curves.clear()
        self._comparison_curve_colors.clear()
        if self._comparison_legend is not None:
            self._comparison_legend.deleteLater()
            self._comparison_legend = None

    def _on_comparison_changed_from_analyzer(self, is_comparing: bool) -> None:
        """React to comparison mode entering or leaving.

        Applies visibility of peaks and threshold lines (mirrors the isComparing
        checks in TapToneAnalysisView+SpectrumViews.swift), applies the
        axis ranges from the comparison data when entering comparison mode, and
        removes the comparison curves when leaving it.

        Also relays the signal outward so external observers can react.
        """
        # The dots show when the analyzer gives the chart peaks (none while comparing), as Swift's
        # tap.chartPeaks.
        showing = self.analyzer.chart_peaks is not None
        self.points.setVisible(showing)
        self.selected_point.setVisible(showing)
        # Peak threshold line is guitar-only; hide during comparison regardless.
        self.line_threshold.setVisible(showing and self.analyzer._measurement_type.is_guitar)
        shown = self._mode_bands_shown(self.analyzer._measurement_type.is_guitar)
        for item in self._mode_band_items:
            item.setVisible(shown)
        # Tap-trigger / Reset lines no longer exist (the threshold is now
        # an RMS-domain trigger displayed on the ThresholdSlider widget;
        # rendering it on the FFT chart was misleading).

        if is_comparing:
            # On the restore path (loading a saved comparison record), the analyzer
            # has populated _comparison_data but the canvas may have stale curves
            # from a previous multi-tap comparison.  Clear stale curves first,
            # then render the new comparison curves.
            if self.analyzer._comparison_data:
                if self._comparison_curves:
                    self._clear_comparison_curves()
                self._render_comparison_curves()
            # Axis bounds are applied by _on_loaded_axis_range_changed, which fires
            # before this handler because set_loaded_axis_range() emits
            # loadedAxisRangeChanged before the model emits comparisonChanged.
        else:
            self._clear_comparison_curves()

        self.comparisonChanged.emit(is_comparing)

    def _on_loaded_axis_range_changed(
        self, min_freq: float, max_freq: float, min_db: float, max_db: float
    ) -> None:
        """Apply all four axis bounds emitted by the model's set_loaded_axis_range().

        Mirrors Swift TapToneAnalysisView's .onReceive(tap.$loadedAxisRange) handler
        which sets minFreq/maxFreq/minDB/maxDB view-state in one pass.  Keeping the
        union computation in the model and the application here in the canvas means
        the canvas never needs to reach back into model internals (comparison_snapshots)
        to derive axis bounds — the model is the single source of truth.
        """
        self.update_axis(min_freq, max_freq)
        self.setYRange(min_db, max_db, padding=0)
        self._loaded_chart_range = self.chart_range()

    # ── The chart's range ─────────────────────────────────────────────────────

    def chart_range(self):
        """The chart's current four bounds. Mirrors Swift TapToneAnalysisView.chartRange."""
        from guitar_tap.models.display_range import ChartRange
        db_min, db_max = (float(v) for v in self.getPlotItem().vb.viewRange()[1])
        return ChartRange(self._minFreq, self._maxFreq, db_min, db_max)

    @staticmethod
    def saved_chart_range(meas_type=None):
        """The saved view for *meas_type* (the current measurement type by default). Mirrors Swift
        savedChartRange."""
        from guitar_tap.models.display_range import ChartRange
        from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS
        t = meas_type if meas_type is not None else TDS.measurement_type()
        return ChartRange(TDS.min_frequency_for(t), TDS.max_frequency_for(t),
                          TDS.min_magnitude(), TDS.max_magnitude())

    def apply_chart_range(self, r) -> None:
        """Set all four bounds."""
        self._apply_axis_range(r.min_freq, r.max_freq, r.min_db, r.max_db)

    def widen_onto(self, lo: float, hi: float) -> None:
        """Widen the frequency axis onto an identified plate / brace peak, remembering the widened
        range as the loaded one if the chart was showing a load. Mirrors Swift
        expandFreqRangeToInclude."""
        from guitar_tap.models.display_range import loaded_after_widening
        before = self.chart_range()
        self.update_axis(lo, hi)
        self._loaded_chart_range = loaded_after_widening(self._loaded_chart_range, before,
                                                         self.chart_range())

    def apply_new_measurement_range(self) -> None:
        """A new measurement started (New Tap, Play File): apply ``on_new_measurement``. Mirrors
        Swift applyNewMeasurementRange."""
        from guitar_tap.models.display_range import on_new_measurement
        r = on_new_measurement(self.chart_range(), self._loaded_chart_range, self.saved_chart_range())
        if r is not None:
            self.apply_chart_range(r)
        self._loaded_chart_range = None

    def set_measurement_complete(self, is_measurement_complete: bool) -> None:
        """Update canvas-side UI for frozen/live state.

        Called by the view in response to the measurementComplete signal from the
        model.  Does NOT call analyzer.set_measurement_complete — the model is the
        source of truth and already emitted the signal that triggered this call.
        """
        if not is_measurement_complete:
            self.selected_point.setData(x=[], y=[])
            # clear_comparison was already called by analyzer.set_measurement_complete
            # but we need to clear the view curves too
            self._clear_comparison_view()
            # A new measurement started: the chart returns to the saved view after a load the user
            # has not moved, and otherwise stays where it is.
            self.apply_new_measurement_range()

    def _clear_comparison_view(self) -> None:
        """Remove comparison view curves (called when returning to live mode)."""
        self._locked_series_index = 0
        for curve in self._comparison_curves:
            self.removeItem(curve)
        self._comparison_curves.clear()
        self._comparison_curve_colors.clear()
        self._has_material_spectra = False
        if self._comparison_legend is not None:
            self._comparison_legend.deleteLater()
            self._comparison_legend = None

    def load_material_spectra(
        self,
        spectra: "list[tuple[str, palette.Role, list, list]]",
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

        for label, role, freq_list, mag_list in spectra:
            freq_arr = np.array(freq_list, dtype=np.float64)
            mag_arr  = np.array(mag_list,  dtype=np.float64)
            curve = pg.PlotDataItem(
                freq_arr, mag_arr,
                pen=chart_style.pen(palette.rgb(role), chart_style.SCREEN.overlay_width),
                name=label, antialias=True,
            )
            self.addItem(curve)
            self._comparison_curves.append(curve)
            self._comparison_curve_colors.append(role)

        self._build_comparison_legend([label for label, _role, _f, _m in spectra], font_size=10)

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
        self.analyzer.peak_min_threshold = float(threshold - 100)

        # The projection updated when peak_min_threshold was assigned at the top of this method
        # (property setter, mirroring Swift peakMinThreshold.didSet). peaks_above_peak_min is a plain
        # attr, not @Published, so the view must be told explicitly. Safe here: display-only,
        # all other state already set (unlike the capture path).
        self.analyzer.peaksChanged.emit(list(
            self.analyzer.peaks_above_peak_min if _tds.measurement_type().is_guitar
            else self.analyzer.material_identified_peaks
        ))
        self.show_peak_min(self.analyzer.peak_min_threshold)

    def show_peak_min(self, db: float) -> None:
        """Show a Peak Min on the chart — the dashed line and its label. Writes no state: after a load
        the model already holds the measurement's Peak Min, and this only brings the chart up to it."""
        self.threshold_x = self.analyzer.mic.rate // 2
        self.threshold_y = int(round(db))

        self.line_threshold.setPos(self.threshold_y)
        self.line_threshold.label.setText(f"Peak: {self.threshold_y} dB")

    def _peak_brushes(self, freqs) -> list:
        """Return a list of QBrush objects, one per peak, coloured by mode."""
        brushes = []
        for f in freqs:
            r, g, b = self._mode_color_map.get(float(f), palette.rgb(palette.Role.MODE_UNKNOWN))
            brushes.append(pg.mkBrush(r, g, b))
        return brushes

    def update_mode_colors(self, color_map: dict) -> None:
        """Update the per-peak mode colour map and redraw scatter points."""
        self._mode_color_map = color_map
        if self._all_peaks_in_range:
            freqs = [p.frequency for p in self._all_peaks_in_range]
            mags  = [p.magnitude for p in self._all_peaks_in_range]
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

        The dot set is the shared rule GuitarMode.peaks_in_display_range() -- visible
        frequency range, then the unknown-mode filter for guitar -- so Swift, Python and the
        web share one testable definition (@parity view/dot-layer).  It is deliberately
        annotation-INDEPENDENT: visible_peaks (the badges) narrows by ALL/SELECTED/NONE, the
        dots never do.

        The range used is the canvas viewport (_minFreq/_maxFreq), which follows pan and
        zoom -- _refresh_peaks_for_viewport re-emits peaksChanged on sigXRangeChanged, so
        this handler re-runs and the dots track the visible window.  Previously no range
        filter was applied here at all and pyqtgraph merely clipped the drawing, which left
        out-of-range peaks in _all_peaks_in_range (the click hit-test set) unlike Swift.
        """
        if peaks:
            mt = _as.AppSettings.measurement_type()
            guitar_type_str = _as.AppSettings.guitar_type()
            try:
                guitar_type = gt.GuitarType(guitar_type_str)
            except ValueError:
                guitar_type = gt.GuitarType.GENERIC
            peaks = gm.GuitarMode.peaks_in_display_range(
                peaks,
                self._minFreq,
                self._maxFreq,
                mt.is_guitar,
                _as.AppSettings.show_unknown_modes(),
                self.analyzer.overridden_peak_ids,
                guitar_type,
            )
            # _all_peaks_in_range MUST stay index-aligned with the setData arrays below --
            # point_picked() maps a clicked scatter index back through it.
            self._all_peaks_in_range = peaks
            freqs = [p.frequency for p in peaks]
            mags  = [p.magnitude for p in peaks]
            self.points.setData(x=freqs, y=mags, brush=self._peak_brushes(freqs))
        else:
            self._all_peaks_in_range = []
            self.points.setData(x=[], y=[])
        self._draw_highlight()

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

    # ── find_peaks: thin wrapper that delegates to analyzer ───────────────────

    def find_peaks(self, mag_y_db):
        """Delegate peak finding to the analyzer.

        Returns (triggered, peaks) for call sites that need the return value.
        The analyzer emits peaksChanged, which is forwarded to FftCanvas.peaksChanged.
        """
        return self.analyzer.find_peaks(mag_y_db, list(self.analyzer.freq))

    # -{66} #
    # Spectrum handler (TapToneAnalyzer.spectrumUpdated)
    # -{66} #

    def _on_live_frame(self) -> None:
        """A frame announced on the engine's live frame: draw the spectrum the chart shows with it — nothing
        while a device change settles, the frozen spectrum once the measurement is complete, the live one
        otherwise; in comparison only the overlays. Mirrors Swift's FrameReader around the chart, with
        displaySpectrum(live:)."""
        analyzer = self.analyzer
        if analyzer.is_settling:
            self.set_draw_data(np.array([]), freqs=np.array([]))
        elif analyzer.display_mode == AnalysisDisplayMode.LIVE:
            if analyzer.is_measurement_complete:
                self.set_draw_data(analyzer.frozen_magnitudes, freqs=analyzer.frozen_frequencies)
            else:
                self.set_draw_data(analyzer.mic.frame.magnitudes, freqs=analyzer.freq)

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

