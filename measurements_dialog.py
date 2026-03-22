"""
    Dialog for listing, loading, and deleting saved measurements.
"""

import os

from PyQt6 import QtWidgets, QtCore

import measurement as M


class MeasurementsDialog(QtWidgets.QDialog):
    """Show a list of saved measurements; allow load and delete."""

    measurementSelected: QtCore.pyqtSignal = QtCore.pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Saved Measurements")
        self.resize(520, 340)
        self._paths: list[str] = []

        layout = QtWidgets.QVBoxLayout(self)

        self._list = QtWidgets.QListWidget()
        self._list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        layout.addWidget(self._list)

        btn_layout = QtWidgets.QHBoxLayout()
        self._load_btn = QtWidgets.QPushButton("Load")
        self._delete_btn = QtWidgets.QPushButton("Delete")
        self._import_btn = QtWidgets.QPushButton("Import…")
        close_btn = QtWidgets.QPushButton("Close")

        btn_layout.addWidget(self._load_btn)
        btn_layout.addWidget(self._delete_btn)
        btn_layout.addWidget(self._import_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._load_btn.clicked.connect(self._on_load)
        self._delete_btn.clicked.connect(self._on_delete)
        self._import_btn.clicked.connect(self._on_import)
        close_btn.clicked.connect(self.accept)
        self._list.itemDoubleClicked.connect(self._on_load)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        self._paths = M.list_measurements()
        for path in self._paths:
            try:
                m = M.load_measurement(path)
                label = (
                    f"{m.display_name()}  —  {m.guitar_type}  —  "
                    f"{os.path.basename(path)}"
                )
            except Exception:  # noqa: BLE001
                label = os.path.basename(path)
            self._list.addItem(label)

        no_items = len(self._paths) == 0
        self._load_btn.setEnabled(not no_items)
        self._delete_btn.setEnabled(not no_items)

    def _selected_path(self) -> str | None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._paths):
            return None
        return self._paths[row]

    def _on_load(self, _=None) -> None:
        path = self._selected_path()
        if not path:
            return
        try:
            m = M.load_measurement(path)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Load Error", f"Could not load measurement:\n{exc}"
            )
            return
        self.measurementSelected.emit(m)
        self.accept()

    def _on_delete(self) -> None:
        path = self._selected_path()
        if not path:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Measurement",
            f"Delete {os.path.basename(path)}?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                os.remove(path)
            except OSError as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Delete Error", f"Could not delete:\n{exc}"
                )
            self._refresh()

    def _on_import(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import Measurement",
            os.path.expanduser("~"),
            "Measurement files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            m = M.load_measurement(path)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Import Error", f"Could not load measurement:\n{exc}"
            )
            return
        self.measurementSelected.emit(m)
        self.accept()
