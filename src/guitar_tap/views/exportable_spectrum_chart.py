"""
exportable_spectrum_chart.py  —  Python port of ExportableSpectrumChart.swift

# ExportableSpectrumChart

A stripped-down, static spectrum chart suitable for off-screen rendering
with pyqtgraph + QPainter (replacing Swift's ImageRenderer).

## Why a Separate Class?

SpectrumView uses live pyqtgraph signals, hover effects, and scroll-wheel
handlers that prevent reliable off-screen capture.  ExportableSpectrumChart
reproduces the same visual appearance using only a static PlotWidget so the
renderer can produce a pixel-accurate PNG without interactive side effects —
exactly as the Swift struct removes AppKit NSEvent monitors and gesture
recognizers.

## Supported Overlay Layers

1. **Spectrum line** — primary (red) or per-phase colored series
2. **Mode boundaries** — dashed vertical InfiniteLine items in mode colors
3. **Peak annotations** — cards + dashed connection lines drawn with QPainter,
   positions from annotation_positions in absolute data-space (replacing ConnectionLineShape)

## Peak Coloring

- Guitar mode: peaks colored by GuitarMode (air=cyan, top=green, etc.)
- Plate/brace mode: L=blue, C=orange, FLC=purple, unselected=secondary

## Connection Lines

Because ConnectionLineShape (a Shape-conforming type) has no direct PySide6
equivalent inside a composited image, connection lines are drawn with
QPainter.drawLine() directly onto the captured chart QImage, which renders
correctly in all contexts.

## Structure mirrors the Swift file section-for-section:

  Swift                                    Python
  ───────────────────────────────────────  ──────────────────────────────────────
  // MARK: - Connection Line Shape         (not needed — QPainter.drawLine used)
  struct ExportableSpectrumChart: View     class ExportableSpectrumChart
    var chartData                            .chart_data (property)
    var visibleModeBoundaries                .visible_mode_boundaries (property)
    var visiblePeaks                         .visible_peaks (property)
    var frequencyAxisValues                  (handled by pyqtgraph automatically)
    var peakModeMap                          .peak_mode_map (property)
    func peakColor(for:)                     .peak_color(peak, idx)
    func peakModeLabel(for:)                 .peak_mode_label(peak, idx)
    func isStartOfModeRange(_:for:)          .is_start_of_mode_range(freq, mode)
    func seriesData(frequencies:magnitudes:) .series_data(frequencies, magnitudes)
    var body: some View                      .render() -> QImage
  // MARK: - Shared Export View Builder     # MARK: - Shared Export View Builder
  func makeExportableSpectrumView(...)      def make_exportable_spectrum_view(...)

Callers of make_exportable_spectrum_view mirror the Swift callers of
makeExportableSpectrumView:
  PDFReportGenerator.swift        → tap_analysis_results_view.py
  TapToneAnalysisView+Export.swift → tap_tone_analysis_view.py

- SeeAlso: tap_analysis_results_view.py, tap_tone_analysis_view.py
"""

from __future__ import annotations

from models.annotation_visibility_mode import AnnotationVisibilityMode

__all__ = [
    "ExportableSpectrumChart",
    "make_exportable_spectrum_view",
]


# MARK: - Static Export Spectrum View

class ExportableSpectrumChart:
    """Python port of ``ExportableSpectrumChart`` in ExportableSpectrumChart.swift.

    A simplified, static version of SpectrumView designed for off-screen
    rendering.  Removes all interactive elements (gestures, hover effects,
    scroll-wheel handlers, context menus) that prevent reliable off-screen
    capture — exactly as the Swift struct removes AppKit NSEvent monitors and
    gesture recognizers.

    Properties mirror the Swift stored/computed properties.
    ``render()`` corresponds to ``var body: some View``.
    """

    # ── Stored properties (mirrors Swift stored vars) ─────────────────────────

    def __init__(
        self,
        *,
        frequencies: list,           # Raw frequency bins (Hz) from the FFT output.
        magnitudes: list,            # Magnitude values (dBFS) corresponding to each frequency bin.
        min_freq: float,             # Minimum frequency (Hz) of the visible chart range.
        max_freq: float,             # Maximum frequency (Hz) of the visible chart range.
        min_db: float,               # Minimum magnitude (dBFS) of the visible chart range.
        max_db: float,               # Maximum magnitude (dBFS) of the visible chart range.
        is_logarithmic: bool = False,           # When True, the frequency axis uses a logarithmic scale.
        peaks: list | None = None,              # Peaks to annotate. Pass None to suppress all peak annotations.
        show_mode_boundaries: bool = True,      # Whether to draw guitar mode boundary lines.
        # Absolute label-center positions in data-space ({uuid: [abs_freq_hz, abs_db]}).
        # Mirrors Swift annotationOffsets: [UUID: CGPoint] where x=absFreqHz, y=absDB.
        # When absent for a peak, the default (ANNOT_OFFS_Y px above peak) is used.
        annotation_positions: dict | None = None,
        show_unknown_modes: bool | None = None, # Override for TapDisplaySettings.showUnknownModes. None = use default.
        measurement_type_str: str | None = None,              # Measurement type string: controls colour coding and boundary visibility.
        selected_longitudinal_peak_id: str | None = None,     # ID of the peak selected as the longitudinal (L) mode.
        selected_cross_peak_id: str | None = None,            # ID of the peak selected as the cross-grain (C) mode.
        selected_flc_peak_id: str | None = None,              # ID of the peak selected as the FLC (diagonal) mode.
        mode_overrides: dict | None = None,     # Per-peak user-assigned mode overrides. Empty = all peaks use auto classification.
        peak_modes: dict | None = None,         # Pre-computed context-aware mode assignments, keyed by peak id.
        material_spectra: list | None = None,   # Per-phase spectra overlay for plate/brace measurements.
        chart_title: str = "FFT Peaks",         # Title shown above the chart. Mirrors Swift ``var chartTitle``.
        guitar_type_str: str | None = None,     # Guitar body type string, used for mode classification.
    ):
        self.frequencies = frequencies
        self.magnitudes = magnitudes
        self.min_freq = min_freq
        self.max_freq = max_freq
        self.min_db = min_db
        self.max_db = max_db
        self.is_logarithmic = is_logarithmic
        self.peaks = peaks or []
        self.show_mode_boundaries = show_mode_boundaries
        self.annotation_positions = annotation_positions or {}
        self.show_unknown_modes = show_unknown_modes
        self.measurement_type_str = measurement_type_str
        self.selected_longitudinal_peak_id = selected_longitudinal_peak_id
        self.selected_cross_peak_id = selected_cross_peak_id
        self.selected_flc_peak_id = selected_flc_peak_id
        self.mode_overrides = mode_overrides or {}
        self._peak_modes_override = peak_modes or {}
        self.material_spectra = material_spectra or []
        self.chart_title = chart_title
        self.guitar_type_str = guitar_type_str

        # Resolve is_guitar and guitar_type from measurement_type_str —
        # mirrors Swift where MeasurementType carries both is_guitar and guitarType
        # as computed properties, so a single measurementType parameter implicitly
        # provides both pieces of information.
        self.is_guitar = True
        _derived_guitar_type_str: str | None = guitar_type_str
        if measurement_type_str:
            try:
                from models import measurement_type as _mt_mod
                _mt_enum = _mt_mod.MeasurementType(measurement_type_str)
                self.is_guitar = _mt_enum.is_guitar
                # Derive guitar_type from measurement_type when not explicitly provided,
                # matching Swift's implicit derivation via MeasurementType.guitarType.
                if _derived_guitar_type_str is None and _mt_enum.guitar_type is not None:
                    _derived_guitar_type_str = _mt_enum.guitar_type.value
            except Exception:
                pass

        # Build mode_map — mirrors peakModeMap computed property.
        # classify_all() accepts ResonantPeak objects and returns {peak.id: GuitarMode},
        # matching Swift's [UUID: GuitarMode] exactly.  No index-to-id translation needed.
        try:
            from models.guitar_mode import GuitarMode
            from models.guitar_type import GuitarType
            self._GuitarMode = GuitarMode
            gt_enum = GuitarType(_derived_guitar_type_str) if _derived_guitar_type_str else GuitarType.CLASSICAL
            self._guitar_type_enum = gt_enum
            if self.is_guitar:
                # Pass all peaks (not just visible) so the claiming algorithm has the
                # full context — mirrors Swift peakModeMap which calls classifyAll on
                # the full peaks array, not the filtered visiblePeaks subset.
                self._mode_map = GuitarMode.classify_all(self.peaks, gt_enum)
            else:
                self._mode_map = {}
        except Exception:
            self._GuitarMode = None
            self._mode_map = {}
            self._guitar_type_enum = None

    # ── Computed properties (mirrors Swift private computed vars) ─────────────

    @property
    def chart_data(self) -> list:
        """Mirrors ``private var chartData: [SpectrumDataPoint]``."""
        return [
            (f, m) for f, m in zip(self.frequencies, self.magnitudes)
            if self.min_freq <= f <= self.max_freq
        ]

    @property
    def visible_mode_boundaries(self) -> list:
        """Mirrors ``private var visibleModeBoundaries``."""
        if not self.is_guitar:
            return []
        GuitarMode = self._GuitarMode
        if GuitarMode is None:
            return []
        try:
            gt = self._guitar_type_enum
            ranges = gt.mode_ranges
            all_bounds = [
                (ranges.air[0],       GuitarMode.AIR),
                (ranges.air[1],       GuitarMode.AIR),
                (ranges.top[0],       GuitarMode.TOP),
                (ranges.top[1],       GuitarMode.TOP),
                (ranges.back[0],      GuitarMode.BACK),
                (ranges.back[1],      GuitarMode.BACK),
                (ranges.dipole[0],    GuitarMode.DIPOLE),
                (ranges.dipole[1],    GuitarMode.DIPOLE),
                (ranges.ring_mode[0], GuitarMode.RING_MODE),
                (ranges.ring_mode[1], GuitarMode.RING_MODE),
            ]
            return [(f, m) for f, m in all_bounds if self.min_freq <= f <= self.max_freq]
        except Exception:
            return []

    @property
    def visible_peaks(self) -> list:
        """Mirrors ``private var visiblePeaks: [ResonantPeak]``."""
        filtered = [p for p in self.peaks if self.min_freq <= p.frequency <= self.max_freq]
        if not self.is_guitar:
            return filtered
        # show_unknown_modes mirrors showUnknownModes ?? TapDisplaySettings.showUnknownModes
        show_unknown = self.show_unknown_modes
        if show_unknown is None:
            show_unknown = True   # default — mirrors TapDisplaySettings default
        if show_unknown:
            return filtered
        GuitarMode = self._GuitarMode
        if GuitarMode is None:
            return filtered
        return [p for p in filtered if GuitarMode.is_known(p.frequency)]

    @property
    def peak_mode_map(self) -> dict:
        """Mirrors ``private var peakModeMap: [UUID: GuitarMode]``.

        Prefers the pre-computed map from the caller (peakModes parameter);
        falls back to classifying from visible_peaks when empty.
        """
        if self._peak_modes_override:
            return self._peak_modes_override
        return self._mode_map

    def peak_color(self, peak, idx: int):
        """Mirrors ``private func peakColor(for peak: ResonantPeak) -> Color``."""
        from PySide6 import QtGui
        if self.is_guitar:
            # _mode_map is {peak.id: GuitarMode} — mirrors Swift [UUID: GuitarMode].
            mode = self._mode_map.get(getattr(peak, "id", None))
            if mode is not None and self._GuitarMode is not None:
                r, g, b = mode.color
                return QtGui.QColor(r, g, b)
        else:
            if peak.id == self.selected_longitudinal_peak_id:
                return QtGui.QColor(0, 100, 200)
            if peak.id == self.selected_cross_peak_id:
                return QtGui.QColor(220, 120, 40)
            if peak.id == self.selected_flc_peak_id:
                return QtGui.QColor(130, 60, 200)
        return QtGui.QColor(130, 130, 130)

    def peak_mode_label(self, peak, idx: int) -> str:
        """Mirrors ``private func peakModeLabel(for peak: ResonantPeak) -> String``."""
        override = self.mode_overrides.get(getattr(peak, "id", None))
        if override:
            return override
        if self.is_guitar:
            # _mode_map is {peak.id: GuitarMode} — mirrors Swift [UUID: GuitarMode].
            mode = self._mode_map.get(getattr(peak, "id", None))
            if mode is not None and self._GuitarMode is not None:
                return mode.display_name
            return getattr(peak, "mode_label", None) or "Unknown"
        else:
            if peak.id == self.selected_longitudinal_peak_id:
                return "Longitudinal"
            if peak.id == self.selected_cross_peak_id:
                return "Cross-grain"
            if peak.id == self.selected_flc_peak_id:
                return "FLC"
            return "Peak"

    def is_start_of_mode_range(self, frequency: float, mode) -> bool:
        """Mirrors ``private func isStartOfModeRange(_:for:) -> Bool``."""
        try:
            lo, _ = mode.mode_range(self._guitar_type_enum)
            return abs(frequency - lo) < 0.1
        except Exception:
            return False

    def series_data(self, frequencies: list, magnitudes: list) -> list:
        """Mirrors ``private func seriesData(frequencies:magnitudes:)``."""
        return [
            (f, m) for f, m in zip(frequencies, magnitudes)
            if self.min_freq <= f <= self.max_freq
        ]

    def annotation_position(
        self,
        peak,
        peak_position: tuple[float, float],
        freq_to_x,
        db_to_y,
        default_offset_y: int,
    ) -> tuple[float, float]:
        """Compute annotation center in pixel-space for *peak*.

        Mirrors ``private func annotationPosition(for:peakPosition:frame:)``
        in ExportableSpectrumChart.swift.

        Returns the pixel coordinate for the annotation card center.
        When ``annotation_positions`` has no entry for the peak, the default
        position (``default_offset_y`` px above the peak marker) is returned.

        Args:
            peak:             ResonantPeak whose position is being resolved.
            peak_position:    (px, py) pixel coords of the peak dot.
            freq_to_x:        Callable mapping a frequency (Hz) to a pixel x.
            db_to_y:          Callable mapping a magnitude (dB) to a pixel y.
            default_offset_y: Pixels above the peak dot for the default position.
        """
        peak_id = getattr(peak, "id", None)
        abs_pos = self.annotation_positions.get(peak_id)
        if abs_pos is not None:
            return (freq_to_x(float(abs_pos[0])), db_to_y(float(abs_pos[1])))
        px, py = peak_position
        return (px, py - default_offset_y)

    def render(self) -> "QImage":
        """Mirrors ``var body: some View`` — renders the chart to a QImage.

        Step 1: Build a pyqtgraph PlotWidget (replaces SwiftUI Charts Chart{})
        Step 2: Overlay peak annotation cards with QPainter (replaces chartOverlay)
        Returns a QImage sized CHART_W × CHART_H at SCALE=2.
        """
        import pyqtgraph as pg
        from pyqtgraph.exporters import ImageExporter
        from PySide6 import QtCore, QtGui, QtWidgets

        if QtWidgets.QApplication.instance() is None:
            QtWidgets.QApplication([])

        # Layout constants — mirrors .frame(width: 1400, height: 800) at ImageRenderer(scale: 2.0)
        SCALE    = 2
        CHART_W  = 1400 * SCALE   # final PNG pixel width
        CHART_H  = 800  * SCALE   # final PNG pixel height
        # Widget size at 1x: pyqtgraph scene coordinates are in logical (1x) pixels.
        # We set the widget to exactly 1400×800 so scene-space insets are integers
        # and png_scale = CHART_W / widget_w = exactly 2.0 — no floating-point drift.
        WIDGET_W = 1400
        WIDGET_H = 800

        # ── Chart (mirrors Chart { } block) ───────────────────────────────────
        # No setTitle() — title is painted by the caller above the chart image,
        # matching the Swift VStack layout in ExportableSpectrumChart.body /
        # makeExportableSpectrumView where Text(chartTitle) sits above the Chart.
        # setFixedSize ensures the off-screen widget has the exact pixel dimensions;
        # resize() alone does not take effect on an unshown widget.
        plot = pg.PlotWidget()
        plot.setFixedSize(WIDGET_W, WIDGET_H)
        plot.setBackground("w")
        plot.setLabel("bottom", "Frequency (Hz)")    # mirrors chartXAxisLabel
        plot.setLabel("left",   "FFT Magnitude (dB)")  # mirrors chartYAxisLabel

        # Show all four borders — mirrors .chartPlotStyle { plotArea in plotArea.border(Color.gray, width:1) }
        pi_setup = plot.getPlotItem()
        pi_setup.showAxis("top")
        pi_setup.showAxis("right")
        pi_setup.getAxis("top").setStyle(showValues=False)
        pi_setup.getAxis("right").setStyle(showValues=False)
        pi_setup.getAxis("top").setPen(pg.mkPen((180, 180, 180), width=1))
        pi_setup.getAxis("right").setPen(pg.mkPen((180, 180, 180), width=1))
        pi_setup.getAxis("bottom").setPen(pg.mkPen((180, 180, 180), width=1))
        pi_setup.getAxis("left").setPen(pg.mkPen((180, 180, 180), width=1))

        # Grid lines — mirrors the live canvas: self.showGrid(x=True, y=True, alpha=0.15).
        plot.showGrid(x=True, y=True, alpha=0.15)

        if self.material_spectra:
            # Mirrors: ForEach(materialSpectra) { LineMark.foregroundStyle(by: .value("Series", series.label)) }
            # Each series carries its own color — use it directly rather than a positional palette.
            # Color strings "blue"/"orange"/"purple" match Swift's .blue/.orange/.purple system colors.
            _COLOR_MAP = {
                "blue":   (  0, 122, 255),   # Swift .blue  (iOS/macOS system blue)
                "orange": (255, 149,   0),   # Swift .orange
                "purple": (175,  82, 222),   # Swift .purple
                "red":    (255,  59,  48),   # Swift .red
                "green":  ( 52, 199,  89),   # Swift .green
            }
            for series in self.material_spectra:
                sf = series.get("frequencies", [])
                sm = series.get("magnitudes", [])
                if sf and sm:
                    sc = [max(self.min_db, min(self.max_db, v)) for v in sm]
                    color_key = series.get("color", "blue")
                    # color may be an (r,g,b) tuple (comparison path) or a string (plate/brace path)
                    rgb = color_key if isinstance(color_key, tuple) else _COLOR_MAP.get(color_key, (0, 122, 255))
                    plot.plot(sf, sc, pen=pg.mkPen(rgb, width=2))
        else:
            # Mirrors: LineMark(...).foregroundStyle(.red)
            clamped = [max(self.min_db, min(self.max_db, v)) for v in self.magnitudes]
            plot.plot(self.frequencies, clamped, pen=pg.mkPen((210, 50, 50), width=2))

        # Mirrors: if showModeBoundaries { ForEach(visibleModeBoundaries) { RuleMark } }
        # visibleModeBoundaries already returns [] when not is_guitar, but also gate here
        # to match Swift's guard measurementType.isGuitar else { return [] }.
        if self.show_mode_boundaries and self.is_guitar and not self.material_spectra:
            for freq_b, mode_b in self.visible_mode_boundaries:
                r, g, b = mode_b.color
                pen_b = pg.mkPen(
                    QtGui.QColor(r, g, b, 80), width=2,
                    style=QtCore.Qt.PenStyle.DashLine,
                )
                plot.addItem(pg.InfiniteLine(pos=freq_b, angle=90, pen=pen_b))

        # Mirrors: ForEach(visiblePeaks) { PointMark(...).foregroundStyle(peakColor(for:)) }
        for idx, peak in enumerate(self.visible_peaks):
            color = self.peak_color(peak, idx)
            plot.plot(
                [peak.frequency], [peak.magnitude],
                pen=None, symbol="o", symbolSize=10,
                symbolBrush=pg.mkBrush(color.red(), color.green(), color.blue()),
                symbolPen=None,
            )

        # Lock axis ranges before layout/export.
        # disableAutoRange() must be called before grab() so the layout pass uses
        # our range, not the data's natural extent.
        # Mirrors .chartXScale(domain:) / .chartYScale(domain:) in Swift.
        vb_setup = plot.getPlotItem().getViewBox()
        vb_setup.disableAutoRange()
        vb_setup.setRange(
            xRange=(self.min_freq, self.max_freq),
            yRange=(self.min_db, self.max_db),
            padding=0,
        )

        # Force a layout pass at WIDGET_W × WIDGET_H and re-apply the range.
        # First grab() commits the widget geometry (1400×800).
        # pyqtgraph may re-enable autorange during the layout pass, so we
        # disable it and re-set the range a second time, then grab() again
        # to commit the final scene geometry used by sceneBoundingRect().
        plot.grab()
        vb_setup.disableAutoRange()
        vb_setup.setRange(
            xRange=(self.min_freq, self.max_freq),
            yRange=(self.min_db, self.max_db),
            padding=0,
        )
        plot.grab()

        # Capture chart → QImage (replaces ImageRenderer).
        # Export at CHART_W (2800px) from a WIDGET_W (1400px) scene — scale factor = 2.0 exactly.
        # This matches Swift's ImageRenderer(scale: 2.0) which renders a 1400pt view at 2x.
        import tempfile, os as _os
        chart_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        chart_tmp.close()
        exporter = ImageExporter(plot.getPlotItem())
        exporter.parameters()["width"] = CHART_W
        exporter.export(chart_tmp.name)
        chart_img = QtGui.QImage(chart_tmp.name)
        try:
            _os.remove(chart_tmp.name)
        except OSError:
            pass

        # ── Peak annotation overlay (mirrors chartOverlay { proxy in GeometryReader { … } }) ──
        # QPainter draws directly onto the chart image.
        # After grab(), sceneBoundingRect() is based on the committed 1400×800 layout.
        # png_scale = CHART_W / pi_rect.width() = 2800 / 1400 = 2.0 exactly.
        pi = plot.getPlotItem()
        vb = pi.getViewBox()
        pi_rect = pi.sceneBoundingRect()    # PlotItem scene rect in logical pixels
        vb_rect = vb.sceneBoundingRect()    # ViewBox scene rect in logical pixels

        # png_scale = 2.0 when WIDGET_W=1400 and CHART_W=2800
        png_scale = CHART_W / pi_rect.width() if pi_rect.width() > 0 else float(SCALE)

        AXIS_LEFT   = int((vb_rect.left()   - pi_rect.left())   * png_scale)
        AXIS_TOP    = int((vb_rect.top()    - pi_rect.top())    * png_scale)
        AXIS_RIGHT  = int((pi_rect.right()  - vb_rect.right())  * png_scale)
        AXIS_BOTTOM = int((pi_rect.bottom() - vb_rect.bottom()) * png_scale)
        PLOT_W = CHART_W - AXIS_LEFT - AXIS_RIGHT
        PLOT_H = CHART_H - AXIS_TOP  - AXIS_BOTTOM

        def _freq_to_x(freq: float) -> int:
            frac = (freq - self.min_freq) / max(self.max_freq - self.min_freq, 1e-6)
            return AXIS_LEFT + int(frac * PLOT_W)

        def _db_to_y(db: float) -> int:
            frac = 1.0 - (db - self.min_db) / max(self.max_db - self.min_db, 1e-6)
            return AXIS_TOP + int(frac * PLOT_H)

        # Card geometry — mirrors Swift VStack annotation at annotationY = peakY - 70.
        # All pixel dimensions AND font sizes scale with SCALE.  setPixelSize() sets
        # the font height in device pixels directly, so * SCALE produces the correct
        # apparent size on the 2x canvas — matching Swift's ImageRenderer(scale: 2.0).
        # Card height: mode(28) + pitch(24, guitar only) + freq(24) + db(20) + padding = ~120 with pitch, ~96 without
        ANNOT_W      = int(160 * SCALE)
        ANNOT_H_PITCH   = int(120 * SCALE)   # with pitch note row (guitar mode)
        ANNOT_H_NOPITCH = int(96  * SCALE)   # without pitch note row
        ANNOT_OFFS_Y = int(70  * SCALE)
        ANNOT_CORNER = int(10  * SCALE)

        annot_font_mode = QtGui.QFont()
        annot_font_mode.setPixelSize(16 * SCALE)  # mirrors .font(.system(size: 16, weight: .bold))
        annot_font_mode.setBold(True)

        annot_font_pitch = QtGui.QFont()
        annot_font_pitch.setPixelSize(14 * SCALE)  # mirrors .font(.system(size: 14/16, weight: .bold)) for pitch
        annot_font_pitch.setBold(True)

        annot_font_pitch_sm = QtGui.QFont()
        annot_font_pitch_sm.setPixelSize(13 * SCALE)  # mirrors .font(.system(size: 14)) for cents

        annot_font_freq = QtGui.QFont()
        annot_font_freq.setPixelSize(14 * SCALE)  # mirrors .font(.system(size: 14, weight: .medium))
        annot_font_freq.setWeight(QtGui.QFont.Weight.Medium)

        annot_font_db = QtGui.QFont()
        annot_font_db.setPixelSize(13 * SCALE)    # mirrors .font(.system(size: 13))

        painter = QtGui.QPainter(chart_img)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

        # ── Right axis border — pyqtgraph showAxis("right") doesn't reliably paint a border line.
        # Draw it directly with QPainter at x = AXIS_LEFT + PLOT_W.
        right_x = AXIS_LEFT + PLOT_W
        border_pen = QtGui.QPen(QtGui.QColor(180, 180, 180), 1)
        painter.setPen(border_pen)
        painter.drawLine(right_x, AXIS_TOP, right_x, AXIS_TOP + PLOT_H)

        # ── Mode boundary labels — mirrors RuleMark .annotation(position:.top) ──────────────────
        # Swift draws Text(mode.abbreviation) chips at the top of each boundary line.
        # We paint them directly onto the chart image at the correct x position, just below AXIS_TOP.
        # Guitar-only — mirrors Swift's guard measurementType.isGuitar else { return [] }.
        if self.show_mode_boundaries and self.is_guitar and not self.material_spectra:
            abbrev_font = QtGui.QFont()
            abbrev_font.setPixelSize(14 * SCALE)   # mirrors .font(.system(size: 14, weight: .semibold))
            abbrev_font.setBold(True)
            abbrev_fm = QtGui.QFontMetrics(abbrev_font)
            chip_pad_h = int(4 * SCALE)
            chip_pad_v = int(3 * SCALE)
            chip_y = AXIS_TOP + int(4 * SCALE)   # just inside the top border
            for freq_b, mode_b in self.visible_mode_boundaries:
                if not self.is_start_of_mode_range(freq_b, mode_b):
                    continue
                abbrev = mode_b.abbreviation
                bx = _freq_to_x(freq_b)
                r, g, b = mode_b.color
                mode_color = QtGui.QColor(r, g, b)
                text_w = abbrev_fm.horizontalAdvance(abbrev)
                chip_w = text_w + chip_pad_h * 2
                chip_h = abbrev_fm.height() + chip_pad_v * 2
                chip_x = bx - chip_w // 2
                # Background chip — mirrors .background(mode.color.opacity(0.15)).cornerRadius(6)
                bg = QtGui.QColor(r, g, b, 38)   # opacity 0.15 ≈ 38/255
                painter.setBrush(QtGui.QBrush(bg))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.drawRoundedRect(chip_x, chip_y, chip_w, chip_h, 6 * SCALE, 6 * SCALE)
                painter.setFont(abbrev_font)
                painter.setPen(mode_color)
                painter.drawText(
                    chip_x, chip_y, chip_w, chip_h,
                    QtCore.Qt.AlignmentFlag.AlignCenter, abbrev,
                )

        for idx, peak in enumerate(self.visible_peaks):
            px = _freq_to_x(peak.frequency)
            py = _db_to_y(peak.magnitude)
            color = self.peak_color(peak, idx)
            label = self.peak_mode_label(peak, idx)

            # Determine if pitch note is available for this peak (guitar mode only)
            pitch_note  = getattr(peak, "pitch_note",  None) or getattr(peak, "pitchNote",  None)
            pitch_cents = getattr(peak, "pitch_cents", None) or getattr(peak, "pitchCents", None)
            has_pitch = self.is_guitar and pitch_note is not None

            ANNOT_H = ANNOT_H_PITCH if has_pitch else ANNOT_H_NOPITCH

            # Position the annotation card — mirrors annotationPosition(for:peakPosition:frame:).
            # default_offset_y places the card center at ANNOT_OFFS_Y + ANNOT_H//2 above the peak,
            # which is equivalent to the card top edge being ANNOT_OFFS_Y + ANNOT_H above the peak.
            ann_cx, ann_cy = self.annotation_position(
                peak, (px, py), _freq_to_x, _db_to_y, ANNOT_OFFS_Y + ANNOT_H // 2
            )
            card_x = int(ann_cx) - ANNOT_W // 2
            card_y = int(ann_cy) - ANNOT_H // 2
            # Clamp inside plot area — mirrors Swift .position(x: annotationX, y: annotationY)
            card_x = max(AXIS_LEFT, min(card_x, CHART_W - AXIS_RIGHT - ANNOT_W))
            card_y = max(AXIS_TOP,  min(card_y, CHART_H - AXIS_BOTTOM - ANNOT_H))

            # Dashed connection line — mirrors ConnectionLineShape stroke
            line_pen = QtGui.QPen(QtGui.QColor(color.red(), color.green(), color.blue(), 128))
            line_pen.setWidth(int(2 * SCALE))
            line_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            painter.setPen(line_pen)
            painter.drawLine(card_x + ANNOT_W // 2, card_y + ANNOT_H, px, py)

            # Card background — mirrors ExportableSpectrumChart.swift:
            #   .background(Color.white.opacity(0.95)).cornerRadius(10)
            # Note: PeakAnnotationLabel (live view) uses .background.secondary + modeColor border,
            # but ExportableSpectrumChart (export path, both Swift and Python) uses white.
            painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255, 242)))
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 38), SCALE))
            painter.drawRoundedRect(card_x, card_y, ANNOT_W, ANNOT_H, ANNOT_CORNER, ANNOT_CORNER)

            row_y = card_y + int(4 * SCALE)

            # Mode label — mirrors Text(peakModeLabel(for:)).font(.system(size:16,weight:.bold))
            painter.setFont(annot_font_mode)
            painter.setPen(color)
            painter.drawText(
                card_x, row_y, ANNOT_W, int(28 * SCALE),
                QtCore.Qt.AlignmentFlag.AlignCenter, label,
            )
            row_y += int(28 * SCALE)

            # Pitch note + cents — mirrors HStack { Image("music.note") Text(pitchNote) Text(centsStr) }
            # Only shown for guitar measurements when pitchNote is available.
            if has_pitch:
                purple = QtGui.QColor(130, 60, 200)
                cents_val = pitch_cents if pitch_cents is not None else 0
                sign = "+" if cents_val >= 0 else ""
                cents_str = f"{sign}{int(round(cents_val))} ¢"
                pitch_str = f"♪ {pitch_note}  {cents_str}"
                painter.setFont(annot_font_pitch)
                painter.setPen(purple)
                painter.drawText(
                    card_x, row_y, ANNOT_W, int(24 * SCALE),
                    QtCore.Qt.AlignmentFlag.AlignCenter, pitch_str,
                )
                row_y += int(24 * SCALE)

            # Frequency — mirrors Text(peak.frequency.formattedAsFrequency())
            painter.setFont(annot_font_freq)
            painter.setPen(QtGui.QColor(0, 0, 0))
            painter.drawText(
                card_x, row_y, ANNOT_W, int(24 * SCALE),
                QtCore.Qt.AlignmentFlag.AlignCenter, f"{peak.frequency:.1f} Hz",
            )
            row_y += int(24 * SCALE)

            # dB — mirrors Text("…dB").foregroundColor(.secondary)
            painter.setFont(annot_font_db)
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawText(
                card_x, row_y, ANNOT_W, int(20 * SCALE),
                QtCore.Qt.AlignmentFlag.AlignCenter, f"{peak.magnitude:.1f} dB",
            )

        painter.end()
        return chart_img


# MARK: - Shared Export View Builder

def make_exportable_spectrum_view(
    *,
    frequencies: list,
    magnitudes: list,
    min_freq: float,
    max_freq: float,
    min_db: float,
    max_db: float,
    peaks: list,
    annotation_positions: dict | None = None,
    show_unknown_modes: bool | None = None,
    measurement_type_str: str | None = None,
    selected_longitudinal_peak_id: str | None = None,
    selected_cross_peak_id: str | None = None,
    selected_flc_peak_id: str | None = None,
    mode_overrides: dict | None = None,
    peak_modes: dict | None = None,
    material_spectra: list | None = None,
    date_label: str = "",
    chart_title: str = "FFT Peaks",
    guitar_type_str: str | None = None,
    software_version: str | None = None,
    platform_str: str | None = None,
) -> bytes:
    """Python port of ``func makeExportableSpectrumView(...)`` in ExportableSpectrumChart.swift.

    Builds the full spectrum export composite image — chart, header, peak
    summary, and mode legend — from explicit data parameters, and returns
    the PNG-encoded image as bytes.

    Used by both the live export path (``tap_tone_analysis_view.py``) and the
    measurement export path (``tap_analysis_results_view.py``) so that
    "Export Spectrum Image" produces an identical image regardless of whether
    it is triggered from the live analysis view or from a saved measurement.

    Mirrors the VStack layout of makeExportableSpectrumView():
      Header VStack (title + date/range/peaks count)
      Text(chartTitle)                   ← chart title, center-aligned
      ExportableSpectrumChart(...)       ← chart image via ExportableSpectrumChart.render()
      Peak summary HStack                ← Detected Peaks Summary cards
      Legend HStack                      ← Guitar Modes or Measurements

    :param frequencies: FFT frequency bins (Hz).
    :param magnitudes: FFT magnitude values (dBFS).
    :param min_freq: Minimum displayed frequency (Hz).
    :param max_freq: Maximum displayed frequency (Hz).
    :param min_db: Minimum displayed magnitude (dBFS).
    :param max_db: Maximum displayed magnitude (dBFS).
    :param peaks: Detected resonant peaks to annotate.
    :param annotation_positions: Per-peak absolute label-center positions in data-space ({uuid: [abs_freq_hz, abs_db]}), keyed by peak id.
    :param show_unknown_modes: Whether to show peaks classified as unknown guitar modes.
    :param measurement_type_str: Guitar, plate, or brace — controls colour coding and boundary visibility.
    :param selected_longitudinal_peak_id: ID of the selected longitudinal (L) peak (plate/brace).
    :param selected_cross_peak_id: ID of the selected cross-grain (C) peak (plate).
    :param selected_flc_peak_id: ID of the selected FLC peak (plate, optional).
    :param mode_overrides: Per-peak user-assigned mode label overrides.
    :param peak_modes: Pre-computed context-aware mode assignments, keyed by peak id.
    :param material_spectra: Per-phase spectrum series for plate/brace overlays.
    :param date_label: Date/time string shown in the header (e.g. formatted measurement timestamp).
    :param chart_title: Title rendered above the chart image.
    :param guitar_type_str: Guitar body type string used for mode classification.
    :param output_path: File path where the PNG will be written.
    """
    from PySide6 import QtCore, QtGui, QtWidgets

    if QtWidgets.QApplication.instance() is None:
        QtWidgets.QApplication([])

    # Layout constants — mirrors .frame(width: 1400, height: 800) + ImageRenderer(scale: 2.0).
    # SCALE multiplies pixel dimensions AND font pixel sizes (via setPixelSize).
    # setPixelSize() sets the font height in device pixels, so * SCALE produces the
    # correct apparent size on the 2x canvas — matching Swift's ImageRenderer(scale: 2.0).
    SCALE         = 2
    CHART_W       = 1400 * SCALE   # chart image width in pixels
    CHART_H       = 800  * SCALE   # chart image height in pixels
    PADDING       = 24   * SCALE   # outer padding and section gap
    # Header: title row (36px) + date/range row (28px) + metadata row (24px) + peaks row (24px) = 112px logical → *SCALE
    HEADER_H      = 112  * SCALE
    CHART_TITLE_H = 56   * SCALE   # Text(chartTitle) + .padding(.bottom, 16)
    # Summary: "Detected Peaks Summary" label (24px) + card row (68px) + bottom gap (PADDING) = 116px
    SUMMARY_H     = (116 if peaks else 0) * SCALE
    LEGEND_H      = 36   * SCALE   # legend row height
    TOTAL_W       = CHART_W + PADDING * 2
    TOTAL_H       = (HEADER_H + CHART_TITLE_H + CHART_H + PADDING
                     + SUMMARY_H + LEGEND_H + PADDING * 2)

    # Guitar mode legend entries — mirrors ForEach([.air,.top,.back,.dipole,.ringMode])
    GUITAR_MODE_DISPLAY: list[tuple[str, tuple[int, int, int]]] = [
        ("Air (Helmholtz)", (  0, 183, 235)),
        ("Top",             ( 40, 160,  40)),
        ("Back",            (220, 120,  40)),
        ("Dipole",          (210,  50,  50)),
        ("Ring Mode",       (130,  60, 200)),
    ]

    # Build ExportableSpectrumChart and render the chart image
    chart = ExportableSpectrumChart(
        frequencies=frequencies,
        magnitudes=magnitudes,
        min_freq=min_freq,
        max_freq=max_freq,
        min_db=min_db,
        max_db=max_db,
        peaks=peaks,
        show_mode_boundaries=True,
        annotation_positions=annotation_positions,
        show_unknown_modes=show_unknown_modes,
        measurement_type_str=measurement_type_str,
        selected_longitudinal_peak_id=selected_longitudinal_peak_id,
        selected_cross_peak_id=selected_cross_peak_id,
        selected_flc_peak_id=selected_flc_peak_id,
        mode_overrides=mode_overrides,
        peak_modes=peak_modes,
        material_spectra=material_spectra,
        chart_title=chart_title,
        guitar_type_str=guitar_type_str,
    )
    chart_img = chart.render()

    # ── Compose full image ────────────────────────────────────────────────────
    canvas = QtGui.QImage(TOTAL_W, TOTAL_H, QtGui.QImage.Format.Format_RGB32)
    canvas.fill(QtGui.QColor(255, 255, 255))
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)

    y = PADDING

    def _fmt_freq(f: float) -> str:
        return f"{f / 1000:.1f}k Hz" if f >= 1000 else f"{f:.0f} Hz"

    def _format_date_label(raw: str) -> str:
        """Format a date string to match Swift Date().formatted() output.

        Swift Date().formatted() produces the locale default medium date + short time,
        e.g. "4/3/2026, 2:30 PM".  Accepts an ISO-8601 timestamp string or any
        string already formatted by the caller; falls back to the raw string.

        Uses portable strftime codes (no %-d / %#d platform differences).
        """
        from datetime import datetime
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M",
        ):
            try:
                dt = datetime.strptime(raw, fmt)
                if dt.tzinfo is not None:
                    dt = dt.astimezone()           # convert to local time
                hour = int(dt.strftime("%I"))      # strip leading zero portably
                ampm = dt.strftime("%p")
                return f"{dt.month}/{dt.day}/{dt.year}, {hour}:{dt.minute:02d} {ampm}"
            except ValueError:
                continue
        return raw                                 # already formatted or unrecognised

    # ── Header — mirrors makeExportableSpectrumView VStack(alignment:.leading) header block ──
    title_font = QtGui.QFont()
    title_font.setPixelSize(20 * SCALE)  # mirrors .font(.title).fontWeight(.bold)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QtGui.QColor(0, 0, 0))
    painter.drawText(
        PADDING, y, TOTAL_W - PADDING * 2, 36 * SCALE,
        QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
        "Guitar Tap Tone Analysis - Frequency Response",
    )
    y += 36 * SCALE

    sub_font = QtGui.QFont()
    sub_font.setPixelSize(12 * SCALE)  # mirrors .font(.subheadline)
    painter.setFont(sub_font)
    painter.setPen(QtGui.QColor(100, 100, 100))

    # Swift: HStack { Text("Date:…") Spacer() Text("Range:…") • Text("…dB") }
    if date_label:
        painter.drawText(
            PADDING, y, TOTAL_W // 2, 28 * SCALE,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"Date: {_format_date_label(date_label)}",
        )
    painter.drawText(
        PADDING, y, TOTAL_W - PADDING * 2, 28 * SCALE,
        QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
        f"Range: {_fmt_freq(min_freq)} - {_fmt_freq(max_freq)}"
        f"  \u2022  {int(min_db)} to {int(max_db)} dB",
    )
    y += 28 * SCALE

    # Swift: HStack { Type • Platform • GuitarTap vX.Y (build) }
    meta_parts: list[str] = []
    if measurement_type_str:
        meta_parts.append(f"Type: {measurement_type_str}")
    if platform_str is None:
        import platform as _platform
        _sys = _platform.system()
        platform_str = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(_sys, _sys)
    meta_parts.append(f"Platform: {platform_str}")
    if software_version is None:
        try:
            from _version import __version_string__ as _v
            software_version = _v
        except ImportError:
            software_version = ""
    if software_version:
        meta_parts.append(f"GuitarTap v{software_version}")
    meta_line = "  \u2022  ".join(meta_parts)
    meta_font = QtGui.QFont()
    meta_font.setPixelSize(12 * SCALE)
    painter.setFont(meta_font)
    painter.setPen(QtGui.QColor(100, 100, 100))
    painter.drawText(
        PADDING, y, TOTAL_W - PADDING * 2, 24 * SCALE,
        QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
        meta_line,
    )
    y += 24 * SCALE

    # Swift: if !materialSpectra.isEmpty { Text("Comparing N measurements") }
    #        else if !peaks.isEmpty { Text("Detected Peaks: N") }
    if material_spectra:
        painter.drawText(
            PADDING, y, TOTAL_W - PADDING * 2, 24 * SCALE,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"Comparing {len(material_spectra)} measurements",
        )
    elif peaks:
        painter.drawText(
            PADDING, y, TOTAL_W - PADDING * 2, 24 * SCALE,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            f"Detected Peaks: {len(peaks)}",
        )
    y += 24 * SCALE

    # ── Chart title — mirrors Text(chartTitle).frame(maxWidth:.infinity, alignment:.center) ──
    ct_font = QtGui.QFont()
    ct_font.setPixelSize(24 * SCALE)  # mirrors .font(.system(size: 24, weight: .semibold))
    ct_font.setWeight(QtGui.QFont.Weight.DemiBold)
    painter.setFont(ct_font)
    painter.setPen(QtGui.QColor(0x33, 0x33, 0x33))
    painter.drawText(
        PADDING, y, TOTAL_W - PADDING * 2, CHART_TITLE_H,
        QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter,
        chart_title,
    )
    y += CHART_TITLE_H

    # ── ExportableSpectrumChart — place rendered chart image ──────────────────
    if not chart_img.isNull():
        painter.drawImage(PADDING, y, chart_img)
    y += CHART_H + PADDING

    # ── Detected Peaks Summary — mirrors peak summary VStack + HStack ─────────
    if peaks:
        hdr_font = QtGui.QFont()
        hdr_font.setPixelSize(13 * SCALE)  # mirrors .font(.headline)
        hdr_font.setBold(True)
        painter.setFont(hdr_font)
        painter.setPen(QtGui.QColor(0, 0, 0))
        # Swift: Text("Detected Peaks Summary").font(.headline)
        painter.drawText(
            PADDING, y, TOTAL_W - PADDING * 2, 24 * SCALE,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "Detected Peaks Summary",
        )
        y += 24 * SCALE

        card_w       = 120 * SCALE
        card_h       = 68  * SCALE
        card_spacing = 12  * SCALE
        x_card = PADDING
        # Swift: peaks.prefix(8).sorted(by: { $0.frequency < $1.frequency })
        sorted_peaks = sorted(peaks[:8], key=lambda p: p.frequency)
        for idx, peak in enumerate(sorted_peaks):
            color = chart.peak_color(peak, idx)
            label = chart.peak_mode_label(peak, idx)

            bg = QtGui.QColor(color)
            bg.setAlpha(30)
            painter.setBrush(QtGui.QBrush(bg))
            painter.setPen(QtGui.QPen(color, SCALE))
            painter.drawRoundedRect(x_card, y, card_w, card_h, 6 * SCALE, 6 * SCALE)

            # Swift: Text("…Hz").font(.caption).fontWeight(.bold)
            freq_font = QtGui.QFont()
            freq_font.setPixelSize(10 * SCALE)  # mirrors .font(.caption)
            freq_font.setBold(True)
            painter.setFont(freq_font)
            painter.setPen(color)
            painter.drawText(
                x_card + 4 * SCALE, y + 2 * SCALE, card_w - 8 * SCALE, 22 * SCALE,
                QtCore.Qt.AlignmentFlag.AlignCenter, f"{peak.frequency:.1f} Hz",
            )

            # Swift: Text(mode.displayName).font(.caption2).foregroundColor(mode.color)
            mode_font = QtGui.QFont()
            mode_font.setPixelSize(9 * SCALE)  # mirrors .font(.caption2)
            painter.setFont(mode_font)
            painter.drawText(
                x_card + 4 * SCALE, y + 24 * SCALE, card_w - 8 * SCALE, 18 * SCALE,
                QtCore.Qt.AlignmentFlag.AlignCenter, label,
            )

            # Swift: Text("…dB").font(.caption2).foregroundColor(.secondary)
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawText(
                x_card + 4 * SCALE, y + 44 * SCALE, card_w - 8 * SCALE, 18 * SCALE,
                QtCore.Qt.AlignmentFlag.AlignCenter, f"{peak.magnitude:.1f} dB",
            )

            x_card += card_w + card_spacing

        y += card_h + PADDING

    # ── Legend — mirrors makeExportableSpectrumView legend HStack ─────────────
    legend_font = QtGui.QFont()
    legend_font.setPixelSize(10 * SCALE)  # mirrors .font(.caption).fontWeight(.semibold)
    legend_font.setBold(True)
    painter.setFont(legend_font)
    painter.setPen(QtGui.QColor(0, 0, 0))

    label_font = QtGui.QFont()
    label_font.setPixelSize(10 * SCALE)   # mirrors .font(.caption)

    ROW_H = LEGEND_H   # full legend row height

    if material_spectra:
        # Swift: HStack { Text("Measurements:") ForEach(materialSpectra) { RoundedRect + label } }
        painter.drawText(PADDING, y, 120 * SCALE, ROW_H,
                         QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                         "Measurements:")
        x_leg = PADDING + 124 * SCALE
        _LEG_COLOR_MAP = {
            "blue":   (  0, 122, 255),
            "orange": (255, 149,   0),
            "purple": (175,  82, 222),
            "red":    (255,  59,  48),
            "green":  ( 52, 199,  89),
        }
        painter.setFont(label_font)
        for series in material_spectra[:5]:
            color_key = series.get("color", "blue")
            # color may be an (r,g,b) tuple (comparison path) or a string (plate/brace path)
            r, g, b = color_key if isinstance(color_key, tuple) else _LEG_COLOR_MAP.get(color_key, (0, 122, 255))
            lbl = series.get("label", "?")
            painter.setBrush(QtGui.QBrush(QtGui.QColor(r, g, b)))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(x_leg, y + ROW_H // 2 - 3 * SCALE, 28 * SCALE, 6 * SCALE, 3 * SCALE, 3 * SCALE)
            painter.setPen(QtGui.QColor(0, 0, 0))
            painter.drawText(x_leg + 32 * SCALE, y, 160 * SCALE, ROW_H,
                             QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, lbl)
            x_leg += 200 * SCALE
    elif chart.is_guitar:
        # Swift: HStack { Text("Guitar Modes:") ForEach([.air,.top,.back,.dipole,.ringMode]) { Circle + label } }
        # Guitar-mode only — mirrors Swift's else branch gated implicitly by measurementType.isGuitar
        # (for plate/brace, materialSpectra is always populated so this branch is never reached in Swift).
        painter.drawText(PADDING, y, 120 * SCALE, ROW_H,
                         QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                         "Guitar Modes:")
        x_leg = PADDING + 124 * SCALE
        painter.setFont(label_font)
        for mode_name, (r, g, b) in GUITAR_MODE_DISPLAY:
            painter.setBrush(QtGui.QBrush(QtGui.QColor(r, g, b)))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(x_leg, y + ROW_H // 2 - 7 * SCALE, 14 * SCALE, 14 * SCALE)
            painter.setPen(QtGui.QColor(0, 0, 0))
            painter.drawText(x_leg + 18 * SCALE, y, 160 * SCALE, ROW_H,
                             QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                             mode_name)
            x_leg += 180 * SCALE

    painter.end()

    # Save to in-memory buffer — mirrors Swift ImageRenderer returning Data
    # rather than writing to disk.
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    buf = QByteArray()
    qbuf = QBuffer(buf)
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    canvas.save(qbuf, "PNG")
    qbuf.close()
    return bytes(buf)


# ── Render Spectrum Image for Measurement ─────────────────────────────────────

def render_spectrum_image_for_measurement(m) -> "bytes | None":
    """Render the composite spectrum PNG for a measurement and return the PNG bytes.

    Mirrors ``renderSpectrumImageForMeasurement(_:)`` in ExportableSpectrumChart.swift,
    which returns ``Data?`` (PNG-encoded image bytes).

    Returns PNG bytes, or None if the measurement has no spectrum snapshot.
    """
    primary_snapshot = m.spectrum_snapshot or m.longitudinal_snapshot
    if primary_snapshot is None:
        return None

    snap = primary_snapshot

    # Build material spectra list — mirrors Swift's materialSpectra construction.
    material_spectra = []
    if m.longitudinal_snapshot:
        ls = m.longitudinal_snapshot
        material_spectra.append({
            "frequencies": ls.frequencies,
            "magnitudes": ls.magnitudes,
            "color": "blue",
            "label": "Longitudinal (L)",
        })
    if m.cross_snapshot:
        cs = m.cross_snapshot
        material_spectra.append({
            "frequencies": cs.frequencies,
            "magnitudes": cs.magnitudes,
            "color": "orange",
            "label": "Cross-grain (C)",
        })
    if m.flc_snapshot:
        fs = m.flc_snapshot
        material_spectra.append({
            "frequencies": fs.frequencies,
            "magnitudes": fs.magnitudes,
            "color": "purple",
            "label": "FLC",
        })

    # Mirror TapToneAnalyzer.visiblePeaks: filter by annotationVisibilityMode and selectedPeakIDs.
    all_peaks = m.peaks or []
    visibility_mode = AnnotationVisibilityMode.from_string(m.annotation_visibility_mode or "all")
    selected_ids = set(m.selected_peak_ids or [p.id for p in all_peaks])
    if visibility_mode == AnnotationVisibilityMode.SELECTED:
        visible_peaks = [p for p in all_peaks if p.id in selected_ids]
    elif visibility_mode == AnnotationVisibilityMode.NONE:
        visible_peaks = []
    else:
        visible_peaks = all_peaks

    # Mirrors Swift: makeExportableSpectrumView called directly from renderSpectrumImageForMeasurement.
    return make_exportable_spectrum_view(
        frequencies=list(snap.frequencies),
        magnitudes=list(snap.magnitudes),
        min_freq=float(snap.min_freq),
        max_freq=float(snap.max_freq),
        min_db=float(snap.min_db),
        max_db=float(snap.max_db),
        peaks=visible_peaks,
        annotation_positions=m.annotation_offsets or {},
        show_unknown_modes=snap.show_unknown_modes,
        measurement_type_str=snap.measurement_type or None,
        selected_longitudinal_peak_id=m.selected_longitudinal_peak_id,
        selected_cross_peak_id=m.selected_cross_peak_id,
        selected_flc_peak_id=m.selected_flc_peak_id,
        mode_overrides=m.peak_mode_overrides or {},
        material_spectra=material_spectra if material_spectra else None,
        date_label=str(m.timestamp) if m.timestamp else "",
        chart_title=f"FFT Peaks — {m.tap_location or 'New'}",
        guitar_type_str=snap.guitar_type,
    )
