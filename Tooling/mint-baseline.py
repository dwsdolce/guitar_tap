#!/usr/bin/env python3
# @parity tooling/mint-baseline
"""Mint this configuration's self-baseline — the zero-tolerance regression reference.

    python Tooling/mint-baseline.py           # mint (prompts before overwriting)
    python Tooling/mint-baseline.py --yes     # don't prompt
    python Tooling/mint-baseline.py --check   # print the diff, write nothing

Deliberately separate from the test run. A suite that minted its own expectations could
never fail — delete the file, run the tests, and whatever the machine produces today
becomes the answer it is checked against. So this is an explicit act, and the file it
writes is committed and reviewed like any other change.

Two situations, two behaviours:

  * **No baseline yet.** There is no prior to compare against, so the first run is
    trusted — with the one check that is actually available: the values must pass the
    parity gate against the oracle. Within 1 dB / 1 Hz of the canonical Swift edition
    they are plausible and worth freezing. Outside it there is no baseline to commit,
    there is a finding; committing it would freeze a bug into the thing meant to catch
    bugs.

  * **A baseline exists.** Re-minting means the numbers moved deliberately, so the diff
    against the current baseline is printed and confirmed before anything is written.
    That diff is the review artifact for the change.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import self_baseline  # noqa: E402
from parity_oracle import ORACLE, TOLERANCES, case  # noqa: E402
from parity_runner import compute_all  # noqa: E402

# Which tolerance governs a value, by the leaf its path ends in.
_TOLERANCE_KEYS = {
    "frequency": "freqHz",
    "magnitude": "magDb",
    "q": "q",
    "ringOutSec": "ringOutSec",
    "db": "gatedFftDb",
    "deltaDb": "gatedFftDb",
}


def _tolerance_for(path: str) -> float | None:
    leaf = path.rsplit("/", 1)[-1]
    key = _TOLERANCE_KEYS.get(leaf)
    if key is None:
        return None
    name = path.split("/", 1)[0]
    if name in ORACLE["filePlayback"]:
        return float(case(name).get("tolerances", {}).get(key, TOLERANCES[key]))
    return float(TOLERANCES[key])


def check_against_oracle(computed: dict[str, float]) -> list[str]:
    """Paths where this configuration falls outside the parity gate. Empty is a pass."""
    oracle_flat = self_baseline.flatten(ORACLE)
    failures = []
    for path, value in sorted(computed.items()):
        if path.endswith("/maxDb"):
            ceiling = float(ORACLE["gatedFft"][path.split("/", 1)[0]]["maxDbBelow"])
            if not value < ceiling:
                failures.append(f"  {path}: {value:.6g} is not below the {ceiling} dB ceiling")
            continue
        if path not in oracle_flat:
            continue
        tolerance = _tolerance_for(path)
        if tolerance is None:
            continue
        delta = abs(value - oracle_flat[path])
        if delta >= tolerance:
            failures.append(
                f"  {path}: oracle {oracle_flat[path]!r}, computed {value!r}, "
                f"delta {delta:.6g} >= {tolerance} tolerance"
            )
    return failures


def diff_against(previous: dict, computed: dict[str, float]) -> list[str]:
    was = self_baseline.flatten(previous["values"])
    lines = []
    for path in sorted(set(was) | set(computed)):
        before, after = was.get(path), computed.get(path)
        if before is None:
            lines.append(f"  + {path} = {after!r}")
        elif after is None:
            lines.append(f"  - {path} (was {before!r})")
        elif before != after:
            lines.append(f"  ~ {path}: {before!r} -> {after!r}  (delta {after - before:+.10g})")
    return lines


def provenance() -> dict[str, str]:
    """What the machine was, so a future drift can be explained rather than guessed at.

    None of this is part of the configuration key: a NumPy upgrade that moves the
    numbers must fail the regression check, not silently redefine the baseline.
    """
    try:
        import numpy
        numpy_version = numpy.__version__
    except Exception:  # pragma: no cover - numpy is a hard dependency of the app
        numpy_version = "unknown"
    return {
        "mintedAt": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "oracleVersion": str(ORACLE.get("oracleVersion", "unknown")),
        "python": platform.python_version(),
        "numpy": numpy_version,
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
    }


def main() -> int:
    # Status lines use non-ASCII markers. A Windows console is cp1252 by default and raises
    # UnicodeEncodeError on them, which killed this script at its first status line - on the
    # very platforms it exists to characterise. Same fix as tooling/parity/doc_coverage.py.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="overwrite without prompting")
    parser.add_argument("--check", action="store_true", help="report only; write nothing")
    args = parser.parse_args()

    path = self_baseline.baseline_path()
    key = self_baseline.config_key()
    print(f"Configuration: {key}")
    print(f"Baseline:      {path}")
    print("Running every oracle case ...")

    values = compute_all()
    computed = self_baseline.flatten(values)
    print(f"Computed {len(computed)} values.")

    previous = self_baseline.load()

    if previous is None:
        print("\nNo baseline exists for this configuration — bootstrapping.")
        print("Checking the values against the oracle's parity gate first, since there")
        print("is no prior to compare them to.")
        failures = check_against_oracle(computed)
        if failures:
            print(f"\n❌ {len(failures)} value(s) fall outside the parity gate:")
            print("\n".join(failures[:20]))
            if len(failures) > 20:
                print(f"  ... and {len(failures) - 20} more")
            print("\nNo baseline written. These numbers disagree with the canonical")
            print("edition by more than the cross-edition bar allows, so freezing them")
            print("would freeze the disagreement. Investigate before minting.")
            return 1
        print("✅ Every value is within the parity gate.")
    else:
        lines = diff_against(previous, computed)
        if not lines:
            print("\n✅ Identical to the committed baseline — nothing to do.")
            return 0
        print(f"\n{len(lines)} value(s) differ from the committed baseline:")
        print("\n".join(lines[:40]))
        if len(lines) > 40:
            print(f"  ... and {len(lines) - 40} more")
        print("\nThis diff is the review artifact. Adopt it only if a deliberate change")
        print("explains every line; otherwise it is a regression and re-minting hides it.")
        if args.check:
            return 1
        if not args.yes:
            if input("\nOverwrite the baseline with these values? [y/N] ").strip().lower() != "y":
                print("Not written.")
                return 1

    if args.check:
        print("\n--check: nothing written.")
        return 0

    document = {
        "_generator": (
            "guitar_tap Tooling/mint-baseline.py — this configuration's zero-tolerance "
            "regression reference. Not the oracle: the oracle is the cross-edition "
            "contract minted by canonical Swift."
        ),
        "configuration": self_baseline.configuration(),
        "provenance": provenance(),
        "values": values,
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(document, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(f"\n✅ Wrote {path}")
    print("   Review it, commit it, and publish it to the hub so the parity")
    print("   arithmetic can see this configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
