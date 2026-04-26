"""
Debug logging utility — mirrors Swift GuitarTap/Utilities/Logging.swift.

gt_log  — general-purpose debug logging. Replace print() calls with this.
           To disable all gt_log output after beta, set _gt_log_enabled = False.

TAP_DEBUG — tap-detection specific logging, controlled by _tap_debug_enabled.

Both write to the platform user-data directory alongside saved measurements:
  macOS/Windows: ~/Documents/GuitarTap/guitar_tap-debug.log
  Linux:         ~/.local/share/GuitarTap/guitar_tap-debug.log
"""

import threading
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_documents_dir, user_data_dir

_gt_log_enabled = True
_tap_debug_enabled = True

# MARK: - File logger

class _FileLogger:
    def __init__(self) -> None:
        log_path = self._log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
        self._lock = threading.Lock()
        banner = f"=== GuitarTap session started {datetime.now(timezone.utc).isoformat()} ===\n"
        self._write(banner)

    @staticmethod
    def _log_file_path() -> Path:
        import sys
        if sys.platform == "linux":
            base = Path(user_data_dir("GuitarTap", appauthor=False))
        else:
            base = Path(user_documents_dir()) / "GuitarTap"
        return base / "guitar_tap-debug.log"

    def _write(self, message: str) -> None:
        line = message if message.endswith("\n") else message + "\n"
        with self._lock:
            self._file.write(line)

    def __del__(self) -> None:
        self._file.close()


_file_logger = _FileLogger()

# MARK: - Public logging functions

def gt_log(message: str) -> None:
    if _gt_log_enabled:
        print(message)
        _file_logger._write(message)


def TAP_DEBUG(category: str, message: str) -> None:
    if _tap_debug_enabled:
        msg = f"TAP_DEBUG {category}: {message}"
        print(msg)
        _file_logger._write(msg)
