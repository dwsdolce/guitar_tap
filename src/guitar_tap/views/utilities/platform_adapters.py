# @parity view/platform-adapters
"""
Platform-specific helpers. Mirrors Swift's PlatformAdapters.swift.

Windows: NamedMutex single-instance guard lives in named_mutex.py at the
    project root (entry-point concern, imported only from guitar_tap.py).
"""

import platform
import subprocess

from PySide6 import QtCore, QtGui

# The macOS microphone privacy pane. The legacy preference: scheme first — the newer .extension URL
# can route to the wrong pane on non-administrator accounts. As Swift's alert.
_MAC_MICROPHONE_SETTINGS = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Microphone",
)
_WINDOWS_MICROPHONE_SETTINGS = "ms-settings:privacy-microphone"


def microphone_settings_path() -> str:
    """Where the user grants the microphone, in the words of this platform's settings."""
    if platform.system() == "Windows":
        return "Settings → Privacy & security → Microphone"
    return "System Settings → Privacy & Security → Microphone"


def can_open_microphone_settings() -> bool:
    """Whether this platform has a microphone setting to open (macOS, Windows)."""
    return platform.system() in ("Darwin", "Windows")


def open_microphone_settings() -> None:
    """Open the system's microphone privacy setting."""
    system = platform.system()
    if system == "Darwin":
        for url in _MAC_MICROPHONE_SETTINGS:
            if subprocess.run(["open", url], check=False).returncode == 0:
                return
    elif system == "Windows":
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(_WINDOWS_MICROPHONE_SETTINGS))
