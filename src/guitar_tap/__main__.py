"""
Guitar Tap — application entry point.

All application logic lives in views/tap_tone_analysis_view.py.
This file only contains the launcher code.
"""

import sys
import os

# Ensure models/ and views/ are importable as top-level packages when running
# as `python -m guitar_tap`. __file__ is src/guitar_tap/__main__.py so
# os.path.dirname(__file__) is src/guitar_tap/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6 import QtWidgets, QtGui

from views.tap_tone_analysis_view import MainWindow, basedir

if os.name == "nt":
    import named_mutex as NM
    from ctypes import windll
    MY_APP_ID = "dolcesfogato.guitar-tap.guitar-tap.0.5"
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(MY_APP_ID)


def _redirect_logs_if_needed() -> None:
    """Redirect stdout/stderr to a log file when not running under a debugger."""
    if sys.gettrace() is not None:
        return
    debug_env = (
        "VSCODE_PID", "PYTHONDEBUG", "PYCHARM_HOSTED", "DEBUGGER", "PYDEVD_USE_FRAME_EVAL"
    )
    if any(v in os.environ for v in debug_env):
        return
    log_dir = os.path.expanduser("~/Library/Logs/GuitarTap")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "GuitarTap-debug.log")
    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: WPS515
        sys.stdout = log_file
        sys.stderr = log_file
    except OSError:
        pass


if __name__ == "__main__":
    _redirect_logs_if_needed()

    if os.name == "nt":
        mutex = NM.NamedMutex("guitar-tap-running", True)

    os.environ["QT_LOGGING_TO_CONSOLE"] = "1"
    qapp = QtWidgets.QApplication(sys.argv)

    app = MainWindow()
    app.setWindowIcon(QtGui.QIcon(os.path.join(basedir, "icons/guitar-tap.svg")))
    app.show()
    app.activateWindow()
    app.raise_()
    qapp.exec()
