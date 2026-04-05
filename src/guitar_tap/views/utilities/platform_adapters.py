"""
Platform-specific access helpers.

macOS: wraps AVFoundation mic permission checks and system-settings deep links.
Windows: NamedMutex single-instance guard lives in named_mutex.py at the
    project root (entry-point concern, imported only from guitar_tap.py).

Mirrors Swift's PlatformAdapters.swift.
"""

import subprocess
import sys

import AVFoundation
from PySide6 import QtCore, QtWidgets

_PRIV_URL = (
    "x-apple.systempreferences:"
    "com.apple.settings.PrivacySecurity.extension?Privacy_Microphone"
)

_DENIED_TEXT = (
    "Microphone access has been denied.\n\n"
    "Guitar Tap needs microphone access to operate.\n\n"
    "Open System Settings \u2192 Privacy \u0026 Security \u2192 Microphone "
    "and enable Guitar Tap, then relaunch the app."
)

_RESTRICTED_TEXT = (
    "Microphone access is restricted on this system.\n"
    "You are not able to run this program."
)


def _show_denied(parent: QtWidgets.QWidget) -> None:
    """Show the mic-denied dialog with a button to open System Settings."""
    msg_box = QtWidgets.QMessageBox(parent)
    msg_box.setWindowTitle("Microphone Access Denied")
    msg_box.setText(_DENIED_TEXT)
    open_btn = msg_box.addButton("Open System Settings", QtWidgets.QMessageBox.ButtonRole.ActionRole)
    msg_box.addButton(QtWidgets.QMessageBox.StandardButton.Close)
    msg_box.exec()
    if msg_box.clickedButton() is open_btn:
        subprocess.run(["open", _PRIV_URL], check=False)
    sys.exit()


# pylint: disable=too-few-public-methods
class MacAccess:
    """Use macOS AVFoundation to check and request access to the microphone."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.access = False
        self.access_set = False

        state = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )

        match state:
            case AVFoundation.AVAuthorizationStatusAuthorized:
                self.access = True

            case AVFoundation.AVAuthorizationStatusNotDetermined:
                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVFoundation.AVMediaTypeAudio, self.callback
                )
                # Poll without blocking the Qt event loop.
                loop = QtCore.QEventLoop()
                timer = QtCore.QTimer()
                timer.timeout.connect(lambda: loop.quit() if self.access_set else None)
                timer.start(100)
                loop.exec()
                timer.stop()

                if not self.access:
                    _show_denied(parent)

            case AVFoundation.AVAuthorizationStatusDenied:
                _show_denied(parent)

            case AVFoundation.AVAuthorizationStatusRestricted:
                msg_box = QtWidgets.QMessageBox(parent)
                msg_box.setWindowTitle("Microphone Access Restricted")
                msg_box.setText(_RESTRICTED_TEXT)
                msg_box.exec()
                sys.exit()

            case _:
                msg_box = QtWidgets.QMessageBox(parent)
                msg_box.setWindowTitle("Microphone Access")
                msg_box.setText("Unknown microphone authorization state. Please contact the developer.")
                msg_box.exec()
                sys.exit()

    def callback(self, granted: bool) -> None:
        """Called by AVFoundation (on a background thread) when the user responds."""
        self.access = granted
        self.access_set = True
