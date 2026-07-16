# @parity model/wav-dump-folder tests=test/wav-dump-folder
"""Where 'Dump Capture Audio' saves its per-measurement session WAVs.

See FILE-PATHS-AND-NAMES-SPEC.md §4b / §6. Mirrors Swift ``WavDumpFolder`` — same interface and
method names.

**Default** = the OS Documents folder + ``GuitarTap`` (via ``QStandardPaths``, so a OneDrive-
redirected Documents on Windows and a Linux XDG ``user-dirs`` Documents are honoured — this replaces
the old hardcoded ``~/Documents``). On any platform the user may *Change…* to a custom folder.

**Storage differs from Swift by necessity:** Swift is sandboxed and persists the grant as a
security-scoped bookmark; Python is **not** sandboxed, so the custom folder is stored as a plain
path. The interface is identical.

The debug log deliberately does **not** use this — it stays in the app's Documents (§4c).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6 import QtCore

# Custom-folder path key. Swift: UserDefaults "GuitarTap.wavDumpFolderBookmark" (a bookmark);
# here a plain path string.
_FOLDER_KEY = "dump/folder"
_ORG = "Dolcesfogato"
_APP = "guitar_tap"


def _settings() -> QtCore.QSettings:
    # Mirror AppSettings: redirect to an isolated suite under pytest so tests never touch real prefs.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return QtCore.QSettings(f"{_ORG}.tests", _APP)
    return QtCore.QSettings(_ORG, _APP)


class WavDumpFolder:
    """Static helpers for the WAV-dump folder. Mirrors Swift ``enum WavDumpFolder``."""

    @staticmethod
    def default_folder() -> Path:
        """The OS Documents folder + ``GuitarTap`` (always creatable / writable)."""
        docs = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.DocumentsLocation
        )
        base = Path(docs) if docs else Path.home() / "Documents"
        return base / "GuitarTap"

    @staticmethod
    def has_custom_folder() -> bool:
        """Whether the user has chosen a custom folder (an override path is stored)."""
        return bool(_settings().value(_FOLDER_KEY))

    @staticmethod
    def _custom_folder() -> "Path | None":
        """The stored custom folder, or None. (Swift resolves a bookmark here; Python reads a path.)"""
        v = _settings().value(_FOLDER_KEY)
        return Path(str(v)) if v else None

    @staticmethod
    def current_folder() -> Path:
        """The folder in effect, for **display**: the custom folder if set, else the default."""
        return WavDumpFolder._custom_folder() or WavDumpFolder.default_folder()

    @staticmethod
    def acquire_dump_folder():
        """Return ``(folder, release)`` — the folder to write into and a cleanup callable — or
        ``None`` to **skip** the write (a custom folder is set but no longer at its chosen path).

        Mirrors Swift ``acquireDumpFolder``. Python is not sandboxed, so there is no security scope
        to hold: ``release`` is a no-op. The arm-time ``is_reachable`` check gates arming, so ``None``
        is defensive; a folder that vanished mid-measurement is skipped, never silently redirected to
        the default. No custom folder → the default.
        """
        custom = WavDumpFolder._custom_folder()
        if custom is not None:
            if not custom.is_dir():
                return None
            return custom, (lambda: None)
        return WavDumpFolder.default_folder(), (lambda: None)

    @staticmethod
    def is_reachable() -> bool:
        """Whether the configured dump folder can be written to **right now** — checked at New Tap /
        launch auto-arm when Dump Capture Audio is on (§4b decision 1b). The default is always
        creatable; a custom folder must still be **at its chosen path** — a rename / move / delete
        makes it unreachable (Python stores a plain path, so the folder-must-be-where-you-put-it
        rule is inherent), and the user must Change Location or Turn Off Saving. Do NOT create the
        custom folder here — recreating a renamed-away path would defeat the check.
        """
        custom = WavDumpFolder._custom_folder()
        if custom is None:
            return True
        return custom.is_dir()

    @staticmethod
    def choose_folder(parent=None) -> bool:
        """Present a directory picker; store the chosen path. Returns True if a folder was chosen.
        Opens at the current folder. Mirrors Swift ``chooseFolder`` (NSOpenPanel)."""
        from PySide6 import QtWidgets

        start = str(WavDumpFolder.current_folder())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            parent, "Choose the folder Guitar Tap saves captured audio (WAV files) to", start
        )
        if not chosen:
            return False
        _settings().setValue(_FOLDER_KEY, chosen)
        return True

    @staticmethod
    def use_default_folder() -> None:
        """Forget the custom folder — revert to the default. Mirrors Swift ``useDefaultFolder``."""
        _settings().remove(_FOLDER_KEY)

    @staticmethod
    def reveal_in_finder() -> None:
        """Open the current dump folder in the OS file browser. Mirrors Swift ``revealInFinder``."""
        from PySide6 import QtGui

        folder = WavDumpFolder.current_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))