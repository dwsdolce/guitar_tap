"""
Debug logging utility — mirrors Swift GuitarTap/Utilities/Logging.swift.

To enable: set ENABLE_TAP_DEBUG=1 in the environment.
"""
import os

_tap_debug_enabled = os.environ.get("ENABLE_TAP_DEBUG") is not None


def TAP_DEBUG(category: str, message: str) -> None:
    if _tap_debug_enabled:
        print(f"TAP_DEBUG [{category}] {message}")
