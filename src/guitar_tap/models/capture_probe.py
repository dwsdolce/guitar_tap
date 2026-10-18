"""Diagnostic for where the editions' captured tap buffers diverge.

The editions disagree on the guitar path by 0.0004-0.003 dB, and the cause is known to be
at least partly that Swift aligns the guitar FFT window to the sample-level tap onset while
Python and web do not. Adding that alignment to Python closes only 6-52% of the gap, so
something else still differs in what reaches the FFT.

This narrows that "something else" to one of three places by fingerprinting the two buffers
on either side of the alignment step:

    buffer differs                -> the editions are not capturing the same samples
    buffer same, window differs   -> the alignment picks a different onset
    both same, spectrum differs   -> the arithmetic differs, not the input

Inert unless ``enabled`` is set. The probe script switches it on for a replay. The app switches
it on only when run with ``LIVE_PROBE`` set, and then only while Dump Capture Audio is on: each
measurement's records are written beside its session recording, where the first samples of each
capture buffer place it in that recording.

Mirrors Swift ``CaptureProbe.swift``.
@parity util/capture-probe
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Whether the app itself records captures — a developer switch, False in every released build (the
# packaging builds refuse to run with it on). Set it to True for a diagnostic run; the probe then
# runs for each measurement made with Dump Capture Audio on. Mirrors Swift CaptureProbe.liveProbe.
LIVE_PROBE: bool = False

enabled: bool = False
# Whether a measurement in the app is recording captures (begin_live_session). Separate from
# ``enabled``, which a test or tool owns: a session that begins must not switch that off.
live_session: bool = False
records: list[dict[str, Any]] = []


def reset() -> None:
    records.clear()


def begin_live_session(recording: bool) -> None:
    """A measurement begins in the app: start a fresh set of records, when the app is recording
    them at all. Does nothing unless ``LIVE_PROBE``.

    - Parameter recording: Whether this measurement's audio is being recorded (Dump Capture Audio).

    Mirrors Swift CaptureProbe.beginLiveSession(recording:).
    """
    global live_session
    if not LIVE_PROBE:
        return
    live_session = recording
    if recording:
        reset()


def write_live_records(wav: Any) -> None:
    """A measurement's session recording was written: write its records beside it, as
    ``<recording name>-capture-probe.json``. Does nothing unless ``LIVE_PROBE`` and a session is on.

    - Parameter wav: Where the session recording was written (a ``pathlib.Path``).

    Mirrors Swift CaptureProbe.writeLiveRecords(beside:).
    """
    if not (LIVE_PROBE and live_session):
        return
    from guitar_tap.utilities.logging import gt_log
    path = wav.with_name(f"{wav.stem}-capture-probe.json")
    try:
        path.write_text(encoded(wav.stem, records), encoding="utf-8", newline="\n")
        gt_log(f"📦 Capture probe: {path} ({len(records)} captures)")
    except OSError as exc:
        gt_log(f"⚠️ Capture probe not written: {exc}")


def encoded(case_name: str, records: list[dict[str, Any]]) -> str:
    """The records as a document for this edition and platform, in the form every edition writes.

    - Parameter case_name: The replayed case, or the name of the live measurement's recording.
    - Parameter records: The capture records.
    - Returns: The JSON text.

    Mirrors Swift CaptureProbe.encoded(caseName:records:).
    """
    import json
    import platform
    import sys

    system = {"darwin": "darwin", "win32": "windows"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    document = {"edition": "python", "os": system, "arch": arch,
                "caseName": case_name, "records": list(records)}
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


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
    if not (enabled or live_session):
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
