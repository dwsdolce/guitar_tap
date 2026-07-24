"""
    The data model for the Peaks table.
"""

from enum import Enum

import numpy as np
import numpy.typing as npt
from models import guitar_mode as gm
from models import pitch as pitch_c
from models.annotation_visibility_mode import AnnotationVisibilityMode as AVM
from PySide6 import QtCore


class ColumnIndex(Enum):
    """Enum class so we can use the values for the headers."""

    # pylint: disable=invalid-name
    Show = 0
    Freq = 1
    Mag = 2
    Q = 3
    Pitch = 4
    Cents = 5
    Modes = 6


# pylint: disable=too-many-instance-attributes
# pylint: disable=too-many-public-methods
class PeaksModel(QtCore.QAbstractTableModel):
    """Custom data model to handle deriving pitch and cents from frequency. Also defines
    accessing the underlying data model.
    """

    annotationUpdate: QtCore.Signal = QtCore.Signal(str, float, float, str, str)  # (peak_id, freq, mag, html, mode_str)
    annotationsRefreshed: QtCore.Signal = QtCore.Signal()  # fired once after a batch of annotationUpdate emissions
    clearAnnotations: QtCore.Signal = QtCore.Signal()
    hideAnnotations: QtCore.Signal = QtCore.Signal()
    hideAnnotation: QtCore.Signal = QtCore.Signal(float)
    userModifiedSelectionChanged: QtCore.Signal = QtCore.Signal(bool)
    # A USER per-peak show/selection toggle, carrying the peak id, so the view can route it to
    # the analyzer (mirrors Swift onToggleSelection -> togglePeakSelection). NOT emitted for
    # programmatic bulk updates (select_all/deselect_all).
    selectionToggled: QtCore.Signal = QtCore.Signal(str)
    # A USER mode-override change carrying (peak_id, new_label); "" = reset to auto. The view routes
    # it to analyzer.set_mode_override (mirrors selectionToggled -> toggle_peak_selection), so the
    # definitive-mode uniqueness enforcement runs. Qt is imperative: SwiftUI binds the change to
    # setModeOverride reactively; Python must forward it. NOT emitted for programmatic/bulk updates.
    modeOverrideChanged: QtCore.Signal = QtCore.Signal(str, str)
    modeColorsChanged: QtCore.Signal = QtCore.Signal(object)  # dict[float, tuple[int,int,int]]

    mode_strings: list[str] = [
        "",
        "Air (Helmholtz)",
        "Top",
        "Back",
        "Dipole",
        "Ring Mode",
        "Upper Modes",
        "Unknown",
        "Helmholtz T(1,1)_1",
        "Top T(1,1)_2",
        "Back T(1,1)_3",
        "Cross Dipole T(2,1)",
        "Long Dipole T(1,2)",
        "Quadrapole T(2,2)",
        "Cross Tripole T(3,1)",
    ]

    header_names: list[str] = [e.name for e in ColumnIndex]

    def __init__(self, data: npt.NDArray) -> None:
        super().__init__()
        self._peaks: list = []  # list[ResonantPeak] — authoritative peak objects
        # Optional back-reference to the analyzer, set by the view (as it does for the annotation
        # layer). Used ONLY to resolve the override-BLIND auto mode for the "Reset to Auto-Detected"
        # label via analyzer.auto_detected_mode — the model source of truth (mirrors Swift).
        self._analyzer = None
        self._data: npt.NDArray = data
        self.pitch: pitch_c.Pitch = pitch_c.Pitch(440)
        self.modes_width: int = len(max(self.mode_strings, key=len))
        self.modes_column: int = ColumnIndex.Modes.value
        self.modes: dict[float, str] = {}
        self.is_live: bool = True
        self.selected_peak_ids: set[str] = set()  # mirrors Swift selectedPeakIDs: Set<UUID>
        self.show_column: int = ColumnIndex.Show.value
        self.user_has_modified_peak_selection: bool = False
        self._programmatic_update: bool = False
        # Current annotation visibility mode.
        self._annotation_mode: AVM = AVM.SELECTED
        # peak id → mode, from classify_all. Keyed by IDENTITY, never by frequency: two peaks
        # can share a frequency, and a frequency-keyed map silently collapses them so the last
        # one's label wins for both. See Development/PEAK-FINDING-DUPLICATE-PEAKS.md section 3d.
        self._auto_mode_map: dict[str, gm.GuitarMode] = {}
        # Selected L/C/FLC peak IDs for plate/brace measurements.
        # Mirrors Swift selectedLongitudinalPeakID / selectedCrossPeakID / selectedFlcPeakID
        # passed as parameters to PeakAnnotationsOverlay / DraggablePeakAnnotation.
        self.selected_longitudinal_peak_id: str | None = None
        self.selected_cross_peak_id: str | None = None
        self.selected_flc_peak_id: str | None = None
        # Whether this model is displaying guitar peaks or plate/brace peaks.
        # Mirrors Swift measurementType.isGuitar guard in modeLabel / modeColor.
        self.is_guitar: bool = True

    # MARK: - Annotation mode (reactive, mirrors Swift @Published annotationVisibilityMode)

    @property
    def annotation_mode(self) -> AVM:
        """Current annotation visibility mode."""
        return self._annotation_mode

    @annotation_mode.setter
    def annotation_mode(self, mode: AVM) -> None:
        """Set the annotation visibility mode and re-apply it to the current peaks.

        Mirrors Swift's behaviour where changing annotationVisibilityMode on
        TapToneAnalyzer automatically re-evaluates visiblePeaks (a computed
        property), causing the chart to re-render with the correct subset.
        Uses refresh_annotations() so the pre-installed _auto_mode_map (from
        update_data_with_modes) is preserved — only annotation emission changes,
        not mode classification.
        """
        if self._annotation_mode == mode:
            return
        self._annotation_mode = mode
        if self._peaks:
            self.refresh_annotations()

    # MARK: - Centralised annotation helpers
    # Mirrors Swift's visiblePeaks computed property: a single place that
    # decides whether a peak should have a visible annotation.

    def _should_show_annotation(self, index: QtCore.QModelIndex) -> bool:
        """Return True if *index* should have a visible annotation.

        Centralises the visibility decision that was previously duplicated in
        ``update_annotation``, ``refresh_annotations`` and
        ``update_data_with_modes``.  The rule mirrors Swift's
        ``visiblePeaks`` computed property:

        * ``NONE``     → never show
        * ``ALL``      → always show
        * ``SELECTED`` → show only if the peak's show/selected flag is set
        """
        if self._annotation_mode == AVM.NONE:
            return False
        if self._annotation_mode == AVM.ALL:
            return True
        return self.show_value_bool(index)

    def _emit_annotation(self, index: QtCore.QModelIndex) -> None:
        """Emit the correct annotation signal for *index*.

        If the peak should be visible (per ``_should_show_annotation``),
        emits ``annotationUpdate``; otherwise emits ``hideAnnotation``.
        """
        freq = self.freq_value(index)
        if self._should_show_annotation(index):
            mag = self.magnitude_value(index)
            mode = self.mode_value(index)
            html = self.annotation_html(freq, mag, mode)
            row = index.row()
            peak_id = self._peaks[row].id if row < len(self._peaks) else ""
            self.annotationUpdate.emit(peak_id, freq, mag, html, mode)
        else:
            self.hideAnnotation.emit(freq)

    def set_mode_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """Sets the value of the mode."""
        self.modes[self.freq_value(index)] = value
        # Route a USER mode change to the analyzer (Qt vs SwiftUI) so enforce runs; skip programmatic.
        if not getattr(self, "_programmatic_update", False):
            peak_id = self._peak_id_at(index)
            if peak_id:
                self.modeOverrideChanged.emit(peak_id, value)

    def reset_mode_value(self, index: QtCore.QModelIndex) -> None:
        """Remove any manual mode override, reverting to auto-classification."""
        self.modes.pop(self.freq_value(index), None)
        if not getattr(self, "_programmatic_update", False):
            peak_id = self._peak_id_at(index)
            if peak_id:
                self.modeOverrideChanged.emit(peak_id, "")  # "" = reset to auto

    def _emit_mode_colors(self) -> None:
        """Emit modeColorsChanged with the current freq→RGB color map.

        For guitar measurements, colours come from the auto-classified GuitarMode.
        For plate/brace measurements, colours are determined by the selected
        L/C/FLC peak IDs — matching Swift peakColor(for:) in SpectrumView.
        """
        if self.is_guitar:
            # The signal's contract is frequency-keyed; build it from the id-keyed map so the
            # storage is identity-based while consumers are unchanged.
            color_map = {
                p.frequency: self._auto_mode_map[p.id].color
                for p in self._peaks
                if p.id in self._auto_mode_map
            }
        else:
            color_map: dict[float, tuple[int, int, int]] = {}
            mc = self._MATERIAL_MODE_COLORS
            for i, peak in enumerate(self._peaks):
                pid = peak.id
                if pid == self.selected_longitudinal_peak_id:
                    color_map[peak.frequency] = mc["Longitudinal"]
                elif pid == self.selected_cross_peak_id:
                    color_map[peak.frequency] = mc["Cross-grain"]
                elif pid == self.selected_flc_peak_id:
                    color_map[peak.frequency] = mc["FLC"]
                else:
                    color_map[peak.frequency] = mc["Peak"]
        self.modeColorsChanged.emit(color_map)

    def _recompute_auto_modes(self) -> None:
        """Rebuild the context-aware mode map from current peak data.

        Mirrors Swift identifiedModes computed via GuitarMode.classifyAll —
        overlapping mode ranges resolve correctly because the claiming algorithm
        visits modes in ascending lower-bound order and marks each peak as used.

        For plate/brace measurements (is_guitar=False), the mode map is cleared
        — mirrors Swift PeakAnnotationsOverlay.peakModeMap:
          guard measurementType.isGuitar else { return [:] }
        """
        if not self.is_guitar or self._data.shape[0] == 0:
            self._auto_mode_map = {}
            return
        peaks = [(float(self._data[i, 0]), float(self._data[i, 1]))
                 for i in range(self._data.shape[0])]
        idx_map = gm.GuitarMode._classify_all_tuples(peaks)
        self._auto_mode_map = {
            self._peaks[i].id: mode
            for i, mode in idx_map.items()
            if i < len(self._peaks)
        }

    def _peak_id_at(self, index: QtCore.QModelIndex) -> str:
        """Peak id for a row, or "" when out of range. The key for every per-peak lookup."""
        row = index.row()
        return self._peaks[row].id if 0 <= row < len(self._peaks) else ""

    def mode_value(self, index: QtCore.QModelIndex) -> str:
        """Return mode: manual override if set, else resolved by measurement type.

        For plate/brace measurements (non-guitar), mirrors Swift modeLabel in
        DraggablePeakAnnotation: checks peak.id against selectedLongitudinalPeakID,
        selectedCrossPeakID, selectedFlcPeakID, returning the matching label or "Peak".

        For guitar measurements, uses manual override, then auto-classified GuitarMode.
        """
        freq = self.freq_value(index)
        if freq in self.modes:
            return self.modes[freq]
        # Plate/brace: determine label by selected peak ID, mirrors Swift modeLabel.
        if not self.is_guitar:
            row = index.row()
            peak_id = self._peaks[row].id if row < len(self._peaks) else None
            if peak_id is not None:
                if peak_id == self.selected_longitudinal_peak_id:
                    return "Longitudinal"
                if peak_id == self.selected_cross_peak_id:
                    return "Cross-grain"
                if peak_id == self.selected_flc_peak_id:
                    return "FLC"
            return "Peak"
        mode = self._auto_mode_map.get(self._peak_id_at(index))
        if mode is not None:
            return mode.display_name
        # Fallback: _auto_mode_map should always be populated for every current peak,
        # but if somehow a frequency is missing, use classify_all (claiming algorithm)
        # rather than classify_peak (simple range lookup) — mirrors Swift, which has
        # no single-peak classify fallback; classifyAll is always used.
        from models.resonant_peak import ResonantPeak as _RP
        _fake = _RP(frequency=freq, magnitude=0.0, quality=1.0)
        _mode = gm.GuitarMode.classify_all([_fake]).get(_fake.id, gm.GuitarMode.UNKNOWN)
        return _mode.display_name

    def peak_mode(self, index: QtCore.QModelIndex) -> str:
        """Return the AUTO-detected mode string for a peak — **override-blind** — for the
        "Reset to Auto-Detected (X)" menu label (the target of the reset, not the current label).

        Delegates to the analyzer's ``auto_detected_mode`` — the model source of truth — mirroring
        Swift where the reset row consumes ``analyzer.autoDetectedMode(for:)``. **Must NOT read
        ``_auto_mode_map``**: that map is populated from the override-AWARE ``analyzer.peak_mode`` (it
        drives mode colours), so reading it here showed the *current* label, not the auto one — the
        exact bug Swift Phase 5 fixed. Falls back to an override-blind ``classify_all`` only when no
        analyzer is wired (isolated model tests).
        """
        if not self.is_guitar:
            # Plate/brace: auto-label is the phase-assigned role, same as mode_value
            # (there are no user overrides for plate/brace in the card menu).
            return self.mode_value(index)
        row = index.row()
        peak = self._peaks[row] if 0 <= row < len(self._peaks) else None
        if peak is not None and self._analyzer is not None:
            return self._analyzer.auto_detected_mode(peak).display_name
        # Fallback (no analyzer wired): override-blind classify_all on the frequency.
        from models.resonant_peak import ResonantPeak as _RP
        _fake = _RP(frequency=self.freq_value(index), magnitude=0.0, quality=1.0)
        _mode = gm.GuitarMode.classify_all([_fake]).get(_fake.id, gm.GuitarMode.UNKNOWN)
        return _mode.display_name

    def set_show_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """Sets the value of the show."""
        row = index.row()
        peak_id = self._peaks[row].id if row < len(self._peaks) else None
        if peak_id is None:
            return
        if value == "on":
            self.selected_peak_ids.add(peak_id)
        else:
            self.selected_peak_ids.discard(peak_id)
        # Route a USER toggle to the analyzer (the view connects selectionToggled ->
        # analyzer.toggle_peak_selection); skip programmatic bulk updates.
        if not getattr(self, "_programmatic_update", False):
            self.selectionToggled.emit(peak_id)

    def show_value_bool(self, index: QtCore.QModelIndex) -> bool:
        """Return whether this peak is shown/selected.

        Mirrors Swift visiblePeaks filtering currentPeaks by selectedPeakIDs:
          case .selected: candidates = currentPeaks.filter { selectedPeakIDs.contains($0.id) }
        In live guitar mode every peak is shown (mirrors Swift .all candidates path
        during live capture). In frozen/plate/brace mode, consult selectedPeakIDs.
        """
        if self.is_live and self.is_guitar:
            return True
        row = index.row()
        if row >= len(self._peaks):
            return False
        return self._peaks[row].id in self.selected_peak_ids

    def show_value(self, index: QtCore.QModelIndex) -> str:
        """Return the show for the row as "on" or "off"."""
        return "on" if self.show_value_bool(index) else "off"

    def freq_index(self, freq: float) -> QtCore.QModelIndex:
        """From a frequency return the index in the data array."""
        index = np.where(self._data[:, 0] == freq)
        if len(index[0]) == 1:
            return index[0][0]
        return -1

    def freq_value(self, index: QtCore.QModelIndex) -> float:
        """Return the frequency value from the correct column for the row"""
        # print("PeaksModel: freq_value")
        return self._data[index.row()][0]

    def magnitude_value(self, index: QtCore.QModelIndex) -> float:
        """Return the magnitude value from the correct column for the row"""
        return self._data[index.row()][1]

    def q_value(self, index: QtCore.QModelIndex) -> float:
        """Return the Q factor for the row (0 if not available)."""
        if self._data.shape[1] > 2:
            return float(self._data[index.row()][2])
        return 0.0

    # Material (plate/brace) mode label → RGB colour, matching Swift PeakAnnotations.swift
    _MATERIAL_MODE_COLORS: dict[str, tuple[int, int, int]] = {
        "Longitudinal": (50,  100, 220),   # blue
        "Cross-grain":  (220, 130,  0),    # orange
        "FLC":          (150,  50, 200),   # purple
        "Peak":         (150, 150, 150),   # secondary grey
    }

    def annotation_html(self, freq: float, mag: float, mode: str) -> str:
        """Build the HTML label for an annotation, matching Swift PeakAnnotationLabel.

        Layout (top to bottom):
          • Mode name  — bold, mode colour
          • Pitch / cents  — purple  (guitar only)
          • Frequency (Hz) — dark
          • Magnitude (dB) — grey
        """
        rows: list[str] = []

        if mode in self._MATERIAL_MODE_COLORS:
            # Plate / brace: label by phase (no pitch row — not meaningful for material)
            r, g, b = self._MATERIAL_MODE_COLORS[mode]
            rows.append(f'<b style="color:rgb({r},{g},{b});">{mode}</b>')
        else:
            # Guitar: use GuitarMode classifier for colour and display name.
            # Freeform user-defined labels → distinct teal colour.
            guitar_mode = gm.GuitarMode.from_mode_string(mode)
            if (guitar_mode is gm.GuitarMode.UNKNOWN
                    and mode and mode != "Unknown"):
                r, g, b = gm.GuitarMode.USER_DEFINED_COLOR
            else:
                r, g, b = guitar_mode.color
            display = gm.mode_display_name(mode) or ""
            if display:
                rows.append(f'<b style="color:rgb({r},{g},{b});">{display}</b>')
            note  = self.pitch.note(freq)
            cents = self.pitch.cents(freq)
            rows.append(
                f'<span style="color:rgb(120,60,180);">&#9834; {note}&nbsp;&nbsp;{cents:+.0f}&#162;</span>'
            )

        rows.append(f'<span style="color:rgb(50,50,50);">{freq:.1f} Hz</span>')
        rows.append(f'<span style="color:rgb(110,110,110);">{mag:.1f} dB</span>')
        return '<center>' + '<br/>'.join(rows) + '</center>'

    def data_value(self, index: QtCore.QModelIndex) -> QtCore.QVariant:
        """Return the value from the data for cols 1/2 and the value in
        the table for 3/4.
        """
        match index.column():
            case ColumnIndex.Show.value:
                value = self.show_value(index)
            case ColumnIndex.Freq.value:
                value = self.freq_value(index)
            case ColumnIndex.Mag.value:
                value = self.magnitude_value(index)
            case ColumnIndex.Q.value:
                value = self.q_value(index)
            case ColumnIndex.Pitch.value | ColumnIndex.Cents.value:
                value = self.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
            case ColumnIndex.Modes.value:
                value = self.mode_value(index)
            case _:
                value = QtCore.QVariant()
        return value

    def data(
        self, index: QtCore.QModelIndex, role: QtCore.Qt.ItemDataRole
    ) -> QtCore.QVariant:
        """Return the requested data based on role."""
        # print("PeaksModel: data")
        match role:
            case QtCore.Qt.ItemDataRole.DisplayRole:
                match index.column():
                    case ColumnIndex.Show.value:
                        str_value = ""
                    case ColumnIndex.Freq.value:
                        str_value = f"{self.freq_value(index):.1f}"
                    case ColumnIndex.Mag.value:
                        str_value = f"{self.magnitude_value(index):.1f}"
                    case ColumnIndex.Q.value:
                        q = self.q_value(index)
                        str_value = f"{q:.0f}" if q > 0 else ""
                    case ColumnIndex.Pitch.value:
                        str_value = self.pitch.note(self.freq_value(index))
                    case ColumnIndex.Cents.value:
                        str_value = f"{self.pitch.cents(self.freq_value(index)):+.0f}"
                    case ColumnIndex.Modes.value:
                        str_value = self.mode_value(index)
                    case _:
                        str_value = ""
                return str_value
            case QtCore.Qt.ItemDataRole.EditRole:
                match index.column():
                    case ColumnIndex.Modes.value:
                        return self.mode_value(index)
                    case _:
                        return ""

            case QtCore.Qt.ItemDataRole.TextAlignmentRole:
                match index.column():
                    case ColumnIndex.Modes.value:
                        return QtCore.Qt.AlignmentFlag.AlignLeft
                    case _:
                        return QtCore.Qt.AlignmentFlag.AlignRight
            case _:
                return QtCore.QVariant()

    # pylint: disable=invalid-name
    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: QtCore.Qt.ItemDataRole,
    ) -> QtCore.QVariant:
        """Return the header data"""
        match role:
            case QtCore.Qt.ItemDataRole.DisplayRole:
                match orientation:
                    case QtCore.Qt.Orientation.Horizontal:
                        return self.header_names[section]
                    case _:
                        return QtCore.QVariant()
            case _:
                return QtCore.QVariant()

    def update_data(self, peaks: list) -> None:
        """Update the data model from outside the object and then update the table.

        Accepts list[ResonantPeak] — objects all the way through, mirroring Swift's
        currentPeaks: [ResonantPeak]. Builds the internal ndarray for existing display
        logic (freq_value, magnitude_value, q_value, row-based accessors).

        Pure notifier — never touches selection state (selected_peak_ids or
        is_live).  The caller owns selection state; this method only stores the
        new peak list, recomputes derived mode data, and refreshes annotations.

        Mirrors Swift's reactive approach: SpectrumView re-evaluates
        selectedPeakIDs filtering at render time whenever currentPeaks changes,
        so no ordering constraint exists between selection-state mutations and
        data updates.
        """
        self.layoutAboutToBeChanged.emit()
        self._peaks = peaks
        if peaks:
            self._data = np.array(
                [[p.frequency, p.magnitude, p.quality] for p in peaks],
                dtype=np.float64,
            )
        else:
            self._data = np.zeros((0, 3), dtype=np.float64)
        self._recompute_auto_modes()
        self._emit_mode_colors()
        self.layoutChanged.emit()

    def update_data_with_modes(
        self,
        peaks_with_modes: "list[tuple]",  # list[(ResonantPeak, GuitarMode)]
    ) -> None:
        """Update the data model with pre-classified (peak, mode) pairs.

        Mirrors Swift TapAnalysisResultsView.sortedPeaksWithModes (line 287–290)
        which maps each peak through ``analyzer.peakMode(for:)`` to produce
        ``(peak: ResonantPeak, mode: GuitarMode)`` tuples.  By accepting the
        pre-computed modes the model skips ``_recompute_auto_modes()`` and uses
        the analyzer's ``identifiedModes`` as the authoritative source — ensuring
        context-aware, overlap-resolving classification is applied (e.g. classical
        Top/Back both in 190–230 Hz show distinct labels).

        Args:
            peaks_with_modes: Sequence of ``(peak, mode)`` tuples already
                              classified by ``TapToneAnalyzer.peak_mode()``.
        """
        peaks = [p for p, _ in peaks_with_modes]
        self.layoutAboutToBeChanged.emit()
        self._peaks = peaks
        if peaks:
            self._data = np.array(
                [[p.frequency, p.magnitude, p.quality] for p in peaks],
                dtype=np.float64,
            )
        else:
            self._data = np.zeros((0, 3), dtype=np.float64)
        # Install the caller-supplied mode map directly — bypasses classify_all.
        self._auto_mode_map = {p.id: mode for p, mode in peaks_with_modes}
        self._emit_mode_colors()
        self.layoutChanged.emit()

        # Refresh annotations using the centralised visibility check.
        self.clearAnnotations.emit()
        for row in range(self._data.shape[0]):
            idx = self.index(row, 0)
            if self._should_show_annotation(idx):
                freq = self.freq_value(idx)
                mag  = self.magnitude_value(idx)
                mode = self.mode_value(idx)
                peak_id = peaks[row].id if row < len(peaks) else ""
                self.annotationUpdate.emit(
                    peak_id, freq, mag,
                    self.annotation_html(freq, mag, mode), mode,
                )
        self.annotationsRefreshed.emit()

    def refresh_annotations(self) -> None:
        """Re-emit annotation signals for the current peaks and annotation_mode.

        Call this after mutating mode labels (model.modes) without changing
        the underlying peak data, so the canvas re-renders annotations with
        updated text.  Mirrors Swift where mutating peakModeOverrides (@Published)
        invalidates visiblePeaks and causes the chart to re-render.

        Uses ``_should_show_annotation`` so visibility logic is centralised.
        """
        if self._data is None or self._data.shape[0] == 0:
            return
        self.clearAnnotations.emit()
        for row in range(self._data.shape[0]):
            idx = self.index(row, 0)
            if self._should_show_annotation(idx):
                freq = self.freq_value(idx)
                mag  = self.magnitude_value(idx)
                mode = self.mode_value(idx)
                peak_id = self._peaks[row].id if row < len(self._peaks) else ""
                self.annotationUpdate.emit(
                    peak_id, freq, mag,
                    self.annotation_html(freq, mag, mode), mode,
                )
        self.annotationsRefreshed.emit()

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        self.clearAnnotations.emit()

    def select_all_peaks(self) -> None:
        """Set the show/selected flag on every peak and show its annotation."""
        self._programmatic_update = True
        try:
            for row in range(self.rowCount(QtCore.QModelIndex())):
                idx = self.index(row, self.show_column)
                self.setData(idx, "on")
        finally:
            self._programmatic_update = False
        self._set_user_modified(True)

    def deselect_all_peaks(self) -> None:
        """Clear the show/selected flag on every peak and hide its annotation."""
        self._programmatic_update = True
        try:
            for row in range(self.rowCount(QtCore.QModelIndex())):
                idx = self.index(row, self.show_column)
                self.setData(idx, "off")
        finally:
            self._programmatic_update = False
        self._set_user_modified(True)

    def _set_user_modified(self, value: bool) -> None:
        if self.user_has_modified_peak_selection != value:
            self.user_has_modified_peak_selection = value
            self.userModifiedSelectionChanged.emit(value)

    def update_annotation(self, index: QtCore.QModelIndex) -> None:
        """Update the annotation for a single peak at *index*.

        Delegates to ``_emit_annotation`` which uses the centralised
        ``_should_show_annotation`` visibility check.
        """
        self._emit_annotation(index)

    def setData(
        self,
        index: QtCore.QModelIndex,
        value: str,
        role=QtCore.Qt.ItemDataRole.EditRole,
    ) -> bool:
        """
        Sets the data in the model from the Editor for the
        column.
        """
        if role == QtCore.Qt.ItemDataRole.EditRole:
            match index.column():
                case ColumnIndex.Show.value:
                    # print(f"PeaksModel: setData: Show: index: {index.row()}, {index.column()}")
                    self.set_show_value(index, value)
                    self.dataChanged.emit(
                        index, index, [QtCore.Qt.ItemDataRole.DisplayRole]
                    )
                    self.update_annotation(index)
                    if not self._programmatic_update:
                        self._set_user_modified(True)
                    return True
                case ColumnIndex.Modes.value:
                    self.set_mode_value(index, value)
                    self.dataChanged.emit(
                        index, index, [QtCore.Qt.ItemDataRole.DisplayRole]
                    )
                    self.update_annotation(index)
                    self._emit_mode_colors()
                    return True
        return False

    # pylint: disable=invalid-name
    def rowCount(self, index: QtCore.QModelIndex) -> int:
        """Return the number of rows"""
        # print("PeaksModel: rowCount")
        if index.isValid():
            row_count = 0
        else:
            row_count = self._data.shape[0]

        # print(f"PeaksModel: rowCount: {row_count}")
        return row_count

    # pylint: disable=invalid-name
    def columnCount(self, index: QtCore.QModelIndex) -> int:
        """
        Return the number of columns for the table
        """
        # print("PeaksModel: columnCount")
        if index.isValid():
            return 0
        return len(ColumnIndex)

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        """
        Set the flag for editing the Modes column or selecting the columns.
        Editing is disabled in live mode (is_live=True) — the table becomes
        interactive only once a measurement is frozen (is_live=False).
        """
        if self.is_live:
            # flag = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            flag = QtCore.Qt.ItemFlag.NoItemFlags
        else:
            flag = (
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            if index.isValid():
                match index.column():
                    case ColumnIndex.Show.value:
                        flag = (
                            QtCore.Qt.ItemFlag.ItemIsEditable
                            | QtCore.Qt.ItemFlag.ItemIsEnabled
                            | QtCore.Qt.ItemFlag.ItemIsSelectable
                        )
                    case ColumnIndex.Modes.value:
                        flag = (
                            QtCore.Qt.ItemFlag.ItemIsEditable
                            | QtCore.Qt.ItemFlag.ItemIsEnabled
                            | QtCore.Qt.ItemFlag.ItemIsSelectable
                        )
        return flag

    def data_held(self, held: bool) -> None:
        """Transition between live mode (held=False) and frozen mode (held=True).

        In live mode (is_live=True) the table is read-only and show_value_bool
        returns True for every peak.  In frozen mode (is_live=False) the table
        is interactive and show_value_bool consults selected_peak_ids.
        """
        self.layoutAboutToBeChanged.emit()
        self.is_live = not held
        if held:
            self.refresh_annotations()
        else:
            self.hideAnnotations.emit()
        self.layoutChanged.emit()

    def auto_select_peaks_by_mode(self) -> None:
        """Auto-select the highest-magnitude peak assigned to each guitar mode.

        Mirrors Swift guitarModeSelectedPeakIDs (updated algorithm):
        1. Use the classifyAll mode map (_auto_mode_map) to get the mode
           already assigned to each peak via context-aware claiming.
        2. For each named mode, pick the highest-magnitude peak assigned to it.
        3. Select exactly those peaks (one per mode at most).

        The claiming/overlap logic is entirely delegated to classifyAll —
        this method just picks the best representative of each assigned mode.
        """
        self.selected_peak_ids = set()
        self._programmatic_update = True
        self._set_user_modified(False)
        self.clearAnnotations.emit()
        # Notify the view that all show-column cells may have changed.
        rows = self.rowCount(QtCore.QModelIndex())
        if rows > 0:
            top_left = self.index(0, self.show_column)
            bot_right = self.index(rows - 1, self.show_column)
            self.dataChanged.emit(top_left, bot_right, [QtCore.Qt.ItemDataRole.DisplayRole])

        named_modes = {
            gm.GuitarMode.AIR, gm.GuitarMode.TOP, gm.GuitarMode.BACK,
            gm.GuitarMode.DIPOLE, gm.GuitarMode.RING_MODE, gm.GuitarMode.UPPER_MODES,
        }
        # best_per_mode: mode → (row index, magnitude)
        best_per_mode: dict[gm.GuitarMode, tuple[int, float]] = {}
        for row in range(rows):
            idx = self.index(row, 0)
            freq = self.freq_value(idx)
            mode = self._auto_mode_map.get(self._peak_id_at(idx))
            if mode is None or mode not in named_modes:
                continue
            mag = self.magnitude_value(idx)
            if mode not in best_per_mode or mag > best_per_mode[mode][1]:
                best_per_mode[mode] = (row, mag)

        for best_row, _ in best_per_mode.values():
            show_idx = self.index(best_row, self.show_column)
            self.setData(show_idx, "on")

        self._programmatic_update = False

    def new_data(self, held: bool) -> None:
        """
        This is called if there is new data availble (as upposed to an
        update of data from redrawing more or less data in the data).
        This is used to clear the modes since they are not cleared until
        the underlying data is completely replaced.
        """
        if not held:
            self.clear_annotations()
            self.modes = {}
            self.selected_peak_ids = set()
            self._auto_mode_map = {}
            self.selected_longitudinal_peak_id = None
            self.selected_cross_peak_id = None
            self.selected_flc_peak_id = None
