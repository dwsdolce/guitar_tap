"""
    Table for display the peak information. Allows for row selection and highlighting, sorting,
    and saving of the table to a csv file.
"""

import os
import csv

import numpy as np
from PyQt6 import QtWidgets, QtCore, QtGui
import modeComboDelegate as mcd
import peaksFilterModel as pfm
import peaksModel as pm

class PeakTableView(QtWidgets.QTableView):
    clearPeaks = QtCore.pyqtSignal()
    def mousePressEvent(self, event: QtGui.QMouseEvent):
        mouseBtn = event.button()
        if mouseBtn == QtCore.Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if index.row() == -1 and index.column() == -1:
                self.clearPeaks.emit()

        super().mousePressEvent(event)

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
        self.peak_table = PeakTableView()
        data = np.vstack(([], [])).T
        self.model = pm.PeaksModel(data)
        # Use custom QSortFilterProxyModel to define the sort
        proxy_model = pfm.PeaksFilterModel()
        proxy_model.setSourceModel(self.model)
        self.peak_table.setModel(proxy_model)
        self.peak_table.setSortingEnabled(True)
        self.peak_table.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.peak_table.resizeColumnsToContents()
        self.peak_table.setColumnWidth(self.model.modes_column, self.model.modes_width*8)
        self.peak_table.setSelectionBehavior(QtWidgets.QTableView.SelectionBehavior.SelectRows)
        self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection)
        self.peak_table.setItemDelegateForColumn(self.model.modes_column, mcd.ModeComboDelegate(self, self.model.mode_strings)) 
        self.peak_table.setEditTriggers(QtWidgets.QTableView.EditTrigger.AllEditTriggers)
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

    def updateData(self, data: np.ndarray):
        #print(f"Peak: updateData: {data}")
        self.model.updateData(data)
        return True

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

    def select_row(self, freq_index: int):
        #print("PeakTable: select_row")
        """ For the specified frequency index select the corresponding row
            in the peak table and set the focus to it. Setting the focus will
            scroll the table so the row is in view and highlight it.
        """
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
        #print("PeakTable: delect_row")
        self.peak_table.selectionModel().clearSelection()
    
    def data_held(self, held: bool):
        #print("PeakTable: data_held")

        self.model.data_held(held)

        if held:
            self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.SingleSelection)
            self.peak_table.setEditTriggers(QtWidgets.QTableView.EditTrigger.AllEditTriggers)
        else:
            self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection)
            self.peak_table.setEditTriggers(QtWidgets.QTableView.EditTrigger.NoEditTriggers)
            self.peak_table.clearSelection()
            self.peak_table.reset()
        
    def new_data(self, held: bool):
        self.model.new_data(held)