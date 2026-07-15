# @parity test/measurement-name
"""Pin the required-name rule (FILE-PATHS-AND-NAMES-SPEC §3).

A measurement name must be non-empty after trimming before Save is allowed, and the stored name
is trimmed. Three-way with Swift MeasurementNameTests.swift and web measurement-name.test.ts.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement as M


# ── is_valid_name — what enables Save ───────────────────────────────────────

def test_empty_and_whitespace_are_invalid():
    assert M.is_valid_name("") is False
    assert M.is_valid_name("   ") is False
    assert M.is_valid_name("\t\n ") is False


def test_any_real_text_is_valid():
    assert M.is_valid_name("x") is True
    assert M.is_valid_name("Martin 000-28") is True
    assert M.is_valid_name("  padded  ") is True


# ── normalized_name — what gets stored ──────────────────────────────────────

def test_normalized_trims_and_blanks_to_none():
    assert M.normalized_name("  Martin 000-28  ") == "Martin 000-28"
    assert M.normalized_name("Ramírez") == "Ramírez"
    assert M.normalized_name("") is None
    assert M.normalized_name("   ") is None


# ── validity agrees with storage ────────────────────────────────────────────

def test_validity_matches_storage():
    for candidate in ["", "  ", "\n", "a", "  a  ", "Spruce Top"]:
        assert M.is_valid_name(candidate) == (M.normalized_name(candidate) is not None)