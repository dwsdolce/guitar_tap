# @parity test/uuid-case
"""Minted UUIDs are UPPERCASE, and nothing mints outside the one helper.

Swift's ``UUID().uuidString`` is uppercase and the web mints
``crypto.randomUUID().toUpperCase()`` to match it. This edition minted lowercase at 14 sites
across 7 files, so the same measurement exported from here and from Swift differed by case in
``id`` — the field that identifies a dataset — and anything comparing ids as strings would read
them as two different things. Swift uppercases whatever it decodes while the ports preserve what
the file holds, so nothing normalised it back. See SLUG-SWEEP.md F22.

The second test is the one that prevents a regression. Checking that ``new_uuid()`` is uppercase
proves the helper works; it does nothing about a new ``str(uuid.uuid4())`` added somewhere else
next month, which would pass every other test in this suite while quietly reintroducing the
divergence. F22 corrected the values without pinning the rule, and a rule with no test is a rule
that drifts — so this scans the source instead of trusting it.

Case has never affected correctness *within* one file: a file's internal references agree with its
own ids whatever their case. It matters only when two editions compare ids for the same thing.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.utilities.new_uuid import new_uuid  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap")
HELPER = os.path.join(SRC, "utilities", "new_uuid.py")


def test_new_uuid_is_uppercase():
    """Many draws, because a lowercase hex digit only appears when the random bytes call for one."""
    minted = [new_uuid() for _ in range(2000)]
    assert all(u == u.upper() for u in minted), "new_uuid() must mint uppercase"
    # And it must still be a well-formed UUID, not merely an uppercase string.
    pattern = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
    assert all(pattern.match(u) for u in minted)
    assert len(set(minted)) == len(minted), "minted ids must be distinct"


def test_no_module_mints_outside_the_helper():
    """``uuid4()`` appears in exactly one file: the helper.

    Every other module must go through ``new_uuid()``. This is what fails when someone
    reintroduces a direct mint — the case test above would not.
    """
    offenders = []
    for root, _dirs, files in os.walk(SRC):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            if os.path.abspath(path) == os.path.abspath(HELPER):
                continue
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if "uuid4()" in line:
                        offenders.append(f"{os.path.relpath(path, SRC)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "these mint a UUID directly instead of calling new_uuid():\n  " + "\n  ".join(offenders)
    )


def test_model_factories_mint_uppercase():
    """The rule where it actually reaches a file: measurement and peak ids."""
    from guitar_tap.models.resonant_peak import ResonantPeak
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

    measurement = TapToneMeasurement.create(peaks=[])
    peak = ResonantPeak(frequency=200.0, magnitude=-30.0)
    assert measurement.id == measurement.id.upper()
    assert peak.id == peak.id.upper()
