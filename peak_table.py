"""
    Table for display the peak information. Allows for row selection and highlighting, sorting,
    and saving of the table to a csv file.
"""

import os
import csv

import numpy as np
from PyQt6 import QtWidgets, QtCore

import pitch as pitch_c

# pylint: disable=too-few-public-methods
class PeaksFilterModel(QtCore.QSortFilterProxyModel):
    """ Add a custom filter to handle the sorting of the columns. This is required
        due to the value displayed in the table being a string but we want to sort
        on the original numeric data or, for the case of cents on the absolute
        value of the cents.
    """
    # pylint: disable=invalid-name
    def lessThan(self, left, right):
        """ Calculate per the class description. """
        if left.column() == 0 or left.column() == 1:
            # Sort by numeric value (assumes left and right column are the same)
            # Use the python value instead of the numpy value so that a bool is
            # returned instead of a numpy.bool_.
            less_than = (self.sourceModel().data_value(left) <
                         self.sourceModel().data_value(right))
            less_than = less_than.item()
        elif left.column() == 2:
            # Use the freq to define order
            # Use the python value instead of the numpy value so that a bool is
            # returned instead of a numpy.bool_.
            left_freq = self.sourceModel().freq_value(left)
            right_freq  = self.sourceModel().freq_value(right)
            less_than = left_freq < right_freq
            less_than = less_than.item()
        elif left.column() == 3:
            # Sort by absolute value of cents (so +/-3 is less than +/- 4)
            left_cents = self.sourceModel().pitch.cents(self.sourceModel().freq_value(left))
            right_cents = self.sourceModel().pitch.cents(self.sourceModel().freq_value(right))
            less_than = abs(left_cents) < abs(right_cents)
        else:
            less_than = True
        """
        match left.column():
            case 0 | 1:
                # Sort by numeric value (assumes left and right column are the same)
                # Use the python value instead of the numpy value so that a bool is
                # returned instead of a numpy.bool_.
                less_than = (self.sourceModel().data_value(left) <
                             self.sourceModel().data_value(right))
                less_than = less_than.item()
            case 2:
                # Use the freq to define order
                # Use the python value instead of the numpy value so that a bool is
                # returned instead of a numpy.bool_.
                left_freq = self.sourceModel().freq_value(left)
                right_freq  = self.sourceModel().freq_value(right)
                less_than = left_freq < right_freq
                less_than = less_than.item()
            case 3:
                # Sort by absolute value of cents (so +/-3 is less than +/- 4)
                left_cents = self.sourceModel().pitch.cents(self.sourceModel().freq_value(left))
                right_cents = self.sourceModel().pitch.cents(self.sourceModel().freq_value(right))
                less_than = abs(left_cents) < abs(right_cents)
            case _:
                less_than = True
        """
        return less_than

class PeaksModel(QtCore.QAbstractTableModel):
    """ Custom data model to handle deriving pitch and cents from frequency. ALso defines
        accessing the underlying data model.
    """
    header_names = ['Frequency', 'Magnitude', 'Pitch', 'Cents']
    def __init__(self, data):
        super().__init__()
        self._data = data
        self.pitch = pitch_c.Pitch(440)

    def freq_value(self, index):
        """ Return the frequency valuy from column 0 for the row """
        return self._data[index.row()][0]

    def data_value(self, index):
        """ Return the value from the data for cols 1/2 and the value in
            the table for 3/4.
        """
        if index.column() == 0 or index.column() == 1:
            value = self._data[index.row()][index.column()]
        elif index.column() == 2 or index.column() == 3:
            value = self.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
        else:
            value = QtCore.QVariant()
        """
        match index.column():
            case 0 | 1:
                value = self._data[index.row()][index.column()]
            case 2 | 3:
                value = self.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
            case _:
                value = QtCore.QVariant()
        """
        return value

    def data(self, index, role):
        """ Return the requested data based on role. """
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if index.column() == 0 or index.column() == 1:
                value = self._data[index.row()][index.column()]
                str_value = f'{value:.1f}'
            elif index.column() == 2:
                value = self._data[index.row()][0]
                str_value = self.pitch.note(value)
            elif index.column() == 3:
                value = self._data[index.row()][0]
                str_value = f'{self.pitch.cents(value):+.0f}'
            else:
                value = self._data[index.row()][index.column()]
                str_value = str(value)
            return str_value
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignRight
        else:
            return QtCore.QVariant()
        """
        match role:
            case QtCore.Qt.ItemDataRole.DisplayRole:
                match index.column():
                    case 0 | 1:
                        value = self._data[index.row()][index.column()]
                        str_value = f'{value:.1f}'
                    case 2:
                        value = self._data[index.row()][0]
                        str_value = self.pitch.note(value)
                    case 3:
                        value = self._data[index.row()][0]
                        str_value = f'{self.pitch.cents(value):+.0f}'
                    case _:
                        value = self._data[index.row()][index.column()]
                        str_value = str(value)
                return str_value
            case QtCore.Qt.ItemDataRole.TextAlignmentRole:
                return QtCore.Qt.AlignmentFlag.AlignRight
            case _:
                return QtCore.QVariant()
        """

    # pylint: disable=invalid-name
    def headerData(self, section, orientation, role):
        """ Return the header data """
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return self.header_names[section]
            else:
                return QtCore.QVariant()
        else:
            return QtCore.QVariant()
        """
        match role:
            case QtCore.Qt.ItemDataRole.DisplayRole:
                match orientation:
                    case QtCore.Qt.Orientation.Horizontal:
                        return self.header_names[section]
                    case _:
                        return QtCore.QVariant()
            case _:
                return QtCore.QVariant()
        """

    # pylint: disable=invalid-name
    def updateData(self, data):
        """ Update the data model from outside the object and
            then update the table.
        """
        self.layoutAboutToBeChanged.emit()
        self._data = data
        self.layoutChanged.emit()
        return True

    # pylint: disable=invalid-name
    def rowCount(self, parent):
        """ Return the number of rows """
        if parent.isValid():
            return 0
        return self._data.shape[0]

    # pylint: disable=invalid-name
    def columnCount(self, parent):
        """ Return the number of columnes """
        if parent.isValid():
            return 0
        return self._data.shape[1] + 2


class PeakTable(QtWidgets.QWidget):
    """ Table and save button for displaying table of peaks and interacting with it. """
    def __init__(self):
        super().__init__()

        self.saved_path = ""

        #.....
        # Setup a vertical layout to add spacing
        peaks_layout = QtWidgets.QVBoxLayout()

        #.....
        # Spacing above controls
        peaks_layout.addSpacing(20)

        #.....
        # Use tableview to display fft peaks
        self.peak_table = QtWidgets.QTableView()
        data = np.vstack(([], [])).T
        self.model = PeaksModel(data)
        # Use custom QSortFilterProxyModel to define the sort
        proxy_model = PeaksFilterModel()
        proxy_model.setSourceModel(self.model)
        self.peak_table.setModel(proxy_model)
        self.peak_table.setSortingEnabled(True)
        self.peak_table.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.peak_table.resizeColumnsToContents()
        self.peak_table.setSelectionBehavior(QtWidgets.QTableView.SelectionBehavior.SelectRows)
        self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection)
        self.peak_table.setToolTip('Displays the peaks found. When results are held, select\n'
            'a cell to highlight the peak in the FFT Peaks display or\n'
            'select a peak on the FFT Peaks waveform to highlight\n'
            'the peak in the table.')

        header_width = self.peak_table.horizontalHeader().length()
        self.peak_table.setFixedWidth(header_width + 30)

        peaks_layout.addWidget(self.peak_table)

        #.....
        # Save button
        save_peaks = QtWidgets.QToolButton()
        save_peaks.setText('Save Peaks')
        save_peaks.setToolTip('Save the captured peaks and related information to a file')

        peaks_layout.addWidget(save_peaks)

        save_peaks.clicked.connect(self.save_peaks)

        #.....
        # Add space at the bottom
        peaks_layout.addSpacing(40)

        self.setLayout(peaks_layout)

    def save_peaks(self):
        """ Save the peaks in the table to a CVS file that is compatible with
            Excel.
        """
        if self.saved_path == '':
            self.saved_path = os.getenv('HOME')

        filename, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            caption='Save Peaks to CSV',
            directory=self.saved_path,
            filter= "Comma Separated Values (*.csv)",
            initialFilter="Comma Separated Values (*.csv)",
        )
        if filename and selected_filter:
            self.saved_path = os.path.dirname(filename)
            proxy_model = self.peak_table.model()
            data_model = proxy_model.sourceModel()
            columns = range(self.peak_table.horizontalHeader().count())
            header = [data_model.headerData(column, QtCore.Qt.Orientation.Horizontal,
                QtCore.Qt.ItemDataRole.DisplayRole) for column in columns]
            with open(filename, 'w', encoding='utf-8-sig') as csvfile:
                writer = csv.writer(csvfile, dialect='excel', lineterminator='\n')
                writer.writerow(header)
                for row in range(data_model.rowCount(QtCore.QVariant())):
                    writer.writerow(data_model.data_value(data_model.index(row, column))
                        for column in columns)

    def select_row(self, freq_index):
        """ For the specified frequency index select the corresponding row
            in the peak table and set the focus to it. Setting the focus will
            scroll the table so the row is in view and highlight it.
        """
        #print(f"select_row: freq_index: {freq_index}")
        proxy_model = self.peak_table.model()
        data_model = proxy_model.sourceModel()

        data_freq_index = data_model.index(freq_index, 0)
        proxy_freq_index = proxy_model.mapFromSource(data_freq_index)
        select_current = QtCore.QItemSelectionModel.SelectionFlag.SelectCurrent
        select_rows = QtCore.QItemSelectionModel.SelectionFlag.Rows
        flags = select_current | select_rows
        self.peak_table.setFocus()
        self.peak_table.selectionModel().setCurrentIndex(proxy_freq_index, flags)

    def deselect_row(self):
        self.peak_table.selectionModel().clearSelection()
