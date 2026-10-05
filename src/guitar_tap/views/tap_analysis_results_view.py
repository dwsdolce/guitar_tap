"""
Measurement persistence layer.

Data model classes live in the models/ package:
  models.resonant_peak        → ResonantPeak
  models.spectrum_snapshot    → SpectrumSnapshot
  models.tap_tone_measurement → TapToneMeasurement

JSON format:
  - Single saved_measurements.json in the platform app-data dir. The app name is pinned to
    "guitar-tap" (QCoreApplication.setApplicationName in __main__.py), so:
      macOS:   ~/Library/Application Support/guitar-tap/
      Windows: %APPDATA%\\guitar-tap\\
      Linux:   ~/.local/share/guitar-tap/
  - Each measurement identified by UUID, ISO-8601 timestamp
  - Peaks have UUIDs; mode overrides, selected IDs, annotation offsets
    are keyed by peak UUID
  - spectrumSnapshot embeds freq/mag arrays so the file is self-contained
  - Format is cross-compatible with Swift GuitarTap .guitartap files
"""

# @parity view/pdf-report tests=test/pdf-report

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from guitar_tap.models import field_precision as fp
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
from guitar_tap.utilities.logging import gt_log

__all__ = [
    "load_all_measurements",
    "save_all_measurements",
    "measurements_to_json",
    "measurements_from_json",
    "export_measurement_json",
    "import_measurements_from_json",
    "export_pdf",
    "pdf_report_data_from_measurement",
    "PDFReportData",
    "measurements_file",
    "render_spectrum_image_for_measurement",
    "render_spectrum_image_for_comparison",
    "render_spectrum_image_for_multi_tap",
    "ComparisonPDFReportData",
    "comparison_pdf_report_data_from_measurement",
    "export_comparison_pdf",
    "export_multi_tap_pdf",
    "multi_tap_comparison_pdf_report_data_from_measurement",
    "export_report_for_measurement",
    "report_basename",
    "default_export_dir",
    "last_export_dir",
    "update_export_dir",
]

# ── Multi-tap comparison palette and averaged color ───────────────────────────
# Both re-exported from TapToneAnalyzerMeasurementManagementMixin, which is the
# single authoritative definition — mirrors Swift's TapToneAnalyzer.multiTapPalette
# and TapToneAnalyzer.multiTapAvgColor.
from guitar_tap.models.tap_tone_analyzer_measurement_management import (  # noqa: E402
    TapToneAnalyzerMeasurementManagementMixin as _AnalyzerMixin,
)

MULTI_TAP_PALETTE = _AnalyzerMixin._MULTI_TAP_PALETTE
MULTI_TAP_AVG_COLOR = _AnalyzerMixin._MULTI_TAP_AVG_COLOR

# Spectrum image rendering lives in exportable_spectrum_chart.py (mirrors ExportableSpectrumChart.swift).
from guitar_tap.views.exportable_spectrum_chart import (
    render_spectrum_image_for_measurement,  # noqa: E402
)
from guitar_tap.views.utilities import extensions as _ext  # noqa: E402
from guitar_tap.views.utilities import palette  # noqa: E402

# ── Export directory tracking ─────────────────────────────────────────────────
# Mirrors MeasurementFileExporter.lastUsedDirectory in Swift: remembers the
# last directory the user saved to or opened from, persisted across launches
# via QSettings (mirrors UserDefaults bookmark storage in Swift).

_EXPORT_DIR_KEY = "GuitarTap/lastUsedExportDirectory"


def default_export_dir() -> str:
    """Return ~/Documents/GuitarTap, creating it if needed."""
    path = os.path.join(os.path.expanduser("~"), "Documents", "GuitarTap")
    os.makedirs(path, exist_ok=True)
    return path


def last_export_dir() -> str:
    """Return the last directory used for export/import, or the default.

    Persisted across launches via QSettings — mirrors Swift's UserDefaults
    bookmark storage in MeasurementFileExporter.
    """
    from guitar_tap.views.utilities.tap_settings_view import AppSettings
    stored = AppSettings._s().value(_EXPORT_DIR_KEY)
    if stored and os.path.isdir(stored):
        return stored
    return default_export_dir()


def update_export_dir(chosen_path: str) -> None:
    """Persist the directory of *chosen_path* as the new last-used export dir."""
    from guitar_tap.views.utilities.tap_settings_view import AppSettings
    AppSettings._s().setValue(_EXPORT_DIR_KEY, os.path.dirname(chosen_path))


# ── Persistence paths ─────────────────────────────────────────────────────────

def _app_data_dir() -> str:
    """Return the platform-appropriate Application Support directory.

    Uses QStandardPaths.AppDataLocation which resolves to:
      macOS:   ~/Library/Application Support/GuitarTap
      Windows: %APPDATA%\\GuitarTap
      Linux:   ~/.local/share/GuitarTap
    """
    from PySide6.QtCore import QStandardPaths
    path = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return path


def measurements_file() -> str:
    # Mirror Swift's XCTestConfigurationFilePath check: redirect to an isolated
    # temp directory when running under pytest so tests never touch the user's
    # real saved measurements.
    from guitar_tap.models.settings_scope import measurements_dir  # noqa: PLC0415
    data_dir = measurements_dir(_app_data_dir())
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "saved_measurements.json")


# ── Persistence API ───────────────────────────────────────────────────────────

def load_all_measurements() -> list[TapToneMeasurement]:
    """Load all measurements from saved_measurements.json.

    Reads through the single ``measurements_from_json`` decoder so that loading
    the persisted library and importing a shared ``.guitartap`` file are the same
    code path (mirrors Swift's one decodeMeasurements)."""
    path = measurements_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return measurements_from_json(f.read())
    except Exception as exc:
        gt_log(f"Failed to load measurements: {exc}")
        return []


def measurements_to_json(measurements: "list[TapToneMeasurement]") -> str:
    """The on-disk library form (saved_measurements.json) — a `.guitartap` JSON array.
    Shared by the internal persistence and by Export All, so a backup IS the library file."""
    return json.dumps([m.to_dict() for m in measurements], indent=2, ensure_ascii=False, sort_keys=True)


def save_all_measurements(measurements: list[TapToneMeasurement]) -> None:
    """Write the full measurements list to disk atomically."""
    path = measurements_file()
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(measurements_to_json(measurements))
        os.replace(tmp, path)
    except OSError as exc:
        gt_log(f"Failed to save measurements: {exc}")


def export_measurement_json(m: TapToneMeasurement) -> str:
    """Return the canonical `.guitartap` JSON for a single measurement.

    A single-element library file — identical bytes to what persistence and
    Export All write for the same measurement, because they all serialize through
    ``measurements_to_json`` / ``TapToneMeasurement.to_dict`` (which resolves each
    peak's modeLabel exactly as Swift's single encode(to:) does).  Mirrors Swift:
    a one-measurement export is just the one encoder applied to a one-element array.
    """
    return measurements_to_json([m])


def measurements_from_json(data: str | bytes) -> list[TapToneMeasurement]:
    """Decode canonical `.guitartap` JSON into measurements.

    Accepts a JSON array or a single measurement object.  THE deserializer:
    both persistence load (load_all_measurements) and file import go through it,
    so reading saved_measurements.json and importing a shared file are one path
    (mirrors Swift's single TapToneAnalyzer.decodeMeasurements).
    """
    raw = json.loads(data)
    if isinstance(raw, list):
        return [TapToneMeasurement.from_dict(d) for d in raw]
    return [TapToneMeasurement.from_dict(raw)]


def import_measurements_from_json(data: str | bytes) -> list[TapToneMeasurement]:
    """Import measurements from a .guitartap or .json file (array or single object).

    Thin alias kept for the import UI; delegates to the shared
    ``measurements_from_json`` decoder."""
    return measurements_from_json(data)


# ── PDF Report Data ───────────────────────────────────────────────────────────

@dataclass
class PDFReportData:
    """All data required to render a PDF tap tone analysis report.

    Mirrors Swift's ``PDFReportData`` struct in PDFReportGenerator.swift.

    This is a pure value type that carries pre-computed, display-ready data.
    Create it from a saved measurement with ``pdf_report_data_from_measurement()``,
    or construct it directly for custom reports (e.g., from live analyzer state).

    The factory re-derives ``PlateProperties`` / ``BraceProperties`` from the
    measurement's stored peak IDs and snapshot dimensions so that computed
    values match the live analysis view.  Peaks are filtered to those within
    the saved display frequency range.
    """
    # Measurement metadata
    timestamp: str
    measurement_name: str | None
    notes: str | None
    measurement_type_str: str          # display string (e.g. "Classical Guitar")
    guitar_type_str: str               # raw value (e.g. "Classical")
    microphone_name: str | None
    calibration_name: str | None

    # Display frequency range
    min_freq: float
    max_freq: float

    # Peaks (already filtered to display range; ``visible_peaks`` are the selected subset)
    peaks: list                        # list[ResonantPeak], range-filtered
    selected_peak_ids: set             # set[str]
    peak_modes: dict                   # dict[str, GuitarMode] — classify_all result
    peak_mode_overrides: dict          # dict[str, str] — user overrides

    # Per-measurement-type IDs
    selected_longitudinal_peak_id: str | None
    selected_cross_peak_id: str | None
    selected_flc_peak_id: str | None

    # Analysis results
    decay_time: float | None
    tap_tone_ratio: float | None

    # Material properties (None for guitar measurements)
    # G_LC shear modulus is read from plate_properties.gore_shear_modulus (derived from f_flc).
    plate_properties: Any | None       # PlateProperties | None
    brace_properties: Any | None       # BraceProperties | None

    # Gore thicknessing inputs (plate only).
    # The gore target thickness is computed live in export_pdf from these inputs +
    # plate_properties.gore_shear_modulus — mirrors Swift's PDFReportContentView
    # calling props.goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:).
    guitar_body_length: float
    guitar_body_width: float
    plate_stiffness: float
    plate_stiffness_preset_str: str

    # PNG-encoded spectrum chart image, or None if none was captured.
    spectrum_image_data: bytes | None


def pdf_report_data_from_measurement(
    measurement: TapToneMeasurement,
    spectrum_image_data: bytes | None = None,
    tap_tone_ratio: "float | None" = None,
    peak_modes: "dict | None" = None,
) -> PDFReportData:
    """Build a ``PDFReportData`` from a persisted ``TapToneMeasurement``.

    Mirrors Swift's ``PDFReportData.from(measurement:spectrumImageData:)`` in
    PDFReportGenerator.swift.

    The factory re-derives ``PlateProperties`` / ``BraceProperties`` from the
    measurement's stored peak IDs and snapshot dimensions so that computed
    values match the live analysis view.  Peaks are filtered to those within
    the saved display frequency range.

    Args:
        measurement:       The measurement to export.
        spectrum_image_data: PNG-encoded spectrum chart, or None.
        tap_tone_ratio:    Pre-computed ratio from the live analyzer
                           (``TapToneAnalyzer.calculate_tap_tone_ratio()``).
                           When supplied this overrides the value derived from
                           the measurement peaks so that user mode overrides and
                           context-aware classification from ``identifiedModes``
                           are reflected in the PDF.  Mirrors
                           ``TapToneAnalysisView+Export.swift:124`` which passes
                           ``tap.calculateTapToneRatio()`` directly.
                           Pass ``None`` (default) when building from a saved
                           measurement where no live analyzer is available.
        peak_modes:        Pre-computed ``{peak_id: GuitarMode}`` dict from the
                           live analyzer's ``identified_modes``.  Mirrors Swift
                           ``peakModes: Dictionary(uniqueKeysWithValues:
                           tap.identifiedModes.map { ($0.peak.id, $0.mode) })``.
                           When supplied this overrides the ``classify_all``
                           result so user mode overrides and context-aware
                           classification are preserved.  Pass ``None`` (default)
                           when building from a saved measurement.
    """
    from guitar_tap.models import guitar_mode as GM
    from guitar_tap.models import guitar_type as GT_module
    from guitar_tap.models import measurement_type as MT
    from guitar_tap.models import plate_stiffness_preset as PSP
    from guitar_tap.models.material_properties import (
        BraceProperties,
        MaterialDimensions,
        PlateProperties,
    )

    m = measurement

    # ── Derive measurement type and guitar type ───────────────────────────
    any_snap = m.spectrum_snapshot or m.longitudinal_snapshot or m.cross_snapshot
    mt_str = m.measurement_type or (any_snap.measurement_type if any_snap else MT.MeasurementType.GENERIC.value)
    try:
        mt = MT.MeasurementType(mt_str)
    except ValueError:
        mt = MT.MeasurementType.GENERIC

    gt_str = m.guitar_type or (any_snap.guitar_type if any_snap else GT_module.GuitarType.GENERIC.value)
    try:
        gt = GT_module.GuitarType(gt_str)
    except Exception:
        gt = GT_module.GuitarType.GENERIC

    # ── Display frequency range ───────────────────────────────────────────
    display_snap = m.spectrum_snapshot or any_snap
    min_freq = display_snap.min_freq if display_snap else 50.0
    max_freq = display_snap.max_freq if display_snap else 1000.0

    # ── Filter peaks to display range ─────────────────────────────────────
    range_peaks = [p for p in m.peaks if min_freq <= p.frequency <= max_freq]
    selected_ids = m.effective_selected_peak_ids

    # ── Mode classification ───────────────────────────────────────────────
    visible_peaks = sorted(
        [p for p in range_peaks if p.id in selected_ids],
        key=lambda p: p.frequency,
    )
    # Use caller-supplied peak_modes (from live analyzer.identified_modes) when
    # available — mirrors Swift peakModes: Dictionary(uniqueKeysWithValues:
    # tap.identifiedModes.map { ($0.peak.id, $0.mode) }).
    # Fall back to classify_all for saved measurements without a live analyzer.
    if peak_modes is None:
        peak_modes = {}
        try:
            peak_modes = GM.GuitarMode.classify_all(visible_peaks, gt)
        except Exception:
            pass

    # ── Derive material properties ────────────────────────────────────────
    plate_props = None
    brace_props = None
    snap_for_dims = m.longitudinal_snapshot or any_snap

    if mt == MT.MeasurementType.PLATE:
        long_peak  = next((p for p in m.peaks if p.id == m.selected_longitudinal_peak_id), None)
        cross_peak = next((p for p in m.peaks if p.id == m.selected_cross_peak_id), None)
        flc_peak   = next((p for p in m.peaks if p.id == m.selected_flc_peak_id), None) if m.selected_flc_peak_id else None
        if long_peak and cross_peak and snap_for_dims:
            dims = MaterialDimensions(
                length_mm    = snap_for_dims.plate_length    or 0,
                width_mm     = snap_for_dims.plate_width     or 0,
                thickness_mm = snap_for_dims.plate_thickness or 0,
                mass_g       = snap_for_dims.plate_mass      or 0,
            )
            if dims.length_mm > 0 and dims.mass_g > 0:
                plate_props = PlateProperties(
                    dims, long_peak.frequency, cross_peak.frequency,
                    flc_peak.frequency if flc_peak else None,
                )

    elif mt == MT.MeasurementType.BRACE:
        long_peak = next((p for p in m.peaks if p.id == m.selected_longitudinal_peak_id), None)
        if long_peak and snap_for_dims:
            dims = MaterialDimensions(
                length_mm    = snap_for_dims.brace_length    or 0,
                width_mm     = snap_for_dims.brace_width     or 0,
                thickness_mm = snap_for_dims.brace_thickness or 0,
                mass_g       = snap_for_dims.brace_mass      or 0,
            )
            if dims.length_mm > 0 and dims.mass_g > 0:
                brace_props = BraceProperties(dims, long_peak.frequency)

    # ── Gore settings (plate only) ────────────────────────────────────────
    snap_for_gore = m.longitudinal_snapshot or any_snap
    guitar_body_length = (
        snap_for_gore.guitar_body_length
        if snap_for_gore and snap_for_gore.guitar_body_length else None
    ) or 490.0
    guitar_body_width = (
        snap_for_gore.guitar_body_width
        if snap_for_gore and snap_for_gore.guitar_body_width else None
    ) or 390.0
    _preset_str = (
        snap_for_gore.plate_stiffness_preset
        if snap_for_gore and snap_for_gore.plate_stiffness_preset else None
    ) or "Steel String Top"
    try:
        _preset = PSP.PlateStiffnessPreset(_preset_str)
    except ValueError:
        _preset = PSP.PlateStiffnessPreset.STEEL_STRING_TOP
    if _preset == PSP.PlateStiffnessPreset.CUSTOM:
        plate_stiffness = (
            snap_for_gore.custom_plate_stiffness
            if snap_for_gore and snap_for_gore.custom_plate_stiffness else None
        ) or 75.0
    else:
        plate_stiffness = _preset.stiffness

    return PDFReportData(
        timestamp=m.timestamp,
        measurement_name=m.measurement_name,
        notes=m.notes,
        measurement_type_str=mt_str,
        guitar_type_str=gt_str,
        microphone_name=m.microphone_name,
        calibration_name=m.calibration_name,
        min_freq=min_freq,
        max_freq=max_freq,
        peaks=range_peaks,
        selected_peak_ids=selected_ids,
        peak_modes=peak_modes,
        peak_mode_overrides=m.peak_mode_overrides or {},
        selected_longitudinal_peak_id=m.selected_longitudinal_peak_id,
        selected_cross_peak_id=m.selected_cross_peak_id,
        selected_flc_peak_id=m.selected_flc_peak_id,
        decay_time=m.decay_time,
        # Use the caller-supplied ratio (from the live analyzer) when available,
        # falling back to the measurement's computed property for saved measurements.
        # Mirrors TapToneAnalysisView+Export.swift:124: tapToneRatio: tap.calculateTapToneRatio().
        tap_tone_ratio=tap_tone_ratio if tap_tone_ratio is not None else m.tap_tone_ratio,
        plate_properties=plate_props,
        brace_properties=brace_props,
        guitar_body_length=guitar_body_length,
        guitar_body_width=guitar_body_width,
        plate_stiffness=plate_stiffness,
        plate_stiffness_preset_str=_preset_str,
        spectrum_image_data=spectrum_image_data,
    )


# Spectrum-image matte (pt). Mirrors Swift PDFReportGenerator.swift:405-410 —
# `.background(Color(white: 0.05)).cornerRadius(6)` behind the chart image.
_SPECTRUM_MATTE_PT = 5
_SPECTRUM_CORNER_PT = 6

# SwiftUI lays out a line of Helvetica text in a box exactly its font size tall, with the baseline 0.77 ×
# the size below the top, and steps wrapped lines by the size. reportlab's Paragraph puts the first
# baseline a full font size below the top, so the report's text is drawn a little higher, by the
# difference; with Swift's paddings and spacings around it, each line lands where Swift's does.
_SWIFT_ASCENT = 0.77
_swift_text_cls = None


def _text(text: str, size: float, *, bold: bool = False, italic: bool = False, color=None,
          align: str = "left", markup: bool = False):
    """A Paragraph laid out as SwiftUI lays out a Text (see ``_SWIFT_ASCENT``).

    ``text`` is plain text unless ``markup`` is set, when it is reportlab paragraph markup (inline
    ``<font>`` / ``<b>`` for a row mixing colours or weights)."""
    global _swift_text_cls
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    if _swift_text_cls is None:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        class _SwiftText(Paragraph):
            def drawOn(self, canvas, x, y, _sW=0):
                super().drawOn(canvas, x, y + (1 - _SWIFT_ASCENT) * self.style.fontSize, _sW)

            def breakLines(self, width):
                # As Swift's Text wraps: the last line never holds a single word when the line above
                # can spare one — Apple's push-out line-break strategy, which avoids an orphan word.
                para = super().breakLines(width)
                lines = getattr(para, "lines", None)
                if getattr(para, "kind", 1) != 0 or not lines or len(lines) < 2:
                    return para
                prev, last = lines[-2][1], lines[-1][1]
                if len(last) != 1 or len(prev) < 2:
                    return para
                max_w = width[-1] if isinstance(width, (list, tuple)) else width
                kept, moved = prev[:-1], [prev[-1]] + last
                moved_w = stringWidth(" ".join(moved), para.fontName, para.fontSize)
                if moved_w <= max_w:
                    kept_w = stringWidth(" ".join(kept), para.fontName, para.fontSize)
                    lines[-2] = (max_w - kept_w, kept)
                    lines[-1] = (max_w - moved_w, moved)
                return para
        _swift_text_cls = _SwiftText

    font = "Helvetica-Oblique" if italic else "Helvetica-Bold" if bold else "Helvetica"
    style = ParagraphStyle(
        "swift", fontName=font, fontSize=size, leading=size,
        textColor=color if color is not None else colors.black,
        alignment=TA_RIGHT if align == "right" else TA_LEFT,
    )
    return _swift_text_cls(text if markup else escape(text), style)


def _grid(rows: list, col_widths: list, style: list | None = None, **kw):
    """A table with no cell padding, its cells top-aligned — every gap is set explicitly, as Swift's
    stacks and paddings set them."""
    from reportlab.platypus import Table, TableStyle

    tbl = Table(rows, colWidths=col_widths, **kw)
    tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        *(style or []),
    ]))
    return tbl


def _rule(width: float, thickness: float, color):
    """A filled rule — Swift's accentBar and sectionDivider (a Rectangle of the given height)."""
    return _grid([[""]], [width], [("BACKGROUND", (0, 0), (-1, -1), color)], rowHeights=[thickness])


def _report_header(subtitle: str, date_str: str, accent, secondary, content_w: float):
    """Swift's report header: HStack(top) { VStack(spacing 2) { "GuitarTap" 22 bold, subtitle 13 },
    the date 11 } with 8 below, then the 3 pt accent bar with 12 below."""
    from reportlab.platypus import Spacer

    return [
        _grid(
            [[[_text("GuitarTap", 22, bold=True, color=accent), Spacer(1, 2), _text(subtitle, 13, color=secondary)],
              _text(date_str, 11, color=secondary, align="right")]],
            [content_w * 0.6, content_w * 0.4],
            [("BOTTOMPADDING", (0, 0), (-1, -1), 8)],
        ),
        _rule(content_w, 3, accent),
        Spacer(1, 12),
    ]


def _meta_rows(rows: list, label_w: float, secondary, value_color, content_w: float) -> list:
    """Swift's metadata: VStack(spacing 4) of HStack(top, spacing 6) { label 11 bold in a ``label_w``
    frame, value 11 }."""
    from reportlab.platypus import Spacer

    out: list = []
    for label, value in rows:
        if out:
            out.append(Spacer(1, 4))
        out.append(_grid(
            [[_text(label + ":", 11, bold=True, color=secondary), _text(value, 11, color=value_color)]],
            [label_w + 6, content_w - label_w - 6],
        ))
    return out


def _report_footer(generated_by: str, secondary, content_w: float) -> list:
    """Swift's footer: Spacer 16, a 1 pt rule, Spacer 8, then "Generated by …" and the time of
    generation, 9 pt."""
    from datetime import datetime as _dt

    from reportlab.lib import colors
    from reportlab.platypus import Spacer

    from guitar_tap.utilities.date_format import format_display_datetime

    now_str = format_display_datetime(_dt.now())  # PDF generation time (local)
    return [
        Spacer(1, 16),
        _rule(content_w, 1, colors.Color(0.5, 0.5, 0.5, 0.2)),
        Spacer(1, 8),
        _grid(
            [[_text(generated_by, 9, color=secondary), _text(now_str, 9, color=secondary, align="right")]],
            [content_w * 0.6, content_w * 0.4],
        ),
    ]


def _spectrum_image_matte(image_data: bytes, content_w: float):
    """The spectrum image inside a dark rounded matte, as a single flowable.

    The matte makes it obvious where the captured spectrum ends and the report begins.

    Mirrors Swift::

        reportImage(from: imageData)
            .resizable().aspectRatio(contentMode: .fit)
            .frame(width: contentWidth)
            .background(Color(white: 0.05))
            .cornerRadius(6)

    On Swift the frame is not a stroke: its chart PNG carries transparent padding (hence the
    DeviceGray alpha mask in its PDF) and the near-black background shows *through* it. Our chart
    image is opaque, so the same look is drawn deliberately — a near-black rounded cell the size of
    Swift's image (the content width, at the image's proportions), with the image inset by
    ``_SPECTRUM_MATTE_PT``.

    Shared by both story builders (`_build_averaged_story` / `_build_comparison_story`), as Swift has
    the matte at both of its sites.

    Args:
        image_data: PNG bytes of the rendered spectrum.
        content_w: Full content width (pt); the image is inset within it.

    Returns:
        A reportlab ``Table`` flowable wrapping the image.
    """
    import io as _io

    from PIL import Image as _PILImage
    from reportlab.lib import colors
    from reportlab.platypus import Image as _RLImg
    from reportlab.platypus import Table, TableStyle

    _pil = _PILImage.open(_io.BytesIO(image_data))
    w_px, h_px = _pil.size
    aspect = h_px / w_px if w_px > 0 else 0.5
    frame_h = content_w * aspect
    inner_h = frame_h - _SPECTRUM_MATTE_PT * 2
    inner_w = inner_h / aspect
    side = (content_w - inner_w) / 2
    img = _RLImg(_io.BytesIO(image_data), width=inner_w, height=inner_h)

    cell = Table([[img]], colWidths=[content_w], rowHeights=[frame_h])
    cell.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.05, 0.05, 0.05)),
        ("LEFTPADDING",   (0, 0), (-1, -1), side),
        ("RIGHTPADDING",  (0, 0), (-1, -1), side),
        ("TOPPADDING",    (0, 0), (-1, -1), _SPECTRUM_MATTE_PT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _SPECTRUM_MATTE_PT),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ROUNDEDCORNERS", [_SPECTRUM_CORNER_PT] * 4),
    ]))
    return cell


def _build_averaged_story(data: "PDFReportData") -> list:
    """Build and return the reportlab story list for an averaged-result report.

    Called by export_pdf and export_multi_tap_pdf.

    Mirrors Swift PDFReportContentView (PDFReportGenerator.swift).
    """
    from xml.sax.saxutils import escape

    from guitar_tap._version import __version_string__ as _app_version
    from reportlab.lib import colors
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import Flowable, Spacer

    from guitar_tap.models import guitar_mode as GM
    from guitar_tap.models import guitar_type as GT_module
    from guitar_tap.models import measurement_type as MT
    from guitar_tap.models import plate_stiffness_preset as PSP

    # ── Unpack PDFReportData into local names used by the story builder ───
    mt_str           = data.measurement_type_str
    gt_str           = data.guitar_type_str
    min_freq         = data.min_freq
    max_freq         = data.max_freq
    range_peaks      = data.peaks
    selected_ids     = data.selected_peak_ids
    peak_modes       = data.peak_modes
    peak_mode_overrides = data.peak_mode_overrides
    plate_props      = data.plate_properties
    brace_props      = data.brace_properties
    # G_LC is read from the plate's own gore_shear_modulus (mirrors Swift props.goreShearModulus).
    glc_pa           = plate_props.gore_shear_modulus if plate_props is not None else None
    guitar_body_length = data.guitar_body_length
    guitar_body_width  = data.guitar_body_width
    plate_stiffness  = data.plate_stiffness
    _preset_str      = data.plate_stiffness_preset_str
    spectrum_image_data = data.spectrum_image_data
    # Compute gore target thickness live — mirrors Swift PDFReportContentView calling
    # props.goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:).
    gore_thickness_mm: float | None = None
    if plate_props is not None:
        gore_thickness_mm = plate_props.gore_target_thickness(
            guitar_body_length, guitar_body_width, plate_stiffness,
        )

    try:
        mt = MT.MeasurementType(mt_str)
    except ValueError:
        mt = MT.MeasurementType.GENERIC

    try:
        gt = GT_module.GuitarType(gt_str)
    except Exception:
        gt = GT_module.GuitarType.GENERIC

    try:
        _preset = PSP.PlateStiffnessPreset(_preset_str)
    except ValueError:
        _preset = PSP.PlateStiffnessPreset.STEEL_STRING_TOP

    # Measurement timestamp — unified locale-aware display (local time).
    from guitar_tap.utilities.date_format import format_display_datetime
    datetime_str = format_display_datetime(data.timestamp)

    # Visible (selected) peaks, sorted by frequency
    visible_peaks = sorted(
        [p for p in range_peaks if p.id in selected_ids],
        key=lambda p: p.frequency,
    )

    # ── Geometry (mirrors Swift) ──────────────────────────────────────────
    MARGIN        = 36             # 36 pt on every side (pt == 1 in reportlab)
    CONTENT_W     = 612 - 2 * MARGIN   # 540 pt

    # ── Accent colour (matches Swift Color(red:0.15, green:0.35, blue:0.75)) ──
    ACCENT = colors.Color(0.15, 0.35, 0.75)
    SECONDARY = colors.Color(0.45, 0.45, 0.45)
    # Mirrors Swift Color.gray.opacity(...). SwiftUI's Color.gray is approx
    # RGB (0.5, 0.5, 0.5) at full opacity.
    BG_GREY   = colors.Color(0.5, 0.5, 0.5, 0.07)       # gray opacity 0.07
    BG_LIGHT  = colors.Color(0.5, 0.5, 0.5, 0.06)       # gray opacity 0.06 for sub-tables
    BG_ACCENT = colors.Color(0.15, 0.35, 0.75, 0.07)  # blue accent bg for Gore box
    DIVIDER   = colors.Color(0.5, 0.5, 0.5, 0.3)

    def _hex(c: colors.Color) -> str:
        return f"#{int(c.red*255):02x}{int(c.green*255):02x}{int(c.blue*255):02x}"

    # ── Quality helpers (mirrors Swift extensions) ────────────────────────
    def _quality_color(label: str) -> colors.Color:
        """A WoodQuality label's colour: its role's light value (the report is drawn on white)."""
        from guitar_tap.models.material_properties import WoodQuality as _WQ
        return _light(palette.quality_role(_WQ(label)))

    def _mode_color(mode: GM.GuitarMode) -> colors.Color:
        """A guitar mode's colour: its role's light value. Mirrors Swift PDFReportGenerator."""
        return _light(palette.mode_role(mode))

    def _light(role: palette.Role) -> colors.Color:
        return colors.HexColor(palette.pair(role).light)

    # ── Custom Flowables ──────────────────────────────────────────────────

    class _DotFlowable(Flowable):
        """Small filled circle — mirrors Swift Circle().fill(color) in tapInstructionRow."""
        _DOT_SIZE = 7  # 7 pt diameter, matching Swift

        def __init__(self, hex_color: str):
            super().__init__()
            self._color = colors.HexColor(hex_color)

        def draw(self):
            r = self._DOT_SIZE / 2
            self.canv.setFillColor(self._color)
            self.canv.setStrokeColor(self._color)
            # The flowable's top is the row's top; Swift's .padding(.top, 2) puts the dot's centre
            # 2 + r below it, i.e. r - 2 above this 7 pt box's bottom.
            self.canv.circle(r, r - 2, r, fill=1, stroke=0)

        def wrap(self, avail_w, avail_h):
            return (self._DOT_SIZE, self._DOT_SIZE)

    class _AnalysisBox(Flowable):
        """Rounded grey box with a primary value and quality label on the right.

        Mirrors Swift analysisBox(): HStack(top) { VStack(spacing 2) { title 10 bold, value 18 bold,
        subtitle 9 }, VStack(trailing, spacing 2) { detail 10, detailSubtitle 9, hint 9 italic } },
        padded 10.
        """
        PAD = 10

        def __init__(self, title, value, subtitle, detail, detail_color,
                     detail_subtitle=None, hint=None, width=None):
            super().__init__()
            self._title    = title
            self._value    = value
            self._subtitle = subtitle
            self._detail   = detail
            self._dc       = detail_color
            self._dsub     = detail_subtitle
            self._hint     = hint
            self._w        = width or 250
            # The left column sets the height: title 10 + 2 + value 18 + 2 + subtitle 9.
            self.height    = self.PAD + 10 + 2 + 18 + 2 + 9 + self.PAD

        def _at(self, text, x, top, font, size, color, right=False):
            """Draw ``text`` with its line box's top ``top`` below the box's top, as Swift places a Text."""
            c = self.canv
            c.setFont(font, size)
            c.setFillColor(color)
            y = self.height - top - _SWIFT_ASCENT * size
            (c.drawRightString if right else c.drawString)(x, y, text)

        def draw(self):
            P = self.PAD
            # Background rounded rect — uses BG_GREY (Swift Color.gray.opacity(0.07))
            self.canv.setFillColor(BG_GREY)
            self.canv.roundRect(0, 0, self._w, self.height, 6, stroke=0, fill=1)
            # Left side: title → big value → subtitle
            self._at(self._title, P, P, "Helvetica-Bold", 10, SECONDARY)
            self._at(self._value, P, P + 10 + 2, "Helvetica-Bold", 18, colors.black)
            if self._subtitle:
                self._at(self._subtitle, P, P + 10 + 2 + 18 + 2, "Helvetica", 9, SECONDARY)
            # Right side: detail quality → detail subtitle → hint
            right = self._w - P
            self._at(self._detail, right, P, "Helvetica", 10, self._dc, right=True)
            top = P + 10 + 2
            if self._dsub:
                self._at(self._dsub, right, top, "Helvetica", 9, SECONDARY, right=True)
                top += 9 + 2
            if self._hint:
                self._at(self._hint, right, top, "Helvetica-Oblique", 9, SECONDARY, right=True)

        def wrap(self, avail_w, avail_h):
            return (self._w, self.height)

    # ── Section builders (mirror Swift's views) ───────────────────────────
    def _separator() -> list:
        """Spacer 14 · sectionDivider · Spacer 14 — between Swift's analysis blocks."""
        return [Spacer(1, 14), _rule(CONTENT_W, 1, DIVIDER), Spacer(1, 14)]

    def _pprow(label: str, value: str):
        """Swift platePropRow: HStack(spacing 6) { label 10 secondary, value 10 bold }."""
        return _text(f"<font color='#737373'>{escape(label)}:</font>  <b>{escape(value)}</b>", 10, markup=True)

    def _qrow(label: str, value: float, quality: str):
        """Swift specificModulusRow: platePropRow with the value and a 9 pt quality in its colour."""
        hex_c = _hex(_quality_color(quality))
        return _text(
            f"<font color='#737373'>{escape(label)}:</font>  "
            f"<b><font color='{hex_c}'>{fp.string(value, fp.SPECIFIC_MODULUS)}</font></b>  "
            f"<font color='{hex_c}' size='9'>({escape(quality)})</font>",
            10, markup=True,
        )

    def _grey_box(heading: str, rows: list, col_widths: list, style: list | None = None):
        """Swift dimensionsSubsection / plateBodyDimensionsPDFSection: VStack(spacing 4) { heading 10
        bold, rows of 10 pt props }, padded 6 in a grey box."""
        cells = [[_text(heading, 10, bold=True, color=SECONDARY)] + [[] for _ in col_widths[1:]]] + rows
        return _grid(cells, col_widths, [
            ("SPAN",          (0, 0), (-1, 0)),
            ("BACKGROUND",    (0, 0), (-1, -1), BG_LIGHT),
            ("LEFTPADDING",   (0, 0), (0, -1), 6),
            ("RIGHTPADDING",  (-1, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, 0), 6),
            ("TOPPADDING",    (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
            ("ROUNDEDCORNERS", [4]),
            *(style or []),
        ])

    def _sample_dimensions(dims, density_kg_m3: float):
        """Swift dimensionsSubsection: Length | Width | Thickness, then Mass | Density, in three equal
        columns inside the box's 6 pt padding."""
        col = (CONTENT_W - 12) / 3
        return _grey_box("Sample Dimensions", [
            [
                _pprow("Length", f"{fp.string(dims.length_mm, fp.LINEAR_DIMENSION_MM)} mm") if dims.length_mm else [],
                _pprow("Width", f"{fp.string(dims.width_mm, fp.LINEAR_DIMENSION_MM)} mm") if dims.width_mm else [],
                _pprow("Thickness", f"{fp.string(dims.thickness_mm, fp.LINEAR_DIMENSION_MM)} mm") if dims.thickness_mm else [],
            ],
            [
                _pprow("Mass", f"{fp.string(dims.mass_g, fp.MASS_G)} g") if dims.mass_g else [],
                _pprow("Density", f"{fp.string(density_kg_m3/1000, fp.DENSITY_G_PER_CM3)} g/cm³"),
                [],
            ],
        ], [col + 6, col, col + 6])

    def _overall_quality(value: str, color: colors.Color):
        """Swift's Overall Quality row: HStack { label 10 bold, value 13 bold }, padded 8 in a grey
        box; the label is centred on the value's line."""
        label = "Overall Quality:"
        label_w = stringWidth(label, "Helvetica-Bold", 10) + 8
        return _grid(
            [[[Spacer(1, (13 - 10) / 2), _text(label, 10, bold=True, color=SECONDARY)],
              _text(value, 13, bold=True, color=color)]],
            [8 + label_w, CONTENT_W - 8 - label_w],
            [
                ("BACKGROUND",    (0, 0), (-1, -1), BG_GREY),
                ("LEFTPADDING",   (0, 0), (0, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("ROUNDEDCORNERS", [4]),
            ],
        )

    def _two_columns(left: list, right: list):
        """Two side-by-side VStack(spacing 6) columns of 10 pt rows — Swift's property block."""
        def stack(rows):
            out: list = []
            for row in rows:
                if out:
                    out.append(Spacer(1, 6))
                out.append(row)
            return out
        return _grid([[stack(left), stack(right)]], [CONTENT_W / 2] * 2)

    def _tap_instructions(title: str, steps: list, foot: str) -> list:
        """Swift tapInstructionsSection: VStack(spacing 6) { divider, Spacer 6, heading 10 bold, one
        row per tap, foot 9 italic }, then Spacer 14. A row is HStack(top, spacing 6) { 7 pt dot,
        VStack(spacing 1) { title 10 bold, detail 9 } }."""
        out: list = [_rule(CONTENT_W, 1, DIVIDER), Spacer(1, 6 + 6 + 6), _text(title, 10, bold=True)]
        for dot_color, label, detail in steps:
            out.append(Spacer(1, 6))
            out.append(_grid(
                [[_DotFlowable(dot_color),
                  [_text(label, 10, bold=True), Spacer(1, 1), _text(detail, 9, color=SECONDARY)]]],
                [7 + 6, CONTENT_W - 7 - 6],
            ))
        out += [Spacer(1, 6), _text(foot, 9, italic=True, color=SECONDARY), Spacer(1, 14)]
        return out

    # ── Build story ───────────────────────────────────────────────────────
    story: list = _report_header("Tap Tone Analysis Report", datetime_str, ACCENT, SECONDARY, CONTENT_W)

    # --- METADATA ---------------------------------------------------------
    # No recorded microphone means it is unknown (a played file, say): say so, and keep the calibration.
    cal_suffix = f" · calibrated ({data.calibration_name})" if data.calibration_name else " · uncalibrated"
    meta = []
    if data.measurement_name:
        meta.append(("Measurement Name", data.measurement_name))
    meta.append(("Type", mt_str))
    if data.notes:
        meta.append(("Notes", data.notes))
    meta.append((
        "Frequency Range",
        f"{_ext.formatted_as_frequency(min_freq)} – {_ext.formatted_as_frequency(max_freq)}",
    ))
    meta.append(("Microphone", (data.microphone_name or "unknown") + cal_suffix))
    story += _meta_rows(meta, 120, SECONDARY, colors.black, CONTENT_W)
    story.append(Spacer(1, 14))

    # --- SPECTRUM IMAGE ---------------------------------------------------
    # Swift: VStack(spacing 6) { "Frequency Spectrum" 12 bold, the image }, then Spacer 14.
    if spectrum_image_data:
        story.append(_text("Frequency Spectrum", 12, bold=True, color=SECONDARY))
        story.append(Spacer(1, 6))
        story.append(_spectrum_image_matte(spectrum_image_data, CONTENT_W))
        story.append(Spacer(1, 14))

    # --- SECTION DIVIDER --------------------------------------------------
    story.append(_rule(CONTENT_W, 1, DIVIDER))
    story.append(Spacer(1, 14))

    # --- PEAKS TABLE ------------------------------------------------------
    # Swift peaksSection: VStack(spacing 6) { "Detected Peaks" 13 bold, the header (10 bold, padded 3
    # vertically and 6 horizontally, 2 below), one row per peak (10, padded 2 / 6) }.
    # Role colors — mirrors Swift .blue / .orange / .purple
    _ROLE_BLUE   = "#0077FF"
    _ROLE_ORANGE = "#FF9500"
    _ROLE_PURPLE = "#AF52DE"

    story.append(_text("Detected Peaks", 13, bold=True))
    story.append(Spacer(1, 6))

    if not visible_peaks:
        story.append(_text("No peaks detected in this measurement.", 11, color=SECONDARY))
    else:
        # Column widths mirror Swift's .frame widths (90 · 80 · 80, then Mode, or Q 70 + Role), the
        # first widened by the row's 6 pt leading padding.
        is_guitar = mt.is_guitar
        if is_guitar:
            col_w = [96, 80, 80, CONTENT_W - 256]
            hdr_row = ["Frequency", "Magnitude", "Note", "Mode"]
        else:
            col_w = [96, 80, 80, 70, CONTENT_W - 326]
            hdr_row = ["Frequency", "Magnitude", "Note", "Q Factor", "Role"]

        def _effective_mode_label(peak) -> tuple[str, bool]:
            """(label, is_overridden) — mirrors Swift effectiveModeLabel."""
            ovr = peak_mode_overrides.get(peak.id)
            if ovr:
                return ovr + " *", True
            mode = peak_modes.get(peak.id, GM.GuitarMode.UNKNOWN)
            return mode.display_name if hasattr(mode, "display_name") else str(mode), False

        def _colored(text: str, hex_color: str, italic: bool = False):
            return _text(f"<font color='{hex_color}'>{'<i>' if italic else ''}{escape(text)}{'</i>' if italic else ''}</font>",
                         10, markup=True)

        def _role_cell(peak):
            """A coloured Role cell — mirrors Swift peakRoleCell."""
            if mt == MT.MeasurementType.PLATE:
                if peak.id == data.selected_longitudinal_peak_id:
                    return _colored("Longitudinal (fL)", _ROLE_BLUE)
                if peak.id == data.selected_cross_peak_id:
                    return _colored("Cross-grain (fC)", _ROLE_ORANGE)
                if peak.id == data.selected_flc_peak_id:
                    return _colored("Diagonal (fLC)", _ROLE_PURPLE)
                return _text("–", 10)
            elif mt == MT.MeasurementType.BRACE:
                if peak.id == data.selected_longitudinal_peak_id:
                    return _colored("Longitudinal (fL)", _ROLE_BLUE)
                return _text("–", 10)
            return []

        peak_rows: list[list] = []
        for peak in visible_peaks:
            cells = [
                _text(f"{fp.string(peak.frequency, fp.PEAK_FREQUENCY_HZ)} Hz", 10),
                _text(f"{fp.string(peak.magnitude, fp.PEAK_MAGNITUDE_DB)} dB", 10),
                _text(peak.pitch_note or "–", 10),
            ]
            if is_guitar:
                label, is_ovr = _effective_mode_label(peak)
                # Color is override-aware too (matching the label): a predefined override → that
                # mode's color; a freeform label → user-defined teal; else the auto mode.
                _ovr = peak_mode_overrides.get(peak.id)
                if _ovr:
                    _resolved = GM.GuitarMode.from_display_name(_ovr)
                    if _resolved is None:
                        mc = _light(palette.Role.MODE_USER_DEFINED)
                    else:
                        mc = _mode_color(_resolved)
                else:
                    mc = _mode_color(peak_modes.get(peak.id, GM.GuitarMode.UNKNOWN))
                cells.append(_colored(label, _hex(mc), italic=is_ovr))
            else:
                cells.append(_text(f"{fp.string(peak.quality, fp.Q_FACTOR)}", 10))
                cells.append(_role_cell(peak))
            peak_rows.append(cells)

        story.append(_grid(
            [[_text(h, 10, bold=True, color=SECONDARY) for h in hdr_row]],
            col_w,
            [
                ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.1)),
                ("LEFTPADDING",   (0, 0), (0, -1), 6),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROUNDEDCORNERS", [4]),
            ],
        ))
        story.append(Spacer(1, 2))
        # Each row: the stack's 6 pt spacing, then the row's own 2 pt padding above and below.
        story.append(_grid(peak_rows, col_w, [
            ("LEFTPADDING",   (0, 0), (0, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 6 + 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

    story.append(Spacer(1, 14))

    # --- ANALYSIS RESULTS ------------------------------------------------
    if mt.is_guitar:
        # Swift guitarAnalysisSection: VStack(spacing 10) { "Analysis Results" 13 bold, HStack(top,
        # spacing 16) of boxes, each filling its share of the width }.
        story.append(_text("Analysis Results", 13, bold=True))
        story.append(Spacer(1, 10))

        box_specs: list[dict] = []
        if data.decay_time is not None:
            try:
                decay_label = _ext.decay_quality_label(data.decay_time, gt)
                dc = colors.HexColor(_ext.decay_quality_color(data.decay_time, gt).light)
            except Exception:
                decay_label = ""
                dc = colors.Color(0.45, 0.45, 0.45)
            box_specs.append(dict(
                title="Ring-Out Time",
                value=f"{fp.string(data.decay_time, fp.DECAY_TIME_S)} s",
                subtitle="Time to decay 15 dB",
                detail=decay_label,
                detail_subtitle="Sustain quality",
                detail_color=dc,
            ))

        ratio = data.tap_tone_ratio
        if ratio is not None:
            box_specs.append(dict(
                title="Tap Tone Ratio",
                value=f"{fp.string(ratio, fp.DECAY_RATIO)} : 1",
                subtitle="Top / Air",
                detail=_ext.tap_tone_ratio_quality_label(ratio),
                detail_color=colors.HexColor(_ext.tap_tone_ratio_quality_color(ratio).light),
                hint="Ideal: 1.9–2.1",
            ))

        if box_specs:
            box_w = (CONTENT_W - 16 * (len(box_specs) - 1)) / len(box_specs)
            boxes = [_AnalysisBox(width=box_w, **spec) for spec in box_specs]
            if len(boxes) == 2:
                story.append(_grid([[boxes[0], Spacer(16, 1), boxes[1]]], [box_w, 16, box_w]))
            else:
                story.append(boxes[0])

    elif mt == MT.MeasurementType.PLATE and plate_props is not None:
        # Material analysis order mirrors Swift analysisSection (plate):
        #   Sample Dimensions -> Body Dimensions -> Gore Target Thickness -> Plate Properties,
        # separated by Spacer 14 · divider · Spacer 14 (also after the Gore slot when there is no target).
        dims = plate_props.dimensions

        if dims:
            story.append(_sample_dimensions(dims, plate_props.density_kg_m3))
            story += _separator()

        # -- Body Dimensions (Gore inputs) --------------------------------
        # Mirrors Swift plateBodyDimensionsPDFSection: finished-guitar body dims (a, b)
        # and panel stiffness (f_vs) -- feeds only the Gore target below.
        if _preset == PSP.PlateStiffnessPreset.CUSTOM:
            preset_label = f"f_vs = {int(plate_stiffness)} (custom)"
        else:
            preset_label = f"f_vs = {int(plate_stiffness)} ({_preset_str})"
        half = (CONTENT_W - 12) / 2
        story.append(_grey_box("Body Dimensions", [
            [
                _pprow("Body Length (a)", f"{fp.string(guitar_body_length, fp.BODY_DIMENSION_MM)} mm"),
                _pprow("Lower Bout Width (b)", f"{fp.string(guitar_body_width, fp.BODY_DIMENSION_MM)} mm"),
            ],
            [_pprow("Panel Stiffness", preset_label), []],
        ], [half + 6, half + 6], [("SPAN", (0, 2), (-1, 2))]))
        story += _separator()

        # -- Gore Target Thickness (just the number) ----------------------
        # Swift goreThicknessPDFSection: VStack(spacing 4) { heading 10 bold, the thickness 16 bold },
        # padded 6 in an accent-tinted box.
        if gore_thickness_mm is not None:
            story.append(_grid(
                [[[_text("Gore Target Thickness", 10, bold=True, color=SECONDARY),
                   Spacer(1, 4),
                   _text(f"{fp.string(gore_thickness_mm, fp.GORE_THICKNESS_MM)} mm", 16, bold=True, color=ACCENT)]]],
                [CONTENT_W],
                [
                    ("BACKGROUND",    (0, 0), (-1, -1), BG_ACCENT),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                    ("TOPPADDING",    (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("ROUNDEDCORNERS", [4]),
                ],
            ))
        story += _separator()

        # -- Plate Properties ---------------------------------------------
        # Swift plateSection: VStack(spacing 10) { title 13 bold, two property columns, GLC row,
        # ratios, Overall Quality }.
        # (fL / fC / fLC are inputs, shown in the Detected Peaks table -- not repeated here.)
        story.append(_text("Plate Properties", 13, bold=True))
        story.append(Spacer(1, 10))
        story.append(_two_columns(
            [
                _pprow("Speed of Sound (L)", f"{fp.string(plate_props.c_long_m_s, fp.SPEED_OF_SOUND_MS)} m/s"),
                _pprow("Speed of Sound (C)", f"{fp.string(plate_props.c_cross_m_s, fp.SPEED_OF_SOUND_MS)} m/s"),
                _pprow("Young's Modulus (L)", f"{fp.string(plate_props.youngsModulusLongGPa, fp.YOUNGS_MODULUS_GPA)} GPa"),
                _pprow("Young's Modulus (C)", f"{fp.string(plate_props.youngsModulusCrossGPa, fp.YOUNGS_MODULUS_GPA)} GPa"),
            ],
            [
                _qrow("Specific Modulus (L)", plate_props.specific_modulus_long, plate_props.quality_long),
                _qrow("Specific Modulus (C)", plate_props.specific_modulus_cross, plate_props.quality_cross),
                _pprow("Radiation Ratio (L)", f"{fp.string(plate_props.radiation_ratio_long, fp.RADIATION_RATIO)}"),
                _pprow("Radiation Ratio (C)", f"{fp.string(plate_props.radiation_ratio_cross, fp.RADIATION_RATIO)}"),
            ],
        ))
        story.append(Spacer(1, 10))

        if glc_pa is not None and glc_pa > 0:
            story.append(_pprow("GLC (Shear Modulus)", f"{fp.string(glc_pa/1e9, fp.SHEAR_MODULUS_GPA)} GPa"))
        else:
            story.append(_text("GLC assumed 0 — fLC tap not performed", 10, italic=True, color=SECONDARY))
        story.append(Spacer(1, 10))

        # Ratios: two side-by-side VStack(spacing 2) { row, typical-range note 9 italic }.
        story.append(_grid([[
            [
                _pprow("Cross/Long Ratio", f"{fp.string(plate_props.cross_long_ratio, fp.CROSS_LONG_RATIO)}"),
                Spacer(1, 2),
                _text("typical: 0.04–0.08", 9, italic=True, color=SECONDARY),
            ],
            [
                _pprow("Long/Cross Ratio", f"{fp.string(plate_props.long_cross_ratio, fp.LONG_CROSS_RATIO)}"),
                Spacer(1, 2),
                _text("typical: 12–25", 9, italic=True, color=SECONDARY),
            ],
        ]], [CONTENT_W / 2] * 2))
        story.append(Spacer(1, 10))
        story.append(_overall_quality(plate_props.overall_quality, _quality_color(plate_props.overall_quality)))

    elif mt == MT.MeasurementType.BRACE and brace_props is not None:
        # Material analysis order mirrors Swift analysisSection (brace):
        #   Sample Dimensions -> Brace Properties.
        dims = brace_props.dimensions

        if dims:
            story.append(_sample_dimensions(dims, brace_props.density_kg_m3))
            story += _separator()

        # -- Brace Properties ---------------------------------------------
        # (fL is an input, shown in the Detected Peaks table -- not repeated here.)
        story.append(_text("Brace Properties", 13, bold=True))
        story.append(Spacer(1, 10))
        story.append(_two_columns(
            [
                _pprow("Speed of Sound", f"{fp.string(brace_props.c_long_m_s, fp.SPEED_OF_SOUND_MS)} m/s"),
                _pprow("Young's Modulus (E)", f"{fp.string(brace_props.youngsModulusLongGPa, fp.YOUNGS_MODULUS_GPA)} GPa"),
            ],
            [
                _qrow("Specific Modulus", brace_props.specific_modulus, brace_props.quality),
                _pprow("Radiation Ratio", f"{fp.string(brace_props.radiation_ratio, fp.RADIATION_RATIO)}"),
            ],
        ))
        story.append(Spacer(1, 10))
        story.append(_overall_quality(brace_props.quality, _quality_color(brace_props.quality)))

    # --- TAP INSTRUCTIONS (plate / brace only, at end — mirrors live view ordering) ---
    # Flush (0 gap) against the preceding analysis section, as in Swift.
    if mt == MT.MeasurementType.PLATE:
        has_flc = bool(data.selected_flc_peak_id)
        steps = [
            (_ROLE_BLUE, "1. Longitudinal (fL) Tap",
             "Hold plate at 22% from one end along the length, near one long edge (not at the width node). Tap center."),
            (_ROLE_ORANGE, "2. Cross-grain (fC) Tap",
             "Rotate 90°. Hold plate at 22% from one end along the width, near one short edge (not at the length node). Tap center."),
        ]
        if has_flc:
            steps.append((_ROLE_PURPLE, "3. Diagonal (fLC) Tap",
                          "Hold plate at the midpoint of one long edge. Tap near the opposite corner (~22% from both the end and the side). Measures shear stiffness."))
        story += _tap_instructions(
            "Three-Tap Measurement Process:" if has_flc else "Two-Tap Measurement Process:",
            steps,
            "The strongest peak from each tap is auto-selected.",
        )
    elif mt == MT.MeasurementType.BRACE:
        story += _tap_instructions(
            "Single-Tap Measurement (fL only):",
            [(_ROLE_BLUE, "1. Longitudinal (fL) Tap", "Hold brace at 22% from one end along the length. Tap center.")],
            "The strongest peak is auto-selected.",
        )

    # --- FOOTER -----------------------------------------------------------
    story += _report_footer(f"Generated by GuitarTap Python {_app_version}", SECONDARY, CONTENT_W)

    return story


# Report page geometry — matches Swift PDFReportContentView (US Letter width, 36 pt margins).
_PAGE_W = 612
_MARGIN = 36
_CONTENT_W = _PAGE_W - 2 * _MARGIN
# Zero frame padding so content spans the full 540 pt width (matching Swift's margin-only
# layout) and so the measure/build frames agree exactly.
_FRAME_PAD = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)


def _measure_story_height(story: list) -> float:
    """Measure the exact vertical space a story consumes at the report content width.

    Swift renders each report page as a SINGLE variable-height page: ImageRenderer's PDF
    media box is the SwiftUI view's natural size (e.g. 612 × 1107), so a page never
    paginates. To mirror that, lay the story out on a throwaway very-tall frame and read
    back how far the frame cursor descended — that is the natural content height.

    The caller sizes the real page to this height (+ margins), instead of a fixed Letter
    page that would spill a tall report onto extra pages.
    """
    import io

    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Frame

    big = 20_000.0
    frame = Frame(_MARGIN, _MARGIN, _CONTENT_W, big - 2 * _MARGIN, id="measure", **_FRAME_PAD)
    frame.addFromList(list(story), Canvas(io.BytesIO(), pagesize=(_PAGE_W, big)))
    top = _MARGIN + (big - 2 * _MARGIN)   # frame top edge (y grows upward, no padding)
    return top - frame._y                  # height actually used by the flowables


def _build_variable_page_pdf(output_path: str, story: list) -> None:
    """Render a story to a single variable-height PDF page sized to fit its content."""
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    page_h = _measure_story_height(story) + 2 * _MARGIN + 2  # +2 pt guard keeps it 1 page
    frame = Frame(_MARGIN, _MARGIN, _CONTENT_W, page_h - 2 * _MARGIN, id="main", **_FRAME_PAD)
    doc = BaseDocTemplate(
        output_path,
        pagesize=(_PAGE_W, page_h),
        pageTemplates=[PageTemplate(id="report", frames=[frame])],
        leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=_MARGIN, bottomMargin=_MARGIN,
    )
    doc.build(story)


def export_pdf(data: PDFReportData, output_path: str) -> None:
    """Render a tap-tone averaged-result report to PDF.

    Mirrors Swift PDFReportGenerator.generate(data:) in PDFReportGenerator.swift.
    Delegates story construction to _build_averaged_story.
    """
    _build_variable_page_pdf(output_path, _build_averaged_story(data))


# ── Comparison Mode Support ────────────────────────────────────────────────────
# The functions below mirror Swift's comparison export:
#   - renderSpectrumImageForComparison  (ExportableSpectrumChart.swift)
#   - ComparisonPDFReportData           (PDFReportGenerator.swift)
#   - generateComparison / ComparisonPDFReportContentView (PDFReportGenerator.swift)
#   - exportComparisonPDFReport         (TapToneAnalysisView+Export.swift)


def render_spectrum_image_for_comparison(measurement: TapToneMeasurement) -> "bytes | None":
    """Render the comparison overlay chart to PNG bytes for a saved comparison record.

    Mirrors Swift renderSpectrumImageForComparison(_:) in ExportableSpectrumChart.swift.

    Returns PNG bytes, or None if the measurement is not a comparison record or has
    no entries.
    """
    from guitar_tap.views.exportable_spectrum_chart import make_exportable_spectrum_view

    if not measurement.is_comparison:
        return None
    entries = measurement.comparison_entries
    if not entries:
        return None

    # Build comparison_spectra list matching the format expected by make_exportable_spectrum_view
    # when passed as material_spectra (each with frequencies, magnitudes, color, label).
    comparison_spectra = []
    for entry in entries:
        comps = (entry.color_components + [1.0])[:4]
        r, g, b, _a = comps
        # make_exportable_spectrum_view accepts color as an (r,g,b) tuple or named color string.
        color = (int(r * 255), int(g * 255), int(b * 255))
        comparison_spectra.append({
            "frequencies": list(entry.snapshot.frequencies),
            "magnitudes":  list(entry.snapshot.magnitudes),
            "color": color,
            "label": entry.label,
        })

    snaps = [e.snapshot for e in entries]
    min_freq = float(min(s.min_freq for s in snaps))
    max_freq = float(max(s.max_freq for s in snaps))
    min_db   = float(min(s.min_db   for s in snaps))
    max_db   = float(max(s.max_db   for s in snaps))

    loc = measurement.measurement_name
    chart_title = f"Comparison — {loc}" if (loc and loc.strip()) else "Comparison"
    date_label = str(measurement.timestamp) if measurement.timestamp else ""

    return make_exportable_spectrum_view(
        frequencies=[],
        magnitudes=[],
        min_freq=min_freq,
        max_freq=max_freq,
        min_db=min_db,
        max_db=max_db,
        peaks=[],
        material_spectra=comparison_spectra,
        date_label=date_label,
        chart_title=chart_title,
    )


def render_spectrum_image_for_multi_tap(measurement: TapToneMeasurement) -> "bytes | None":
    """Render the per-tap overlay chart to PNG bytes for a saved multi-tap record.

    Mirrors Swift renderSpectrumImageForMultiTap(_:) in ExportableSpectrumChart.swift.

    Returns PNG bytes, or None if the measurement has no tap entries.
    """
    from guitar_tap.views.exportable_spectrum_chart import make_exportable_spectrum_view

    tap_entries = measurement.tap_entries
    if not tap_entries:
        return None

    comparison_spectra = []
    for idx, entry in enumerate(tap_entries):
        color = MULTI_TAP_PALETTE[idx % len(MULTI_TAP_PALETTE)]
        comparison_spectra.append({
            "frequencies": list(entry.snapshot.frequencies),
            "magnitudes":  list(entry.snapshot.magnitudes),
            "color": color,
            "label": f"Tap {entry.tap_index}",
        })

    # Append averaged entry using the measurement's spectrum snapshot
    if measurement.spectrum_snapshot:
        avg_snap = measurement.spectrum_snapshot
        comparison_spectra.append({
            "frequencies": list(avg_snap.frequencies),
            "magnitudes":  list(avg_snap.magnitudes),
            "color": MULTI_TAP_AVG_COLOR,
            "label": "Averaged",
        })

    snaps = [e.snapshot for e in tap_entries]
    min_freq = float(min(s.min_freq for s in snaps))
    max_freq = float(max(s.max_freq for s in snaps))
    min_db   = float(min(s.min_db   for s in snaps))
    max_db   = float(max(s.max_db   for s in snaps))

    loc = measurement.measurement_name
    # Mirrors Swift: "Tap Comparison — \(measurement.measurementName ?? "Multi-Tap")"
    chart_title = f"Tap Comparison — {loc}" if (loc and loc.strip()) else "Tap Comparison — Multi-Tap"
    date_label = str(measurement.timestamp) if measurement.timestamp else ""

    return make_exportable_spectrum_view(
        frequencies=[],
        magnitudes=[],
        min_freq=min_freq,
        max_freq=max_freq,
        min_db=min_db,
        max_db=max_db,
        peaks=[],
        measurement_type_str="classical",
        material_spectra=comparison_spectra,
        date_label=date_label,
        chart_title=chart_title,
    )


@dataclass
class ComparisonPDFReportData:
    """All data required to render a PDF comparison report.

    Mirrors Swift ComparisonPDFReportData struct (PDFReportGenerator.swift).

    Create from a saved comparison measurement with
    comparison_pdf_report_data_from_measurement(), or from live comparison state
    in tap_tone_analysis_view_export.py.
    """

    # Date/time the report was generated.  ISO-8601 string.
    # Mirrors Swift ComparisonPDFReportData.timestamp (Date).
    timestamp: str

    # User-supplied name for the comparison (from measurement_name), or None.
    # Mirrors Swift ComparisonPDFReportData.comparisonLabel.
    comparison_label: str | None

    # Free-text notes from the save form, or None.
    # Mirrors Swift ComparisonPDFReportData.notes.
    notes: str | None

    # PNG-encoded spectrum overlay chart image, or None if unavailable.
    # Mirrors Swift ComparisonPDFReportData.spectrumImageData.
    spectrum_image_data: bytes | None

    # Comparison entries — one per overlaid spectrum.
    # Mirrors Swift ComparisonPDFReportData.entries ([ComparisonEntry]).
    entries: list   # list[ComparisonEntry]

    # Resolved Air/Top/Back frequencies per entry.
    # Each tuple: (label, color_rgb, air_hz, top_hz, back_hz, override_modes) where *_hz may be None
    # and override_modes is a set of GuitarMode whose value is a user override (marked "*"/italic in
    # the table — only the multi-tap Averaged row ever sets it). Mirrors Swift
    # ComparisonPDFReportData.modeFrequencies (…, overrideModes: Set<GuitarMode>).
    mode_frequencies: list


def comparison_pdf_report_data_from_measurement(
    measurement: TapToneMeasurement,
    spectrum_image_data: "bytes | None" = None,
) -> ComparisonPDFReportData:
    """Build a ComparisonPDFReportData from a saved comparison TapToneMeasurement.

    If spectrum_image_data is not provided it is rendered from the measurement's
    comparisonEntries.

    Mirrors Swift PDFReportGenerator.comparisonData(for:).
    """
    from guitar_tap.models.guitar_mode import GuitarMode

    entries = measurement.comparison_entries or []

    if spectrum_image_data is None:
        spectrum_image_data = render_spectrum_image_for_comparison(measurement)

    mode_frequencies = []
    for entry in entries:
        comps = (entry.color_components + [1.0])[:4]
        r, g, b, _a = comps
        color_rgb = (int(r * 255), int(g * 255), int(b * 255))
        # Values come from the entry's stored definitive modes (self-describing, override-correct);
        # `mode_frequency` falls back to a positional re-derive only for a map-less entry. No override
        # tag on comparison rows (that marking is the multi-tap Averaged row's concern). Mirrors Swift
        # exportComparisonPDFReport's `freq(mode, entry)`.
        mode_frequencies.append((
            entry.label,
            color_rgb,
            entry.mode_frequency(GuitarMode.AIR),
            entry.mode_frequency(GuitarMode.TOP),
            entry.mode_frequency(GuitarMode.BACK),
            set(),
        ))

    return ComparisonPDFReportData(
        timestamp=measurement.timestamp,
        comparison_label=measurement.measurement_name or None,
        notes=measurement.notes or None,
        spectrum_image_data=spectrum_image_data,
        entries=entries,
        mode_frequencies=mode_frequencies,
    )


def multi_tap_comparison_pdf_report_data_from_measurement(
    measurement: TapToneMeasurement,
    spectrum_image_data: "bytes | None" = None,
) -> ComparisonPDFReportData:
    """A multi-tap measurement's per-tap comparison page: one row per tap (each tap's own modes) and the
    averaged row (the definitive, override-aware modes). Mirrors Swift
    PDFReportGenerator.multiTapComparisonData(for:)."""
    from guitar_tap.models.guitar_mode import GuitarMode
    from guitar_tap.models.tap_tone_analyzer_peak_analysis import TapToneAnalyzerPeakAnalysisMixin
    from guitar_tap.models.tap_tone_measurement import ComparisonEntry
    from guitar_tap.utilities.new_uuid import new_uuid

    if spectrum_image_data is None:
        spectrum_image_data = render_spectrum_image_for_multi_tap(measurement)

    cmp_entries: list[ComparisonEntry] = []
    for idx, entry in enumerate(measurement.tap_entries or []):
        r, g, b = MULTI_TAP_PALETTE[idx % len(MULTI_TAP_PALETTE)]
        sel_ids = set(entry.selected_peak_ids)
        cmp_entries.append(ComparisonEntry(
            id=new_uuid(),
            label=f"Tap {entry.tap_index}",
            color_components=[r / 255.0, g / 255.0, b / 255.0, 1.0],
            snapshot=entry.snapshot,
            peaks=[p for p in entry.peaks if p.id in sel_ids],
            guitar_type=entry.snapshot.guitar_type if entry.snapshot else None,
            source_measurement_id=None,
        ))
    avg_snap = measurement.spectrum_snapshot
    if avg_snap is not None:
        avg_sel_ids = measurement.effective_selected_peak_ids
        avg_r, avg_g, avg_b = MULTI_TAP_AVG_COLOR
        cmp_entries.append(ComparisonEntry(
            id=new_uuid(),
            label="Averaged",
            color_components=[avg_r / 255.0, avg_g / 255.0, avg_b / 255.0, 1.0],
            snapshot=avg_snap,
            peaks=[p for p in (measurement.peaks or []) if p.id in avg_sel_ids],
            guitar_type=avg_snap.guitar_type,
            source_measurement_id=None,
        ))

    avg_info = measurement.definitive_mode_info()
    mode_frequencies = []
    for cmp_entry in cmp_entries:
        c = cmp_entry.color_components
        color = (round(c[0] * 255), round(c[1] * 255), round(c[2] * 255))
        if cmp_entry.label == "Averaged":
            air_t = avg_info.get(GuitarMode.AIR)
            top_t = avg_info.get(GuitarMode.TOP)
            back_t = avg_info.get(GuitarMode.BACK)
            mode_frequencies.append((
                cmp_entry.label, color,
                air_t[0] if air_t is not None else None,
                top_t[0] if top_t is not None else None,
                back_t[0] if back_t is not None else None,
                {mode for mode, (_f, ov) in avg_info.items() if ov},
            ))
            continue
        mode_peaks = TapToneAnalyzerPeakAnalysisMixin.resolved_mode_peaks(
            cmp_entry.peaks, guitar_type=cmp_entry.guitar_type
        )
        air = mode_peaks.get(GuitarMode.AIR)
        top = mode_peaks.get(GuitarMode.TOP)
        back = mode_peaks.get(GuitarMode.BACK)
        mode_frequencies.append((
            cmp_entry.label, color,
            air.frequency if air is not None else None,
            top.frequency if top is not None else None,
            back.frequency if back is not None else None,
            set(),
        ))

    return ComparisonPDFReportData(
        timestamp=measurement.timestamp,
        comparison_label=measurement.measurement_name or None,
        notes=measurement.notes or None,
        spectrum_image_data=spectrum_image_data,
        entries=cmp_entries,
        mode_frequencies=mode_frequencies,
    )


def report_basename(measurement: TapToneMeasurement) -> str:
    """The exported report's file name, without extension. Mirrors Swift PDFReportData.baseFilename."""
    return measurement.export_stem_for("report")


def export_report_for_measurement(measurement: TapToneMeasurement, output_path: str) -> None:
    """Write a saved measurement's PDF report: a multi-tap measurement's two pages (the averaged result,
    then the per-tap comparison), a comparison's report, or the single report. What the measurement list
    exports. Mirrors Swift PDFReportGenerator.report(for:)."""
    if measurement.tap_entries:
        export_multi_tap_pdf(
            pdf_report_data_from_measurement(measurement, render_spectrum_image_for_measurement(measurement)),
            multi_tap_comparison_pdf_report_data_from_measurement(measurement),
            output_path,
        )
    elif measurement.is_comparison:
        export_comparison_pdf(comparison_pdf_report_data_from_measurement(measurement), output_path)
    else:
        export_pdf(
            pdf_report_data_from_measurement(measurement, render_spectrum_image_for_measurement(measurement)),
            output_path,
        )


def _build_comparison_story(data: ComparisonPDFReportData) -> list:
    """Build and return the reportlab story list for a comparison report.

    Called by export_comparison_pdf and export_multi_tap_pdf.

    Mirrors Swift ComparisonPDFReportContentView (PDFReportGenerator.swift).
    """

    from reportlab.graphics.shapes import Circle, Drawing
    from reportlab.lib import colors
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Spacer

    from guitar_tap._version import __version_string__ as _app_version
    from guitar_tap.utilities.date_format import format_display_datetime

    MARGIN = 36
    CONTENT_W = 612 - 2 * MARGIN

    # ── Colours ───────────────────────────────────────────────────────────────
    BLUE     = HexColor("#2659BF")  # GuitarTap brand blue
    SECONDARY = colors.Color(0.4, 0.4, 0.4)
    DARK     = colors.Color(0.1, 0.1, 0.1)

    story: list = _report_header("Comparison Report", format_display_datetime(data.timestamp), BLUE, SECONDARY, CONTENT_W)

    # ── Metadata ─────────────────────────────────────────────────────────────
    meta = []
    if data.comparison_label:
        meta.append(("Comparison", data.comparison_label))
    if data.notes:
        meta.append(("Notes", data.notes))
    # Use mode_frequencies count for live exports (entries is empty); fall back to entries.
    n = len(data.mode_frequencies) if data.mode_frequencies else len(data.entries)
    meta.append(("Spectra", f"{n} spectra compared"))

    # Frequency range from entries
    if data.entries:
        snaps = [e.snapshot for e in data.entries]
        try:
            min_f = min(s.min_freq for s in snaps)
            max_f = max(s.max_freq for s in snaps)
            meta.append((
                "Frequency Range",
                f"{_ext.formatted_as_frequency(min_f)} – {_ext.formatted_as_frequency(max_f)}",
            ))
        except Exception:
            pass
    # The comparison report's label frame is 100 pt (the measurement report's is 120).
    story += _meta_rows(meta, 100, SECONDARY, DARK, CONTENT_W)
    story.append(Spacer(1, 14))

    # ── Spectrum image ────────────────────────────────────────────────────────
    if data.spectrum_image_data:
        story.append(_text("Frequency Spectrum", 12, bold=True, color=SECONDARY))
        story.append(Spacer(1, 6))
        try:
            # Dark rounded matte around the image — mirrors Swift, which applies it at both sites.
            story.append(_spectrum_image_matte(data.spectrum_image_data, CONTENT_W))
        except Exception:
            pass
        story.append(Spacer(1, 14))

    story.append(_rule(CONTENT_W, 1, colors.Color(0.5, 0.5, 0.5, 0.3)))
    story.append(Spacer(1, 14))

    # ── Peak Mode Comparison table ────────────────────────────────────────────
    # Swift peakModeTableSection: VStack(spacing 6) { title 13 bold, the header (10 bold, padded 4
    # vertically), one row per spectrum (10, padded 4, top-aligned: a long name wraps, its dot and values
    # level with its first line) }. Each frequency column is 90 pt, right-aligned,
    # with 6 pt after it; the spectrum column takes the rest, padded 6.
    story.append(_text("Peak Mode Comparison", 13, bold=True, color=DARK))
    story.append(Spacer(1, 6))

    col_w = [CONTENT_W - 3 * 96, 96, 96, 96]
    cell_style = [
        ("LEFTPADDING",   (0, 0), (0, -1), 6),
        ("RIGHTPADDING",  (1, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    story.append(_grid(
        [[_text("Spectrum", 10, bold=True, color=SECONDARY)]
         + [_text(h, 10, bold=True, color=SECONDARY, align="right") for h in ("Air", "Top", "Back")]],
        col_w,
        cell_style + [
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
            ("ROUNDEDCORNERS", [4]),
        ],
    ))

    # The dot column: an 8 pt circle and 5 pt spacing, mirroring Swift HStack(spacing: 5) { Circle()
    # .frame(width: 8, height: 8); Text(...) }, the circle centred on the 10 pt line.
    _dot_col_w = 13.0

    from guitar_tap.models.guitar_mode import GuitarMode as _GM_pdf
    rows: list = []
    for row in data.mode_frequencies:
        # Tuples are 6-wide (…, override_modes); tolerate legacy 5-wide callers with an empty set.
        label, color_rgb, air_hz, top_hz, back_hz = row[:5]
        override_modes = row[5] if len(row) > 5 else set()

        def freq_cell(hz, is_override):
            if hz is None:
                return _text("—", 10, color=SECONDARY, align="right")
            # Overridden Averaged value: italic + " *" (mirrors Swift's overrideModes marking).
            if is_override:
                return _text(f"{fp.string(hz, fp.PEAK_FREQUENCY_HZ)} Hz *", 10, italic=True, color=DARK, align="right")
            return _text(f"{fp.string(hz, fp.PEAK_FREQUENCY_HZ)} Hz", 10, color=DARK, align="right")

        r8, g8, b8 = color_rgb
        dot = Drawing(8, 8)
        dot.add(Circle(4, 4, 4, fillColor=colors.Color(r8 / 255.0, g8 / 255.0, b8 / 255.0), strokeColor=None))
        label_cell = _grid(
            [[[Spacer(1, 1), dot], _text(label, 10, color=DARK)]],
            [_dot_col_w, col_w[0] - 6 - 6 - _dot_col_w],  # the column padded 6 each side,
        )
        rows.append([
            label_cell,
            freq_cell(air_hz,  _GM_pdf.AIR in override_modes),
            freq_cell(top_hz,  _GM_pdf.TOP in override_modes),
            freq_cell(back_hz, _GM_pdf.BACK in override_modes),
        ])
    if rows:
        # Each row: the stack's 6 pt spacing, then the row's own 4 pt padding.
        story.append(_grid(rows, col_w, cell_style + [("TOPPADDING", (0, 0), (-1, -1), 6 + 4)]))

    story += _report_footer(f"Generated by GuitarTap Python {_app_version}", SECONDARY, CONTENT_W)
    return story


def export_comparison_pdf(data: ComparisonPDFReportData, output_path: str) -> None:
    """Render a comparison tap-tone report to PDF.

    Mirrors Swift PDFReportGenerator.generateComparison(data:) in PDFReportGenerator.swift.
    Delegates story construction to _build_comparison_story.
    """
    _build_variable_page_pdf(output_path, _build_comparison_story(data))


# ── Multi-Tap PDF Report ───────────────────────────────────────────────────────
# Mirrors Swift PDFReportGenerator.generateMultiTapReport(averaged:comparison:).


def export_multi_tap_pdf(
    averaged: "PDFReportData",
    comparison: ComparisonPDFReportData,
    output_path: str,
) -> None:
    """Render a two-page multi-tap PDF report using reportlab.

    Page 1 — averaged-result single-measurement report (mirrors export_pdf).
    Page 2 — per-tap comparison report (mirrors export_comparison_pdf).

    The result is identical regardless of which view was displayed at export
    time, mirroring Swift PDFReportGenerator.generateMultiTapReport(averaged:comparison:).

    Each of the two pages is sized independently to its own content height — mirroring
    Swift, where the averaged page and the comparison page are each their view's natural
    size (e.g. 612 × 966), rather than a fixed Letter page that spills onto extra pages.
    """
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
    )

    page1_story = _build_averaged_story(averaged)
    page2_story = _build_comparison_story(comparison)

    page1_h = _measure_story_height(page1_story) + 2 * _MARGIN + 2
    page2_h = _measure_story_height(page2_story) + 2 * _MARGIN + 2

    # Each PageTemplate carries an onPage hook that stamps that page's media box, so the
    # two pages can differ in height within a single document.
    def _size_hook(height: float):
        def _apply(canvas, _doc):
            canvas.setPageSize((_PAGE_W, height))
        return _apply

    pt1 = PageTemplate(
        id="averaged",
        frames=[Frame(_MARGIN, _MARGIN, _CONTENT_W, page1_h - 2 * _MARGIN, id="f1", **_FRAME_PAD)],
        onPage=_size_hook(page1_h),
    )
    pt2 = PageTemplate(
        id="comparison",
        frames=[Frame(_MARGIN, _MARGIN, _CONTENT_W, page2_h - 2 * _MARGIN, id="f2", **_FRAME_PAD)],
        onPage=_size_hook(page2_h),
    )

    story = [NextPageTemplate("comparison")] + page1_story + [PageBreak()] + page2_story
    doc = BaseDocTemplate(
        output_path,
        pagesize=(_PAGE_W, page1_h),
        pageTemplates=[pt1, pt2],
        leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=_MARGIN, bottomMargin=_MARGIN,
    )
    doc.build(story)


