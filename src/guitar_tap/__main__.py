"""
Guitar Tap — application entry point.

All application logic lives in views/tap_tone_analysis_view.py.
This file only contains the launcher code.
"""

import os
import sys
import traceback

# Catch C-level crashes (segfaults, abort, illegal instruction) and dump a
# stack trace for ALL threads.  Without this, Qt/PySide6 segfaults disappear
# silently and the app exits with no output.  Must be enabled before any
# heavy imports so it's already armed when the crash happens.
#
# Output target: prefer sys.stderr when it's available (developer/console
# runs).  In a pyinstaller windowed build on Windows, sys.stderr is None
# because there is no console attached — passing None to faulthandler.enable
# raises RuntimeError before anything else runs.  In that case open a log
# file under the same directory as the crash log so a C-level crash leaves
# a diagnosable trace.
import faulthandler

def _faulthandler_target():
    """Return a writable file object for faulthandler output.

    sys.stderr in the developer/console case; a fresh log file under the
    user's app-data directory in the pyinstaller-windowed case where stderr
    has been detached.
    """
    if sys.stderr is not None:
        return sys.stderr
    # Mirror _crash_log_path() layout but use a separate filename so the
    # C-crash trace doesn't overwrite the Python-exception crash log.
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        path = os.path.join(base, "guitar-tap", "faulthandler.log")
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Logs/GuitarTap/faulthandler.log")
    else:
        path = os.path.expanduser("~/.local/share/GuitarTap/faulthandler.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return open(path, "w", encoding="utf-8", buffering=1)
    except OSError:
        return None

_fh_target = _faulthandler_target()
if _fh_target is not None:
    faulthandler.enable(file=_fh_target, all_threads=True)

# Register SIGUSR1 to dump all thread stacks on demand.  Qt/PySide6 blocks
# SIGINT on the main thread so Ctrl+C doesn't work when the app is hung.
# Use `kill -USR1 <pid>` from a terminal to get a thread dump.
if sys.platform != "win32" and _fh_target is not None:
    import signal
    faulthandler.register(signal.SIGUSR1, file=_fh_target, all_threads=True)

# Ensure models/ and views/ are importable as top-level packages when running
# as `python -m guitar_tap`. __file__ is src/guitar_tap/__main__.py so
# os.path.dirname(__file__) is src/guitar_tap/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6 import QtGui, QtWidgets
from views.tap_tone_analysis_view import MainWindow, basedir

if os.name == "nt":
    from ctypes import windll

    import named_mutex as NM
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


if __name__ == "__main__":
    # _redirect_logs_if_needed()

    if os.name == "nt":
        mutex = NM.NamedMutex("guitar-tap-running", True)

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
        app.apply_saved_geometry()
        app.activateWindow()
        app.raise_()
        qapp.exec()
    except Exception:
        _show_crash_dialog(*sys.exc_info())
        sys.exit(1)
