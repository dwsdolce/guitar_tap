""" Samples audio signal and finds the peaks of the guitar tap resonances
"""
import sys

import numpy as np
from PyQt6 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

import threshold_slider as TS
import fft_canvas as fft_c
import pitch as pitch_c

class MyNavigationToolbar(NavigationToolbar):
    def home(self, *args):
        axes = self.canvas.fft_axes.set_ylim(-100,0)
        super().home()

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
        match index.column():
            case 0 | 1:
                value = self._data[index.row()][index.column()]
            case 2 | 3:
                value = self.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
            case _:
                value = QtCore.QVariant()
        return value

    def data(self, index, role):
        """ Return the requested data based on role. """
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

    # pylint: disable=invalid-name
    def headerData(self, section, orientation, role):
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

class MainWindow(QtWidgets.QMainWindow):
    """ Defines the layout of the application window
    """
    def __init__(self):
        super().__init__()

        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)

        self.setWindowTitle("Guitar Tap")

        pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, 'SP_MediaSkipBackward')
        restart_icon = self.style().standardIcon(pixmapi)

        self.red_pixmap = QtGui.QPixmap('./icons/led_red.png')
        self.red_icon = QtGui.QIcon(self.red_pixmap)
        self.green_pixmap = QtGui.QPixmap('./icons/led_green.png')
        self.green_icon = QtGui.QIcon(self.green_pixmap)
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
        self.threshold_slider.setToolTip('Shows the magnitude of the FFT of the signal.\nMove the red slider to define threshold used for finding peaks.')
        plot_layout.addWidget(self.threshold_slider)

        self.threshold = 50
        self.threshold_slider.valueChanged.connect(self.threshold_changed)

        # Add an fft Canvas
        f_range = {'f_min': 75, 'f_max': 350}

        window_length = 16384
        sampling_rate = 11025
        spectral_line_resolution = sampling_rate / window_length
        bandwidth = sampling_rate / 2
        sample_size = window_length / sampling_rate

        self.fft_canvas = fft_c.DrawFft(window_length, sampling_rate, f_range, self.threshold)
        self.fft_canvas.setMinimumSize(600, 400)
        self.toolbar = MyNavigationToolbar(self.fft_canvas, self)

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
        control_layout.addSpacing(20)

        #.....
        # Enable Peak hold
        hold_results_layout = QtWidgets.QHBoxLayout()
        hold_results_label = QtWidgets.QLabel("Hold results")
        hold_results_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        hold_results_layout.addWidget(hold_results_label)

        self.hold_results = QtWidgets.QToolButton()
        self.hold_results.setIcon(self.green_icon)
        self.hold_results.setIconSize(QtCore.QSize(21, 21))
        self.hold_results.setStyleSheet('border: none')
        self.hold_results.setCheckable(True)
        self.hold_results.setChecked(False)
        self.hold_results.setToolTip('Enable to stop sampling audio and hold the current results')

        hold_results_layout.addWidget(self.hold_results)

        self.hold_results.toggled.connect(self.set_hold_results)

        control_layout.addLayout(hold_results_layout)

        #.....
        # Averages Group Box
        avg_group_box = QtWidgets.QGroupBox()
        avg_group_box.setTitle("Spectrum Averaging")

        #...
        # Vertical layout of the controls for averaging
        averages_layout = QtWidgets.QVBoxLayout(avg_group_box)

        #.....
        # Enable averaging
        avg_enable_layout = QtWidgets.QHBoxLayout()
        avg_enable_label = QtWidgets.QLabel("Averaging enable")
        avg_enable_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_enable_layout.addWidget(avg_enable_label)

        self.avg_enable = QtWidgets.QToolButton()
        self.avg_enable.setIcon(self.red_icon)
        self.avg_enable.setIconSize(QtCore.QSize(21, 21))
        self.avg_enable.setStyleSheet('border: none')
        self.avg_enable.setCheckable(True)
        self.avg_enable.setChecked(False)
        self.avg_enable.setToolTip('Select to start averaging the fft samples.')
        avg_enable_layout.addWidget(self.avg_enable)

        self.avg_enable_saved = self.avg_enable.isChecked()
        self.avg_enable.toggled.connect(self.set_avg_enable)

        averages_layout.addLayout(avg_enable_layout)

        #.....
        # Number of averages
        num_averages_layout = QtWidgets.QHBoxLayout()

        num_averages_label = QtWidgets.QLabel("Number of averages")
        num_averages_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        num_averages_layout.addWidget(num_averages_label)

        self.num_averages = QtWidgets.QSpinBox(main_widget)
        self.num_averages.setMinimum(0)
        self.num_averages.setMaximum(10)
        self.num_averages.setValue(0)
        self.num_averages.setToolTip('Set the number of fft samples to average')

        self.num_averages.valueChanged.connect(self.fft_canvas.set_max_average_count)

        num_averages_layout.addWidget(self.num_averages)

        averages_layout.addLayout(num_averages_layout)

        #.....
        # Averages completed
        avg_completed_layout = QtWidgets.QHBoxLayout()

        avg_completed_label = QtWidgets.QLabel("Averages completed")
        avg_completed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_completed_layout.addWidget(avg_completed_label)

        self.avg_completed = QtWidgets.QLabel("0")
        self.avg_completed.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        avg_completed_layout.addWidget(self.avg_completed)

        averages_layout.addLayout(avg_completed_layout)

        #.....
        # Averaging done
        avg_done_layout = QtWidgets.QHBoxLayout()

        avg_done_label = QtWidgets.QLabel("Averaging done")
        avg_done_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_done_layout.addWidget(avg_done_label)

        self.avg_done = QtWidgets.QLabel()
        self.avg_done.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.avg_done.setMaximumSize(21, 21)
        self.avg_done.setPixmap(self.red_pixmap)
        self.avg_done.setScaledContents(True)
        avg_done_layout.addWidget(self.avg_done)

        self.avg_done_flag = False

        averages_layout.addLayout(avg_done_layout)

        #.....
        # Restart averaging
        avg_restart_layout = QtWidgets.QHBoxLayout()

        avg_restart_label = QtWidgets.QLabel("Restart averaging")
        avg_restart_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_restart_layout.addWidget(avg_restart_label)

        self.avg_restart = QtWidgets.QPushButton()
        self.avg_restart.setIcon(restart_icon)
        self.avg_restart.setToolTip('Reset the number of averages completed and start averaging')

        avg_restart_layout.addWidget(self.avg_restart)

        self.avg_restart.clicked.connect(self.reset_averaging)

        averages_layout.addLayout(avg_restart_layout)

        control_layout.addWidget(avg_group_box)
  
        #.....
        # Spectral line resolution
        freq_resolution_layout = QtWidgets.QHBoxLayout()

        freq_resolution_label= QtWidgets.QLabel("Frequency resolution")
        freq_resolution_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        freq_resolution_layout.addWidget(freq_resolution_label)

        freq_res_string = f'{spectral_line_resolution:.1} Hz'
        freq_resolution = QtWidgets.QLabel(freq_res_string)
        freq_resolution.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        freq_resolution_layout.addWidget(freq_resolution)

        control_layout.addLayout(freq_resolution_layout)
  
        #.....
        # Bandwidth
        bandwidth_layout = QtWidgets.QHBoxLayout()

        bandwidth_label= QtWidgets.QLabel("Bandwidth")
        bandwidth_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        bandwidth_layout.addWidget(bandwidth_label)

        bandwidth_string = f'{bandwidth:.1f} Hz'
        bandwidth = QtWidgets.QLabel(bandwidth_string)
        bandwidth.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        bandwidth_layout.addWidget(bandwidth)

        control_layout.addLayout(bandwidth_layout)
  
        #.....
        # Sample length
        sample_length_layout = QtWidgets.QHBoxLayout()

        sample_length_label= QtWidgets.QLabel("Sample length")
        sample_length_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        sample_length_layout.addWidget(sample_length_label)

        sample_length_string = f'{sample_size:.1f} s'
        sample_length = QtWidgets.QLabel(sample_length_string)
        sample_length.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        sample_length_layout.addWidget(sample_length)

        control_layout.addLayout(sample_length_layout)

        #.....
        # Frame rate
        framerate_layout = QtWidgets.QHBoxLayout()

        framerate_label = QtWidgets.QLabel("FrameRate")
        framerate_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        framerate_layout.addWidget(framerate_label)

        self.framerate = QtWidgets.QLabel("0")
        self.framerate.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        framerate_layout.addWidget(self.framerate)

        control_layout.addLayout(framerate_layout)

        #.....
        # Audio sample time
        sampletime_layout = QtWidgets.QHBoxLayout()

        sampletime_label = QtWidgets.QLabel("Sample time")
        sampletime_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        sampletime_layout.addWidget(sampletime_label)

        self.sampletime = QtWidgets.QLabel("0")
        self.sampletime.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        sampletime_layout.addWidget(self.sampletime)

        control_layout.addLayout(sampletime_layout)

        #.....
        # Processing time
        processing_layout = QtWidgets.QHBoxLayout()

        processing_label = QtWidgets.QLabel("Processing time")
        processing_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        processing_layout.addWidget(processing_label)

        self.processingtime = QtWidgets.QLabel("0")
        self.processingtime.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        processing_layout.addWidget(self.processingtime)

        control_layout.addLayout(processing_layout)

        #.....
        # Stretch space to support windo resize
        control_layout.addStretch()

        #.....
        # Minimum frequency for peak results
        min_layout = QtWidgets.QHBoxLayout()
        min_label = QtWidgets.QLabel("Start Freq (Hz)")
        min_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        min_layout.addWidget(min_label)

        self.min_spin = QtWidgets.QSpinBox(main_widget)
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(f_range['f_min'])
        self.min_spin.valueChanged.connect(self.fmin_changed)
        self.min_spin.setToolTip('The lowest frequency for which peaks are reported')

        min_layout.addWidget(self.min_spin)

        control_layout.addLayout(min_layout)

        # Maximum frequency for peak results
        max_layout = QtWidgets.QHBoxLayout()
        max_label = QtWidgets.QLabel("Stop Freq (Hz)")
        max_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        max_layout.addWidget(max_label)

        self.max_spin = QtWidgets.QSpinBox(main_widget)
        self.max_spin.setMinimum(0)
        self.max_spin.setMaximum(22050)
        self.max_spin.setValue(f_range['f_max'])
        self.max_spin.setToolTip('The highest frequency for which peaks are reported')

        self.max_spin.valueChanged.connect(self.fmax_changed)

        max_layout.addWidget(self.max_spin)

        control_layout.addLayout(max_layout)

        #.....
        # Add space at the bottom
        control_layout.addSpacing(40)

        hlayout.addLayout(control_layout)

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
        model = PeaksModel(data)
        # Use custom QSortFilterProxyModel to define the sort
        proxy_model = PeaksFilterModel()
        proxy_model.setSourceModel(model)
        self.peak_table.setModel(proxy_model)
        self.peak_table.setSortingEnabled(True)
        self.peak_table.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.peak_table.resizeColumnsToContents()
        self.peak_table.setSelectionBehavior(QtWidgets.QTableView.SelectionBehavior.SelectRows);
        self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection);
        self.peak_table.selectionModel().selectionChanged.connect(self.peak_selection_changed)
        self.peak_table.setToolTip('Displays the peaks found. When results are held, select\na cell to highlight the peak in the FFT Peaks display or\nselect a peak on the FFT Peaks waveform to highlight\nthe peak in the table.')

        header_width = self.peak_table.horizontalHeader().length()
        self.peak_table.setFixedWidth(header_width + 30)

        peaks_layout.addWidget(self.peak_table)

        #.....
        # Add space at the bottom
        peaks_layout.addSpacing(40)

        hlayout.addLayout(peaks_layout)

        #.....
        # Connect externalsignals
        self.fft_canvas.peaksChanged.connect(model.updateData)
        self.fft_canvas.peakSelected.connect(self.selectRow)
        self.fft_canvas.ampChanged.connect(self.threshold_slider.set_amplitude)
        self.fft_canvas.averagesChanged.connect(self.set_avg_completed)
        self.fft_canvas.framerateUpdate.connect(self.set_framerate)

        #.....
        # Set the averaging to false.
        self.set_avg_enable(False)
        self.set_hold_results(False)
        self.fft_canvas.set_max_average_count(self.num_averages.value())

    def selectRow(self, freq_index):
        proxy_model = self.peak_table.model()
        data_model = proxy_model.sourceModel()

        data_freq_index = data_model.index(freq_index, 0)
        proxy_freq_index = proxy_model.mapFromSource(data_freq_index)
        flags = QtCore.QItemSelectionModel.SelectionFlag.SelectCurrent | QtCore.QItemSelectionModel.SelectionFlag.Rows
        self.peak_table.setFocus()
        self.peak_table.selectionModel().setCurrentIndex(proxy_freq_index, flags)

    def peak_selection_changed(self, selected, deselected):
        if np.any(selected):
            proxy_model = self.peak_table.model()
            proxy_freq_index = selected.indexes()[0]

            data_freq_index = proxy_model.mapToSource(proxy_freq_index)

            freq = proxy_model.sourceModel().freq_value(data_freq_index)
            self.fft_canvas.select_peak(freq)

    def set_framerate(self, framerate, sampletime, processingtime):
        self.framerate.setText(f'{framerate:.1f} fps')
        self.sampletime.setText(f'{sampletime:.1f} s')
        self.processingtime.setText(f'{processingtime*1000:.1f} ms')

    def set_avg_enable(self, checked):
        """ Change the icon color and also change the fft_plot
            to do averaging or not.
        """
        if checked:
            self.avg_enable.setIcon(self.green_icon)
            self.fft_canvas.set_avg_enable(True)

            self.avg_restart.setEnabled(True)

        else:
            self.avg_enable.setIcon(self.red_icon)
            self.fft_canvas.set_avg_enable(False)

            # Now disable the items
            self.avg_restart.setEnabled(False)


    def set_hold_results(self, checked):
        """ Change the icon color and also change the fft_plot
            to do peak holding or not to do peak holding.
        """
        if checked:
            self.hold_results.setIcon(self.green_icon)
            self.fft_canvas.set_hold_results(True)

            # Save current state of avg_enable
            # and disable it
            self.avg_enable_saved = self.avg_enable.isChecked()
            self.set_avg_enable(False)
            self.avg_enable.setEnabled(False)

            if self.avg_enable.isChecked():
                self.avg_restart.setEnabled(True)
            else:
                self.avg_restart.setEnabled(False)

            self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.SingleSelection);
        else:
            self.hold_results.setIcon(self.red_icon)
            self.fft_canvas.set_hold_results(False)

            # Save current state of avg_enable
            # and enable it
            # restore current state of avg_enable
            self.set_avg_enable(self.avg_enable_saved)
            self.avg_enable.setEnabled(True)

            self.peak_table.setSelectionMode(QtWidgets.QTableView.SelectionMode.NoSelection);
            self.peak_table.clearSelection()

    def threshold_changed(self):
        """ Set the threshold used in fft_canvas
            The threshold value is always 0 to 100.
        """

        self.threshold = self.threshold_slider.value()
        self.fft_canvas.set_threshold(self.threshold)

    def reset_averaging(self):
        self.fft_canvas.reset_averaging()
        self.set_avg_completed(0)
        self.avg_done.setPixmap(self.red_pixmap)
        if self.hold_results.isChecked():
            self.hold_results.click()

    def set_avg_completed(self, count):
        self.avg_completed.setText(str(count))
        if count >= self.num_averages.value():
            # Change the LED to Green
            self.avg_done.setPixmap(self.green_pixmap)

            self.avg_done_flag = True
            self.num_averages.setEnabled(True)
            self.avg_restart.setEnabled(True)

            self.hold_results.click()
        else:
            self.avg_done_flag = False
            self.num_averages.setEnabled(False)
            self.avg_restart.setEnabled(False)
            self.avg_enable.setEnabled(False)

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
