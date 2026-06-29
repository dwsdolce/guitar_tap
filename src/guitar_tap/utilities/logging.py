"""
Debug logging utility — mirrors Swift GuitarTap/Utilities/Logging.swift.

gt_log  — general-purpose debug logging. Replace print() calls with this.
           To disable all gt_log output after beta, set _gt_log_enabled = False.

TAP_DEBUG — tap-detection specific logging, controlled by _tap_debug_enabled.

Both write to the platform user-data directory alongside saved measurements:
  macOS/Windows: ~/Documents/GuitarTap/guitar_tap-debug.log
  Linux:         ~/.local/share/GuitarTap/guitar_tap-debug.log
"""

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from platformdirs import user_data_dir, user_documents_dir

_gt_log_enabled = False
_tap_debug_enabled = False

# MARK: - File logger

class _FileLogger:
    def __init__(self) -> None:
        # Defer opening the file until the first write, so a run with logging
        # disabled never creates or touches the log file.
        self._file: "TextIO | None" = None
        self._lock = threading.Lock()

    @staticmethod
    def _log_file_path() -> Path:
        import sys
        if sys.platform == "linux":
            base = Path(user_data_dir("GuitarTap", appauthor=False))
        else:
            base = Path(user_documents_dir()) / "GuitarTap"
        return base / "guitar_tap-debug.log"

    def _ensure_open(self) -> TextIO:
        """Open the log file and write the session banner on first use."""
        f = self._file
        if f is None:
            log_path = self._log_file_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            f = open(log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
            f.write(f"=== GuitarTap session started {datetime.now(timezone.utc).isoformat()} ===\n")
            self._file = f
        return f

    def _write(self, message: str) -> None:
        line = message if message.endswith("\n") else message + "\n"
        with self._lock:
            self._ensure_open().write(line)

    def __del__(self) -> None:
        if self._file is not None:
            self._file.close()


_file_logger = _FileLogger()

# MARK: - Public logging functions

def gt_log(message: str) -> None:
    if _gt_log_enabled:
        # sys.stdout is None in pyinstaller windowed builds (no console
        # attached).  print() would crash with AttributeError on the missing
        # .write attribute, so skip it in that case — the file logger below
        # still captures the message.
        if sys.stdout is not None:
            print(message)
        _file_logger._write(message)


def TAP_DEBUG(category: str, message: str) -> None:
    if _tap_debug_enabled:
        msg = f"TAP_DEBUG {category}: {message}"
        if sys.stdout is not None:
            print(msg)
        _file_logger._write(msg)
