import numpy as np
from PyQt6 import QtCore

import pitch as pitch_c
from enum import Enum

class ColumnIndex(Enum):
    Frequency = 0
    Magnitude = 1
    Pitch = 2
    Cents = 3
    Modes = 4

class PeaksModel(QtCore.QAbstractTableModel):
    """ Custom data model to handle deriving pitch and cents from frequency. Also defines
        accessing the underlying data model.
    """

    mode_strings = ["",
                    "Helmholtz T(1,1)_1", 
                    "Top T(1,1)_2",
                    "Back T(1,1)_3",
                    "Cross Dipole T(2,1)",
                    "Long Dipole T(1,2)",
                    "Quadrapole T(2,2)",
                    "Cross Tripole T(3,1)"]

    header_names = [e.name for e in ColumnIndex]
    def __init__(self, data: np.ndarray):
        super().__init__()
        self._data = data
        self.pitch = pitch_c.Pitch(440)
        self.modes_width = len(max(self.mode_strings, key=len))
        self.modes_column = ColumnIndex.Modes.value
        self.modes = {}
        self.disable_editing = True

    def set_mode_value(self, index: QtCore.QModelIndex, value: str):
        #print("PeaksModel: set_mode_value")
        self.modes[self.freq_value(index)] = value

    def mode_value(self, index: QtCore.QModelIndex):
        #print("PeaksModel: mode_value")
        """ Return the mode for the row """
        if self.freq_value(index) in self.modes:
            return self.modes[self.freq_value(index)]
        else:
            return ""

    def freq_value(self, index: QtCore.QModelIndex):
        #print("PeaksModel: freq_value")
        """ Return the frequency value from column 0 for the row """
        return self._data[index.row()][ColumnIndex.Frequency.value]

    def data_value(self, index: QtCore.QModelIndex):
        #print("PeaksModel: data_value")
        """ Return the value from the data for cols 1/2 and the value in
            the table for 3/4.
        """
        match index.column():
            case ColumnIndex.Frequency.value | ColumnIndex.Magnitude.value:
                value = self._data[index.row()][index.column()]
            case ColumnIndex.Pitch.value | ColumnIndex.Cents.value:
                value = self.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
            case ColumnIndex.Modes.value:
                value = self.mode_value(index)
            case _:
                value = QtCore.QVariant()
        return value

    def data(self, index: QtCore.QModelIndex, role: QtCore.Qt.ItemDataRole):
        #print("PeaksModel: data")
        """ Return the requested data based on role. """
        match role:
            case QtCore.Qt.ItemDataRole.DisplayRole:
                match index.column():
                    case ColumnIndex.Frequency.value | ColumnIndex.Magnitude.value:
                        value = self._data[index.row()][index.column()]
                        str_value = f'{value:.1f}'
                    case ColumnIndex.Pitch.value:
                        str_value = self.pitch.note(self.freq_value(index))
                    case ColumnIndex.Cents.value:
                        str_value = f'{self.pitch.cents(self.freq_value(index)):+.0f}'
                    case ColumnIndex.Modes.value:
                        str_value = self.mode_value(index)
                    case _:
                        value = self._data[index.row()][index.column()]
                        str_value = str(value)
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
    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: QtCore.Qt.ItemDataRole):
        #print(f"PeaksModel: headerData: {section} {orientation} {QtCore.Qt.ItemDataRole(role).name}")
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

    # pylint: disable=invalid-name
    def updateData(self, data: np.ndarray):
        """ Update the data model from outside the object and
            then update the table.
        """
        print(f"PeaksModel: updateData: data {data}")
        print(f"PeaksModel: updateData: type {type(data)}")

        self.layoutAboutToBeChanged.emit()
        self._data = data
        nrows = data.shape[0]
        self.layoutChanged.emit()

    def setData(self, index: QtCore.QModelIndex, value, role = QtCore.Qt.ItemDataRole.EditRole):
        #print("PeaksModel: setData")
        if index.isValid():
            if index.column() == ColumnIndex.Modes.value:
                self.set_mode_value(index, value)
                self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])
            return True
        else:
            return False
    
    # pylint: disable=invalid-name
    def rowCount(self, index: QtCore.QModelIndex):
        #print("PeaksModel: rowCount")
        """ Return the number of rows """
        if index.isValid():
            row_count = 0
        else:
            row_count = self._data.shape[0]

        #print(f"PeaksModel: rowCount: {row_count}")
        return row_count

    # pylint: disable=invalid-name
    def columnCount(self, index: QtCore.QModelIndex):
        #print("PeaksModel: columnCount")
        """ Return the number of columnes """
        if index.isValid():
            return 0
        return len(ColumnIndex)

    def flags(self, index: QtCore.QModelIndex):
        #print("PeaksModel: flags")
        if self.disable_editing:
            flag = QtCore.Qt.ItemFlag.NoItemFlags
        else:
            flag = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            if index.isValid():
                if index.column() == ColumnIndex.Modes.value:
                    flag = QtCore.Qt.ItemFlag.ItemIsEditable | QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
        return flag

    def data_held(self, held: bool):
        #print(f"data_held: {held}")
        if held:
            self.disable_editing = False
        else:
            self.disable_editing = True
    
    def new_data(self, held: bool):
        if not held:
            self.modes = {}