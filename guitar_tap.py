""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys
import os

import numpy as np
from PyQt6 import QtWidgets, QtGui

import plot_controls as PC
import peak_controls as PKC
import peak_table as PT
import show_devices as SD

if os.name == 'nt':
    import named_mutex as NM

basedir = os.path.dirname(__file__)
try:
    from ctypes import windll # Only exists on Windows.
    MY_APP_ID = "dolcesfogato.guitar-tap.guitar-tap.0.5"
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(MY_APP_ID)
except ImportError:
    pass

class MainWindow(QtWidgets.QMainWindow):
    """ Defines the layout of the application window
    """
    def __init__(self):
        super().__init__()

        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)

        self.saved_path = ""

        self.setWindowTitle("Guitar Tap 0.7")

        hlayout = QtWidgets.QHBoxLayout(main_widget)

        # ==========================================================
        # Create the plot plus controls
        # ==========================================================
        self.threshold = 50
        fft_settings = {'sampling_rate': 11025, 'window_length': 16384}
        f_range = {'f_min': 75, 'f_max': 350}
        self.plot_controls = PC.PlotControls(self.threshold, f_range, fft_settings)

        hlayout.addWidget(self.plot_controls)

        # ==========================================================
        # Create control layout
        # ==========================================================

        self.peak_controls = PKC.PeakControls(f_range, fft_settings)

        hlayout.addWidget(self.peak_controls)

        # ==========================================================
        # Create peaks table
        # ==========================================================
        self.peak_widget = PT.PeakTable()

        hlayout.addWidget(self.peak_widget)

        #.....
        # Connect externalsignals
        self.peak_controls.min_spin.valueChanged.connect(self.plot_controls.fmin_changed)
        self.peak_controls.max_spin.valueChanged.connect(self.plot_controls.fmax_changed)
        self.peak_controls.hold_results.toggled.connect(self.set_hold_results)
        self.peak_controls.avg_enable.toggled.connect(self.set_avg_enable)
        self.peak_controls.num_averages.valueChanged.connect(
            self.plot_controls.fft_canvas.set_max_average_count)
        self.peak_controls.avg_restart.clicked.connect(self.reset_averaging)
        self.peak_controls.show_devices.clicked.connect(self.show_device_dialog)

        self.plot_controls.fft_canvas.peaksChanged.connect(self.peak_widget.model.updateData)
        self.plot_controls.fft_canvas.peakSelected.connect(self.peak_widget.select_row)
        self.plot_controls.fft_canvas.averagesChanged.connect(self.peak_controls.set_avg_completed)
        self.plot_controls.fft_canvas.framerateUpdate.connect(self.peak_controls.set_framerate)

        self.peak_widget.peak_table.selectionModel().selectionChanged.connect(
            self.peak_selection_changed)

        #.....
        # Set the averaging to false.
        self.set_avg_enable(False)
        self.set_hold_results(False)
        self.plot_controls.fft_canvas.set_max_average_count(self.peak_controls.num_averages.value())

    def show_device_dialog(self, _):
        """ Create and show the Devices dialog """
        dlg = SD.ShowDevices(self.plot_controls.fft_canvas.get_py_audio())
        dlg.exec()

    def peak_selection_changed(self, selected, _deselected):
        """ Process the selection of peaks in the peak table and select
            the corresponding peak in the FFT graph.
        """
        if np.any(selected):
            proxy_model = self.peak_widget.peak_table.model()
            proxy_freq_index = selected.indexes()[0]

            data_freq_index = proxy_model.mapToSource(proxy_freq_index)

            freq = proxy_model.sourceModel().freq_value(data_freq_index)
            self.plot_controls.fft_canvas.select_peak(freq)

    def set_avg_enable(self, checked):
        """ Change the icon color and also change the fft_plot
            to do averaging or not.
        """
        self.plot_controls.fft_canvas.set_avg_enable(checked)
        self.peak_controls.set_avg_enable(checked)

    def set_hold_results(self, checked):
        """ Change the icon color and also change the fft_plot
            to do peak holding or not to do peak holding.
        """
        self.plot_controls.fft_canvas.set_hold_results(checked)
        self.peak_controls.set_hold_results(checked)

        if checked:
            self.set_avg_enable(False)

            self.peak_widget.peak_table.setSelectionMode(
                QtWidgets.QTableView.SelectionMode.SingleSelection)
        else:
            self.set_avg_enable(self.peak_controls.avg_enable_saved)

            self.peak_widget.peak_table.setSelectionMode(
                QtWidgets.QTableView.SelectionMode.NoSelection)
            self.peak_widget.peak_table.clearSelection()

    def reset_averaging(self):
        """ Reset the controls restart averaging """
        self.plot_controls.fft_canvas.reset_averaging()
        self.peak_controls.reset_averaging()

if __name__ == "__main__":
    if os.name == 'nt':
        mutex = NM.NamedMutex('guitar-tap-running', True)

    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.setWindowIcon(QtGui.QIcon(os.path.join(basedir,'icons/guitar-tap.svg')))
    app.resize(800, 500)
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
