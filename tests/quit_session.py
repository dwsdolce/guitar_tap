# @parity none — the driver for test_quit's PySide teardown check; Swift and the web have no equivalent.
"""Run the app (``python -m guitar_tap``) through a session, then close its window as the close button does.

Usage: python tests/quit_session.py [steps]   — steps, comma-separated: metrics, measurements, settings.

Each step opens its window and closes it again, as a user does: the metrics panel (deleted when closed), Saved
Measurements and Settings (hidden when closed, and kept). Then the main window is closed and the app's own exit
sequence runs, so the process's exit code is the app's.
"""

import runpy
import sys

from PySide6 import QtCore, QtWidgets

import guitar_tap.views.tap_tone_analysis_view as TV

_STEP_MS = 2500
_steps = [s for s in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if s]
del sys.argv[1:]
_show = TV.MainWindow.show


def _close_modal_soon() -> None:
    """Close the modal window once it is open — the window a step's call opens and waits on."""
    def close() -> None:
        modal = QtWidgets.QApplication.activeModalWidget()
        if modal is not None:
            modal.reject()
        else:
            QtCore.QTimer.singleShot(200, close)
    QtCore.QTimer.singleShot(800, close)


def _close_metrics(window: TV.MainWindow) -> None:
    if window._metrics_dialog is not None:
        window._metrics_dialog.close()


def _show_and_run_session(window: TV.MainWindow) -> None:
    _show(window)
    at = 1500
    for step in _steps:
        if step == "metrics":
            QtCore.QTimer.singleShot(at, window._show_metrics)
            QtCore.QTimer.singleShot(at + 1500, lambda: _close_metrics(window))
        elif step == "measurements":
            QtCore.QTimer.singleShot(at, lambda: (_close_modal_soon(), window._on_open_measurements()))
        elif step == "settings":
            QtCore.QTimer.singleShot(at, lambda: (_close_modal_soon(), window._show_settings()))
        else:
            raise SystemExit(f"Unknown step: {step}")
        at += _STEP_MS
    QtCore.QTimer.singleShot(at, window.close)


TV.MainWindow.show = _show_and_run_session
runpy.run_module("guitar_tap", run_name="__main__")
