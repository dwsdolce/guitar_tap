# @parity test/self-regression
"""Zero-tolerance regression check against this configuration's own baseline.

The parity suites ask whether Python still agrees with Swift, and must allow 1 dB /
1 Hz to do it — the editions genuinely differ. That looseness is not a bar the Python
edition can be held to against itself: a change of 0.003 dB is invisible under it, and
a drift of exactly that size sat in the Swift goldens undetected until the oracle was
re-minted.

So this compares what Python computes now against what Python computed when this
machine's baseline was minted, and allows **nothing**. Any movement at all is either a
deliberate algorithm change — in which case re-mint, review the diff, and commit it —
or a regression.

Minting is never automatic (``Tooling/mint-baseline.py``). A suite that wrote its own
expectations could not fail: delete the file, run the tests, and today's output becomes
the answer it is checked against.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import self_baseline
from parity_runner import compute_all

_BASELINE = self_baseline.load()

pytestmark = pytest.mark.skipif(
    _BASELINE is None,
    reason=(
        f"NO SELF-BASELINE for {self_baseline.config_key()} — this configuration has "
        f"never been minted, so its regression bar is not in force. It is still covered "
        f"at the 1 dB / 1 Hz parity bar by the other suites. To close the gap: "
        f"python Tooling/mint-baseline.py"
    ),
)


@pytest.fixture(scope="module")
def computed() -> dict[str, float]:
    return self_baseline.flatten(compute_all())


@pytest.fixture(scope="module")
def expected() -> dict[str, float]:
    assert _BASELINE is not None
    return self_baseline.flatten(_BASELINE["values"])


def test_baseline_covers_every_computed_value(computed, expected):
    """Neither side may quietly gain or lose a value."""
    missing = sorted(set(expected) - set(computed))
    extra = sorted(set(computed) - set(expected))
    assert not missing, (
        f"{len(missing)} value(s) in the baseline are no longer computed: {missing[:8]}"
    )
    assert not extra, (
        f"{len(extra)} newly computed value(s) are not in the baseline "
        f"(re-mint to adopt them): {extra[:8]}"
    )


def test_every_value_is_unchanged(computed, expected):
    """Zero tolerance. Swift is bit-reproducible on a fixed machine; so is this."""
    drifted = [
        (key, expected[key], computed[key])
        for key in sorted(expected)
        if key in computed and computed[key] != expected[key]
    ]
    if drifted:
        lines = "\n".join(
            f"  {key}: baseline {was!r} -> now {now!r}  (delta {now - was:+.10g})"
            for key, was, now in drifted[:20]
        )
        more = "" if len(drifted) <= 20 else f"\n  ... and {len(drifted) - 20} more"
        baseline = _BASELINE or {}
        raise AssertionError(
            f"{len(drifted)} of {len(expected)} values moved since "
            f"{baseline.get('provenance', {}).get('mintedAt', 'the baseline was minted')} "
            f"on {self_baseline.config_key()}:\n{lines}{more}\n\n"
            f"Nothing legitimately moves these. Either a change altered the numbers — "
            f"re-mint with Tooling/mint-baseline.py, review the diff, and commit it — "
            f"or this is a regression."
        )
