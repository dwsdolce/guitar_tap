# @parity model/wav-dump-folder tests=test/wav-dump-folder
"""Where 'Dump Capture Audio' saves its per-measurement session WAVs.

Mirrors Swift ``WavDumpFolder`` — same interface and
method names.

**Default** = the OS Documents folder + ``GuitarTap`` (via ``QStandardPaths``, so a OneDrive-
redirected Documents on Windows and a Linux XDG ``user-dirs`` Documents are honoured). On any
platform the user may *Change…* to a custom folder.

**Storage differs from Swift by necessity:** Swift is sandboxed and persists the grant as a
security-scoped bookmark; Python is **not** sandboxed, so the custom folder is stored as a plain
path. The interface is identical.

The debug log deliberately does **not** use this — it stays in the app's Documents.
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
    # Mirror AppSettings: redirect to a PER-PROCESS isolated suite under pytest so tests never
    # touch real prefs — and never each other's (see models/settings_scope.py).
    from guitar_tap.models.settings_scope import settings_org  # noqa: PLC0415
    return QtCore.QSettings(settings_org(_ORG), _APP)


class WavDumpFolder:
    """Static helpers for the WAV-dump folder. Mirrors Swift ``enum WavDumpFolder``."""

    @staticmethod
    def default_folder() -> Path:
        """The OS Documents folder + ``GuitarTap`` (always creatable / writable). Under test, a
        per-process temp folder instead, like the measurements file — a test that turns dumps on never
        writes into the user's folder. Mirrors Swift ``defaultFolder``."""
        from guitar_tap.models.settings_scope import measurements_dir, sandbox_id  # noqa: PLC0415
        if sandbox_id() is not None:
            return Path(measurements_dir("")) / "GuitarTap"
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
        """Whether the configured dump folder is still where the user put it — checked at New Tap /
        launch auto-arm when Dump Capture Audio is on. The default is always
        creatable; a custom folder must still be **at its chosen path** — a rename / move / delete
        makes it unreachable (Python stores a plain path, so the folder-must-be-where-you-put-it
        rule is inherent), and the user must Change Location or Turn Off Saving. Do NOT create the
        custom folder here — recreating a renamed-away path would defeat the check. Write
        permission is not checked — a write that fails is logged by the capture.
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
        return WavDumpFolder.set_custom_folder(Path(chosen))

    @staticmethod
    def set_custom_folder(folder: Path) -> bool:
        """Store ``folder`` as the custom folder. Returns True.
        Mirrors Swift ``setCustomFolder``."""
        _settings().setValue(_FOLDER_KEY, str(folder))
        return True

    @staticmethod
    def use_default_folder() -> None:
        """Forget the custom folder — revert to the default. Mirrors Swift ``useDefaultFolder``."""
        _settings().remove(_FOLDER_KEY)

    @staticmethod
    def open_folder() -> None:
        """Open the dump folder in the OS file browser: the custom folder if reachable, else the
        default. Mirrors Swift ``openFolder``."""
        from PySide6 import QtGui

        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(WavDumpFolder.folder_to_open())))

    @staticmethod
    def folder_to_open() -> Path:
        """The folder Open Folder opens, created if missing: the custom folder if reachable, else
        the default. A custom folder that is not at its chosen path is never re-created."""
        acquired = WavDumpFolder.acquire_dump_folder()
        folder = acquired[0] if acquired is not None else WavDumpFolder.default_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return folder