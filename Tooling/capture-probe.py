#!/usr/bin/env python3
"""Write this edition's capture-window fingerprints for the REG-G2 per-tap case.

    .venv/bin/python Tooling/capture-probe.py [-o out.json]

Companion to Swift's CaptureProbeTests. Compare the two files with
guitar-tap-project/tooling/compare-capture-probes.py — see capture_probe.py for what the
three outcomes mean.

@parity tooling/capture-probe
"""

from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from guitar_tap.models import capture_probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", default=os.path.join(REPO_ROOT, "capture-probe-python.json"))
    args = parser.parse_args()

    capture_probe.reset()
    capture_probe.enabled = True
    try:
        from parity_runner import _play  # the same setup REG-G2's regression test uses
        _play("REG-G2")
    finally:
        capture_probe.enabled = False

    records = list(capture_probe.records)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(capture_probe.encoded("REG-G2", records))
    print(f"CAPTURE_PROBE_WROTE {args.out}")
    for index, record in enumerate(records, start=1):
        print(f"  tap {index}: buffer {record['bufferCount']} {record['bufferHash']}"
              f"  window {record['windowCount']} {record['windowHash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
