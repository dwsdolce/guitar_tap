"""
    Dialog displaying the current attached input devices, allowing the user
    to select one as the active recording device.
"""

import os

import sounddevice as sd
from PyQt6 import QtWidgets

basedir = os.path.dirname(__file__)


class ShowInputDevices(QtWidgets.QDialog):
    """Dialog containing the table of input devices.

    After exec(), call selected_device_index() to get the chosen device
    index, or -1 if the user cancelled or made no selection.
    """

    def __init__(self, current_device_index: int = -1) -> None:
        super().__init__()
        self.setWindowTitle("Input Devices")
        self.setMinimumWidth(800)
        self.setMinimumHeight(300)

        self._device_indices: list[int] = []
        self._selected_index: int = -1

        buttons = (
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box = QtWidgets.QDialogButtonBox(buttons)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        self._device_table = self._create_device_table(current_device_index)
        layout.addWidget(self._device_table)
        layout.addWidget(button_box)
        self.setLayout(layout)

    # ------------------------------------------------------------------ #

    def selected_device_index(self) -> int:
        """Return the sounddevice index of the row the user selected, or -1."""
        return self._selected_index

    def _on_accept(self) -> None:
        rows = self._device_table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            if 0 <= row < len(self._device_indices):
                self._selected_index = self._device_indices[row]
        self.accept()

    # ------------------------------------------------------------------ #

    def _create_device_table(self, current_device_index: int) -> QtWidgets.QTableWidget:
        default_input = sd.query_devices(device=sd.default.device, kind="input")
        default_input_index = default_input.get("index")

        host_apis = [h["name"] for h in sd.query_hostapis()]

        input_devices = [d for d in sd.query_devices() if d["max_input_channels"] > 0]

        desired_keys = [k for k in default_input.keys() if "output" not in k.lower()]

        table = QtWidgets.QTableWidget()
        table.setRowCount(len(input_devices))
        table.setColumnCount(len(desired_keys) + 2)   # default marker + keys + supported rates
        table.setHorizontalHeaderLabels([""] + list(desired_keys) + ["Supported Rates"])
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        current_row = -1
        for row, device in enumerate(input_devices):
            idx = device["index"]
            self._device_indices.append(idx)

            marker = "default" if idx == default_input_index else ""
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(marker))

            for col, key in enumerate(desired_keys, start=1):
                value = device[key]
                if key == "hostapi":
                    value = host_apis[value]
                table.setItem(row, col, QtWidgets.QTableWidgetItem(str(value)))

            rates = self._get_supported_rates(idx, device["default_samplerate"])
            table.setItem(row, len(desired_keys) + 1, QtWidgets.QTableWidgetItem(str(rates)))

            if idx == current_device_index:
                current_row = row

        table.resizeColumnsToContents()

        if current_row >= 0:
            table.selectRow(current_row)

        return table

    @staticmethod
    def _get_supported_rates(index: int, default_sample_rate: float) -> list[int]:
        rates: list[int] = []
        for rate in [default_sample_rate, default_sample_rate / 2, default_sample_rate / 4]:
            try:
                sd.check_input_settings(device=index, channels=1, samplerate=rate, dtype="float32")
                rates.append(int(rate))
            except sd.PortAudioError:
                continue
        return rates
