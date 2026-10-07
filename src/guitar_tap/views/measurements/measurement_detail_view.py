"""
Detail dialog for a single saved TapToneMeasurement.
Matches MeasurementDetailView.swift / CombinedPeakModeRowView.swift.
"""

# @parity view/measurement-detail

from PySide6 import QtWidgets

from guitar_tap.models import TapToneMeasurement
from guitar_tap.models import guitar_mode as GM
from guitar_tap.models import guitar_type as GT
from guitar_tap.models import pitch as P
from guitar_tap.utilities.date_format import format_display_datetime
from guitar_tap.views.shared.peak_card_widget import PeakCardWidget
from guitar_tap.views.utilities import palette
from guitar_tap.views.utilities.material_peak_role import MaterialPeakRole

# ── Helpers ───────────────────────────────────────────────────────────────────

_PITCH = P.Pitch(440)

def _resolve_guitar_type(guitar_type_str: str | None) -> GT.GuitarType:
    """Convert a guitar_type string to GuitarType enum, defaulting to Generic."""
    if guitar_type_str:
        try:
            return GT.GuitarType(guitar_type_str)
        except ValueError:
            pass
    return GT.GuitarType.GENERIC


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

        info_layout.addRow("Measurement Type:", QtWidgets.QLabel(m.measurement_type_short_name))
        if m.number_of_taps is not None:
            info_layout.addRow(
                "Number of Taps:", QtWidgets.QLabel(str(m.number_of_taps))
            )
        # No recorded microphone means it is unknown (a played file, say). A comparison has no
        # microphone of its own. Mirrors Swift MeasurementDetailView.
        if not m.is_comparison:
            info_layout.addRow(
                "Microphone:", QtWidgets.QLabel(m.microphone_name or "unknown")
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
            from guitar_tap.views.comparison_results_view import ComparisonResultsView
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
                gt = _resolve_guitar_type(m.guitar_type)
                is_material = (
                    m.longitudinal_snapshot is not None
                    or m.selected_longitudinal_peak_id is not None
                )
                id_map = {} if is_material else GM.GuitarMode.classify_all(shown, gt)
                pitch = P.Pitch(440)
                for peak in shown:
                    # The results panel's peak card, read-only — as Swift's Details reuses
                    # CombinedPeakModeRowView.
                    override = None
                    if is_material:
                        if peak.id == m.selected_longitudinal_peak_id:
                            label = MaterialPeakRole.LONGITUDINAL.display_name
                        elif peak.id == m.selected_cross_peak_id:
                            label = MaterialPeakRole.CROSS.display_name
                        elif peak.id == m.selected_flc_peak_id:
                            label = MaterialPeakRole.FLC.display_name
                        else:
                            label = "Peak"
                        auto_label = ""
                    else:
                        mode = id_map.get(peak.id, GM.GuitarMode.UNKNOWN)
                        override = (
                            m.peak_mode_overrides.get(peak.id)
                            if m.peak_mode_overrides else None
                        )
                        # override > classification. NOT peak.mode_label: that is an
                        # export-only convenience injected at serialisation time, not stored
                        # state, and preferring it here showed a label this app's own writer
                        # would never save — a loaded file's stale label outlived the
                        # reclassification that replaced it. Swift derives at display time for
                        # the same reason (MeasurementDetailView).
                        label = override or mode.display_name
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
        # presented here.  Only the Close button remains.
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)
