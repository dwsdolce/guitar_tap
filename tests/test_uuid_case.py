# @parity test/uuid-case
"""Ids are UUIDs, written UPPERCASE, and nothing mints outside the one helper.

An id is a ``uuid.UUID`` — compared by value, so case never matters, as Swift's ``UUID`` — and is text
only in a file, where it is written uppercase, as Swift's ``uuidString`` and the web write it.

The second test is the one that prevents a regression. Checking the helper proves the helper works;
it does nothing about a new ``uuid.uuid4()`` added somewhere else later, which would pass every other
test in this suite while quietly going around the rule. A rule with no test is a rule that drifts —
so this scans the source instead of trusting it.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import uuid  # noqa: E402

from guitar_tap.utilities.new_uuid import new_uuid, uuid_text  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap")
HELPER = os.path.join(SRC, "utilities", "new_uuid.py")


def test_new_uuid_is_a_uuid_written_uppercase():
    """Many draws, because a lowercase hex digit only appears when the random bytes call for one."""
    minted = [new_uuid() for _ in range(2000)]
    assert all(isinstance(u, uuid.UUID) for u in minted), "new_uuid() mints a UUID, not text"
    pattern = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
    assert all(pattern.match(uuid_text(u)) for u in minted), "written uppercase, hyphenated"
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


def test_model_factories_mint_uuids_written_uppercase():
    """The rule where it actually reaches a file: measurement and peak ids."""
    from guitar_tap.models.resonant_peak import ResonantPeak
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

    peak = ResonantPeak(frequency=200.0, magnitude=-30.0)
    measurement = TapToneMeasurement.create(peaks=[peak])
    assert isinstance(measurement.id, uuid.UUID) and isinstance(peak.id, uuid.UUID)
    written = measurement.to_dict()
    assert written["id"] == written["id"].upper()
    assert written["peaks"][0]["id"] == written["peaks"][0]["id"].upper()
