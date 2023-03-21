"""
    Table for display the peak information. Allows for row selection and highlighting, sorting,
    and saving of the table to a csv file.
"""

import os
import csv

import typing
import numpy as np
import numpy.typing as npt
from PyQt6 import QtWidgets, QtCore, QtGui
import mode_combo_delegate as mcd
import show_button_delegate as sbd
import peaks_filter_model as pfm
import peaks_model as pm

# pylint: disable=too-few-public-methods
class PeakTableView(QtWidgets.QTableView):
    """
        Subclass QTableView to grab the mouse event. This is used to clear the peaks when the
        mouse is selected on the area off of the indices.
    """
    clearPeaks = QtCore.pyqtSignal()

    # pylint: disable=invalid-name
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """
            Handle mouse press event to clear the peaks when it is done with an
            invalid index
        """
        #print(f"PeakTableView: mousePressEvent: {event.type().name}")
        mouseBtn = event.button()
        if mouseBtn == QtCore.Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if index.row() == -1 and index.column() == -1:
                self.clearPeaks.emit()

        super().mousePressEvent(event)

# pylint: disable=too-many-instance-attributes
class PeakTable(QtWidgets.QWidget):
    """ Table and save button for displaying table of peaks and interacting with it. """

    def __init__(self) -> None:
        super().__init__()

        self.selected_freq_index = -1
        self.selected_freq = 0.0
        self.saved_path: str = ""
        self.data_is_held: bool = False

        #.....
        # Setup a vertical layout to add spacing
        peaks_layout = QtWidgets.QVBoxLayout()

        #.....
        # Spacing above controls
        peaks_layout.addSpacing(20)

        #.....
        # Use tableview to display fft peaks
        self.peaks_table = PeakTableView()
        self.peaks_table.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.peaks_table.setFocus()

        data: npt.NDArray  = np.vstack(([], [])).T
        self.model: pm.PeaksModel = pm.PeaksModel(data)
        # Use custom QSortFilterProxyModel to define the sort
        proxy_model: pfm.PeaksFilterModel = pfm.PeaksFilterModel()
        proxy_model.setSourceModel(self.model)
        self.peaks_table.setModel(proxy_model)
        self.peaks_table.setSortingEnabled(True)
        self.peaks_table.sortByColumn(pm.ColumnIndex.Freq.value, QtCore.Qt.SortOrder.AscendingOrder)
        self.peaks_table.resizeColumnsToContents()
        self.peaks_table.setColumnWidth(self.model.modes_column, self.model.modes_width*8)
        self.peaks_table.setSelectionBehavior(QtWidgets.QTableView.SelectionBehavior.SelectRows)
        self.peaks_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection)
        self.mode_delegate = mcd.ModeComboDelegate(self, self.model.mode_strings)
        self.peaks_table.setItemDelegateForColumn(self.model.modes_column, self.mode_delegate)
        self.show_delegate = sbd.ShowComboDelegate(self)
        self.peaks_table.setItemDelegateForColumn(self.model.show_column, self.show_delegate)
        self.peaks_table.setEditTriggers(QtWidgets.QTableView.EditTrigger.AllEditTriggers)
        self.peaks_table.setToolTip('Displays the peaks found. When results are held, select\n'
            'a cell to highlight the peak in the FFT Peaks display or\n'
            'select a peak on the FFT Peaks waveform to highlight\n'
            'the peak in the table.')

        header_width: int = self.peaks_table.horizontalHeader().length()
        #self.peaks_table.setFixedWidth(header_width + 30)
        self.peaks_table.setFixedWidth(header_width + 10)

        peaks_layout.addWidget(self.peaks_table)

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

        self.model.dataChanged.connect(self.data_changed)

    def data_changed(
            self,
            top_left: QtCore.QModelIndex,
            _bottom_right: QtCore.QModelIndex,
            _roles: typing.Iterable[int] = ...
        ) -> None:
        """ Respond to data changes for a particular model index and select it. """
        #print(f"PeakTable: data_changed: top_left: {top_left.row()}, {top_left.column()}")
        freq_index = self.model.index(top_left.row(), 1)
        freq = self.model.freq_value(freq_index)
        self.select_row(freq)

    def update_data(self, data: np.ndarray) -> bool:
        """ Update the data model from outside the object and
            then update the table.
        """

        # Delete the persistent editors.
        #print(f" update_data: rowCount = {self.peaks_table.model().rowCount()}")
        for row in range(0, self.peaks_table.model().rowCount()):
            #print(f"closePersistentEditor: row: {row}, column{pm.ColumnIndex.Show.value}")
            self.peaks_table.closePersistentEditor(
                self.peaks_table.model().index(row, pm.ColumnIndex.Show.value))
            self.peaks_table.closePersistentEditor(
                self.peaks_table.model().index(row, pm.ColumnIndex.Modes.value))

        #print(f"Peak: update_data: {data}")
        self.model.update_data(data)
        self.update_selected_freq_index()

        # Create new persistent editors
        #print(f" update_data: rowCount = {self.peaks_table.model().rowCount()}")
        for row in range(0, self.peaks_table.model().rowCount()):
            #print(f"openPersistentEditor: row: {row}, column{pm.ColumnIndex.Show.value}")
            self.peaks_table.openPersistentEditor(
                self.peaks_table.model().index(row, pm.ColumnIndex.Show.value))
            self.peaks_table.openPersistentEditor(
                self.peaks_table.model().index(row, pm.ColumnIndex.Modes.value))

        # Select the row.
        if self.selected_freq > 0:
            self.select_row(self.selected_freq)

        return True

    def save_peaks(self) -> None:
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
            proxy_model = self.peaks_table.model()
            data_model = proxy_model.sourceModel()
            columns = range(self.peaks_table.horizontalHeader().count())
            header = [data_model.headerData(column, QtCore.Qt.Orientation.Horizontal,
                QtCore.Qt.ItemDataRole.DisplayRole) for column in columns]
            try:
                with open(filename, 'w', encoding='utf-8-sig') as csvfile:
                    writer = csv.writer(csvfile, dialect='excel', lineterminator='\n')
                    writer.writerow(header)
                    for row in range(data_model.rowCount(QtCore.QVariant())):
                        writer.writerow(data_model.data_value(data_model.index(row, column))
                            for column in columns)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error in saving peaks", f"Table was not saved\n{str(e)}")
                
            

    def restore_focus(self) -> None:
        """ Restore the focus to the peaks_table so selected items higlight
            correctly.
        """
        #print("PeakTable: restore_focus")
        self.peaks_table.setFocus()

    def select_row(self, freq: int) -> None:
        """ For the specified frequency index select the corresponding row
            in the peak table and set the focus to it. Setting the focus will
            scroll the table so the row is in view and highlight it.
        """

        #print(f"PeakTable: select_row {freq}")

        proxy_model = self.peaks_table.model()
        data_model: pm.PeaksModel = proxy_model.sourceModel()
        freq_index = data_model.freq_index(freq)

        self.peaks_table.setFocus()

        if freq_index >= 0:
            data_freq_index = data_model.index(freq_index, 0)
            proxy_freq_index: QtCore.QModelIndex = proxy_model.mapFromSource(data_freq_index)

            select_current = QtCore.QItemSelectionModel.SelectionFlag.SelectCurrent
            select_rows = QtCore.QItemSelectionModel.SelectionFlag.Rows
            flags = select_current | select_rows
            self.peaks_table.selectionModel().clearSelection()
            self.peaks_table.selectionModel().select(proxy_freq_index, flags)

        #print(f"PeakTable: select_row: is")

        self.selected_freq_index = freq_index
        self.selected_freq = freq

    def clear_selection(self) -> None:
        """ Clear all selections form the table. """

        #print("PeakTable: clear_selection")

        self.peaks_table.selectionModel().clearSelection()

    def data_held(self, held: bool) -> None:
        """
            This is used to indicate the change of the data being held. If it is not held
            then the table cannot be edited.
        """
        #print(f"PeakTable: data_held: held: {held}, selected_freq = {self.selected_freq}")
        self.data_is_held = held
        if held:
            #print("data_hel: enable editing")
            self.show_delegate.enable = True
            self.mode_delegate.enable = True
            self.peaks_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.SingleSelection)
            self.peaks_table.setEditTriggers(QtWidgets.QTableView.EditTrigger.AllEditTriggers)
            #if self.selected_freq_index >= 0:
            #    self.select_row(self.selected_freq_index)
        else:
           #print("data_hel: disable editing")
            self.show_delegate.enable = False
            self.mode_delegate.enable = False
            self.peaks_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection)
            self.peaks_table.setEditTriggers(QtWidgets.QTableView.EditTrigger.NoEditTriggers)
            #self.peaks_table.clearSelection()

        self.model.data_held(held)

        if self.selected_freq > 0:
            self.select_row(self.selected_freq)

    def new_data(self, held: bool) -> None:
        """
            This is called if there is new data availble (as upposed to an
            update of data from redrawing more or less data in the data).
            This is used to clear the modes since they are not cleared until
            the underlying data is completely replaced.
        """
        self.model.new_data(held)
        self.clear_selected_peak()

    def update_selected_freq_index(self):
        """
          For the current selected frequency update the related index. The
          inde is the index in the table.
        """
        if self.selected_freq == 0.0:
            self.selected_freq_index = -1
        else:
            self.selected_freq_index = self.model.freq_index(self.selected_freq)

    def clear_selected_peak(self) -> None:
        """ Clear the information related to the selected peak. """
        self.selected_freq_index = -1
        self.selected_freq = 0.0
