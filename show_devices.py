"""
    Dialog displaying the current attached devices
"""

import os

import sounddevice as sd
from PyQt6 import QtWidgets

basedir = os.path.dirname(__file__)


class ShowInputDevices(QtWidgets.QDialog):
    """Dialog containing the table of devices"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Input Devices")
        self.setMinimumWidth(800)
        self.setMinimumHeight(300)

        button = QtWidgets.QDialogButtonBox.StandardButton.Ok
        button_box = QtWidgets.QDialogButtonBox(button)
        button_box.clicked.connect(self.accept)

        self.layout = QtWidgets.QVBoxLayout()

        self.create_device_table()
        self.layout.addWidget(self.device_table)

        self.layout.addWidget(button_box)
        self.setLayout(self.layout)

    def add_device(
        self, default: str, row_index: int, values, supported_rates: list[int]
    ) -> None:
        """Add a device to the table includeing wether the device is a default device or not"""
        self.device_table.setItem(
            row_index, 0, QtWidgets.QTableWidgetItem(default))
        column = 1
        for value in values:
            self.device_table.setItem(
                row_index, column, QtWidgets.QTableWidgetItem(str(value))
            )
            column += 1
        self.device_table.setItem(
            row_index, column, QtWidgets.QTableWidgetItem(str(supported_rates))
        )

    def create_device_table(self) -> None:
        """The device table shows the sounddevice settings for each device and indicates
        which devices are the default
        """
        self.device_table = QtWidgets.QTableWidget()

        default_input = sd.query_devices(device=sd.default.device, kind='input')
        default_input_index = default_input.get("index")

        # Get the host APIs
        host_apis = []
        for host_api in sd.query_hostapis():
            host_apis.append(host_api["name"])

        # for i in range(py_audio.get_host_api_count()):
        #     host_api = py_audio.get_host_api_info_by_index(i)
        #     host_apis.append(host_api["name"])

        # Get lits of input devices
        input_devices = []
        for device in sd.query_devices():
            if device["max_input_channels"] > 0:
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
        number_keys = len(desired_keys)
        # The count is the number of devices plus the default column and the supported rates
        self.device_table.setColumnCount(number_keys + 2)

        # Add header
        header = [""] + list(desired_keys) + ["Supported Rates"]
        self.device_table.setHorizontalHeaderLabels(header)

        row_index = 0
        for device in input_devices:
            index = device["index"]
            desired_device_values = [device[x] for x in desired_keys]
            host_api_key = desired_keys.index("hostapi")
            desired_device_values[host_api_key] = host_apis[device["hostapi"]]

            if index == default_input_index:
                default = "default"
            else:
                default = ""
            default_sample_rate = device["default_samplerate"]
            supported_rates = self.get_supported_rates(
                index, default_sample_rate
            )
            self.add_device(default, row_index,
                            desired_device_values, supported_rates)
            row_index += 1

        self.device_table.resizeColumnsToContents()
        self.device_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )

    def get_supported_rates(
        self, index: int, default_sample_rate: int
    ) -> list[int]:
        """Get the supported sample rates for the input devices"""
        supported_rates = []
        for rate in [
            default_sample_rate,
            default_sample_rate // 2,
            default_sample_rate // 4,
        ]:
            try:
                sd.check_input_settings(
                    device=index, channels=1, samplerate=rate, dtype='float32')
                supported_rates.append(rate)
            except sd.PortAudioError as _e:
                # print(
                    # f"Sample rate {rate} for device {index} not supported: {e}")
                continue

        return supported_rates
