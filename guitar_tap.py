""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys
import os

from PyQt6 import QtWidgets, QtGui, QtCore

import plot_controls as PC
import peaks_controls as PKC
import peaks_table as PT
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
    def __init__(self) -> None:
        super().__init__()

        main_widget: QtWidgets.QWidget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)

        self.saved_path: str = ""
        with open(os.path.join(basedir, './version'), 'r', encoding='UTF-8') as file_handle:
            version = file_handle.read().rstrip()

        self.setWindowTitle(f"Guitar Tap {version}")

        hlayout = QtWidgets.QHBoxLayout(main_widget)

        # ==========================================================
        # Create the plot plus controls
        # ==========================================================
        self.threshold: int = 50
        fft_settings: dict[str, int] = {'sampling_rate': 11025, 'window_length': 16384}
        f_range: dict[str, int] = {'f_min': 75, 'f_max': 350}
        self.plot_controls = PC.PlotControls(self.threshold, f_range, fft_settings)

        hlayout.addWidget(self.plot_controls)

        # ==========================================================
        # Create control layout
        # ==========================================================

        self.peaks_controls = PKC.PeakControls(f_range, fft_settings)

        hlayout.addWidget(self.peaks_controls)

        # ==========================================================
        # Create peaks table
        # ==========================================================
        self.peak_widget = PT.PeakTable()

        hlayout.addWidget(self.peak_widget)

        #.....
        # Connect externalsignals
        self.peaks_controls.min_spin.valueChanged.connect(self.plot_controls.fmin_changed)
        self.peaks_controls.max_spin.valueChanged.connect(self.plot_controls.fmax_changed)
        self.peaks_controls.hold_results.toggled.connect(self.set_hold_results)
        self.peaks_controls.avg_enable.toggled.connect(self.set_avg_enable)
        self.peaks_controls.num_averages.valueChanged.connect(
            self.plot_controls.fft_canvas.set_max_average_count)
        self.peaks_controls.avg_restart.clicked.connect(self.reset_averaging)
        self.peaks_controls.show_devices.clicked.connect(self.show_device_dialog)

        self.plot_controls.fft_canvas.peaksChanged.connect(self.peak_widget.update_data)
        self.plot_controls.fft_canvas.peakSelected.connect(self.peak_widget.select_row)
        self.plot_controls.fft_canvas.peakDeselected.connect(self.peak_widget.clear_selection)
        self.plot_controls.fft_canvas.averagesChanged.connect(self.peaks_controls.set_avg_completed)
        self.plot_controls.fft_canvas.framerateUpdate.connect(self.peaks_controls.set_framerate)
        self.plot_controls.fft_canvas.newSample.connect(self.peak_widget.new_data)

        self.peak_widget.peaks_table.clearPeaks.connect(
            self.plot_controls.fft_canvas.clear_selected_peak)
        self.peak_widget.peaks_table.selectionModel().selectionChanged.connect(
            self.peak_selection_changed)

        #....m
        # Set the averaging to false.
        self.set_avg_enable(False)
        self.set_hold_results(False)
        self.plot_controls.fft_canvas.set_max_average_count(self.peaks_controls.num_averages.value())

    def show_device_dialog(self, _) -> None:
        """ Create and show the Devices dialog """
        dlg = SD.ShowDevices(self.plot_controls.fft_canvas.get_py_audio())
        dlg.exec()

    def peak_selection_changed(self,
                               selected: QtCore.QItemSelection,
                               deselected: QtCore.QItemSelection
                              ) -> None:
        """ Process the selection of peaks in the peak table and select
            the corresponding peak in the FFT graph.
        """
        if len(deselected.indexes()) > 0:
            proxy_model = self.peak_widget.peaks_table.model()
            proxy_freq_index = deselected.indexes()[0]
            print(f"MainWindow: peak_selection_changed: deselected: {proxy_freq_index.row()}")

            data_freq_index = proxy_model.mapToSource(proxy_freq_index)
            freq = proxy_model.sourceModel().freq_value(data_freq_index)
            self.plot_controls.fft_canvas.deselect_peak(freq)
            self.peak_widget.selected_freq_index = -1
        if len(selected.indexes()) > 0:
            proxy_model = self.peak_widget.peaks_table.model()
            proxy_freq_index = selected.indexes()[0]
            print(f"MainWindow: peak_selection_changed: selected: {proxy_freq_index.row()}")

            #data_freq_index: QtCore.QModelIndex = proxy_model.mapToSource(proxy_freq_index)
            data_freq_index = proxy_model.mapToSource(proxy_freq_index)

            freq = proxy_model.sourceModel().freq_value(data_freq_index)
            self.plot_controls.fft_canvas.select_peak(freq)
            self.peak_widget.selected_freq_index = data_freq_index.row()

    def set_avg_enable(self, checked: bool) -> None:
        """ Change the icon color and also change the fft_plot
            to do averaging or not.
        """
        self.plot_controls.fft_canvas.set_avg_enable(checked)
        self.peaks_controls.set_avg_enable(checked)

    def set_hold_results(self, checked: bool) -> None:
        """ Change the icon color and also change the fft_plot
            to do peak holding or not to do peak holding.
        """
        self.plot_controls.fft_canvas.set_hold_results(checked)
        self.peaks_controls.set_hold_results(checked)
        self.peak_widget.data_held(checked)

        if checked:
            self.set_avg_enable(False)
        else:
            self.set_avg_enable(self.peaks_controls.avg_enable_saved)

    def reset_averaging(self) -> None:
        """ Reset the controls restart averaging """
        self.plot_controls.fft_canvas.reset_averaging()
        self.peaks_controls.reset_averaging()

if __name__ == "__main__":
    if os.name == 'nt':
        mutex = NM.NamedMutex('guitar-tap-running', True)

    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.setWindowIcon(QtGui.QIcon(os.path.join(basedir, 'icons/guitar-tap.svg')))
    app.resize(800, 500)
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
