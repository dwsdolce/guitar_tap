# @parity none — Python's Settings dialog sets its details labels itself, so they must be refreshed
# when the picker changes; Swift's and the web's views are bound to the active calibration. The
# details' text is shared: CD1–CD2 (test/calibration).
"""
Settings: the active calibration's details follow the Calibration picker while the dialog is open.

The details (sensitivity, data points, frequency range) were filled in once, when Settings was built,
so choosing None left the old calibration's details showing, and choosing one showed nothing, until
Settings was opened again. Swift shows them from ``fftAnalyzer.activeCalibration``, so they follow
every change; Python now shows them from the model's active calibration the same way.
"""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from guitar_tap.models import microphone_calibration as mc
from tests.test_export_e2e import edges, window  # noqa: F401 — fixtures

CAL_FILE = Path(__file__).parent / "7108913.txt"


def _details(dlg: QtWidgets.QWidget) -> tuple[bool, str]:
    """Whether the details are shown, and their data-points line."""
    labels = [lbl for lbl in dlg.findChildren(QtWidgets.QLabel) if lbl.text().startswith("Data points:")]
    if not labels:
        return False, ""
    return labels[0].parentWidget().isVisibleTo(dlg), labels[0].text()


def test_details_follow_the_calibration_picker(qtbot, window):  # noqa: F811
    cal = mc.MicrophoneCalibration.from_path(str(CAL_FILE))
    mc.CalibrationStorage.save(cal)
    window.fft_canvas.choose_calibration(cal)
    seen: dict[str, tuple[bool, str]] = {}

    def in_settings() -> None:
        dlg = QtWidgets.QApplication.activeModalWidget()
        if dlg is None:
            QtCore.QTimer.singleShot(20, in_settings)
            return
        combo = next(c for c in dlg.findChildren(QtWidgets.QComboBox)
                     if c.count() and c.itemText(0) == "None (Uncalibrated)")
        seen["opened"] = _details(dlg)
        combo.setCurrentIndex(0)                       # None
        seen["none"] = _details(dlg)
        # By equality, as the view does: Qt's findData matches a Python object only by identity.
        combo.setCurrentIndex(next(i for i in range(combo.count()) if combo.itemData(i) == cal.id))  # the calibration again
        seen["chosen"] = _details(dlg)
        dlg.reject()

    QtCore.QTimer.singleShot(0, in_settings)
    window._show_settings()

    points = f"Data points: {len(cal.correction_points)}"
    assert seen["opened"] == (True, points), seen
    assert seen["none"][0] is False, f"choosing None must hide the details: {seen}"
    assert seen["chosen"] == (True, points), f"choosing the calibration must show its details: {seen}"
