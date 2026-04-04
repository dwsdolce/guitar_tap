"""
Measurement persistence layer.

Data model classes live in the models/ package:
  models.resonant_peak        → ResonantPeak
  models.spectrum_snapshot    → SpectrumSnapshot
  models.tap_tone_measurement → TapToneMeasurement

JSON format:
  - Single saved_measurements.json in the platform Application Support dir:
      macOS:   ~/Library/Application Support/GuitarTap/
      Windows: %APPDATA%\\GuitarTap\\
      Linux:   ~/.local/share/GuitarTap/
  - Each measurement identified by UUID, ISO-8601 timestamp
  - Peaks have UUIDs; mode overrides, selected IDs, annotation offsets
    are keyed by peak UUID
  - spectrumSnapshot embeds freq/mag arrays so the file is self-contained
  - Format is cross-compatible with Swift GuitarTap .guitartap files
"""

from __future__ import annotations

import json
import os
from typing import Any

from models.tap_tone_measurement import TapToneMeasurement
from models.resonant_peak import ResonantPeak
from models.spectrum_snapshot import SpectrumSnapshot

__all__ = [
    "load_all_measurements",
    "save_all_measurements",
    "export_measurement_json",
    "import_measurements_from_json",
    "export_pdf",
    "measurements_file",
    "render_spectrum_image_for_measurement",
    "default_export_dir",
    "last_export_dir",
    "update_export_dir",
]

# Spectrum image rendering lives in exportable_spectrum_chart.py (mirrors ExportableSpectrumChart.swift).
from views.exportable_spectrum_chart import render_spectrum_image_for_measurement  # noqa: E402


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
    from PyQt6.QtCore import QSettings
    stored = QSettings().value(_EXPORT_DIR_KEY)
    if stored and os.path.isdir(stored):
        return stored
    return default_export_dir()


def update_export_dir(chosen_path: str) -> None:
    """Persist the directory of *chosen_path* as the new last-used export dir."""
    from PyQt6.QtCore import QSettings
    QSettings().setValue(_EXPORT_DIR_KEY, os.path.dirname(chosen_path))


# ── Persistence paths ─────────────────────────────────────────────────────────

def _app_data_dir() -> str:
    """Return the platform-appropriate Application Support directory.

    Uses QStandardPaths.AppDataLocation which resolves to:
      macOS:   ~/Library/Application Support/GuitarTap
      Windows: %APPDATA%\\GuitarTap
      Linux:   ~/.local/share/GuitarTap
    """
    from PyQt6.QtCore import QStandardPaths
    path = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return path


def measurements_file() -> str:
    data_dir = _app_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "saved_measurements.json")


# ── Persistence API ───────────────────────────────────────────────────────────

def load_all_measurements() -> list[TapToneMeasurement]:
    """Load all measurements from saved_measurements.json."""
    path = measurements_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [TapToneMeasurement.from_dict(d) for d in data]
        return [TapToneMeasurement.from_dict(data)]
    except Exception as exc:
        print(f"Failed to load measurements: {exc}")
        return []


def save_all_measurements(measurements: list[TapToneMeasurement]) -> None:
    """Write the full measurements list to disk atomically."""
    path = measurements_file()
    try:
        data = [m.to_dict() for m in measurements]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"Failed to save measurements: {exc}")


def export_measurement_json(m: TapToneMeasurement) -> str:
    """Return pretty-printed JSON for a single measurement.

    Mirrors Swift TapToneMeasurement.encode(to:) by injecting a resolved
    ``modeLabel`` into each peak entry.  For guitar measurements the label is
    determined by GuitarMode.classify_all (with any user override applied);
    for plate/brace it is the role name (Longitudinal, Cross-grain, FLC, Peak).
    """
    d = m.to_dict()

    # Resolve measurement type and guitar type from the snapshot — mirrors Swift:
    #   let resolvedMeasurementType = spectrumSnapshot?.measurementType
    #                               ?? longitudinalSnapshot?.measurementType
    snap = m.spectrum_snapshot or m.longitudinal_snapshot
    resolved_mt = (snap.measurement_type if snap else None) or m.measurement_type
    resolved_gt = (snap.guitar_type if snap else None) or m.guitar_type

    is_guitar = True
    if resolved_mt:
        try:
            from models import measurement_type as _mt_mod
            mt_obj = _mt_mod.MeasurementType(resolved_mt)
            is_guitar = mt_obj.is_guitar
        except Exception:
            pass

    # Build the mode-label map for peaks — mirrors Swift PeakExportCodingKeys loop.
    if is_guitar and m.peaks:
        try:
            from models.guitar_mode import GuitarMode
            from models.guitar_type import GuitarType
            gt_enum = GuitarType(resolved_gt) if resolved_gt else GuitarType.CLASSICAL
            mode_map = GuitarMode.classify_all(m.peaks, gt_enum)
        except Exception:
            mode_map = {}

        overrides = m.peak_mode_overrides or {}
        for i, peak_d in enumerate(d["peaks"]):
            peak = m.peaks[i]
            override = overrides.get(peak.id)
            if override:
                label = override
            else:
                mode = mode_map.get(peak.id)
                label = mode.display_name if mode else "Unknown"
            peak_d["modeLabel"] = label
    else:
        # Plate / brace: label by which selected-peak-id matches.
        for i, peak_d in enumerate(d["peaks"]):
            peak = m.peaks[i]
            if peak.id == m.selected_longitudinal_peak_id:
                label = "Longitudinal"
            elif peak.id == m.selected_cross_peak_id:
                label = "Cross-grain"
            elif peak.id == m.selected_flc_peak_id:
                label = "FLC"
            else:
                label = "Peak"
            peak_d["modeLabel"] = label

    return json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True)


def import_measurements_from_json(data: str | bytes) -> list[TapToneMeasurement]:
    """
    Parse JSON from a .guitartap or .json file.
    Accepts a JSON array or a single measurement object.
    """
    raw = json.loads(data)
    if isinstance(raw, list):
        return [TapToneMeasurement.from_dict(d) for d in raw]
    return [TapToneMeasurement.from_dict(raw)]


def export_pdf(
    m: TapToneMeasurement, spectrum_image_data: bytes | None, output_path: str
) -> None:
    """Export a tap-tone analysis report to PDF using reportlab.

    Mirrors the layout of Swift PDFReportGenerator / PDFReportContentView:

      Header  — "GuitarTap" title + blue accent bar + timestamp (right-aligned)
      Metadata — Location, Type, Notes, Frequency Range, Microphone rows
      Spectrum image (if supplied, full content width)
      Grey divider line
      Detected Peaks table (Frequency / Magnitude / Note / Mode  or  Q / Role)
      Tap Instructions (plate/brace only)
      Analysis Results:
        Guitar → Ring-Out Time box + Tap Tone Ratio box
        Plate  → full PlateProperties section + Gore Target Thickness
        Brace  → BraceProperties section
      Footer — "Generated by GuitarTap" + generation timestamp

    Page geometry (US Letter, 72 pt/inch):
      pageWidth = 612 pt, margin = 36 pt, contentWidth = 540 pt.
    """
    import io as _io
    from datetime import datetime as _dt, timezone as _tz
    from _version import __version_string__ as _app_version

    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import (
        BaseDocTemplate,
        PageTemplate,
        Frame,
        Flowable,
        Spacer,
        Table,
        TableStyle,
        Image,
        HRFlowable,
        Paragraph,
        KeepTogether,
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from models import measurement_type as MT
    from models import guitar_mode as GM
    from models import guitar_type as GT_module
    from models import plate_stiffness_preset as PSP
    from models.material_properties import (
        MaterialDimensions,
        PlateProperties,
        BraceProperties,
        calculate_plate_properties,
        calculate_brace_properties,
        calculate_glc_from_flc,
        calculate_gore_target_thickness,
        QUALITY_COLORS,
    )

    # ── Geometry (mirrors Swift) ──────────────────────────────────────────
    PAGE_W, PAGE_H = letter        # 612 × 792 pt
    MARGIN        = 36             # 36 pt on every side (pt == 1 in reportlab)
    CONTENT_W     = PAGE_W - 2 * MARGIN   # 540 pt

    # ── Accent colour (matches Swift Color(red:0.15, green:0.35, blue:0.75)) ──
    ACCENT = colors.Color(0.15, 0.35, 0.75)
    SECONDARY = colors.Color(0.45, 0.45, 0.45)
    GRID_GREY = colors.Color(0.75, 0.75, 0.75)
    BG_GREY   = colors.Color(0, 0, 0, 0.07)       # gray opacity 0.07
    BG_LIGHT  = colors.Color(0, 0, 0, 0.06)       # gray opacity 0.06 for sub-tables
    BG_ACCENT = colors.Color(0.15, 0.35, 0.75, 0.07)  # blue accent bg for Gore box

    # ── Style helpers ─────────────────────────────────────────────────────
    def _style(name, **kw) -> ParagraphStyle:
        base = ParagraphStyle(name)
        for k, v in kw.items():
            setattr(base, k, v)
        return base

    S_TITLE    = _style("title",    fontSize=22, fontName="Helvetica-Bold",  textColor=ACCENT,     leading=26)
    S_SUBTITLE = _style("subtitle", fontSize=13, fontName="Helvetica",       textColor=SECONDARY,  leading=16)
    S_DATE     = _style("date",     fontSize=11, fontName="Helvetica",       textColor=SECONDARY,  leading=14, alignment=TA_RIGHT)
    S_META_LBL = _style("meta_lbl", fontSize=11, fontName="Helvetica-Bold",  textColor=SECONDARY,  leading=13)
    S_META_VAL = _style("meta_val", fontSize=11, fontName="Helvetica",       textColor=colors.black, leading=13)
    S_SECTION  = _style("section",  fontSize=13, fontName="Helvetica-Bold",  textColor=colors.black, leading=16)
    S_SUBSEC   = _style("subsec",   fontSize=12, fontName="Helvetica-Bold",  textColor=SECONDARY,  leading=14)
    S_BODY     = _style("body",     fontSize=10, fontName="Helvetica",       textColor=colors.black, leading=12)
    S_BODY_B   = _style("body_b",   fontSize=10, fontName="Helvetica-Bold",  textColor=colors.black, leading=12)
    S_SMALL    = _style("small",    fontSize=9,  fontName="Helvetica",       textColor=SECONDARY,  leading=11)
    S_SMALL_I  = _style("small_i",  fontSize=9,  fontName="Helvetica-Oblique", textColor=SECONDARY, leading=11)
    S_FOOTER   = _style("footer",   fontSize=9,  fontName="Helvetica",       textColor=SECONDARY,  leading=11)
    S_BIG_VAL  = _style("bigval",   fontSize=18, fontName="Helvetica-Bold",  textColor=colors.black, leading=22)
    S_SPEC_HDR = _style("spec_hdr", fontSize=12, fontName="Helvetica-Bold",  textColor=SECONDARY,  leading=14)

    # ── Derive measurement type and snapshots ─────────────────────────────
    any_snap = m.spectrum_snapshot or m.longitudinal_snapshot or m.cross_snapshot
    mt_str = m.measurement_type or (any_snap.measurement_type if any_snap else "Classical")
    try:
        mt = MT.MeasurementType(mt_str)
    except ValueError:
        mt = MT.MeasurementType.CLASSICAL

    gt_str = m.guitar_type or (any_snap.guitar_type if any_snap else "Classical")
    try:
        gt = GT_module.GuitarType(gt_str)
    except Exception:
        gt = GT_module.GuitarType.CLASSICAL

    # Display snapshot for freq range
    display_snap = m.spectrum_snapshot or any_snap
    min_freq = display_snap.min_freq if display_snap else 50
    max_freq = display_snap.max_freq if display_snap else 1000

    # Timestamp
    try:
        ts = _dt.fromisoformat(m.timestamp)
    except Exception:
        ts = _dt.now(_tz.utc)
    date_str = f"{ts.strftime('%B')} {ts.day}, {ts.year}"
    _hour = ts.hour % 12 or 12
    _ampm = "AM" if ts.hour < 12 else "PM"
    time_str = f"{_hour}:{ts.strftime('%M')} {_ampm}"

    # Peaks: filter to display range, sort by frequency, apply selection filter
    range_peaks = [p for p in m.peaks if min_freq <= p.frequency <= max_freq]
    selected_ids = set(m.selected_peak_ids or [p.id for p in range_peaks])
    visible_peaks = sorted(
        [p for p in range_peaks if p.id in selected_ids],
        key=lambda p: p.frequency,
    )

    # Mode classification for peaks
    peak_modes: dict[str, GM.GuitarMode] = {}
    try:
        peak_modes = GM.GuitarMode.classify_all(visible_peaks, gt_str)
    except Exception:
        pass

    # Mode overrides
    peak_mode_overrides: dict[str, str] = m.peak_mode_overrides or {}

    # ── Derive material properties ────────────────────────────────────────
    plate_props: PlateProperties | None = None
    brace_props: BraceProperties | None = None

    if mt == MT.MeasurementType.PLATE:
        long_id   = m.selected_longitudinal_peak_id
        cross_id  = m.selected_cross_peak_id
        flc_id    = m.selected_flc_peak_id
        long_peak  = next((p for p in m.peaks if p.id == long_id),  None)
        cross_peak = next((p for p in m.peaks if p.id == cross_id), None)
        flc_peak   = next((p for p in m.peaks if p.id == flc_id),   None)
        snap_for_dims = m.longitudinal_snapshot or any_snap
        if long_peak and cross_peak and snap_for_dims:
            dims = MaterialDimensions(
                length_mm  = snap_for_dims.plate_length   or 0,
                width_mm   = snap_for_dims.plate_width    or 0,
                thickness_mm = snap_for_dims.plate_thickness or 0,
                mass_g     = snap_for_dims.plate_mass     or 0,
            )
            if dims.is_valid():
                try:
                    plate_props = calculate_plate_properties(
                        dims, long_peak.frequency, cross_peak.frequency
                    )
                except Exception:
                    pass

    elif mt == MT.MeasurementType.BRACE:
        long_id   = m.selected_longitudinal_peak_id
        long_peak = next((p for p in m.peaks if p.id == long_id), None)
        snap_for_dims = m.longitudinal_snapshot or any_snap
        if long_peak and snap_for_dims:
            dims = MaterialDimensions(
                length_mm    = snap_for_dims.brace_length    or 0,
                width_mm     = snap_for_dims.brace_width     or 0,
                thickness_mm = snap_for_dims.brace_thickness or 0,
                mass_g       = snap_for_dims.brace_mass      or 0,
            )
            if dims.is_valid():
                try:
                    brace_props = calculate_brace_properties(dims, long_peak.frequency)
                except Exception:
                    pass

    # Gore settings (plate only) — read from snapshot if present, else AppSettings
    snap_for_gore = m.longitudinal_snapshot or any_snap
    guitar_body_length = (snap_for_gore.guitar_body_length if snap_for_gore and snap_for_gore.guitar_body_length else None) or 490.0
    guitar_body_width  = (snap_for_gore.guitar_body_width  if snap_for_gore and snap_for_gore.guitar_body_width  else None) or 390.0
    _preset_str = (snap_for_gore.plate_stiffness_preset if snap_for_gore and snap_for_gore.plate_stiffness_preset else None) or "Steel String Top"
    try:
        _preset = PSP.PlateStiffnessPreset(_preset_str)
    except ValueError:
        _preset = PSP.PlateStiffnessPreset.STEEL_STRING_TOP
    if _preset == PSP.PlateStiffnessPreset.CUSTOM:
        plate_stiffness = (snap_for_gore.custom_plate_stiffness if snap_for_gore and snap_for_gore.custom_plate_stiffness else None) or 75.0
    else:
        plate_stiffness = _preset.value

    # G_LC shear modulus (from FLC tap, if available)
    glc_pa: float | None = None
    if mt == MT.MeasurementType.PLATE and plate_props is not None:
        flc_id  = m.selected_flc_peak_id
        flc_peak = next((p for p in m.peaks if p.id == flc_id), None) if flc_id else None
        snap_for_dims2 = m.longitudinal_snapshot or any_snap
        if flc_peak and snap_for_dims2:
            dims2 = MaterialDimensions(
                length_mm    = snap_for_dims2.plate_length    or 0,
                width_mm     = snap_for_dims2.plate_width     or 0,
                thickness_mm = snap_for_dims2.plate_thickness or 0,
                mass_g       = snap_for_dims2.plate_mass      or 0,
            )
            if dims2.is_valid():
                try:
                    glc_pa = calculate_glc_from_flc(dims2, flc_peak.frequency)
                    if glc_pa == 0.0:
                        glc_pa = None
                except Exception:
                    glc_pa = None

    # Gore target thickness
    gore_result = None
    if plate_props is not None:
        try:
            gore_result = calculate_gore_target_thickness(
                plate_props, guitar_body_length, guitar_body_width,
                plate_stiffness, _preset_str, glc_pa,
            )
        except Exception:
            gore_result = None

    # ── Quality helpers (mirrors Swift extensions) ────────────────────────
    def _quality_color(label: str) -> colors.Color:
        """Map WoodQuality / sustain quality label to a reportlab Color."""
        hex_map = {
            "Excellent": (0.0,  0.5,  0.9),
            "Very Good": (0.0,  0.6,  0.0),
            "Good":      (0.13, 0.53, 0.0),
            "Fair":      (1.0,  0.6,  0.0),
            "Poor":      (1.0,  0.24, 0.19),
            # Sustain quality labels
            "Very Short": (1.0, 0.24, 0.19),
            "Short":      (1.0, 0.6,  0.0),
            "Moderate":   (1.0, 0.6,  0.0),
        }
        r, g, b = hex_map.get(label, (0.45, 0.45, 0.45))
        return colors.Color(r, g, b)

    def _ratio_quality(ratio: float) -> tuple[str, colors.Color]:
        if ratio < 1.7:
            return "Low",          colors.Color(0.957, 0.263, 0.212)
        if ratio < 1.9:
            return "Below Target", colors.Color(1.0, 0.596, 0.0)
        if ratio <= 2.1:
            return "Ideal",        colors.Color(0.298, 0.686, 0.314)
        if ratio < 2.3:
            return "Above Target", colors.Color(1.0, 0.596, 0.0)
        return "High",             colors.Color(0.957, 0.263, 0.212)

    def _mode_color(mode: GM.GuitarMode) -> colors.Color:
        norm = mode.normalized if hasattr(mode, "normalized") else mode
        map_ = {
            GM.GuitarMode.AIR:      colors.Color(0.0, 0.5, 0.8),
            GM.GuitarMode.TOP:      colors.Color(0.2, 0.65, 0.2),
            GM.GuitarMode.BACK:     colors.Color(0.8, 0.4, 0.0),
            GM.GuitarMode.DIPOLE:   colors.Color(0.6, 0.0, 0.8),
            GM.GuitarMode.RING_MODE: colors.Color(0.8, 0.0, 0.4),
        }
        return map_.get(norm, SECONDARY)

    # ── Custom Flowables ──────────────────────────────────────────────────

    class _HLine(Flowable):
        """Thin horizontal rule — mirrors Swift sectionDivider / accentBar."""
        def __init__(self, width, thickness=1, color=GRID_GREY, spaceAfter=0):
            super().__init__()
            self._w = width
            self._t = thickness
            self._c = color
            self.spaceAfter = spaceAfter

        def draw(self):
            self.canv.setStrokeColor(self._c)
            self.canv.setLineWidth(self._t)
            self.canv.line(0, 0, self._w, 0)

        def wrap(self, avail_w, avail_h):
            return (self._w, self._t)

    class _TwoColRow(Flowable):
        """Single key:value metadata row — mirrors Swift metaRow."""
        LBL_W = 100              # 100 pt label column width (pt == 1 in reportlab)

        def __init__(self, label: str, value: str, content_w: float):
            super().__init__()
            self._label = label + ":"
            self._value = value
            self._cw    = content_w

        def draw(self):
            c = self.canv
            # Label (semibold secondary)
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(SECONDARY)
            c.drawString(0, 0, self._label)
            # Value (regular black)
            c.setFont("Helvetica", 11)
            c.setFillColor(colors.black)
            c.drawString(106, 0, self._value)

        def wrap(self, avail_w, avail_h):
            return (self._cw, 13)

    class _AnalysisBox(Flowable):
        """Rounded grey box with a primary value and quality label on the right.

        Mirrors Swift analysisBox().
        """
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
            self.height    = 64

        def draw(self):
            c = self.canv
            # Background rounded rect
            c.setFillColor(colors.Color(0.5, 0.5, 0.5, 0.07))
            c.roundRect(0, 0, self._w, self.height, 6, stroke=0, fill=1)
            # Left side: title → big value → subtitle
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(SECONDARY)
            c.drawString(10, self.height - 16, self._title)
            c.setFont("Helvetica-Bold", 18)
            c.setFillColor(colors.black)
            c.drawString(10, self.height - 38, self._value)
            if self._subtitle:
                c.setFont("Helvetica", 9)
                c.setFillColor(SECONDARY)
                c.drawString(10, self.height - 50, self._subtitle)
            # Right side: detail quality → detail subtitle → hint
            c.setFont("Helvetica", 10)
            c.setFillColor(self._dc)
            detail_x = self._w - stringWidth(self._detail, "Helvetica", 10) - 10
            c.drawString(detail_x, self.height - 16, self._detail)
            if self._dsub:
                c.setFont("Helvetica", 9)
                c.setFillColor(SECONDARY)
                dsub_x = self._w - stringWidth(self._dsub, "Helvetica", 9) - 10
                c.drawString(dsub_x, self.height - 28, self._dsub)
            if self._hint:
                c.setFont("Helvetica-Oblique", 9)
                c.setFillColor(SECONDARY)
                hint_x = self._w - stringWidth(self._hint, "Helvetica-Oblique", 9) - 10
                bottom = 10 if not self._dsub else 8
                c.drawString(hint_x, bottom, self._hint)

        def wrap(self, avail_w, avail_h):
            return (self._w, self.height)

    # ── Build story ───────────────────────────────────────────────────────
    story: list = []

    # --- HEADER -----------------------------------------------------------
    # Two-column: app name/subtitle on left, date/time on right.
    # Implemented as a Table so the right column aligns.
    header_left = [
        Paragraph("GuitarTap",                  S_TITLE),
        Paragraph("Tap Tone Analysis Report",   S_SUBTITLE),
    ]
    header_right = [
        Paragraph(date_str, S_DATE),
        Paragraph(time_str, S_DATE),
    ]
    header_tbl = Table(
        [[header_left, header_right]],
        colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN",  (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(header_tbl)

    # Blue accent bar (3 pt tall, mirrors Swift accentBar)
    story.append(_HLine(CONTENT_W, thickness=3, color=ACCENT, spaceAfter=12))
    story.append(Spacer(1, 12))

    # --- METADATA ---------------------------------------------------------
    if m.tap_location:
        story.append(_TwoColRow("Location", m.tap_location, CONTENT_W))
        story.append(Spacer(1, 4))
    story.append(_TwoColRow("Type", mt_str, CONTENT_W))
    story.append(Spacer(1, 4))
    if m.notes:
        story.append(_TwoColRow("Notes", m.notes, CONTENT_W))
        story.append(Spacer(1, 4))
    story.append(_TwoColRow(
        "Frequency Range",
        f"{min_freq:.0f} Hz \u2013 {max_freq:.0f} Hz",
        CONTENT_W,
    ))
    if m.microphone_name:
        cal_suffix = f" \u00b7 calibrated ({m.calibration_name})" if m.calibration_name else " \u00b7 uncalibrated"
        story.append(Spacer(1, 4))
        story.append(_TwoColRow("Microphone", m.microphone_name + cal_suffix, CONTENT_W))

    story.append(Spacer(1, 14))

    # --- SPECTRUM IMAGE ---------------------------------------------------
    if spectrum_image_data:
        from PIL import Image as PILImage
        pil_img = PILImage.open(_io.BytesIO(spectrum_image_data))
        img_w_px, img_h_px = pil_img.size
        aspect = img_h_px / img_w_px if img_w_px > 0 else 0.5
        img_h_pt = min(CONTENT_W * aspect, 220)  # cap at 220 pt — mirrors Swift max 220
        story.append(Paragraph("Frequency Spectrum", S_SPEC_HDR))
        story.append(Spacer(1, 6))
        story.append(Image(
            _io.BytesIO(spectrum_image_data),
            width=CONTENT_W,
            height=img_h_pt,
        ))
        story.append(Spacer(1, 14))

    # --- SECTION DIVIDER --------------------------------------------------
    story.append(_HLine(CONTENT_W, thickness=1, color=colors.Color(0.5, 0.5, 0.5, 0.3)))
    story.append(Spacer(1, 14))

    # --- PEAKS TABLE ------------------------------------------------------
    story.append(Paragraph("Detected Peaks", S_SECTION))
    story.append(Spacer(1, 6))

    if not visible_peaks:
        story.append(Paragraph("No peaks detected in this measurement.", S_BODY))
    else:
        # Column widths (mirror Swift .frame widths, scaled to 540 pt content width)
        # Swift: Freq 90, Mag 80, Note 80, Mode fills rest (290 pt at 540 content).
        # For plate/brace: Freq 90, Mag 80, Note 80, Q 70, Role fills rest.
        is_guitar = mt.is_guitar
        if is_guitar:
            col_w = [90, 80, 80, CONTENT_W - 250]
            hdr_row = ["Frequency", "Magnitude", "Note", "Mode"]
        else:
            col_w = [90, 80, 80, 70, CONTENT_W - 320]
            hdr_row = ["Frequency", "Magnitude", "Note", "Q Factor", "Role"]

        def _effective_mode_label(peak) -> tuple[str, bool]:
            """(label, is_overridden) — mirrors Swift effectiveModeLabel."""
            ovr = peak_mode_overrides.get(peak.id)
            if ovr:
                return ovr + " *", True
            mode = peak_modes.get(peak.id, GM.GuitarMode.UNKNOWN)
            return mode.display_name if hasattr(mode, "display_name") else str(mode), False

        def _role_label(peak) -> str:
            if mt == MT.MeasurementType.PLATE:
                if peak.id == m.selected_longitudinal_peak_id:
                    return "Longitudinal (L)"
                if peak.id == m.selected_cross_peak_id:
                    return "Cross-grain (C)"
                flc_snap2 = m.flc_snapshot
                if peak.id == m.selected_flc_peak_id:
                    return "FLC (Diagonal)"
                return "\u2013"
            elif mt == MT.MeasurementType.BRACE:
                if peak.id == m.selected_longitudinal_peak_id:
                    return "fL (Longitudinal)"
                return "\u2013"
            return ""

        # Build rows
        peak_rows: list[list] = [hdr_row]
        for peak in visible_peaks:
            note_str = peak.pitch_note or "\u2013"
            freq_str = f"{peak.frequency:.1f} Hz"
            mag_str  = f"{peak.magnitude:.1f} dB"
            if is_guitar:
                label, is_ovr = _effective_mode_label(peak)
                mode  = peak_modes.get(peak.id, GM.GuitarMode.UNKNOWN)
                mc    = _mode_color(mode)
                mode_para = Paragraph(
                    f"<font color='#{int(mc.red*255):02x}{int(mc.green*255):02x}{int(mc.blue*255):02x}'>"
                    f"{'<i>' if is_ovr else ''}{label}{'</i>' if is_ovr else ''}</font>",
                    S_BODY
                )
                peak_rows.append([freq_str, mag_str, note_str, mode_para])
            else:
                q_str   = f"{peak.quality:.1f}"
                role_str = _role_label(peak)
                peak_rows.append([freq_str, mag_str, note_str, q_str, role_str])

        peaks_tbl = Table(peak_rows, colWidths=col_w)
        hdr_style = [
            # Header row background
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.5, 0.5, 0.5, 0.1)),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 10),
            ("TEXTCOLOR",  (0, 0), (-1, 0), SECONDARY),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.97, 0.97, 0.97)]),
            ("ROUNDEDCORNERS", [4]),
        ]
        peaks_tbl.setStyle(TableStyle(hdr_style))
        story.append(peaks_tbl)

    story.append(Spacer(1, 14))

    # --- TAP INSTRUCTIONS (plate / brace only) ---------------------------
    if mt == MT.MeasurementType.PLATE:
        has_flc = bool(m.selected_flc_peak_id)
        tap_title = "Three-Tap Measurement Process:" if has_flc else "Two-Tap Measurement Process:"
        story.append(_HLine(CONTENT_W, thickness=1, color=colors.Color(0.5, 0.5, 0.5, 0.3)))
        story.append(Spacer(1, 6))
        story.append(Paragraph(tap_title, S_BODY_B))
        story.append(Spacer(1, 4))

        def _instr_row(label: str, detail: str):
            return Paragraph(f"<b>{label}</b>  {detail}", S_SMALL)

        story.append(_instr_row(
            "1. Longitudinal (L) Tap",
            "Hold plate at 22% from one end along the length, near one long edge (not at the width node). Tap center.",
        ))
        story.append(Spacer(1, 2))
        story.append(_instr_row(
            "2. Cross-grain (C) Tap",
            "Rotate 90\u00b0. Hold plate at 22% from one end along the width, near one short edge (not at the length node). Tap center.",
        ))
        if has_flc:
            story.append(Spacer(1, 2))
            story.append(_instr_row(
                "3. FLC (Diagonal) Tap",
                "Hold plate at the midpoint of one long edge. Tap near the opposite corner (~22% from both the end and the side). Measures shear stiffness.",
            ))
        story.append(Spacer(1, 4))
        story.append(Paragraph("The strongest peak from each tap is auto-selected.", S_SMALL_I))
        story.append(Spacer(1, 14))

    elif mt == MT.MeasurementType.BRACE:
        story.append(_HLine(CONTENT_W, thickness=1, color=colors.Color(0.5, 0.5, 0.5, 0.3)))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Single-Tap Measurement (fL only):", S_BODY_B))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "<b>1. Longitudinal (fL) Tap</b>  Hold brace at 22% from one end along the length. Tap center.",
            S_SMALL,
        ))
        story.append(Spacer(1, 4))
        story.append(Paragraph("The strongest peak is auto-selected.", S_SMALL_I))
        story.append(Spacer(1, 14))

    # --- ANALYSIS RESULTS ------------------------------------------------
    if mt.is_guitar:
        story.append(Paragraph("Analysis Results", S_SECTION))
        story.append(Spacer(1, 10))

        boxes: list[Flowable] = []
        box_w = (CONTENT_W - 16) / 2   # two boxes side-by-side with 16 pt gap

        if m.decay_time is not None:
            try:
                decay_label = gt.decay_quality_label(m.decay_time)
            except Exception:
                decay_label = ""
            dc = _quality_color(decay_label)
            boxes.append(_AnalysisBox(
                title="Ring-Out Time",
                value=f"{m.decay_time:.2f} s",
                subtitle="Time to decay 15 dB",
                detail=decay_label,
                detail_subtitle="Sustain quality",
                detail_color=dc,
                width=box_w,
            ))

        ratio = m.tap_tone_ratio
        if ratio is not None:
            ratio_label, ratio_color = _ratio_quality(ratio)
            boxes.append(_AnalysisBox(
                title="Tap Tone Ratio",
                value=f"{ratio:.2f} : 1",
                subtitle="Top / Air",
                detail=ratio_label,
                detail_color=ratio_color,
                hint="Ideal: 1.9 \u2013 2.1",
                width=box_w,
            ))

        if boxes:
            if len(boxes) == 2:
                box_tbl = Table(
                    [[boxes[0], Spacer(16, 1), boxes[1]]],
                    colWidths=[box_w, 16, box_w],
                )
                box_tbl.setStyle(TableStyle([
                    ("VALIGN",         (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING",    (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING",   (0, 0), (-1, -1), 0),
                    ("TOPPADDING",     (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING",  (0, 0), (-1, -1), 0),
                ]))
                story.append(box_tbl)
            else:
                story.append(boxes[0])

    elif mt == MT.MeasurementType.PLATE and plate_props is not None:
        # ── Plate Properties ────────────────────────────────────────────
        story.append(Paragraph("Plate Properties", S_SECTION))
        story.append(Spacer(1, 10))

        # Sample Dimensions sub-table
        snap_d = m.longitudinal_snapshot or any_snap
        if snap_d:
            dims_rows = [[
                Paragraph(f"<b>Length:</b> {snap_d.plate_length:.1f} mm" if snap_d.plate_length else "", S_BODY),
                Paragraph(f"<b>Width:</b> {snap_d.plate_width:.1f} mm" if snap_d.plate_width else "", S_BODY),
                Paragraph(f"<b>Thickness:</b> {snap_d.plate_thickness:.2f} mm" if snap_d.plate_thickness else "", S_BODY),
            ], [
                Paragraph(f"<b>Mass:</b> {snap_d.plate_mass:.1f} g" if snap_d.plate_mass else "", S_BODY),
                Paragraph(f"<b>Density:</b> {plate_props.density_kg_m3/1000:.3f} g/cm\u00b3", S_BODY),
                Paragraph("", S_BODY),
            ]]
            dims_tbl = Table(dims_rows, colWidths=[CONTENT_W/3]*3)
            dims_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.06)),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(Paragraph("Sample Dimensions", S_SMALL))
            story.append(Spacer(1, 4))
            story.append(dims_tbl)
            story.append(Spacer(1, 6))

        # fL / fC / fLC frequencies row
        freq_cells = [
            Paragraph(f"<b>fL:</b> {plate_props.f_long:.1f} Hz", S_BODY),
            Paragraph(f"<b>fC:</b> {plate_props.f_cross:.1f} Hz", S_BODY),
        ]
        if m.selected_flc_peak_id:
            flc_pk = next((p for p in m.peaks if p.id == m.selected_flc_peak_id), None)
            freq_cells.append(Paragraph(f"<b>fLC:</b> {flc_pk.frequency:.1f} Hz" if flc_pk else "", S_BODY))
        else:
            freq_cells.append(Paragraph("", S_BODY))
        freq_tbl = Table([freq_cells], colWidths=[CONTENT_W/3]*3)
        freq_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.06)),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROUNDEDCORNERS", [4]),
        ]))
        story.append(freq_tbl)
        story.append(Spacer(1, 8))

        # Two-column properties (mirrors Swift left/right VStack)
        def _pprow(label: str, value: str) -> Paragraph:
            return Paragraph(f"<font color='#737373'>{label}:</font>  <b>{value}</b>", S_BODY)

        def _qrow(label: str, value: float, quality: str) -> Paragraph:
            qc = _quality_color(quality)
            hex_c = f"#{int(qc.red*255):02x}{int(qc.green*255):02x}{int(qc.blue*255):02x}"
            return Paragraph(
                f"<font color='#737373'>{label}:</font>  "
                f"<b><font color='{hex_c}'>{value:.1f}</font></b>  "
                f"<font color='{hex_c}' size='9'>({quality})</font>",
                S_BODY,
            )

        left_col = [
            _pprow("Speed of Sound (L)", f"{plate_props.c_long_m_s:.0f} m/s"),
            Spacer(1, 6),
            _pprow("Speed of Sound (C)", f"{plate_props.c_cross_m_s:.0f} m/s"),
            Spacer(1, 6),
            _pprow("Young\u2019s Modulus (L)", f"{plate_props.E_long_GPa:.2f} GPa"),
            Spacer(1, 6),
            _pprow("Young\u2019s Modulus (C)", f"{plate_props.E_cross_GPa:.2f} GPa"),
        ]
        right_col = [
            _qrow("Specific Modulus (L)", plate_props.specific_modulus_long, plate_props.quality_long),
            Spacer(1, 6),
            _qrow("Specific Modulus (C)", plate_props.specific_modulus_cross, plate_props.quality_cross),
            Spacer(1, 6),
            _pprow("Radiation Ratio (L)", f"{plate_props.radiation_ratio_long:.1f}"),
            Spacer(1, 6),
            _pprow("Radiation Ratio (C)", f"{plate_props.radiation_ratio_cross:.1f}"),
        ]
        props_tbl = Table([[left_col, right_col]], colWidths=[CONTENT_W/2]*2)
        props_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(props_tbl)
        story.append(Spacer(1, 8))

        # G_LC shear modulus
        if glc_pa is not None and glc_pa > 0:
            story.append(_pprow("GLC (Shear Modulus)", f"{glc_pa/1e9:.3f} GPa"))
        else:
            story.append(Paragraph("GLC assumed 0 \u2014 FLC tap not performed", S_SMALL_I))
        story.append(Spacer(1, 8))

        # Cross/Long and Long/Cross ratios
        ratio_tbl = Table([[
            [
                _pprow("Cross/Long Ratio", f"{plate_props.cross_long_ratio:.3f}"),
                Paragraph("typical: 0.04 \u2013 0.08", S_SMALL_I),
            ],
            [
                _pprow("Long/Cross Ratio", f"{plate_props.long_cross_ratio:.1f}"),
                Paragraph("typical: 12 \u2013 25", S_SMALL_I),
            ],
        ]], colWidths=[CONTENT_W/2]*2)
        ratio_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(ratio_tbl)
        story.append(Spacer(1, 8))

        # Overall Quality box
        oq = plate_props.overall_quality
        oq_color = _quality_color(oq)
        oq_hex = f"#{int(oq_color.red*255):02x}{int(oq_color.green*255):02x}{int(oq_color.blue*255):02x}"
        oq_tbl = Table([[
            Paragraph(
                f"<font color='#737373'><b>Overall Quality:</b></font>  "
                f"<b><font size='13' color='{oq_hex}'>{oq}</font></b>",
                S_BODY,
            )
        ]])
        oq_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.07)),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ROUNDEDCORNERS", [4]),
        ]))
        story.append(oq_tbl)

        # Gore Target Thickness box (blue background)
        if gore_result is not None:
            story.append(Spacer(1, 8))
            if _preset == PSP.PlateStiffnessPreset.CUSTOM:
                preset_label = f"f_vs = {int(plate_stiffness)} (custom)"
            else:
                preset_label = f"f_vs = {int(plate_stiffness)} ({_preset_str})"
            body_label = (
                f"Body: {guitar_body_length:.0f} \u00d7 {guitar_body_width:.0f} mm "
                f"\u00b7 {preset_label}"
            )
            if glc_pa is not None and glc_pa > 0:
                glc_line = f"GLC (Shear Modulus): {glc_pa/1e9:.3f} GPa"
            else:
                glc_line = "GLC assumed 0 \u2014 FLC tap not performed"
            gore_content = [
                Paragraph("Gore Target Thickness", S_SMALL),
                Spacer(1, 4),
                Paragraph(
                    f"<b><font size='16' color='#2659C0'>{gore_result.thickness_mm:.2f} mm</font></b>",
                    S_BODY,
                ),
                Paragraph(body_label, S_SMALL),
                Paragraph(glc_line, S_SMALL_I),
            ]
            gore_tbl = Table([[gore_content]])
            gore_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.15, 0.35, 0.75, 0.07)),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            story.append(gore_tbl)

    elif mt == MT.MeasurementType.BRACE and brace_props is not None:
        # ── Brace Properties ────────────────────────────────────────────
        story.append(Paragraph("Brace Properties", S_SECTION))
        story.append(Spacer(1, 10))

        snap_d = m.longitudinal_snapshot or any_snap
        if snap_d:
            dims_rows = [[
                Paragraph(f"<b>Length:</b> {snap_d.brace_length:.1f} mm" if snap_d.brace_length else "", S_BODY),
                Paragraph(f"<b>Width:</b> {snap_d.brace_width:.1f} mm" if snap_d.brace_width else "", S_BODY),
                Paragraph(f"<b>Thickness:</b> {snap_d.brace_thickness:.2f} mm" if snap_d.brace_thickness else "", S_BODY),
            ], [
                Paragraph(f"<b>Mass:</b> {snap_d.brace_mass:.1f} g" if snap_d.brace_mass else "", S_BODY),
                Paragraph(f"<b>Density:</b> {brace_props.density_kg_m3/1000:.3f} g/cm\u00b3", S_BODY),
                Paragraph("", S_BODY),
            ]]
            dims_tbl = Table(dims_rows, colWidths=[CONTENT_W/3]*3)
            dims_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.06)),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(Paragraph("Sample Dimensions", S_SMALL))
            story.append(Spacer(1, 4))
            story.append(dims_tbl)
            story.append(Spacer(1, 6))

        # fL row
        fl_tbl = Table([[
            Paragraph(f"<b>fL:</b> {brace_props.f_long:.1f} Hz", S_BODY),
            Paragraph("", S_BODY),
            Paragraph("", S_BODY),
        ]], colWidths=[CONTENT_W/3]*3)
        fl_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.06)),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROUNDEDCORNERS", [4]),
        ]))
        story.append(fl_tbl)
        story.append(Spacer(1, 8))

        def _pprow(label, value):
            return Paragraph(f"<font color='#737373'>{label}:</font>  <b>{value}</b>", S_BODY)

        def _qrow(label, value, quality):
            qc = _quality_color(quality)
            hex_c = f"#{int(qc.red*255):02x}{int(qc.green*255):02x}{int(qc.blue*255):02x}"
            return Paragraph(
                f"<font color='#737373'>{label}:</font>  "
                f"<b><font color='{hex_c}'>{value:.1f}</font></b>  "
                f"<font color='{hex_c}' size='9'>({quality})</font>",
                S_BODY,
            )

        left_col = [
            _pprow("Speed of Sound", f"{brace_props.c_long_m_s:.0f} m/s"),
            Spacer(1, 6),
            _pprow("Young\u2019s Modulus (E)", f"{brace_props.E_long_GPa:.2f} GPa"),
        ]
        right_col = [
            _qrow("Specific Modulus", brace_props.specific_modulus, brace_props.quality),
            Spacer(1, 6),
            _pprow("Radiation Ratio", f"{brace_props.radiation_ratio:.1f}"),
        ]
        props_tbl = Table([[left_col, right_col]], colWidths=[CONTENT_W/2]*2)
        props_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(props_tbl)
        story.append(Spacer(1, 8))

        # Overall Quality box
        oq = brace_props.quality
        oq_color = _quality_color(oq)
        oq_hex = f"#{int(oq_color.red*255):02x}{int(oq_color.green*255):02x}{int(oq_color.blue*255):02x}"
        oq_tbl = Table([[
            Paragraph(
                f"<font color='#737373'><b>Overall Quality:</b></font>  "
                f"<b><font size='13' color='{oq_hex}'>{oq}</font></b>",
                S_BODY,
            )
        ]])
        oq_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.Color(0.5, 0.5, 0.5, 0.07)),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ROUNDEDCORNERS", [4]),
        ]))
        story.append(oq_tbl)

    # --- FOOTER -----------------------------------------------------------
    story.append(Spacer(1, 16))
    story.append(_HLine(CONTENT_W, thickness=1, color=colors.Color(0.5, 0.5, 0.5, 0.2)))
    story.append(Spacer(1, 8))

    version_str = _app_version
    _now = _dt.now()
    _now_hour = _now.hour % 12 or 12
    _now_ampm = "AM" if _now.hour < 12 else "PM"
    now_str = f"{_now.strftime('%b')} {_now.day}, {_now.year}, {_now_hour}:{_now.strftime('%M')} {_now_ampm}"
    footer_tbl = Table(
        [[
            Paragraph(f"Generated by GuitarTap {version_str}", S_FOOTER),
            Paragraph(now_str, _style("footer_r", fontSize=9, fontName="Helvetica",
                                      textColor=SECONDARY, leading=11, alignment=TA_RIGHT)),
        ]],
        colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4],
    )
    footer_tbl.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(footer_tbl)

    # ── Build PDF ─────────────────────────────────────────────────────────
    frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN, id="main")
    page_template = PageTemplate(id="letter", frames=[frame])
    doc = BaseDocTemplate(
        output_path,
        pagesize=letter,
        pageTemplates=[page_template],
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    doc.build(story)


