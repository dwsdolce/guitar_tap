"""
Detail dialog for a single saved TapToneMeasurement.
Matches MeasurementDetailView.swift / CombinedPeakModeRowView.swift.
"""

# @parity view/measurement-detail

import qtawesome as qta
from models import ResonantPeak, TapToneMeasurement
from models import guitar_mode as GM
from models import guitar_type as GT
from models import pitch as P
from PySide6 import QtCore, QtGui, QtWidgets
from utilities.date_format import format_display_datetime

# ── Helpers ───────────────────────────────────────────────────────────────────

_PITCH = P.Pitch(440)

def _pitch_str(freq: float) -> str:
    """Return 'A4  +12¢' style string."""
    try:
        note = _PITCH.note(freq)
        cents = _PITCH.cents(freq)
        sign = "+" if cents >= 0 else "−"
        return f"{note}  {sign}{abs(cents):.0f}¢"
    except Exception:
        return ""


def _mag_color(mag: float) -> QtGui.QColor:
    """Color-code magnitude dB like Swift magnitudeColor()."""
    if mag >= -40:
        return QtGui.QColor(40, 160, 40)     # green
    elif mag >= -60:
        return QtGui.QColor(60, 120, 220)    # blue
    elif mag >= -80:
        return QtGui.QColor(210, 130, 40)    # orange
    else:
        return QtGui.QColor(200, 50, 50)     # red


def _mode_qcolor(mode: GM.GuitarMode) -> QtGui.QColor:
    r, g, b = mode.color
    return QtGui.QColor(r, g, b)


def _resolve_guitar_type(guitar_type_str: str | None) -> GT.GuitarType:
    """Convert a guitar_type string to GuitarType enum, defaulting to Classical."""
    if guitar_type_str:
        try:
            return GT.GuitarType(guitar_type_str)
        except ValueError:
            pass
    return GT.GuitarType.CLASSICAL


def _type_name(m) -> str:
    """Single Settings-vocabulary type word for the Details pane."""
    if m.is_comparison:
        return "Comparison"
    from models.measurement_type import MeasurementType
    try:
        return MeasurementType(m.measurement_type).short_name
    except (ValueError, TypeError):
        return m.guitar_type or m.measurement_type or "\u2014"


def _comparison_data(m) -> "list[dict]":
    """Build ComparisonResultsView rows from a saved comparison's entries."""
    data = []
    for e in (m.comparison_entries or []):
        comps = list(e.color_components or [])[:3]
        while len(comps) < 3:
            comps.append(0.0)
        rgb = tuple(int(c * 255) for c in comps)
        data.append(
            {"label": e.label, "color": rgb, "peaks": e.peaks, "guitar_type": e.guitar_type}
        )
    return data


# ── Peak row widget (matches CombinedPeakModeRowView read-only mode) ──────────

class _PeakRow(QtWidgets.QFrame):
    """
    Displays one peak (read-only) matching CombinedPeakModeRowView layout:

      [icon]  [mode label    freq Hz]
              [♪ pitch note + cents ]
              [Q: x.x  BW: x.x Hz   mag dB]
    """

    def __init__(
        self,
        peak: ResonantPeak,
        mode: GM.GuitarMode,
        effective_label: str,
        guitar_type: GT.GuitarType,
        parent=None,
        label_color: "QtGui.QColor | None" = None,
    ) -> None:
        super().__init__(parent)

        # Material peaks pass an explicit L/C/FLC colour; guitar peaks use the mode colour.
        color = label_color if label_color is not None else _mode_qcolor(mode)
        r, g, b = color.red(), color.green(), color.blue()

        # Tinted background (label colour at ~5% opacity)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(r, g, b, 13))
        self.setPalette(pal)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(8)

        # Mode icon (guitar) or colour dot (material).
        if label_color is not None:
            icon_lbl = QtWidgets.QLabel("●")
            icon_lbl.setStyleSheet(f"color: rgb({r},{g},{b}); font-size: 14px;")
        else:
            try:
                icon_lbl = QtWidgets.QLabel()
                icon_lbl.setPixmap(qta.icon(mode.icon, color=color).pixmap(24, 24))
            except Exception:
                icon_lbl = QtWidgets.QLabel("◆")
                icon_lbl.setStyleSheet(f"color: rgb({r},{g},{b}); font-size: 16px;")
        icon_lbl.setFixedWidth(28)
        root.addWidget(icon_lbl)

        # In-range badge (guitar modes only).
        if label_color is None and mode not in (GM.GuitarMode.UNKNOWN, GM.GuitarMode.UPPER_MODES):
            lo, hi = mode.mode_range(guitar_type)
            in_range = lo <= peak.frequency <= hi
            badge = QtWidgets.QLabel("✔" if in_range else "⚠")
            badge.setStyleSheet(
                "color: #28a028; font-size: 9px;" if in_range
                else "color: #d07020; font-size: 9px;"
            )
            badge.setToolTip(
                "Frequency is within the expected mode range"
                if in_range
                else "Frequency is outside the expected mode range"
            )
            badge.setFixedWidth(14)
            root.addWidget(badge)
        else:
            spacer = QtWidgets.QLabel()
            spacer.setFixedWidth(14)
            root.addWidget(spacer)

        # Info column.
        info_col = QtWidgets.QVBoxLayout()
        info_col.setSpacing(2)

        # Row 1: mode label + frequency
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(4)
        mode_lbl = QtWidgets.QLabel(effective_label)
        mode_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: rgb({r},{g},{b});"
        )
        row1.addWidget(mode_lbl)
        row1.addStretch()
        freq_lbl = QtWidgets.QLabel(f"{peak.frequency:.1f} Hz")
        freq_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        row1.addWidget(freq_lbl)
        info_col.addLayout(row1)

        # Row 2: pitch (if available)
        pitch_str = peak.pitch_note
        if not pitch_str:
            try:
                pitch_str = _pitch_str(peak.frequency)
            except Exception:
                pitch_str = ""
        if pitch_str:
            row2 = QtWidgets.QHBoxLayout()
            row2.setSpacing(4)
            note_icon = QtWidgets.QLabel("♪")
            note_icon.setStyleSheet("color: #8844cc; font-size: 10px;")
            row2.addWidget(note_icon)
            pitch_lbl = QtWidgets.QLabel(pitch_str)
            pitch_lbl.setStyleSheet(
                "color: #8844cc; font-size: 11px; font-weight: 600;"
            )
            row2.addWidget(pitch_lbl)
            row2.addStretch()
            info_col.addLayout(row2)

        # Row 3: Q / BW / magnitude
        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(10)
        if peak.quality:
            q_lbl = QtWidgets.QLabel(
                f"<span style='color:grey;font-size:10px;'>Q:</span> "
                f"<b style='font-size:10px;'>{peak.quality:.1f}</b>"
            )
            q_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
            row3.addWidget(q_lbl)
        if peak.bandwidth:
            bw_lbl = QtWidgets.QLabel(
                f"<span style='color:grey;font-size:10px;'>BW:</span> "
                f"<b style='font-size:10px;'>{peak.bandwidth:.1f} Hz</b>"
            )
            bw_lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
            row3.addWidget(bw_lbl)
        row3.addStretch()
        mag_color = _mag_color(peak.magnitude)
        mag_lbl = QtWidgets.QLabel(f"{peak.magnitude:.1f} dB")
        mag_lbl.setStyleSheet(
            f"font-weight: 600; font-size: 11px; "
            f"color: rgb({mag_color.red()},{mag_color.green()},{mag_color.blue()});"
        )
        row3.addWidget(mag_lbl)
        info_col.addLayout(row3)

        root.addLayout(info_col)


# ── Detail dialog ─────────────────────────────────────────────────────────────

class MeasurementDetailDialog(QtWidgets.QDialog):
    """
    Read-only detail dialog.  Shows measurement info and detected peaks.

    Load / Export / Export PDF Report are reached from the popup menu on
    the row in the Measurements list (see MeasurementsListView); only the
    Close button remains here.  Matches MeasurementDetailView.swift.
    """

    def __init__(
        self,
        measurement: TapToneMeasurement,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Measurement Details")
        self.resize(640, 640)
        self._m = measurement
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(inner)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(12)
        scroll.setWidget(inner)
        root.addWidget(scroll)

        m = self._m

        # ── Measurement Info ─────────────────────────────────────────────────
        info_group = QtWidgets.QGroupBox("Measurement Info")
        info_layout = QtWidgets.QFormLayout(info_group)
        info_layout.setHorizontalSpacing(16)
        info_layout.setVerticalSpacing(6)

        if m.measurement_name:
            loc = QtWidgets.QLabel(m.measurement_name)
            loc.setStyleSheet("font-weight: bold;")
            info_layout.addRow("Measurement Name:", loc)

        info_layout.addRow("Date:", QtWidgets.QLabel(format_display_datetime(m.timestamp)))

        info_layout.addRow("Measurement Type:", QtWidgets.QLabel(_type_name(m)))
        if m.number_of_taps is not None:
            info_layout.addRow(
                "Number of Taps:", QtWidgets.QLabel(str(m.number_of_taps))
            )
        if m.microphone_name:
            info_layout.addRow(
                "Microphone:", QtWidgets.QLabel(m.microphone_name)
            )
        if m.calibration_name:
            info_layout.addRow(
                "Calibration:", QtWidgets.QLabel(m.calibration_name)
            )
        if m.notes:
            notes_label = QtWidgets.QLabel(m.notes)
            notes_label.setWordWrap(True)
            info_layout.addRow("Notes:", notes_label)

        vbox.addWidget(info_group)

        # Comparison records show the per-spectrum Air/Top/Back table; everything
        # else shows the identified (selected) peaks only.
        if m.is_comparison:
            from views.comparison_results_view import ComparisonResultsView
            cmp_group = QtWidgets.QGroupBox(
                f"Compared Spectra ({len(m.comparison_entries or [])})"
            )
            cmp_vbox = QtWidgets.QVBoxLayout(cmp_group)
            cmp_view = ComparisonResultsView()
            cmp_view.set_comparison_data(_comparison_data(m))
            cmp_vbox.addWidget(cmp_view)
            vbox.addWidget(cmp_group)
        else:
            selected_ids = set(
                m.selected_peak_ids if m.selected_peak_ids is not None
                else [p.id for p in m.peaks]
            )
            shown = sorted(
                (p for p in m.peaks if p.id in selected_ids),
                key=lambda p: p.frequency,
            )
            peaks_group = QtWidgets.QGroupBox("Identified Peaks")
            peaks_vbox = QtWidgets.QVBoxLayout(peaks_group)
            peaks_vbox.setSpacing(4)

            if not shown:
                peaks_vbox.addWidget(QtWidgets.QLabel("No identified peaks"))
            else:
                from views.shared.peaks_model import PeaksModel
                mat_colors = PeaksModel._MATERIAL_MODE_COLORS
                gt = _resolve_guitar_type(m.guitar_type)
                is_material = (
                    m.longitudinal_snapshot is not None
                    or m.selected_longitudinal_peak_id is not None
                )
                id_map = {} if is_material else GM.GuitarMode.classify_all(shown, gt)
                for peak in shown:
                    if is_material:
                        if peak.id == m.selected_longitudinal_peak_id:
                            label = "Longitudinal"
                        elif peak.id == m.selected_cross_peak_id:
                            label = "Cross-grain"
                        elif peak.id == m.selected_flc_peak_id:
                            label = "FLC"
                        else:
                            label = "Peak"
                        rgb = mat_colors.get(label, (150, 150, 150))
                        row = _PeakRow(
                            peak, GM.GuitarMode.UNKNOWN, label, gt,
                            label_color=QtGui.QColor(*rgb),
                        )
                    else:
                        mode = id_map.get(peak.id, GM.GuitarMode.UNKNOWN)
                        override = (
                            m.peak_mode_overrides.get(peak.id)
                            if m.peak_mode_overrides else None
                        )
                        label = override or peak.mode_label or mode.display_name
                        row = _PeakRow(peak, mode, label, gt)
                    peaks_vbox.addWidget(row)

            vbox.addWidget(peaks_group)
        vbox.addStretch()

        # ── Button row ───────────────────────────────────────────────────────
        # The detail view is read-only.  Load / Export / Export PDF Report
        # are all available from the row's popup menu in the Measurements
        # list (see MeasurementsListView), so no duplicate controls are
        # presented here.  Only the Close button remains.
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)
