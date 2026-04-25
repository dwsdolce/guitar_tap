"""
Guitar Tap — application entry point.

All application logic lives in views/tap_tone_analysis_view.py.
This file only contains the launcher code.
"""

import sys
import os
import traceback

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


def _crash_log_path() -> str:
    """Return a platform-appropriate path for the crash log.

      Windows : %APPDATA%\\guitar-tap\\crash.log
      macOS   : ~/Library/Logs/GuitarTap/crash.log
      Linux   : ~/.local/share/GuitarTap/crash.log
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "guitar-tap", "crash.log")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/GuitarTap/crash.log")
    else:
        return os.path.expanduser("~/.local/share/GuitarTap/crash.log")


def _write_crash_log(exc_type, exc_value, exc_tb) -> str:
    """Write a crash log and return the log path."""
    log_path = _crash_log_path()
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Guitar Tap crash report\n")
            f.write("=" * 60 + "\n\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except OSError:
        pass
    return log_path


def _show_crash_dialog(exc_type, exc_value, exc_tb) -> None:
    """Show a user-facing error dialog and write the crash log."""
    log_path = _write_crash_log(exc_type, exc_value, exc_tb)
    msg = QtWidgets.QMessageBox()
    msg.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    msg.setWindowTitle("Guitar Tap — Startup Error")
    msg.setText(
        f"Guitar Tap could not start.\n\n"
        f"{exc_type.__name__}: {exc_value}\n\n"
        f"A crash log has been saved to:\n{log_path}"
    )
    msg.exec()

def _debug_log_path() -> str:
    """Return a platform-appropriate path for the debug log.

      Windows : %APPDATA%\\guitar-tap\\GuitarTap-debug.log
      macOS   : ~/Library/Logs/GuitarTap/GuitarTap-debug.log
      Linux   : ~/.local/share/GuitarTap/GuitarTap-debug.log
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "guitar-tap", "GuitarTap-debug.log")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/GuitarTap/GuitarTap-debug.log")
    else:
        return os.path.expanduser("~/.local/share/GuitarTap/GuitarTap-debug.log")


def _redirect_logs_if_needed() -> None:
    # """Redirect stdout/stderr to a log file when not running under a debugger."""
    # if sys.gettrace() is not None:
    #     return
    # debug_env = (
    #     "VSCODE_PID", "PYTHONDEBUG", "PYCHARM_HOSTED", "DEBUGGER", "PYDEVD_USE_FRAME_EVAL"
    # )
    # if any(v in os.environ for v in debug_env):
    #     return
    log_path = _debug_log_path()
    log_dir = os.path.dirname(log_path)
    os.makedirs(log_dir, exist_ok=True)
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

    # Install an unhandled-exception hook so background thread crashes also
    # get logged rather than silently swallowed on Windows (console=False build).
    def _excepthook(exc_type, exc_value, exc_tb):
        _write_crash_log(exc_type, exc_value, exc_tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    try:
        app = MainWindow()
        app.setWindowIcon(QtGui.QIcon(os.path.join(basedir, "icons/guitar-tap.svg")))
        app.show()
        app.activateWindow()
        app.raise_()
        qapp.exec()
    except Exception:
        _show_crash_dialog(*sys.exc_info())
        sys.exit(1)
