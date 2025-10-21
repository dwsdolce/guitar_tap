"""
    Check if we are authorized for the microphone and request it if not.
    This requires the application to be correctly signed.
"""

import sys
import time

import AVFoundation
from PyQt6 import QtWidgets


# pylint: disable=too-few-public-methods
class MacAccess:
    """Use MacOS AVFoundation to check and request access to the microphone."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.access = False
        self.access_set = False

        # If Mac we need to check if we are authorized to access the
        # microphone and request it if not
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

                # Now wait until self.acces is set true or false
                while not self.access_set:
                    time.sleep(1)

                if not self.access:
                    msg_box = QtWidgets.QMessageBox(parent)
                    msg_box.setWindowTitle("Microphone Access")
                    msg_box.setText(
                        "Microphone access has been denied.\nIt is required to be able to\
                            access the microphone to run this program.\nPlease reset the\
                            Microphone access in Settings & Privacy -> Security -> Guitar Tap."
                    )
                    msg_box.exec()
                    sys.exit()
            case AVFoundation.AVAuthorizationStatusDenied:
                msg_box = QtWidgets.QMessageBox(parent)
                msg_box.setWindowTitle("Microphone Access")
                msg_box.setText(
                    "Microphone access has been denied.\nIt is required to be\
                            able to access the microphone to run this program.\nPlease reset the\
                            Microphone access in Settings & Privacy -> Security -> Guitar Tap."
                )
                msg_box.exec()
                sys.exit()
            case AVFoundation.AVAuthorizationStatusRestricted:
                msg_box = QtWidgets.QMessageBox(parent)
                msg_box.setWindowTitle("Microphone Access Restricted")
                msg_box.setText(
                    "Microphone access is restricted.\nYou are not able to run this program."
                )
                msg_box.exec()
                sys.exit()
            case _:
                print("Unknown value")
                msg_box.setText("Unknown value")
                msg_box = QtWidgets.QMessageBox(parent)
                msg_box.setWindowTitle("Microphone Access Restricted")
                msg_box.setText("Unknown error. Please contact the developer.")
                msg_box.exec()
                sys.exit()

    def callback(self, state) -> None:
        """Used to wait for the user to respond to request to access the microphone."""
        self.access_set = True
        self.access = state
