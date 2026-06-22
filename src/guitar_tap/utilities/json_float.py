"""Float32 JSON serialization helpers for cross-implementation parity.

The Swift GuitarTap app stores most scalar measurements as ``Float`` (IEEE-754
binary32), and its ``JSONEncoder`` writes the *shortest decimal string that
round-trips to that float32* — and emits integral values with no decimal point
(``-100``, ``200``, ``0``). Python stores the same values as ``float``
(binary64); serialising them verbatim yields longer, higher-precision numbers
(e.g. ``164.1570099078`` instead of Swift's ``164.15701``).

``f32()`` reproduces Swift's exact output so ``.guitartap`` files written by the
Python and Swift builds carry byte-identical scalar fields:

  * the value is first quantised to float32 (matching Swift's ``Float`` storage);
  * integral results are returned as ``int`` so ``json`` emits no ``.0`` suffix,
    matching Swift (``Float(-100)`` -> ``-100``);
  * fractional results are formatted via ``str(np.float32(...))``, the
    shortest-round-trip algorithm Swift's ``Float`` description also uses, then
    parsed back to ``float`` so ``json.dumps`` re-emits that same shortest text.

Only fields that Swift declares as ``Float`` should pass through ``f32()``.
Fields Swift declares as ``Double`` (e.g. ``pitchCents``, ``pitchFrequency``,
``colorComponents``, annotation ``absFreqHz``/``absDB``) already match, because
both languages emit the shortest binary64 decimal, and must be left untouched.
"""

from __future__ import annotations

import math

import numpy as np


def f32(value: float | int | None) -> float | int | None:
    """Quantise a scalar to float32 and return a value whose JSON form matches
    Swift's ``Float`` encoding. ``None`` and non-finite values pass through."""
    if value is None:
        return None
    f = np.float32(value)
    if not math.isfinite(float(f)):
        return float(f)
    # Integral -> int so json emits "-100", not "-100.0" (matches Swift).
    if float(f).is_integer():
        return int(f)
    # str(np.float32(x)) is the shortest decimal that round-trips to the float32
    # value — the same convention Swift uses. Re-parsing to float keeps json's
    # output identical to that shortest text.
    return float(str(f))


def f32_list(values: list | None) -> list | None:
    """Apply :func:`f32` to each element of a list. ``None`` passes through."""
    if values is None:
        return None
    return [f32(v) for v in values]
