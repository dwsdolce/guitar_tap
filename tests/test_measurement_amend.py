# @parity test/measurement-amend
"""The AMEND rule: what it means to change a saved measurement's name or notes.

Name and notes are part of a measurement's DATA, not annotations on top of it, so an amended
measurement is a different dataset and must carry a different ``id``. That gives the identity its
meaning — same ``id`` <=> same content — and it is why ``is_amended`` exists: a Save that changes
nothing would hand unchanged content a new identity, so the edit dialog must not allow one.

These cases lived in test_measurement_codable.py, which is about serialisation; the amend rule is
not a serialisation concern, and the web had no counterpart for it at all. Mirrors Swift
GuitarTapTests/MeasurementAmendTests.swift and web test/measurement-amend.test.ts.
See SLUG-SWEEP.md F20.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402
from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot  # noqa: E402
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement  # noqa: E402
from guitar_tap.utilities.new_uuid import new_uuid  # noqa: E402


def _make_peak(freq: float = 200.0, mag: float = -30.0) -> ResonantPeak:
    return ResonantPeak(id=new_uuid(), frequency=freq, magnitude=mag, quality=10.0, bandwidth=20.0)


def _make_snapshot() -> SpectrumSnapshot:
    return SpectrumSnapshot(
        frequencies=[100.0, 200.0],
        magnitudes=[-30.0, -20.0],
        min_freq=80.0,
        max_freq=1200.0,
        min_db=-90.0,
        max_db=-10.0,
    )


class TestIsAmended:
    """The gate on the edit dialog's Save button. Mirrors Swift MeasurementAmendTests."""

    def test_is_false_when_nothing_differs(self):
        m = TapToneMeasurement.create(peaks=[], measurement_name="Bridge", notes="Some notes")
        assert m.is_amended("Bridge", "Some notes") is False

    def test_is_true_when_the_name_differs(self):
        m = TapToneMeasurement.create(peaks=[], measurement_name="Bridge", notes="Some notes")
        assert m.is_amended("Neck", "Some notes") is True

    def test_is_true_when_the_notes_differ(self):
        m = TapToneMeasurement.create(peaks=[], measurement_name="Bridge", notes="Some notes")
        assert m.is_amended("Bridge", "Edited") is True

    def test_is_true_when_a_field_is_cleared(self):
        m = TapToneMeasurement.create(peaks=[], measurement_name="Bridge", notes="Some notes")
        assert m.is_amended("Bridge", None) is True
        assert m.is_amended(None, "Some notes") is True

    def test_is_false_for_whitespace_only_differences(self):
        """Whitespace-only retyping is NOT an edit, because both fields normalise the same way.

        This is the case that made the rule worth sharing. This edition stripped in the dialog but
        not on the save path, so notes saved with surrounding whitespace made Save light up the
        moment the dialog opened, for a change the user never made. See SLUG-SWEEP.md F21.
        """
        m = TapToneMeasurement.create(peaks=[], measurement_name="Bridge", notes="Some notes")
        name = TapToneMeasurement.normalized_name("  Bridge  ")
        notes = TapToneMeasurement.normalized_notes("\n Some notes \n")
        assert m.is_amended(name, notes) is False

    def test_handles_a_measurement_with_no_name_or_notes(self):
        m = TapToneMeasurement.create(peaks=[])
        assert m.is_amended(None, None) is False
        assert m.is_amended("Named", None) is True


class TestWithMethod:
    """The amend itself. Mirrors Swift MeasurementAmendTests with_* cases."""

    def test_with_updates_measurement_name(self):
        """The copy carries the new name and a NEW id.

        Name and notes are data, so an amended measurement is a different dataset.
        """
        m = TapToneMeasurement.create(peaks=[], measurement_name="Old")
        updated = m.with_(measurement_name="New", notes=None)
        assert updated.measurement_name == "New"
        assert updated.id != m.id, "an amended measurement is a different dataset"

    def test_with_updates_notes(self):
        m = TapToneMeasurement.create(peaks=[], notes="old notes")
        updated = m.with_(measurement_name=None, notes="new notes")
        assert updated.notes == "new notes"

    def test_with_clears_measurement_name_with_none(self):
        m = TapToneMeasurement.create(peaks=[], measurement_name="Bridge")
        updated = m.with_(measurement_name=None, notes=None)
        assert updated.measurement_name is None
        # Clearing the fields is a data change too, so it mints a new id.
        assert updated.id != m.id

    def test_with_preserves_other_fields(self):
        peak = _make_peak()
        snap = _make_snapshot()
        m = TapToneMeasurement.create(
            peaks=[peak],
            spectrum_snapshot=snap,
            decay_time=0.5,
            measurement_name="Bridge",
        )
        updated = m.with_(measurement_name="Neck", notes=None)
        assert updated.peaks == [peak]
        assert updated.spectrum_snapshot == snap
        assert updated.decay_time == 0.5
        assert updated.timestamp == m.timestamp, (
            "timestamp records the capture, which amending does not change"
        )

    def test_with_successive_amendments_each_mint_a_new_id(self):
        """Two successive amendments yield three distinct ids: identity tracks content."""
        a = TapToneMeasurement.create(peaks=[], measurement_name="First")
        b = a.with_(measurement_name="Second", notes=None)
        c = b.with_(measurement_name="Third", notes=None)
        assert a.id != b.id
        assert b.id != c.id
        assert a.id != c.id
