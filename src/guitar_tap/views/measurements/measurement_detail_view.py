"""
Detail dialog for a single saved TapToneMeasurement.
Matches MeasurementDetailView.swift / CombinedPeakModeRowView.swift.
"""

# @parity view/measurement-detail

from PySide6 import QtCore, QtGui, QtWidgets

from guitar_tap.models import TapToneMeasurement
from guitar_tap.models import guitar_mode as GM
from guitar_tap.models import pitch as P
from guitar_tap.utilities.date_format import format_display_datetime
from guitar_tap.views.shared.peak_card_widget import PeakCardWidget
from guitar_tap.views.utilities import palette

# ── Helpers ───────────────────────────────────────────────────────────────────

_PITCH = P.Pitch(440)

def _comparison_data(m) -> "list[dict]":
    """Build ComparisonResultsView rows from a saved comparison's entries."""
    data = []
    for index, e in enumerate(m.comparison_entries or []):
        data.append({
            "label": e.label, "role": palette.comparison_role(index, e.label), "peaks": e.peaks,
            "guitar_type": e.guitar_type,
        })
    return data


# ── Peak row widget (matches CombinedPeakModeRowView read-only mode) ──────────

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
        # The window in background.window, its footer in background.panel, as Swift's.
        palette.surface(self, palette.Role.BACKGROUND_WINDOW)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        # No frame: the group boxes sit on the window, as Swift's.
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        inner = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(inner)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(12)
        scroll.setWidget(inner)
        root.addWidget(scroll)

        m = self._m

        # ── Measurement Info ─────────────────────────────────────────────────
        # Swift's GroupBox rows: a small secondary "Label:" then the value at body size, left to
        # right; the box fits its content.
        info_group = QtWidgets.QGroupBox("Measurement Info")
        palette.tag(info_group, group=True)
        info_group.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Preferred)
        info_rows = QtWidgets.QVBoxLayout(info_group)
        info_rows.setSpacing(8)
        caption = QtGui.QFont(self.font())
        caption.setPointSize(max(8, self.font().pointSize() - 3))

        def _add_row(label: str, value: QtWidgets.QLabel) -> None:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(6)
            lbl = QtWidgets.QLabel(label)
            lbl.setFont(caption)
            palette.tag(lbl, color=palette.Role.TEXT_SECONDARY)
            row.addWidget(lbl, 0, QtCore.Qt.AlignmentFlag.AlignBaseline)
            row.addWidget(value, 1, QtCore.Qt.AlignmentFlag.AlignBaseline)
            info_rows.addLayout(row)

        if m.measurement_name:
            loc = QtWidgets.QLabel(m.measurement_name)
            name_font = QtGui.QFont(self.font())
            name_font.setWeight(QtGui.QFont.Weight.Medium)
            loc.setFont(name_font)
            _add_row("Measurement Name:", loc)

        _add_row("Date:", QtWidgets.QLabel(format_display_datetime(m.timestamp)))

        _add_row("Measurement Type:", QtWidgets.QLabel(m.measurement_type_short_name))
        if m.number_of_taps is not None:
            _add_row(
                "Number of Taps:", QtWidgets.QLabel(str(m.number_of_taps))
            )
        # No recorded microphone means it is unknown (a played file, say). A comparison has no
        # microphone of its own. Mirrors Swift MeasurementDetailView.
        if not m.is_comparison:
            _add_row(
                "Microphone:", QtWidgets.QLabel(m.microphone_name or "unknown")
            )
        if m.calibration_name:
            _add_row(
                "Calibration:", QtWidgets.QLabel(m.calibration_name)
            )
        if m.notes:
            notes_label = QtWidgets.QLabel(m.notes)
            notes_label.setWordWrap(True)
            _add_row("Notes:", notes_label)

        vbox.addWidget(info_group, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        # Comparison records show the per-spectrum Air/Top/Back table; everything
        # else shows the identified (selected) peaks only.
        if m.is_comparison:
            from guitar_tap.views.comparison_results_view import ComparisonResultsView
            cmp_group = QtWidgets.QGroupBox(
                f"Compared Spectra ({len(m.comparison_entries or [])})"
            )
            palette.tag(cmp_group, group=True)
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
            palette.tag(peaks_group, group=True)
            peaks_vbox = QtWidgets.QVBoxLayout(peaks_group)
            peaks_vbox.setSpacing(4)

            if not shown:
                none_lbl = QtWidgets.QLabel("No identified peaks")
                palette.tag(none_lbl, color=palette.Role.TEXT_SECONDARY)
                peaks_vbox.addWidget(none_lbl)
            else:
                # The measurement's own modes and labels — classified among all its peaks, as the
                # file is written and the live view showed them, not among the shown ones.
                gt = m.classification_guitar_type
                is_material = m.is_material
                id_map = m.auto_modes
                labels = m.peak_mode_labels
                pitch = P.Pitch(440)
                for peak in shown:
                    # The results panel's peak card, read-only — as Swift's Details reuses
                    # CombinedPeakModeRowView.
                    override = None
                    fallback = "Peak" if is_material else GM.GuitarMode.UNKNOWN.display_name
                    label = labels.get(peak.id, fallback)
                    if is_material:
                        auto_label = ""
                    else:
                        mode = id_map.get(peak.id, GM.GuitarMode.UNKNOWN)
                        override = (
                            m.peak_mode_overrides.get(peak.id)
                            if m.peak_mode_overrides else None
                        )
                        auto_label = mode.display_name
                    q = float(peak.quality)
                    row = PeakCardWidget(
                        freq=float(peak.frequency),
                        mag_db=float(peak.magnitude),
                        q=q,
                        bandwidth=float(peak.bandwidth),
                        guitar_type=gt,
                        mode=label,
                        auto_mode=auto_label,
                        show="on",
                        is_held=False,
                        pitch_obj=pitch,
                        show_pitch=True,
                        read_only=True,
                    )
                    row.set_mode(label, auto_label, is_manual=override is not None)
                    peaks_vbox.addWidget(row)

            vbox.addWidget(peaks_group)
        vbox.addStretch()

        # ── Button row ───────────────────────────────────────────────────────
        # The detail view is read-only.  Load / Export / Export PDF Report
        # are all available from the row's popup menu in the Measurements
        # list (see MeasurementsListView), so no duplicate controls are
        # presented here.  Only Done remains: bottom right, the platform's button, not the default
        # since it only closes (Swift's Done).
        footer = QtWidgets.QWidget()
        footer.setObjectName("detail_footer")
        footer.setStyleSheet("#detail_footer { border-top-width: 1px; border-top-style: solid; }")
        palette.tag(footer, background=palette.Role.BACKGROUND_PANEL, border=palette.Role.SEPARATOR)
        btn_row = QtWidgets.QHBoxLayout(footer)
        btn_row.setContentsMargins(16, 10, 16, 10)
        btn_row.addStretch()

        close_btn = QtWidgets.QPushButton("Done")
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addWidget(footer)
