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


# ── normalized_notes — the other user-entered field, normalized the same way ─

def test_normalized_notes_trims_and_blanks_to_none():
    """Notes trim exactly as the name does.

    This edition stripped notes in the edit dialog but NOT on the save path, so notes saved with
    surrounding whitespace read as an edit the moment the dialog reopened — a change the user never
    made. Both paths go through the model rule now. See SLUG-SWEEP.md F21.
    """
    assert M.normalized_notes("  Tapped cold  ") == "Tapped cold"
    assert M.normalized_notes("line one\nline two") == "line one\nline two"
    assert M.normalized_notes("") is None
    assert M.normalized_notes("   \n  ") is None


def test_both_fields_normalize_identically():
    """Or a round trip through one of them looks like an edit."""
    for candidate in ["", "  ", "\n", "a", "  a  ", "Spruce Top", " multi word \n"]:
        assert M.normalized_name(candidate) == M.normalized_notes(candidate)


# ── validity agrees with storage ────────────────────────────────────────────

def test_validity_matches_storage():
    for candidate in ["", "  ", "\n", "a", "  a  ", "Spruce Top"]:
        assert M.is_valid_name(candidate) == (M.normalized_name(candidate) is not None)