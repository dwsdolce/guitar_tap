"""
    The data model for the Peaks table.
"""

from enum import Enum
import os

import numpy as np
import numpy.typing as npt
from PyQt6 import QtCore

import pitch as pitch_c
import guitar_type as gt
import guitar_modes as gm

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
        self.disable_editing: bool = True
        self.show: dict[float, str] = {}
        self.show_column: int = ColumnIndex.Show.value
        self.guitar_type: gt.GuitarType = gt.GuitarType.CLASSICAL
        self.user_has_modified_peak_selection: bool = False
        self._programmatic_update: bool = False
        self._auto_mode_map: dict[float, gm.GuitarMode] = {}  # freq → mode, from classify_all

    def set_mode_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """Sets the value of the mode."""
        # print("PeaksModel: set_mode_value")
        self.modes[self.freq_value(index)] = value

    def reset_mode_value(self, index: QtCore.QModelIndex) -> None:
        """Remove any manual mode override, reverting to auto-classification."""
        self.modes.pop(self.freq_value(index), None)

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
        idx_map = gm.GuitarMode.classify_all(peaks, self.guitar_type)
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
        self.show[self.freq_value(index)] = value

    def show_value_bool(self, index: QtCore.QModelIndex) -> bool:
        """Return the show value as a boolean."""
        return bool(self.show_value(index) == "on")
        # if self.show_value(index) == "on":
        #    return True
        # else:
        #    return False

    def show_value(self, index: QtCore.QModelIndex) -> str:
        """Return the show for the row"""
        if self.freq_value(index) in self.show:
            return self.show[self.freq_value(index)]
        return "off"

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

    def annotation_html(self, freq: float, mag: float, mode: str) -> str:
        """Build the HTML label for an annotation, matching Swift PeakAnnotationLabel.

        Layout (top to bottom):
          • Mode name  — bold, mode colour
          • Pitch / cents  — purple
          • Frequency (Hz) — dark
          • Magnitude (dB) — grey
        """
        guitar_mode = gm.GuitarMode.from_mode_string(mode)
        r, g, b = guitar_mode.color
        display = gm.mode_display_name(mode) or ""

        note   = self.pitch.note(freq)
        cents  = self.pitch.cents(freq)

        rows: list[str] = []
        if display:
            rows.append(
                f'<b style="color:rgb({r},{g},{b});">{display}</b>'
            )
        rows.append(
            f'<span style="color:rgb(120,60,180);">&#9834; {note}&nbsp;&nbsp;{cents:+.0f}&#162;</span>'
        )
        rows.append(
            f'<span style="color:rgb(50,50,50);">{freq:.2f} Hz</span>'
        )
        rows.append(
            f'<span style="color:rgb(110,110,110);">{mag:.1f} dB</span>'
        )
        return '<center>' + '<br/>'.join(rows) + '</center>'

    def set_guitar_type(self, guitar_type: str) -> None:
        """Change the guitar type used for auto mode classification."""
        self.layoutAboutToBeChanged.emit()
        self.guitar_type = gt.GuitarType(guitar_type)
        self._recompute_auto_modes()   # mirrors Swift reclassifyPeaks()
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
        """Update the data model from outside the object and
        then update the table.
        """
        self.layoutAboutToBeChanged.emit()
        self._data = data
        self._recompute_auto_modes()   # mirrors Swift identifiedModes update
        self.layoutChanged.emit()

        # Reconcile annotations with the new peak set — mirrors Swift's reactive
        # identifiedModes/selectedPeakIDs which automatically drop annotations
        # for peaks that fell below the threshold.
        # Clear everything, then re-create annotations only for peaks that still
        # exist in _data and have show == "on".
        self.clearAnnotations.emit()
        for row in range(self._data.shape[0]):
            idx = self.index(row, 0)
            if self.show_value_bool(idx):
                freq = self.freq_value(idx)
                mag  = self.magnitude_value(idx)
                mode = self.mode_value(idx)
                self.annotationUpdate.emit(freq, mag, self.annotation_html(freq, mag, mode), mode)

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        self.clearAnnotations.emit()

    def show_annotations(self) -> None:
        """Show annotations for peaks that have the show flag set."""
        for freq in self.show:
            index = self.freq_index(freq)
            if index >= 0 and self.show_value_bool(self.index(index, 0)):
                self.showAnnotation.emit(freq)

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
        If the disable_editing flag is set from the data_held then
        all selection and editing is disabled.
        """
        # print(f"PeaksModel: flags: disable_editing: {self.disable_editing}")
        if self.disable_editing:
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
        """
        This is used to indicate the change of the data being held. If it is not held
        then the table cannot be edited.
        """
        # print(f"PeaksModel: data_held: {held}")
        self.layoutAboutToBeChanged.emit()
        if held:
            self.disable_editing = False
            self.show_annotations()
        else:
            self.disable_editing = True
            self.hideAnnotations.emit()
            # self.clear_annotations()
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
        self.show = {}
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
            self.show = {}
            self._auto_mode_map = {}
