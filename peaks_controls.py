"""
    Custom widget containing all of the controls for calculating peaks from the FFT
"""

import os

from PyQt6 import QtWidgets, QtCore
import gt_images as gt_i

basedir = os.path.dirname(__file__)


# pylint: disable=too-many-instance-attributes
class PeakControls(QtWidgets.QWidget):
    """Layout of the controls for caculating peaks from the FFT"""

    # pylint: disable = too-many-locals
    # pylint: disable = too-many-statements
    def __init__(self, f_range: dict[str, int], fft_settings: dict[str, int]) -> None:
        super().__init__()
        control_layout = QtWidgets.QVBoxLayout()

        spectral_line_resolution = (
            fft_settings["sampling_rate"] / fft_settings["window_length"]
        )
        bandwidth = fft_settings["sampling_rate"] / 2
        sample_size = fft_settings["window_length"] / fft_settings["sampling_rate"]

        pixmapi = getattr(QtWidgets.QStyle.StandardPixmap, "SP_MediaSkipBackward")
        restart_icon = self.style().standardIcon(pixmapi)

        # .....
        # Spacing above controls
        control_layout.addSpacing(20)

        # .....
        # Enable Peak hold
        hold_results_layout = QtWidgets.QHBoxLayout()
        hold_results_label = QtWidgets.QLabel("Hold results")
        hold_results_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        hold_results_layout.addWidget(hold_results_label)

        self.hold_results = QtWidgets.QToolButton()
        self.hold_results.setIcon(gt_i.GtImages.green_button_icon())
        self.hold_results.setIconSize(QtCore.QSize(21, 21))
        self.hold_results.setStyleSheet("border: none")
        self.hold_results.setCheckable(True)
        self.hold_results.setChecked(False)
        self.hold_results.setToolTip(
            "Enable to stop sampling audio and hold the current results"
        )

        hold_results_layout.addWidget(self.hold_results)

        control_layout.addLayout(hold_results_layout)

        # .....
        # Averages Group Box
        avg_group_box = QtWidgets.QGroupBox()
        avg_group_box.setTitle("Spectrum Averaging")

        # ...
        # Vertical layout of the controls for averaging
        averages_layout = QtWidgets.QVBoxLayout(avg_group_box)

        # .....
        # Number of averages
        num_averages_layout = QtWidgets.QHBoxLayout()

        num_averages_label = QtWidgets.QLabel("Number of averages")
        num_averages_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        num_averages_layout.addWidget(num_averages_label)

        self.num_averages = QtWidgets.QSpinBox()
        self.num_averages.setMinimum(0)
        self.num_averages.setMaximum(10)
        self.num_averages.setValue(0)
        self.num_averages.setToolTip("Set the number of fft samples to average")

        num_averages_layout.addWidget(self.num_averages)

        averages_layout.addLayout(num_averages_layout)

        # .....
        # Enable averaging
        avg_enable_layout = QtWidgets.QHBoxLayout()
        avg_enable_label = QtWidgets.QLabel("Averaging enable")
        avg_enable_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_enable_layout.addWidget(avg_enable_label)

        self.avg_enable = QtWidgets.QToolButton()
        self.avg_enable.setIcon(gt_i.GtImages.red_button_icon())
        self.avg_enable.setIconSize(QtCore.QSize(21, 21))
        self.avg_enable.setStyleSheet("border: none")
        self.avg_enable.setCheckable(True)
        self.avg_enable.setChecked(False)
        self.avg_enable.setToolTip("Select to start averaging the fft samples.")
        avg_enable_layout.addWidget(self.avg_enable)

        self.avg_enable_saved: bool = self.avg_enable.isChecked()

        averages_layout.addLayout(avg_enable_layout)

        # .....
        # Averages completed
        avg_completed_layout = QtWidgets.QHBoxLayout()

        avg_completed_label = QtWidgets.QLabel("Averages completed")
        avg_completed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_completed_layout.addWidget(avg_completed_label)

        self.avg_completed = QtWidgets.QLabel("0")
        self.avg_completed.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        avg_completed_layout.addWidget(self.avg_completed)

        averages_layout.addLayout(avg_completed_layout)

        # .....
        # Averaging done
        avg_done_layout = QtWidgets.QHBoxLayout()

        avg_done_label = QtWidgets.QLabel("Averaging done")
        avg_done_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_done_layout.addWidget(avg_done_label)

        self.avg_done = QtWidgets.QLabel()
        self.avg_done.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.avg_done.setMaximumSize(21, 21)
        self.avg_done.setPixmap(gt_i.GtImages.red_pixmap())
        self.avg_done.setScaledContents(True)
        avg_done_layout.addWidget(self.avg_done)

        averages_layout.addLayout(avg_done_layout)

        # .....
        # Restart averaging
        avg_restart_layout = QtWidgets.QHBoxLayout()

        avg_restart_label = QtWidgets.QLabel("Restart averaging")
        avg_restart_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        avg_restart_layout.addWidget(avg_restart_label)

        self.avg_restart = QtWidgets.QPushButton()
        self.avg_restart.setIcon(restart_icon)
        self.avg_restart.setToolTip(
            "Reset the number of averages completed and start averaging"
        )

        avg_restart_layout.addWidget(self.avg_restart)

        averages_layout.addLayout(avg_restart_layout)

        control_layout.addWidget(avg_group_box)

        # .....
        # Spectral line resolution
        freq_resolution_layout = QtWidgets.QHBoxLayout()

        freq_resolution_label = QtWidgets.QLabel("Frequency resolution")
        freq_resolution_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        freq_resolution_layout.addWidget(freq_resolution_label)

        freq_res_string = f"{spectral_line_resolution:.1} Hz"
        freq_resolution = QtWidgets.QLabel(freq_res_string)
        freq_resolution.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        freq_resolution_layout.addWidget(freq_resolution)

        control_layout.addLayout(freq_resolution_layout)

        # .....
        # Bandwidth
        bandwidth_layout = QtWidgets.QHBoxLayout()

        bandwidth_label = QtWidgets.QLabel("Bandwidth")
        bandwidth_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        bandwidth_layout.addWidget(bandwidth_label)

        bandwidth_string = f"{bandwidth:.1f} Hz"
        bandwidth = QtWidgets.QLabel(bandwidth_string)
        bandwidth.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        bandwidth_layout.addWidget(bandwidth)

        control_layout.addLayout(bandwidth_layout)

        # .....
        # Sample length
        sample_length_layout = QtWidgets.QHBoxLayout()

        sample_length_label = QtWidgets.QLabel("Sample length")
        sample_length_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        sample_length_layout.addWidget(sample_length_label)

        sample_length_string = f"{sample_size:.1f} s"
        sample_length = QtWidgets.QLabel(sample_length_string)
        sample_length.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        sample_length_layout.addWidget(sample_length)

        control_layout.addLayout(sample_length_layout)

        # .....
        # Frame rate
        framerate_layout = QtWidgets.QHBoxLayout()

        framerate_label = QtWidgets.QLabel("FrameRate")
        framerate_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        framerate_layout.addWidget(framerate_label)

        self.framerate = QtWidgets.QLabel("0")
        self.framerate.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        framerate_layout.addWidget(self.framerate)

        control_layout.addLayout(framerate_layout)

        # .....
        # Audio sample time
        sampletime_layout = QtWidgets.QHBoxLayout()

        sampletime_label = QtWidgets.QLabel("Sample time")
        sampletime_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        sampletime_layout.addWidget(sampletime_label)

        self.sampletime = QtWidgets.QLabel("0")
        self.sampletime.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        sampletime_layout.addWidget(self.sampletime)

        control_layout.addLayout(sampletime_layout)

        # .....
        # Processing time
        processing_layout = QtWidgets.QHBoxLayout()

        processing_label = QtWidgets.QLabel("Processing time")
        processing_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        processing_layout.addWidget(processing_label)

        self.processingtime = QtWidgets.QLabel("0")
        self.processingtime.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        processing_layout.addWidget(self.processingtime)

        control_layout.addLayout(processing_layout)

        # .....
        # Stretch space to support windo resize
        control_layout.addStretch()

        # .....
        # Minimum frequency for peak results
        min_layout = QtWidgets.QHBoxLayout()
        min_label = QtWidgets.QLabel("Start Freq (Hz)")
        min_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        min_layout.addWidget(min_label)

        self.min_spin = QtWidgets.QSpinBox()
        self.min_spin.setMinimum(0)
        self.min_spin.setMaximum(22050)
        self.min_spin.setValue(f_range["f_min"])
        self.min_spin.setToolTip("The lowest frequency for which peaks are reported")

        min_layout.addWidget(self.min_spin)

        control_layout.addLayout(min_layout)

        # .....
        # Maximum frequency for peak results
        max_layout = QtWidgets.QHBoxLayout()
        max_label = QtWidgets.QLabel("Stop Freq (Hz)")
        max_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        max_layout.addWidget(max_label)

        self.max_spin = QtWidgets.QSpinBox()
        self.max_spin.setMinimum(0)
        self.max_spin.setMaximum(22050)
        self.max_spin.setValue(f_range["f_max"])
        self.max_spin.setToolTip("The highest frequency for which peaks are reported")

        max_layout.addWidget(self.max_spin)

        control_layout.addLayout(max_layout)

        # .....
        # Add devices button to display default devices and known devices
        self.show_devices = QtWidgets.QPushButton("Input Devices")
        self.show_devices.setToolTip("Display the default and all devices")

        control_layout.addWidget(self.show_devices)

        # .....
        # Add space at the bottom
        control_layout.addSpacing(40)

        self.setLayout(control_layout)

    def set_framerate(
        self, framerate: float, sampletime: float, processingtime: float
    ) -> None:
        # print("PeakControls: set_framerate")
        """Update the status display for frame rate, sample time, and
        processing time.
        """
        self.framerate.setText(f"{framerate:.1f} fps")
        self.sampletime.setText(f"{sampletime:.1f} s")
        self.processingtime.setText(f"{processingtime*1000:.1f} ms")

    def set_avg_enable(self, state: bool) -> None:
        # print("PeakControls: set_avg_enable")
        """Change the icon color and also change the fft_plot
        to do averaging or not.
        """
        if state:
            self.avg_enable.setIcon(gt_i.GtImages.green_button_icon())
            # Now enable the items
            self.avg_restart.setEnabled(True)

        else:
            self.avg_enable.setIcon(gt_i.GtImages.red_button_icon())
            # Now disable the items
            self.avg_restart.setEnabled(False)

    def set_hold_results(self, state: bool) -> None:
        """Change the icon color and also change the fft_plot
        to do peak holding or not to do peak holding.
        """
        # print(f"PeakControls: set_hold_results: state: {state}")
        if state:
            self.hold_results.setIcon(gt_i.GtImages.green_button_icon())
            # Save current state of avg_enable
            # and disable it
            self.avg_enable_saved = self.avg_enable.isChecked()
            self.set_avg_enable(False)
            self.avg_enable.setEnabled(False)

            if self.avg_enable.isChecked():
                self.avg_restart.setEnabled(True)
            else:
                self.avg_restart.setEnabled(False)
        else:
            self.hold_results.setIcon(gt_i.GtImages.red_button_icon())
            # Save current state of avg_enable
            # and enable it
            # restore current state of avg_enable
            self.avg_enable.setEnabled(True)

    def reset_averaging(self) -> None:
        """Reset the controls restart averaging"""
        self.set_avg_completed(0)
        self.avg_done.setPixmap(gt_i.GtImages.red_pixmap())
        if self.hold_results.isChecked():
            self.hold_results.click()

    def set_avg_completed(self, count: int) -> None:
        # print("PeakControls: set_avg_completed")
        """Check the count to see if the maximum number of averages has been reached.
        If it has then disable the appropriate controls, set the LED red otherwise
        enable the controls, set the LED green, and set hold results.
        """
        self.avg_completed.setText(str(count))
        if count >= self.num_averages.value():
            # Change the LED to Green
            self.avg_done.setPixmap(gt_i.GtImages.green_pixmap())

            self.num_averages.setEnabled(True)

            self.hold_results.click()

            # Eable the restart after holding the results (hold_results sets the
            # restart to disabled)
            self.avg_restart.setEnabled(True)
        else:
            self.num_averages.setEnabled(False)
            self.avg_restart.setEnabled(False)
            self.avg_enable.setEnabled(False)
