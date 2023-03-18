"""
    The data model for the Peaks table.
"""
from enum import Enum
import os

import numpy as np
import numpy.typing as npt
from PyQt6 import QtCore

import pitch as pitch_c

basedir = os.path.dirname(__file__)

class ColumnIndex(Enum):
    """ Enum class so we can use the values for the headers. """
    # pylint: disable=invalid-name
    Show = 0
    # pylint: disable=invalid-name
    Freq = 1
    # pylint: disable=invalid-name
    Mag = 2
    # pylint: disable=invalid-name
    Pitch = 3
    # pylint: disable=invalid-name
    Cents = 4
    # pylint: disable=invalid-name
    Modes = 5

class PeaksModel(QtCore.QAbstractTableModel):
    """ Custom data model to handle deriving pitch and cents from frequency. Also defines
        accessing the underlying data model.
    """
    annotationUpdate: QtCore.pyqtSignal = QtCore.pyqtSignal(bool, float, float, str)
    mode_strings: list[str] = ["",
                               "Helmholtz T(1,1)_1",
                               "Top T(1,1)_2",
                               "Back T(1,1)_3",
                               "Cross Dipole T(2,1)",
                               "Long Dipole T(1,2)",
                               "Quadrapole T(2,2)",
                               "Cross Tripole T(3,1)"]

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

    def set_mode_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """ Sets the value of the mode. """
        #print("PeaksModel: set_mode_value")
        self.modes[self.freq_value(index)] = value

    def mode_value(self, index: QtCore.QModelIndex) -> str:
        """ Return the mode for the row """
        #print("PeaksModel: mode_value")
        if self.freq_value(index) in self.modes:
            return self.modes[self.freq_value(index)]
        return ""

    def set_show_value(self, index: QtCore.QModelIndex, value: str) -> None:
        """ Sets the value of the show. """
        self.show[self.freq_value(index)] = value

    def show_value_bool(self, index: QtCore.QModelIndex) -> bool:
        if self.show_value(index) == "on":
            return True
        else:
            return False

    def show_value(self, index: QtCore.QModelIndex) -> str:
        """ Return the show for the row """
        if self.freq_value(index) in self.show:
            return self.show[self.freq_value(index)]
        return "off"
    
    def freq_index(self, freq: float) -> QtCore.QModelIndex:
        index = np.where(self._data[:,0] == freq)
        if len(index[0]) == 1:
            return index[0][0]
        return -1

    def freq_value(self, index: QtCore.QModelIndex) -> float:
        """ Return the frequency value from the correct column for the row """
        #print("PeaksModel: freq_value")
        return self._data[index.row()][0]
    
    def magnitude_value(self, index: QtCore.QModelIndex) -> float:
        """ Return the magnitude value from the correct column for the row """
        #print("PeaksModel: freq_value")
        return self._data[index.row()][1]

    def data_value(self, index: QtCore.QModelIndex) -> QtCore.QVariant:
        """ Return the value from the data for cols 1/2 and the value in
            the table for 3/4.
        """
        #print("PeaksModel: data_value")
        match index.column():
            case ColumnIndex.Show.value:
                value = self.show_value[index.row()]
            case ColumnIndex.Freq.value:
                value = self.freq_value(index)
            case ColumnIndex.Mag.value:
                value = self.magnitude_value(index)
            case ColumnIndex.Pitch.value | ColumnIndex.Cents.value:
                value = self.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
            case ColumnIndex.Modes.value:
                value = self.mode_value(index)
            case _:
                value = QtCore.QVariant()
        return value

    def data(self, index: QtCore.QModelIndex, role: QtCore.Qt.ItemDataRole)  -> QtCore.QVariant:
        #print("PeaksModel: data")
        """ Return the requested data based on role. """
        match role:
            case QtCore.Qt.ItemDataRole.DisplayRole:
                match index.column():
                    case ColumnIndex.Show.value:
                        str_value = self.show_value(index)
                    case ColumnIndex.Freq.value:
                        value = self.freq_value(index)
                        str_value = f'{value:.1f}'
                    case ColumnIndex.Mag.value:
                        value = self.magnitude_value(index)
                        str_value = f'{value:.1f}'
                    case ColumnIndex.Pitch.value:
                        str_value = self.pitch.note(self.freq_value(index))
                    case ColumnIndex.Cents.value:
                        str_value = f'{self.pitch.cents(self.freq_value(index)):+.0f}'
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
    def headerData(self,
                   section: int,
                   orientation: QtCore.Qt.Orientation,
                   role: QtCore.Qt.ItemDataRole
                  ) -> QtCore.QVariant:
        """ Return the header data """
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
        """ Update the data model from outside the object and
            then update the table.
        """
        #print(f"PeaksModel: update_data: data {data}")
        #print(f"PeaksModel: update_data: type {type(data)}")

        self.layoutAboutToBeChanged.emit()
        self._data = data
        
        self.layoutChanged.emit()
    
    def clear_annotations(self) -> None:
        for freq in self.show:
            self.annotationUpdate.emit(False, freq, 0.0, "") 

    def update_annotations(self) -> None:
        for freq in self.show:
            row = self.freq_index(freq)
            if row >= 0:
                index = self.index(row, 0)
                self.update_annotation(index)

    def update_annotation(self, index: QtCore.QModelIndex) -> None:
        freq = self.freq_value(index)
        mag = self.magnitude_value(index)
        show = self.show_value_bool(index)
        mode = self.mode_value(index)
        if show:
            # Add annotation
            if mode == "":
                annotation_text = f"{freq:.1f}"
            else:
                annotation_text = f"{mode}\n{freq:.1f}"
            self.annotationUpdate.emit(True, freq, mag, annotation_text) 
            print(f"PeaksModel: update_annotation: {annotation_text}")
        else:
            # Remove annotations
            self.annotationUpdate.emit(False, freq, mag, "") 
            print(f"PeaksModel: update_annotation: remove")


    def setData(self, index: QtCore.QModelIndex, value: str,
                role = QtCore.Qt.ItemDataRole.EditRole
               ) -> bool:
        """
            Sets the data in the model from the Editor for the
            column.
        """
        if role == QtCore.Qt.ItemDataRole.EditRole:
            match index.column():
                case ColumnIndex.Show.value:
                    #print(f"PeaksModel: setData: Show: index: {index.row()}, {index.column()}")
                    self.set_show_value(index, value)
                    self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])
                    self.update_annotation(index)
                    return True
                case ColumnIndex.Modes.value:
                    #print(f"PeaksModel: setData: Modes: index: {index.row()}, {index.column()}")
                    self.set_mode_value(index, value)
                    self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])
                    self.update_annotation(index)
                    return True
        return False

    # pylint: disable=invalid-name
    def rowCount(self, index: QtCore.QModelIndex) -> int:
        """ Return the number of rows """
        #print("PeaksModel: rowCount")
        if index.isValid():
            row_count = 0
        else:
            row_count = self._data.shape[0]

        #print(f"PeaksModel: rowCount: {row_count}")
        return row_count

    # pylint: disable=invalid-name
    def columnCount(self, index: QtCore.QModelIndex) -> int:
        """
            Return the number of columns for the table
        """
        #print("PeaksModel: columnCount")
        if index.isValid():
            return 0
        return len(ColumnIndex)

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        """
            Set the flag for editing the Modes column or selecting the columns.
            If the disable_editing flag is set from the data_held then
            all selection and editing is disabled.
        """
        #print(f"PeaksModel: flags: disable_editing: {self.disable_editing}")
        if self.disable_editing:
            #flag = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            flag = QtCore.Qt.ItemFlag.NoItemFlags
        else:
            flag = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            if index.isValid():
                match index.column():
                    case ColumnIndex.Show.value:
                        flag = QtCore.Qt.ItemFlag.ItemIsEditable | \
                            QtCore.Qt.ItemFlag.ItemIsEnabled | \
                            QtCore.Qt.ItemFlag.ItemIsSelectable
                    case ColumnIndex.Modes.value:
                        flag = QtCore.Qt.ItemFlag.ItemIsEditable | \
                            QtCore.Qt.ItemFlag.ItemIsEnabled | \
                            QtCore.Qt.ItemFlag.ItemIsSelectable
        return flag

    def data_held(self, held: bool) -> None:
        """
            This is used to indicate the change of the data being held. If it is not held
            then the table cannot be edited.
        """
        #print(f"PeaksModel: data_held: {held}")
        self.layoutAboutToBeChanged.emit()
        if held:
            self.disable_editing = False
            self.update_annotations()
        else:
            self.disable_editing = True
            self.clear_annotations()
        self.layoutChanged.emit()

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
