# @parity test/self-baseline
"""This configuration's committed self-baseline: what it computed, last time it was minted.

Two different bars guard the numbers, and conflating them is what let a real drift hide:

  * The **parity** bar (``parity-oracle.json`` ``tolerances``, 1 dB / 1 Hz) asks whether
    the editions agree. It is necessarily loose — Python and Swift are different FFT
    implementations on different runtimes and genuinely differ.
  * The **regression** bar, here, asks whether *this* edition on *this* machine still
    computes what it computed before. Nothing legitimately moves it, so it is **zero**.

Python cannot use the oracle for the second question: the oracle holds Swift's numbers,
and the distance to them is the very thing the parity bar measures. So each
configuration — edition x OS x arch — mints its own absolute baseline and is checked
against itself.

The key deliberately excludes the NumPy, Python and compiler versions. A library upgrade
that moves the numbers is precisely the event this exists to catch; keying on the version
would let the baseline follow the upgrade and report nothing.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from typing import Any

EDITION = "python"

_OS_NAMES = {"darwin": "darwin", "win32": "windows", "cygwin": "windows"}
_ARCH_NAMES = {"aarch64": "arm64", "arm64": "arm64",
               "x86_64": "x86_64", "amd64": "x86_64", "AMD64": "x86_64"}


def os_name() -> str:
    return _OS_NAMES.get(sys.platform, "linux" if sys.platform.startswith("linux") else sys.platform)


def arch_name() -> str:
    machine = platform.machine()
    return _ARCH_NAMES.get(machine, _ARCH_NAMES.get(machine.lower(), machine.lower()))


def configuration() -> dict[str, str]:
    return {"edition": EDITION, "os": os_name(), "arch": arch_name()}


def config_key() -> str:
    return f"{EDITION}-{os_name()}-{arch_name()}"


def baseline_path() -> str:
    """Beside the tests, so the suite reads it with no hub checkout and no network."""
    return os.path.join(os.path.dirname(__file__), f"self-baseline-{os_name()}-{arch_name()}.json")


def load() -> dict[str, Any] | None:
    """The committed baseline for this configuration, or None if none has been minted."""
    path = baseline_path()
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def flatten(values: dict[str, Any]) -> dict[str, float]:
    """Nested case values -> one flat {path: number} map, for value-by-value comparison.

    Every edition produces the same paths, so the hub can subtract one configuration's
    file from another's without knowing anything about either.
    """
    flat: dict[str, float] = {}

    def label(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        if "role" in item:
            return str(item["role"])
        if "tap" in item:
            return f"tap{item['tap']}"
        if "hz" in item:
            return f"{item['hz']}Hz"
        return None

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("role", "tap", "hz") or key.startswith("_"):
                    continue
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}/{label(item) or index}")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            flat[path] = float(node)

    for block in ("filePlayback", "gatedFft"):
        for name, body in values.get(block, {}).items():
            walk(body, name)
    return flat
