"""
    Dialog displaying the current attached devices
"""

import os
import platform

# import pyaudio
if platform.system() == "Windows":
    import pyaudiowpatch as pyaudio
else:
    import pyaudio
from PyQt6 import QtWidgets

basedir = os.path.dirname(__file__)


class ShowInputDevices(QtWidgets.QDialog):
    """Dialog containing the table of devices"""

    def __init__(self, py_audio: pyaudio.PyAudio) -> None:
        super().__init__()
        self.setWindowTitle("Input Devices")
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

    def add_device(
        self, default: str, row_index: int, values, supported_rates: list[int]
    ) -> None:
        """Add a device to the table includeing wether the device is a default device or not"""
        self.device_table.setItem(row_index, 0, QtWidgets.QTableWidgetItem(default))
        column = 1
        for value in values:
            self.device_table.setItem(
                row_index, column, QtWidgets.QTableWidgetItem(str(value))
            )
            column += 1
        self.device_table.setItem(
            row_index, column, QtWidgets.QTableWidgetItem(str(supported_rates))
        )

    def create_device_table(self, py_audio: pyaudio.PyAudio) -> None:
        """The device table shows the pyaudio settings for each device and indicates
        which devices are the default
        """
        self.device_table = QtWidgets.QTableWidget()

        default_input = py_audio.get_default_input_device_info()
        default_input_index = default_input.get("index")

        # Get the host APIs
        host_apis = []
        for i in range(py_audio.get_host_api_count()):
            host_api = py_audio.get_host_api_info_by_index(i)
            host_apis.append(host_api["name"])

        # Get lits of input devices
        input_devices = []
        for index in range(py_audio.get_device_count()):
            device = py_audio.get_device_info_by_index(index)
            if device["maxInputChannels"] > 0:
                input_devices.append(device)

        # Row count
        number_devices = len(input_devices)
        self.device_table.setRowCount(number_devices)

        # Column count
        keys = default_input.keys()
        desired_keys = []
        for key in keys:
            if "Output" not in key:
                desired_keys.append(key)
        print(desired_keys)
        number_keys = len(desired_keys)
        # The count is the number of devices plus the default column and the supported rates
        self.device_table.setColumnCount(number_keys + 2)

        # Add header
        header = [""] + list(desired_keys) + ["Supported Rates"]
        self.device_table.setHorizontalHeaderLabels(header)

        row_index = 0
        for device in input_devices:
            index = device["index"]
            device["hostApi"] = host_apis[device["hostApi"]]
            desired_device_values = [device[x] for x in desired_keys]
            if index == default_input_index:
                default = "default"
            else:
                default = ""
            default_sample_rate = device["defaultSampleRate"]
            supported_rates = self.get_supported_rates(
                py_audio, index, default_sample_rate
            )
            self.add_device(default, row_index, desired_device_values, supported_rates)
            row_index += 1

        self.device_table.resizeColumnsToContents()
        self.device_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )

    def get_supported_rates(
        self, py_audio: pyaudio.PyAudio, index: int, default_sample_rate: int
    ) -> list[int]:
        """Get the supported sample rates for the input devices"""
        supported_rates = []
        for rate in [
            default_sample_rate,
            default_sample_rate // 2,
            default_sample_rate // 4,
        ]:
            try:
                is_supported = py_audio.is_format_supported(
                    rate, index, 1, pyaudio.paFloat32
                )
                if is_supported:
                    supported_rates.append(rate)
            except ValueError as e:
                print(f"Error checking rate {rate} for device {index}: {e}")

        return supported_rates
