""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys

import numpy as np
from PyQt6 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

import threshold_slider as TS
import fft_canvas as fft_c
import pitch as pitch_c

class PeaksModel(QtCore.QAbstractTableModel):
    header_names = ['Frequency', 'Magnitude', 'Pitch', 'Cents']
    def __init__(self, data):
        super().__init__()
        self._data = data
        self.pitch = pitch_c.Pitch(440)

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if (index.column() == 0) or (index.column() == 1):
                value = self._data[index.row()][index.column()]
                str_value = '{:.1f}'.format(value)
            elif index.column() == 2:
                value = self._data[index.row()][0]
                str_value = self.pitch.note(value)
            elif index.column() == 3:
                value = self._data[index.row()][0]
                str_value = '{:+.0f}'.format(self.pitch.cents(value))
            else:
                value = self._data[index.row()][index.column()]
                str_value = str(value)
            return str_value
        elif role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignRight

    def headerData(self, section, orientation, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return self.header_names[section]

    def updateData(self, data):
        self.layoutAboutToBeChanged.emit()
        self._data = data
        self.layoutChanged.emit()

    def rowCount(self, index):
        return self._data.shape[0]

    def columnCount(self, index):
        return self._data.shape[1] + 2

class MainWindow(QtWidgets.QMainWindow):
    """ Defines the layout of the application window
        TODO: MainWindow resize and move need to disable the
        FFT updates.
        TODO: Need to Set the TableView columns to fix size and align contents
    """


    ampChanged = QtCore.pyqtSignal(int)
    peaksChanged = QtCore.pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()

        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)

        self.setWindowTitle("Guitar Tap")

        pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, 'SP_MediaSkipBackward')
        restart_icon = self.style().standardIcon(pixmapi)

        red_pixmap = QtGui.QPixmap('./icons/led_red.png')
        self.red_icon = QtGui.QIcon(red_pixmap)
        green_pixmap = QtGui.QPixmap('./icons/led_green.png')
        self.green_icon = QtGui.QIcon(green_pixmap)
        #blue_pixmap = QtGui.QPixmap('./icons/led_blue.png')
        #blue_icon = QtGui.QIcon(blue_pixmap)

        hlayout = QtWidgets.QHBoxLayout(main_widget)

        # Create layout with threshold slider and fft canvas
        plot_layout = QtWidgets.QVBoxLayout()

        # ==========================================================
        # Create the plot plus controls
        # ==========================================================
        # Add the slider
        self.threshold_slider = TS.ThresholdSlider(QtCore.Qt.Orientation.Horizontal)
        plot_layout.addWidget(self.threshold_slider)
        self.threshold = 50
        self.threshold_slider.valueChanged.connect(self.threshold_changed)

        self.ampChanged.connect(self.threshold_slider.set_amplitude)

        # Add an fft Canvas
        f_range = {'f_min': 50, 'f_max': 1000}
        self.fft_canvas = fft_c.DrawFft(
                self.ampChanged, self.peaksChanged, f_range, self.threshold)
        self.fft_canvas.setMinimumSize(600, 400)
        self.toolbar = NavigationToolbar(self.fft_canvas, self)

        self.fft_canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.fft_canvas.setFocus()

        plot_layout.addWidget(self.fft_canvas)
        plot_layout.addWidget(self.toolbar)

        hlayout.addLayout(plot_layout)

        # ==========================================================
        # Create control layout
        # ==========================================================
        control_layout = QtWidgets.QVBoxLayout()

        #.....
        # Spacing above controls
        control_layout.addSpacing(40)

        #.....
        # Enable Peak hold
        peak_hold_layout = QtWidgets.QHBoxLayout()
        peak_hold_label = QtWidgets.QLabel("Peak hold")
        peak_hold_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        peak_hold_layout.addWidget(peak_hold_label)

        peak_hold = QtWidgets.QToolButton()
        peak_hold.setIcon(self.green_icon)
        peak_hold.setIconSize(QtCore.QSize(21, 21))
        peak_hold.setStyleSheet('border: none')
        peak_hold.setCheckable(True)
        peak_hold.setChecked(True)
        peak_hold_layout.addWidget(peak_hold)
        peak_hold.toggled.connect(self.set_peak_hold)

        control_layout.addLayout(peak_hold_layout)

        #.....
        # Averages Group Box
        avg_group_box = QtWidgets.QGroupBox()
        avg_group_box.setTitle("Spectrum Averaging")

        #...
        # Vertical layout of the controls for averaging
        averages_layout = QtWidgets.QVBoxLayout(avg_group_box)

        #.....
        # Number of averages
        num_averages_layout = QtWidgets.QHBoxLayout()

        num_averages_label = QtWidgets.QLabel("Number of averages")
        num_averages_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        num_averages_layout.addWidget(num_averages_label)

        num_averages = QtWidgets.QSpinBox(main_widget)
        num_averages_layout.addWidget(num_averages)

        averages_layout.addLayout(num_averages_layout)

        #.....
        # Averages completed
        avg_completed_layout = QtWidgets.QHBoxLayout()

        avg_completed_label = QtWidgets.QLabel("Averages completed")
        avg_completed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_completed_layout.addWidget(avg_completed_label)

        avg_completed = QtWidgets.QLabel("0")
        avg_completed.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        avg_completed_layout.addWidget(avg_completed)

        averages_layout.addLayout(avg_completed_layout)

        #.....
        # Averaging done
        avg_done_layout = QtWidgets.QHBoxLayout()

        avg_done_label = QtWidgets.QLabel("Averaging done")
        avg_done_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_done_layout.addWidget(avg_done_label)

        avg_done = QtWidgets.QLabel()
        avg_done.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        avg_done.setMaximumSize(21, 21)
        avg_done.setPixmap(red_pixmap)
        avg_done.setScaledContents(True)
        avg_done_layout.addWidget(avg_done)

        averages_layout.addLayout(avg_done_layout)

        #.....
        # Restart averaging
        avg_restart_layout = QtWidgets.QHBoxLayout()

        avg_restart_label = QtWidgets.QLabel("Restart averaging")
        avg_restart_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_restart_layout.addWidget(avg_restart_label)

        avg_restart = QtWidgets.QPushButton()
        avg_restart.setIcon(restart_icon)
        avg_restart_layout.addWidget(avg_restart)

        averages_layout.addLayout(avg_restart_layout)

        control_layout.addWidget(avg_group_box)

        #.....
        # Stretch space to support windo resize
        control_layout.addStretch()

        #.....
        # Frequency window for peak results
        min_max_layout = QtWidgets.QHBoxLayout()

        min_layout = QtWidgets.QVBoxLayout()
        min_label = QtWidgets.QLabel("Start Freq (Hz)")
        min_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        min_layout.addWidget(min_label)
        self.min_spin = QtWidgets.QSpinBox(main_widget)
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(f_range['f_min'])
        self.min_spin.valueChanged.connect(self.fmin_changed)
        min_layout.addWidget(self.min_spin)

        min_max_layout.addLayout(min_layout)

        max_layout = QtWidgets.QVBoxLayout()
        max_label = QtWidgets.QLabel("Stop Freq (Hz)")
        max_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        max_layout.addWidget(max_label)
        self.max_spin = QtWidgets.QSpinBox(main_widget)
        self.max_spin.setMinimum(0)
        self.max_spin.setMaximum(22050)
        self.max_spin.setValue(f_range['f_max'])
        self.max_spin.valueChanged.connect(self.fmax_changed)
        max_layout.addWidget(self.max_spin)

        min_max_layout.addLayout(max_layout)

        control_layout.addLayout(min_max_layout)

        #.....
        # Add space at the bottom
        control_layout.addSpacing(40)

        hlayout.addLayout(control_layout)

        #.....
        # Setup a vertical layout to add spacing
        peaks_layout = QtWidgets.QVBoxLayout()

        #.....
        # Spacing above controls
        peaks_layout.addSpacing(40)

        #.....
        # Use tableview to display fft peaks
        peak_table = QtWidgets.QTableView()
        data = np.vstack(([], [])).T
        model = PeaksModel(data)
        proxy_model = QtCore.QSortFilterProxyModel()
        proxy_model.setSourceModel(model)
        peak_table.setModel(proxy_model) 
        peak_table.setSortingEnabled(True)
        peak_table.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        peak_table.resizeColumnsToContents()

        header_width = peak_table.horizontalHeader().length()
        peak_table.setFixedWidth(header_width + 30)

        self.peaksChanged.connect(model.updateData)

        peaks_layout.addWidget(peak_table)

        #.....
        # Add space at the bottom
        peaks_layout.addSpacing(40)

        hlayout.addLayout(peaks_layout)

    def set_peak_hold(self, checked):
        """ Change the icon color and also change the fft_plot
            to do peak holding or not to do peak holding.
            TODO: If peak holding is not set then the averaging controls
            need to be disabled.
        """
        if checked:
            self.sender().setIcon(self.green_icon)
            self.fft_canvas.set_peak_hold(True)
        else:
            self.sender().setIcon(self.red_icon)
            self.fft_canvas.set_peak_hold(False)

    def threshold_changed(self):
        """ Set the threshold used in fft_canvas
            The threshold value is always 0 to 100.
        """

        self.threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(self.threshold)

    def fmin_changed(self):
        """ Change the minimum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmin(self.min_spin.value())

    def fmax_changed(self):
        """ Change the maximum frequency used on on peak
        thresholding and for the "home" window size
        """
        self.toolbar.update()
        self.fft_canvas.set_fmax(self.max_spin.value())

if __name__ == "__main__":
    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.resize(800, 500)
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
