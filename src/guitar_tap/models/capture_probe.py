"""Diagnostic for the capture-window alignment family (project issues #7, #3, #5).

The editions disagree on the guitar path by 0.0004-0.003 dB, and the cause is known to be
at least partly that Swift aligns the guitar FFT window to the sample-level tap onset while
Python and web do not. Adding that alignment to Python closes only 6-52% of the gap, so
something else still differs in what reaches the FFT.

This narrows that "something else" to one of three places by fingerprinting the two buffers
on either side of the alignment step:

    buffer differs                -> the editions are not capturing the same samples
    buffer same, window differs   -> the alignment picks a different onset
    both same, spectrum differs   -> the arithmetic differs, not the input

Inert unless ``enabled`` is set. Nothing in the app switches it on; the probe script does.

Mirrors Swift ``CaptureProbe.swift``.
@parity models/capture-probe
"""

from __future__ import annotations

from typing import Any

import numpy as np

enabled: bool = False
records: list[dict[str, Any]] = []


def reset() -> None:
    records.clear()


def fingerprint(samples: Any) -> str:
    """FNV-1a over the little-endian IEEE-754 bit patterns of the samples.

    Deliberately not a checksum of the decimal text: the editions must be comparing the
    same bits, and any formatting step would hide a difference in the low bits — which is
    the size of difference this is chasing. Swift's CaptureProbe.fingerprint implements the
    same function, so the two hex strings are directly comparable.
    """
    data = np.asarray(samples, dtype=np.float32).tobytes()  # little-endian on every target
    h = 0xCBF29CE484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def record(buffer: Any, window: Any) -> None:
    if not enabled:
        return
    records.append({
        "bufferCount": int(len(buffer)),
        "bufferHash": fingerprint(buffer),
        "windowCount": int(len(window)),
        "windowHash": fingerprint(window),
        # First samples of the buffer, as hex bit patterns. Enough to locate the buffer's
        # start offset inside the source file by search, which is what says whether the
        # editions begin accumulating at the same sample.
        "bufferHead": [f"{int(v):08x}" for v in
                       np.asarray(buffer, dtype=np.float32)[:1024].view(np.uint32)],
    })
