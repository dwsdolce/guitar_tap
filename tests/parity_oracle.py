# @parity tooling/parity-oracle
"""Shared parity oracle — the numeric golden contract, read from the vendored copy.

``parity-oracle.json`` is generated in the canonical Swift repo and published to the
project hub (``guitar-tap-project/tooling/parity/parity-oracle.json``); every repo
commits its own copy so tests run offline, refreshed by ``Tooling/sync-oracle.sh``
(``--check`` fails when the local copy has drifted from canonical).

Before this module existed the same numbers were typed out in the Swift, Python and
web suites independently — three copies of one contract, with nothing keeping them
equal. Anything a test asserts numerically and shares with another edition belongs
here, not in a module-level constant.
"""

from __future__ import annotations

import json
import os
from typing import Any

ORACLE_PATH = os.path.join(os.path.dirname(__file__), "parity-oracle.json")

from self_baseline import decode_nonfinite  # noqa: E402 — "-Infinity" strings -> floats

with open(ORACLE_PATH, encoding="utf-8") as _fh:
    ORACLE: dict[str, Any] = decode_nonfinite(json.load(_fh))

TOLERANCES: dict[str, float] = ORACLE["tolerances"]

# The same-configuration bar (the self-regression tests), by class.
SELF_TOLERANCES: dict[str, float] = ORACLE["selfTolerances"]

# Which tolerance class governs a value, by the leaf its path ends in — the hub's parity-report.py
# uses the same table.
TOLERANCE_CLASS = {
    "frequency": "freqHz",
    "magnitude": "magDb",
    "q": "q",
    "ringOutSec": "ringOutSec",
    "db": "gatedFftDb",
    "deltaDb": "gatedFftDb",
    "maxDb": "gatedFftDb",
}


def self_tolerance(path: str) -> float:
    """The same-configuration bar for one value, by its path; a leaf with no class is held exactly."""
    kind = TOLERANCE_CLASS.get(path.rsplit("/", 1)[-1])
    return SELF_TOLERANCES[kind] if kind else 0.0


def case(name: str) -> dict[str, Any]:
    """One filePlayback case (REG-G1, REG-G2, REG-B1, REG-P1, REG-P2)."""
    return ORACLE["filePlayback"][name]


def gated(name: str) -> dict[str, Any]:
    """One gatedFft case (GFFT1-GFFT5)."""
    return ORACLE["gatedFft"][name]


def peak(name: str, role: str, key: str = "peaks") -> dict[str, Any]:
    """The expected peak for one mode role within a case ('peaks' or 'averagedPeaks')."""
    for p in case(name)[key]:
        if p["role"] == role:
            return p
    raise KeyError(f"{name}: no {role!r} peak under {key!r}")


def fixture(name: str) -> str:
    """Absolute path to a case's WAV fixture, which sits beside this file."""
    return os.path.join(os.path.dirname(__file__), case(name)["fixture"])


def calibration(name: str) -> str | None:
    """Absolute path to a case's calibration file, or None when it uses no calibration."""
    cal = case(name)["calibration"]
    return None if cal is None else os.path.join(os.path.dirname(__file__), cal)
