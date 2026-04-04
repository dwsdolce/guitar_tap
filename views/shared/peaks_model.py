"""
    The data model for the Peaks table.
"""

from enum import Enum
import os

import numpy as np
import numpy.typing as npt
from PyQt6 import QtCore

from models import pitch as pitch_c
from models import guitar_type as gt
from models import guitar_mode as gm

basedir = os.path.dirname(__file__)


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

    annotationUpdate: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, str, str)  # (freq, mag, html, mode_str)
    clearAnnotations: QtCore.pyqtSignal = QtCore.pyqtSignal()
    hideAnnotations: QtCore.pyqtSignal = QtCore.pyqtSignal()
    hideAnnotation: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    showAnnotation: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    userModifiedSelectionChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    modeColorsChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)  # dict[float, tuple[int,int,int]]

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
        self._data: npt.NDArray = data
        self.pitch: pitch_c.Pitch = pitch_c.Pitch(440)
        self.modes_width: int = len(max(self.mode_strings, key=len))
        self.modes_column: int = ColumnIndex.Modes.value
        self.modes: dict[float, str] = {}
        self.is_live: bool = True
        self.selected_frequencies: set[float] = set()
        self.show_column: int = ColumnIndex.Show.value
        self.guitar_type: gt.GuitarType = gt.GuitarType.CLASSICAL
        self.user_has_modified_peak_selection: bool = False
        self._programmatic_update: bool = False
        # Current annotation visibility mode.
        # Values: "Selected", "None", "All"  (mirrors Swift annotationVisibilityMode)
        # Use set_annotation_mode() to change — it re-runs update_data() reactively.
        self._annotation_mode: str = "Selected"
        self._auto_mode_map: dict[float, gm.GuitarMode] = {}  # freq → mode, from classify_all

    # MARK: - Annotation mode (reactive, mirrors Swift @Published annotationVisibilityMode)

    @property
    def annotation_mode(self) -> str:
        """Current annotation visibility mode: "Selected", "None", or "All"."""
        return self._annotation_mode

    @annotation_mode.setter
    def annotation_mode(self, mode: str) -> None:
        """Set the annotation visibility mode and re-apply it to the current peaks.

        Mirrors Swift's behaviour where changing annotationVisibilityMode on
        TapToneAnalyzer automatically re-evaluates visiblePeaks (a computed
        property), causing the chart to re-render with the correct subset.
        Here we re-run update_data() so the single annotation-emission path
        in update_data() applies the new mode to whatever peaks are currently
        loaded — no separate imperative show/hide calls needed.
        """
        if self._annotation_mode == mode:
            return
        self._annotation_mode = mode
        if self._data is not None and self._data.shape[0] > 0:
            self.update_data(self._data)

    def set_mode_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """Sets the value of the mode."""
        # print("PeaksModel: set_mode_value")
        self.modes[self.freq_value(index)] = value

    def reset_mode_value(self, index: QtCore.QModelIndex) -> None:
        """Remove any manual mode override, reverting to auto-classification."""
        self.modes.pop(self.freq_value(index), None)

    def _emit_mode_colors(self) -> None:
        """Emit modeColorsChanged with the current freq→RGB color map."""
        color_map = {freq: mode.color for freq, mode in self._auto_mode_map.items()}
        self.modeColorsChanged.emit(color_map)

    def _recompute_auto_modes(self) -> None:
        """Rebuild the context-aware mode map from current peak data.

        Mirrors Swift identifiedModes computed via GuitarMode.classifyAll —
        overlapping mode ranges resolve correctly because the claiming algorithm
        visits modes in ascending lower-bound order and marks each peak as used.
        """
        if self._data.shape[0] == 0:
            self._auto_mode_map = {}
            return
        peaks = [(float(self._data[i, 0]), float(self._data[i, 1]))
                 for i in range(self._data.shape[0])]
        idx_map = gm.GuitarMode._classify_all_tuples(peaks, self.guitar_type)
        self._auto_mode_map = {peaks[i][0]: mode for i, mode in idx_map.items()}

    def mode_value(self, index: QtCore.QModelIndex) -> str:
        """Return mode: manual override if set, else auto-classified."""
        freq = self.freq_value(index)
        if freq in self.modes:
            return self.modes[freq]
        mode = self._auto_mode_map.get(freq)
        if mode is not None:
            return mode.value
        return gm.classify_peak(freq, self.guitar_type)

    def set_show_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """Sets the value of the show."""
        freq = self.freq_value(index)
        if value == "on":
            self.selected_frequencies.add(freq)
        else:
            self.selected_frequencies.discard(freq)

    def show_value_bool(self, index: QtCore.QModelIndex) -> bool:
        """Return whether this peak is shown/selected.

        Computed at query time — mirrors Swift SpectrumView filtering
        currentPeaks using selectedPeakIDs at render time.
        In live mode every peak is shown; in frozen mode only explicitly
        selected frequencies are shown.
        """
        if self.is_live:
            return True
        return float(self.freq_value(index)) in self.selected_frequencies

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
            # Guitar: use GuitarMode classifier for colour and display name
            guitar_mode = gm.GuitarMode.from_mode_string(mode)
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

    def set_guitar_type(self, guitar_type: str) -> None:
        """Change the guitar type used for auto mode classification."""
        self.layoutAboutToBeChanged.emit()
        self.guitar_type = gt.GuitarType(guitar_type)
        self._recompute_auto_modes()   # mirrors Swift reclassifyPeaks()
        self._emit_mode_colors()
        self.layoutChanged.emit()

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

    def update_data(self, data: np.ndarray) -> None:
        """Update the data model from outside the object and then update the table.

        Pure notifier — never touches selection state (selected_frequencies or
        is_live).  The caller owns selection state; this method only stores the
        new peak array, recomputes derived mode data, and refreshes annotations.

        Mirrors Swift's reactive approach: SpectrumView re-evaluates
        selectedPeakIDs filtering at render time whenever currentPeaks changes,
        so no ordering constraint exists between selection-state mutations and
        data updates.
        """
        self.layoutAboutToBeChanged.emit()
        self._data = data
        self._recompute_auto_modes()
        self._emit_mode_colors()
        self.layoutChanged.emit()

        # Refresh annotations based on current is_live / selected_frequencies state.
        # "None"     → hide everything
        # "Selected" → show peaks whose show_value_bool is True
        # "All"      → show every peak regardless of selection
        self.clearAnnotations.emit()
        if self.annotation_mode == "None":
            return

        for row in range(self._data.shape[0]):
            idx = self.index(row, 0)
            freq = self.freq_value(idx)
            mag  = self.magnitude_value(idx)
            mode = self.mode_value(idx)
            if self.annotation_mode == "All" or self.show_value_bool(idx):
                self.annotationUpdate.emit(freq, mag, self.annotation_html(freq, mag, mode), mode)

    def refresh_annotations(self) -> None:
        """Re-emit annotation signals for the current peaks and annotation_mode.

        Call this after mutating mode labels (model.modes) without changing
        the underlying peak data, so the canvas re-renders annotations with
        updated text.  Mirrors Swift where mutating peakModeOverrides (@Published)
        invalidates visiblePeaks and causes the chart to re-render.
        """
        if self._data is None or self._data.shape[0] == 0:
            return
        self.clearAnnotations.emit()
        if self._annotation_mode == "None":
            return
        for row in range(self._data.shape[0]):
            idx = self.index(row, 0)
            freq = self.freq_value(idx)
            mag  = self.magnitude_value(idx)
            mode = self.mode_value(idx)
            if self._annotation_mode == "All" or self.show_value_bool(idx):
                self.annotationUpdate.emit(freq, mag, self.annotation_html(freq, mag, mode), mode)

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        self.clearAnnotations.emit()

    def show_annotations(self) -> None:
        """Show annotations for peaks that are currently selected."""
        for row in range(self._data.shape[0]):
            idx = self.index(row, 0)
            if self.show_value_bool(idx):
                self.showAnnotation.emit(self.freq_value(idx))

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

    def show_all_annotations(self) -> None:
        """Show annotations for every peak regardless of the show flag."""
        for row in range(self.rowCount(QtCore.QModelIndex())):
            idx = self.index(row, 0)
            freq = self.freq_value(idx)
            mag  = self.magnitude_value(idx)
            mode = self.mode_value(idx)
            html = self.annotation_html(freq, mag, mode)
            self.annotationUpdate.emit(freq, mag, html, mode)

    def update_annotation(self, index: QtCore.QModelIndex) -> None:
        """Update the annotation for the model index."""
        freq = self.freq_value(index)
        mag = self.magnitude_value(index)
        show = self.show_value_bool(index)
        mode = self.mode_value(index)
        if show:
            html = self.annotation_html(freq, mag, mode)
            self.annotationUpdate.emit(freq, mag, html, mode)
            # print(f"PeaksModel: update_annotation: {annotation_text}")
        else:
            # Remove annotations
            self.hideAnnotation.emit(freq)
            # print(f"PeaksModel: update_annotation: remove")

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
                    # print(f"PeaksModel: setData: Modes: index: {index.row()}, {index.column()}")
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
        is interactive and show_value_bool consults selected_frequencies.
        """
        self.layoutAboutToBeChanged.emit()
        self.is_live = not held
        if held:
            self.refresh_annotations()
        else:
            self.hideAnnotations.emit()
        self.layoutChanged.emit()

    def auto_select_peaks_by_mode(self, guitar_type: gt.GuitarType) -> None:
        """Auto-select the highest-magnitude peak assigned to each guitar mode.

        Mirrors Swift guitarModeSelectedPeakIDs (updated algorithm):
        1. Use the classifyAll mode map (_auto_mode_map) to get the mode
           already assigned to each peak via context-aware claiming.
        2. For each named mode, pick the highest-magnitude peak assigned to it.
        3. Select exactly those peaks (one per mode at most).

        The claiming/overlap logic is entirely delegated to classifyAll —
        this method just picks the best representative of each assigned mode.
        """
        self.selected_frequencies = set()
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
            mode = self._auto_mode_map.get(freq)
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
            self.selected_frequencies = set()
            self._auto_mode_map = {}
