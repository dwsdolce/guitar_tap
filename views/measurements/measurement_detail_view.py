"""
Detail dialog for a single saved TapToneMeasurement.
Matches MeasurementDetailView.swift / CombinedPeakModeRowView.swift.
"""

import os
from datetime import datetime, timezone

from PyQt6 import QtCore, QtGui, QtWidgets
import qtawesome as qta

from views import tap_analysis_results_view as M
from models import TapToneMeasurement, ResonantPeak
from models import guitar_mode as GM
from models import pitch as P
from models import guitar_type as GT


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


# ── Peak row widget (matches CombinedPeakModeRowView read-only mode) ──────────

class _PeakRow(QtWidgets.QFrame):
    """
    Displays one peak matching CombinedPeakModeRowView layout:

      [★]  [icon]  [mode label    freq Hz]
                   [♪ pitch note + cents ]
                   [Q: x.x  BW: x.x Hz   mag dB]
    """

    def __init__(
        self,
        peak: ResonantPeak,
        mode: GM.GuitarMode,
        effective_label: str,
        is_selected: bool,
        guitar_type: GT.GuitarType,
        parent=None,
    ) -> None:
        super().__init__(parent)

        color = _mode_qcolor(mode)
        r, g, b = mode.color

        # Tinted background (mode color at 5% opacity)
        self.setAutoFillBackground(True)
        pal = self.palette()
        bg = QtGui.QColor(r, g, b, 13)  # ~5% opacity
        pal.setColor(QtGui.QPalette.ColorRole.Window, bg)
        self.setPalette(pal)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)

        opacity = 1.0 if is_selected else 0.4

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(8)

        # ── Star ──────────────────────────────────────────────────────────────
        star_label = QtWidgets.QLabel("★" if is_selected else "☆")
        star_label.setStyleSheet(
            f"color: {'#3478f6' if is_selected else '#888888'}; font-size: 14px;"
        )
        star_label.setFixedWidth(18)
        root.addWidget(star_label)

        # ── Mode icon ─────────────────────────────────────────────────────────
        try:
            icon_lbl = QtWidgets.QLabel()
            icon_pixmap = qta.icon(mode.icon, color=color).pixmap(24, 24)
            icon_lbl.setPixmap(icon_pixmap)
        except Exception:
            icon_lbl = QtWidgets.QLabel("◆")
            icon_lbl.setStyleSheet(f"color: rgb({r},{g},{b}); font-size: 16px;")
        icon_lbl.setFixedWidth(28)
        root.addWidget(icon_lbl)

        # ── In-range badge ────────────────────────────────────────────────────
        if mode not in (GM.GuitarMode.UNKNOWN, GM.GuitarMode.UPPER_MODES):
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

        # ── Info column ───────────────────────────────────────────────────────
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

        freq_lbl = QtWidgets.QLabel(f"{peak.frequency:.2f} Hz")
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

        # Apply opacity to unselected peaks
        if not is_selected:
            effect = QtWidgets.QGraphicsOpacityEffect(self)
            effect.setOpacity(opacity)
            self.setGraphicsEffect(effect)


# ── Detail dialog ─────────────────────────────────────────────────────────────

class MeasurementDetailDialog(QtWidgets.QDialog):
    """
    Shows measurement info, detected peaks, and Load / Export / PDF buttons.
    Matches MeasurementDetailView.swift.

    Emits measurementSelected(m) when the user confirms Load.
    """

    measurementSelected: QtCore.pyqtSignal = QtCore.pyqtSignal(object)

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

        if m.tap_location:
            loc = QtWidgets.QLabel(m.tap_location)
            loc.setStyleSheet("font-weight: bold;")
            info_layout.addRow("Location:", loc)

        try:
            dt = datetime.fromisoformat(m.timestamp).astimezone()
            date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            date_str = m.timestamp
        info_layout.addRow("Date:", QtWidgets.QLabel(date_str))

        if m.decay_time is not None:
            info_layout.addRow(
                "Ring-Out:", QtWidgets.QLabel(f"{m.decay_time:.2f} s")
            )

        # Tap tone ratio (fTop/fAir)
        ratio = self._compute_tap_tone_ratio()
        if ratio is not None:
            ratio_lbl = QtWidgets.QLabel(f"{ratio:.2f} : 1")
            ratio_lbl.setStyleSheet("font-weight: bold;")
            ratio_lbl.setToolTip(
                "fTop / fAir ratio — ideal ≈ 2.0 (Top one octave above Air)"
            )
            info_layout.addRow("Tap Tone Ratio:", ratio_lbl)

        if m.measurement_type:
            info_layout.addRow(
                "Measurement Type:", QtWidgets.QLabel(m.measurement_type)
            )
        if m.guitar_type:
            info_layout.addRow("Guitar Type:", QtWidgets.QLabel(m.guitar_type))
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

        # ── Detected Peaks ───────────────────────────────────────────────────
        selected_ids = set(
            m.selected_peak_ids if m.selected_peak_ids is not None
            else [p.id for p in m.peaks]
        )
        sorted_peaks = sorted(m.peaks, key=lambda p: p.frequency)
        sel_count = sum(1 for p in sorted_peaks if p.id in selected_ids)
        unsel_count = len(sorted_peaks) - sel_count

        group_title = f"Detected Peaks ({sel_count} selected"
        if unsel_count:
            group_title += f", {unsel_count} unselected"
        group_title += ")"
        peaks_group = QtWidgets.QGroupBox(group_title)
        peaks_vbox = QtWidgets.QVBoxLayout(peaks_group)
        peaks_vbox.setSpacing(4)

        if not sorted_peaks:
            peaks_vbox.addWidget(QtWidgets.QLabel("No peaks detected"))
        else:
            gt = _resolve_guitar_type(m.guitar_type)
            # Classify all peaks with context-aware mode map — id_map mirrors Swift [UUID: GuitarMode]
            id_map = GM.GuitarMode.classify_all(sorted_peaks, gt)

            for i, peak in enumerate(sorted_peaks):
                mode = id_map.get(peak.id, GM.GuitarMode.UNKNOWN)
                # Effective label: mode override > stored mode_label > auto mode
                override = (
                    m.peak_mode_overrides.get(peak.id)
                    if m.peak_mode_overrides else None
                )
                if override:
                    label = override
                elif peak.mode_label:
                    label = peak.mode_label
                else:
                    label = mode.display_name

                is_selected = peak.id in selected_ids
                row = _PeakRow(peak, mode, label, is_selected, gt)
                peaks_vbox.addWidget(row)

        vbox.addWidget(peaks_group)
        vbox.addStretch()

        # ── Button row ───────────────────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()

        load_btn = QtWidgets.QPushButton("Load into View")
        load_btn.clicked.connect(self._on_load)
        btn_row.addWidget(load_btn)

        export_btn = QtWidgets.QPushButton("Export JSON…")
        export_btn.clicked.connect(self._on_export_json)
        btn_row.addWidget(export_btn)

        export_pdf_btn = QtWidgets.QPushButton("Export PDF Report…")
        export_pdf_btn.clicked.connect(self._on_export_pdf)
        btn_row.addWidget(export_pdf_btn)

        btn_row.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _compute_tap_tone_ratio(self) -> float | None:
        """Compute fTop/fAir ratio from peaks using classify_all."""
        m = self._m
        if not m.peaks:
            return None
        try:
            gt = _resolve_guitar_type(m.guitar_type)
            id_map = GM.GuitarMode.classify_all(m.peaks, gt)

            air_freq = next(
                (p.frequency for p in m.peaks
                 if id_map.get(p.id, GM.GuitarMode.UNKNOWN).normalized == GM.GuitarMode.AIR),
                None,
            )
            top_freq = next(
                (p.frequency for p in m.peaks
                 if id_map.get(p.id, GM.GuitarMode.UNKNOWN).normalized == GM.GuitarMode.TOP),
                None,
            )
            if air_freq and top_freq and air_freq > 0:
                return top_freq / air_freq
        except Exception:
            pass
        return None

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_load(self) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "Load Measurement",
            "This will replace the current analysis view with this measurement's "
            "data, including peaks and spectrum. Continue?",
            QtWidgets.QMessageBox.StandardButton.Ok
            | QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Ok:
            self.measurementSelected.emit(self._m)
            self.accept()

    def _on_export_json(self) -> None:
        default_name = self._m.base_filename + ".json"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Measurement",
            os.path.join(os.path.expanduser("~/Documents/GuitarTap"), default_name),
            "JSON files (*.json *.guitartap);;All files (*)",
        )
        if not path:
            return
        try:
            text = M.export_measurement_json(self._m)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export Error", f"Could not export:\n{exc}"
            )

    def _on_export_pdf(self) -> None:
        default_name = self._m.base_filename + ".pdf"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            os.path.join(os.path.expanduser("~/Documents/GuitarTap"), default_name),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        try:
            M.export_pdf(self._m, None, path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export Error", f"Could not export PDF:\n{exc}"
            )
