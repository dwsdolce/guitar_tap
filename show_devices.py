"""
    Dialog displaying the current attached devices
"""
import os

import pyaudio
from PyQt6 import QtWidgets

basedir = os.path.dirname(__file__)

class ShowDevices(QtWidgets.QDialog):
    """ Dialog containing the table of devices """
    def __init__(self, py_audio: pyaudio.PyAudio) -> None:
        super().__init__()
        self.setWindowTitle("Devices")
        self.setMinimumWidth(800)
        self.setMinimumHeight(300)

        button = QtWidgets.QDialogButtonBox.StandardButton.Ok
        button_box = QtWidgets.QDialogButtonBox(button)
        button_box.clicked.connect(self.accept)

        self.layout = QtWidgets.QVBoxLayout()

        self.create_device_table(py_audio)
        self.layout.addWidget(self.device_table)

        self.layout.addWidget(button_box)
        self.setLayout(self.layout)

    def add_device(self, default: str, index: int, values) -> None:
        """ Add a device to the table includeing wether the device is a default device or not """
        self.device_table.setItem(index, 0, QtWidgets.QTableWidgetItem(default))
        column = 1
        for value in values:
            self.device_table.setItem(index, column, QtWidgets.QTableWidgetItem(str(value)))
            column += 1

    def create_device_table(self, py_audio: pyaudio.PyAudio) -> None:
        """ The device table shows the pyaudio settings for each device and indicates
            which devices are the default
        """
        self.device_table = QtWidgets.QTableWidget()

        default_input = py_audio.get_default_input_device_info()
        default_input_index = default_input.get("index")
        default_output = py_audio.get_default_output_device_info()
        default_output_index = default_output.get("index")

        # Row count
        number_devices = py_audio.get_device_count()
        self.device_table.setRowCount(number_devices + 1)

        # Column count
        keys = default_input.keys()
        number_keys = len(keys)
        self.device_table.setColumnCount(number_keys + 1)

        # Add header
        header = [''] + list(keys)
        self.device_table.setHorizontalHeaderLabels(header)

        for index in range(py_audio.get_device_count()):
            device = py_audio.get_device_info_by_index(index)
            device_values = device.values()
            if index in (default_input_index, default_output_index):
                default = 'default'
            else:
                default = ''
            self.add_device(default, index, device_values)

        # Resize the columns to match the contents
        self.device_table.resizeColumnsToContents()
        self.device_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
