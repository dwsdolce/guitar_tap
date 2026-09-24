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
from parity_oracle import ORACLE, TOLERANCES  # noqa: E402
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


# The FIRST-MINT bar, not the parity bar. A new configuration has no prior to check
# against, so the only available question is whether its numbers are plausible at all.
# Parity is now tight enough (0.02 Hz / 0.01 dB) that a port still being built could fail
# it — and failing it here would leave that port with no zero-tolerance regression check
# at exactly the moment it most needs one. Falls back to the parity numbers for an older
# oracle that predates the split.
_BOOTSTRAP: dict[str, float] = ORACLE.get("bootstrapTolerances", TOLERANCES)


def _tolerance_for(path: str) -> float | None:
    """The first-mint bar for a value. Per-case overrides are a parity concept and do not
    apply here: this asks whether the numbers are garbage, which is not case-specific."""
    key = _TOLERANCE_KEYS.get(path.rsplit("/", 1)[-1])
    return None if key is None else float(_BOOTSTRAP[key])


def check_against_oracle(computed: dict[str, float]) -> list[str]:
    """Paths where this configuration falls outside the first-mint bar. Empty is a pass."""
    oracle_flat = self_baseline.flatten(ORACLE)
    failures = []
    for path, value in sorted(computed.items()):
        if path.endswith("/maxDb"):
            # Silence: the oracle records Swift's exact value (-inf) — no tolerance applies to it.
            want = float(ORACLE["gatedFft"][path.split("/", 1)[0]]["maxDb"])
            if not value == want:
                failures.append(f"  {path}: {value!r} is not the oracle's {want!r}")
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


def _encoding_is_current(path: str) -> bool:
    """True when the file on disk already stores every non-finite number as its string."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)  # NOT decoded: a bare -Infinity stays a float and shows up below
    return raw == self_baseline.encode_nonfinite(raw)


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
        print("Checking the values against the oracle at the first-mint bar, since there")
        print("is no prior to compare them to.")
        failures = check_against_oracle(computed)
        if failures:
            print(f"\n❌ {len(failures)} value(s) fall outside the first-mint bar:")
            print("\n".join(failures[:20]))
            if len(failures) > 20:
                print(f"  ... and {len(failures) - 20} more")
            print("\nNo baseline written. These numbers are too far from the canonical")
            print("edition to be plausible, so freezing them would freeze the defect into")
            print("the thing meant to detect defects. Investigate before minting.")
            return 1
        print("✅ Every value is within the first-mint bar.")
    else:
        lines = diff_against(previous, computed)
        checked_against = str(previous.get("provenance", {}).get("oracleVersion", "unknown"))
        current_oracle = str(ORACLE.get("oracleVersion", "unknown"))
        if not lines and _encoding_is_current(path) and checked_against == current_oracle:
            print("\n✅ Identical to the committed baseline — nothing to do.")
            return 0
        if not lines and checked_against != current_oracle:
            # Same values, but the baseline names a different oracle than the one it was just checked
            # against — e.g. a -dirty mint superseded by a clean one. Rewrite so the provenance names
            # an oracle anyone can check out; no value changes (#17 F44).
            print(f"\nEvery value is identical, but the baseline names oracle {checked_against}, not the")
            print(f"current {current_oracle}. Re-minting rewrites the provenance; no value changes.")
            if args.check:
                return 1
        elif not lines:
            # Same values, stale FILE: Python's reader accepts the bare, non-standard `-Infinity`
            # token, so a file written before non-finite numbers were stored as strings loads and
            # compares identical — and would never be rewritten. Mint it again so the file is valid
            # JSON and its provenance names the oracle it was actually checked against (#17 F44).
            print("\nEvery value is identical, but the file stores a non-finite number in the old,")
            print("non-standard form rather than as its string. Re-minting rewrites the encoding and")
            print("the provenance; no value changes.")
            if args.check:
                return 1
        if lines:  # a VALUE changed: show the diff, and confirm before adopting it
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
        json.dump(self_baseline.encode_nonfinite(document), fh, indent=2, sort_keys=True,
                  ensure_ascii=False, allow_nan=False)  # "-Infinity" as a string: valid JSON
        fh.write("\n")
    print(f"\n✅ Wrote {path}")
    print("   Review it, commit it, and publish it to the hub so the parity")
    print("   arithmetic can see this configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
