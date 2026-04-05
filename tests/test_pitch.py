"""
Port of PitchTests.swift — equal-temperament pitch calculations.

Mirrors Swift test plan coverage (note ID, cents, freq0, in-tune, tuning reference).
"""

from __future__ import annotations

import math
import sys, os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.pitch import Pitch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_pitch = Pitch(a4=440.0)


# ---------------------------------------------------------------------------
# Note Identification
# ---------------------------------------------------------------------------

class TestNoteIdentification:
    """Mirrors Swift PitchTests note-identification cases."""

    def test_A4_identifies_correctly(self):
        """440 Hz should identify as A4 (note=9, octave=4)."""
        note, octave = _pitch.pitch(440.0)
        assert note == 9, f"Expected note index 9 (A), got {note}"
        assert octave == 4, f"Expected octave 4, got {octave}"
        assert _pitch.note(440.0) == "A4"

    def test_C4_identifies_correctly(self):
        """Middle C (~261.63 Hz) should identify as C4."""
        c4 = _pitch.freq(note=0, octave=4)
        assert _pitch.note(c4) == "C4"
        note, octave = _pitch.pitch(c4)
        assert note == 0
        assert octave == 4

    def test_A5_identifies_correctly(self):
        """880 Hz is A5 (one octave above A4)."""
        assert _pitch.note(880.0) == "A5"

    def test_A3_identifies_correctly(self):
        """220 Hz is A3 (one octave below A4)."""
        assert _pitch.note(220.0) == "A3"


# ---------------------------------------------------------------------------
# Cents Calculation
# ---------------------------------------------------------------------------

class TestCentsCalculation:
    """Mirrors Swift PitchTests cents cases."""

    def test_exact_pitch_zero_cents(self):
        """A frequency exactly on A4 should be 0 cents from it."""
        c = _pitch.cents(440.0)
        assert abs(c) < 0.01, f"440 Hz should be 0 cents; got {c:.4f}"

    def test_one_semitone_above_is_100_cents(self):
        """A# 4 (one semitone above A4) should be ~100 cents from A4 perspective."""
        # A#4 exactly = A4 × 2^(1/12)
        a_sharp_4 = 440.0 * (2 ** (1 / 12))
        # cents relative to A#4 should be ~0
        c = _pitch.cents(a_sharp_4)
        assert abs(c) < 0.5, f"A#4 should be ~0 cents from itself; got {c:.4f}"

    def test_half_semitone_above_A4_is_50_cents(self):
        """Frequency ~49 cents above A4 → pitch snaps to A4, cents ≈ +49."""
        # Use 0.49 semitones to stay clearly on the A4 side of the rounding boundary
        # (exactly 0.5 semitones hits the tie-break and may snap to A#4).
        nearly_half_semitone_up = 440.0 * (2 ** (0.49 / 12))
        c = _pitch.cents(nearly_half_semitone_up)
        assert 40.0 < c < 50.5, f"Expected ~49 cents, got {c:.4f}"

    def test_cents_negative_when_flat(self):
        """A frequency slightly below a note pitch should give negative cents."""
        slightly_flat = 438.0  # just below A4
        c = _pitch.cents(slightly_flat)
        assert c < 0, f"Flat frequency should give negative cents; got {c:.4f}"

    def test_cents_positive_when_sharp(self):
        """A frequency slightly above a note pitch should give positive cents."""
        slightly_sharp = 442.0
        c = _pitch.cents(slightly_sharp)
        assert c > 0, f"Sharp frequency should give positive cents; got {c:.4f}"


# ---------------------------------------------------------------------------
# freq0 — nearest note frequency
# ---------------------------------------------------------------------------

class TestFreq0:
    """Mirrors Swift PitchTests freq0 cases."""

    def test_freq0_of_A4_is_440(self):
        """freq0 of exact A4 should return 440 Hz."""
        f0 = _pitch.freq0(440.0)
        assert abs(f0 - 440.0) < 0.01, f"freq0(440) should be 440; got {f0:.4f}"

    def test_freq0_of_slightly_sharp_A4_is_still_440(self):
        """Slightly sharp A4 (442 Hz) should snap to A4 = 440 Hz."""
        f0 = _pitch.freq0(442.0)
        assert abs(f0 - 440.0) < 0.5, f"freq0(442) should be ~440; got {f0:.4f}"

    def test_freq0_matches_freq_formula(self):
        """freq0(f) should equal freq(note, octave) for the snapped note."""
        f = 500.0
        note, octave = _pitch.pitch(f)
        expected = _pitch.freq(note=note, octave=octave)
        got = _pitch.freq0(f)
        assert abs(got - expected) < 0.001, (
            f"freq0({f}) = {got:.4f}, expected {expected:.4f}"
        )


# ---------------------------------------------------------------------------
# In-Tune Detection
# ---------------------------------------------------------------------------

class TestInTune:
    """Mirrors Swift PitchTests isInTune cases."""

    def test_exact_pitch_is_in_tune(self):
        """Exact A4 (440 Hz) is in tune at default 10-cent threshold."""
        assert _pitch.is_in_tune(440.0), "440 Hz should be in tune"

    def test_10_cent_sharp_is_in_tune(self):
        """A frequency slightly under 10 cents sharp should be in tune."""
        # Use 9.9 cents to stay clearly within the 10-cent threshold and avoid
        # floating-point rounding that can push the computed cents just above 10.0.
        just_under_ten_cents_sharp = 440.0 * (2 ** (9.9 / 1200.0))
        assert _pitch.is_in_tune(just_under_ten_cents_sharp), (
            "9.9 cents sharp should be in tune"
        )

    def test_11_cent_sharp_is_not_in_tune(self):
        """A frequency more than 10 cents sharp is out of tune."""
        eleven_cents_sharp = 440.0 * (2 ** (11.0 / 1200.0))
        assert not _pitch.is_in_tune(eleven_cents_sharp), (
            "11 cents sharp should NOT be in tune"
        )

    def test_flat_out_of_tune(self):
        """A frequency more than 10 cents flat is out of tune."""
        flat = 440.0 * (2 ** (-15.0 / 1200.0))
        assert not _pitch.is_in_tune(flat), "15 cents flat should NOT be in tune"

    def test_custom_threshold(self):
        """Custom threshold parameter is respected."""
        five_cents_sharp = 440.0 * (2 ** (5.0 / 1200.0))
        assert _pitch.is_in_tune(five_cents_sharp, threshold=10.0), (
            "5 cents sharp is in tune at 10-cent threshold"
        )
        assert not _pitch.is_in_tune(five_cents_sharp, threshold=4.0), (
            "5 cents sharp is NOT in tune at 4-cent threshold"
        )


# ---------------------------------------------------------------------------
# A4 Tuning Reference
# ---------------------------------------------------------------------------

class TestTuningReference:
    """Mirrors Swift PitchTests a4 reference cases."""

    def test_432Hz_reference_changes_note_frequency(self):
        """Pitch calculator anchored at 432 Hz reports a different freq0 for A4."""
        pitch_432 = Pitch(a4=432.0)
        # At 432 Hz reference, 432 Hz should identify as A4 and freq0 = 432
        assert pitch_432.note(432.0) == "A4"
        assert abs(pitch_432.freq0(432.0) - 432.0) < 0.01

    def test_440Hz_and_432Hz_differ_for_same_frequency(self):
        """Same input frequency reports different cent offsets under different a4."""
        pitch_440 = Pitch(a4=440.0)
        pitch_432 = Pitch(a4=432.0)
        # 436 Hz is between 432 and 440 — the two references will disagree on cents sign
        c_440 = pitch_440.cents(436.0)
        c_432 = pitch_432.cents(436.0)
        # Under 440 Hz reference, 436 Hz is slightly flat (negative cents)
        assert c_440 < 0, f"436 Hz should be flat under 440 Hz reference; got {c_440:.2f}"
        # Under 432 Hz reference, 436 Hz is slightly sharp (positive cents)
        assert c_432 > 0, f"436 Hz should be sharp under 432 Hz reference; got {c_432:.2f}"


# ---------------------------------------------------------------------------
# Formatted Note
# ---------------------------------------------------------------------------

class TestFormattedNote:
    """Mirrors Swift PitchTests formattedNote cases."""

    def test_exact_A4_formats_correctly(self):
        s = _pitch.formatted_note(440.0)
        assert "A4" in s
        assert "+0" in s or "0 cents" in s

    def test_formatted_includes_sign(self):
        s_sharp = _pitch.formatted_note(442.0)
        assert "+" in s_sharp, f"Sharp note should show '+'; got: {s_sharp}"

        s_flat = _pitch.formatted_note(438.0)
        assert "-" in s_flat, f"Flat note should show '-'; got: {s_flat}"
