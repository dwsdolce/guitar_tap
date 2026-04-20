"""
Port of MeasurementCodableTests.swift — JSON round-trip, snapshot encoding,
tapToneRatio, export labels.

Also contains data-structure tests moved from test_annotation_state.py because
they test TapToneMeasurement JSON fields, not live TapToneAnalyzer state:
  TestAnnotationOffsets, TestPeakSelection, TestAnnotationVisibilityMode,
  TestModeOverrides, TestPeakSelectionTracking.

Mirrors Swift test suites:
  SpectrumSnapshotCodableTests
  ResonantPeakCodableTests
  TapToneMeasurementCodableTests
  TapToneRatioTests
  MeasurementExportModeLabelTests
  FixtureLoadingTests (skipped if fixture not present)
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(
    freqs: list[float] | None = None,
    mags:  list[float] | None = None,
    min_freq: float = 80.0,
    max_freq: float = 1200.0,
    min_db: float = -90.0,
    max_db: float = -10.0,
) -> SpectrumSnapshot:
    return SpectrumSnapshot(
        frequencies=freqs or [100.0, 200.0, 300.0, 400.0],
        magnitudes=mags   or [-40.0, -35.0, -45.0, -50.0],
        min_freq=min_freq,
        max_freq=max_freq,
        min_db=min_db,
        max_db=max_db,
    )


def _make_peak(
    freq: float = 200.0,
    mag: float = -30.0,
    quality: float = 10.0,
    pitch_note: str | None = None,
    pitch_cents: float | None = None,
    pitch_freq: float | None = None,
) -> ResonantPeak:
    return ResonantPeak(
        id=str(uuid.uuid4()),
        frequency=freq,
        magnitude=mag,
        quality=quality,
        bandwidth=freq / quality,
        timestamp="2026-01-01T00:00:00+00:00",
        pitch_note=pitch_note,
        pitch_cents=pitch_cents,
        pitch_frequency=pitch_freq,
    )


# ---------------------------------------------------------------------------
# SpectrumSnapshot serialisation
# ---------------------------------------------------------------------------

class TestSpectrumSnapshotCodable:
    """Mirrors Swift SpectrumSnapshotCodableTests."""

    def test_binary_round_trip_preserves_values(self):
        """Encode then decode via Base64 binary format preserves data within float32 precision."""
        snap = _make_snapshot(
            freqs=[100.0, 200.0, 300.0],
            mags=[-30.0, -35.0, -40.0],
        )
        d = snap.to_dict()
        assert "frequenciesData" in d, "Should use compact binary format"
        assert "magnitudesData" in d

        restored = SpectrumSnapshot.from_dict(d)
        # float32 precision: ±0.001 Hz / dB tolerance
        for orig, got in zip(snap.frequencies, restored.frequencies):
            assert abs(orig - got) < 0.1, f"Frequency {orig} → {got} too large error"
        for orig, got in zip(snap.magnitudes, restored.magnitudes):
            assert abs(orig - got) < 0.01, f"Magnitude {orig} → {got} too large error"

    def test_axis_ranges_preserved(self):
        """min/max freq/db round-trip exactly."""
        snap = _make_snapshot(min_freq=50.0, max_freq=1500.0, min_db=-100.0, max_db=0.0)
        restored = SpectrumSnapshot.from_dict(snap.to_dict())
        assert restored.min_freq == 50.0
        assert restored.max_freq == 1500.0
        assert restored.min_db == -100.0
        assert restored.max_db == 0.0

    def test_legacy_plain_array_format_decoded(self):
        """from_dict accepts legacy 'frequencies'/'magnitudes' plain-float-array format."""
        d = {
            "frequencies": [100.0, 200.0],
            "magnitudes": [-30.0, -40.0],
            "minFreq": 80.0,
            "maxFreq": 500.0,
            "minDB": -90.0,
            "maxDB": -10.0,
            "isLogarithmic": False,
        }
        snap = SpectrumSnapshot.from_dict(d)
        assert snap.frequencies == [100.0, 200.0]
        assert snap.magnitudes == [-30.0, -40.0]

    def test_binary_smaller_than_equivalent_json_array(self):
        """Binary Base64 encoding should produce a shorter string than a JSON float array."""
        freqs = [float(i) for i in range(100)]
        snap = SpectrumSnapshot(
            frequencies=freqs,
            magnitudes=[-40.0] * 100,
        )
        d = snap.to_dict()
        binary_len = len(d["frequenciesData"])
        json_array_len = len(json.dumps(freqs))
        assert binary_len < json_array_len, (
            f"Binary ({binary_len}) should be smaller than JSON array ({json_array_len})"
        )


# ---------------------------------------------------------------------------
# ResonantPeak serialisation
# ---------------------------------------------------------------------------

class TestResonantPeakCodable:
    """Mirrors Swift ResonantPeakCodableTests."""

    def test_round_trip_preserves_all_fields(self):
        """to_dict / from_dict round-trip preserves id, freq, mag, quality, bandwidth."""
        peak = _make_peak(freq=440.0, mag=-22.5, quality=12.3,
                          pitch_note="A4", pitch_cents=+5.0, pitch_freq=440.0)
        restored = ResonantPeak.from_dict(peak.to_dict())
        assert restored.id == peak.id
        assert abs(restored.frequency - 440.0) < 0.001
        assert abs(restored.magnitude - (-22.5)) < 0.001
        assert abs(restored.quality - 12.3) < 0.001
        assert restored.pitch_note == "A4"
        assert abs(restored.pitch_cents - 5.0) < 0.001
        assert abs(restored.pitch_frequency - 440.0) < 0.001

    def test_nil_pitch_fields_absent_from_dict(self):
        """When pitch fields are None, they should not appear in the encoded dict."""
        peak = _make_peak(pitch_note=None, pitch_cents=None, pitch_freq=None)
        d = peak.to_dict()
        assert "pitchNote" not in d
        assert "pitchCents" not in d
        assert "pitchFrequency" not in d

    def test_nil_pitch_round_trip(self):
        """A peak without pitch fields round-trips with None for all pitch fields."""
        peak = _make_peak()
        restored = ResonantPeak.from_dict(peak.to_dict())
        assert restored.pitch_note is None
        assert restored.pitch_cents is None
        assert restored.pitch_frequency is None


# ---------------------------------------------------------------------------
# TapToneMeasurement serialisation
# ---------------------------------------------------------------------------

class TestTapToneMeasurementCodable:
    """Mirrors Swift TapToneMeasurementCodableTests."""

    def test_full_round_trip(self):
        """A measurement with peaks, snapshot, and metadata round-trips through JSON."""
        peak = _make_peak(freq=200.0, mag=-30.0)
        snap = _make_snapshot()
        m = TapToneMeasurement.create(
            peaks=[peak],
            spectrum_snapshot=snap,
            tap_location="Bridge",
            decay_time=0.45,
            number_of_taps=3,
        )
        d = m.to_dict()
        raw_json = json.dumps(d)
        restored = TapToneMeasurement.from_dict(json.loads(raw_json))

        assert restored.id == m.id
        assert restored.tap_location == "Bridge"
        assert abs(restored.decay_time - 0.45) < 0.001
        assert restored.number_of_taps == 3
        assert len(restored.peaks) == 1
        assert abs(restored.peaks[0].frequency - 200.0) < 0.001

    def test_annotation_offsets_round_trip(self):
        """Annotation offsets survive a JSON round-trip using the Swift flat-array format."""
        peak = _make_peak()
        offsets = {peak.id.upper(): [300.0, -45.0]}
        m = TapToneMeasurement.create(peaks=[peak], annotation_offsets=offsets)
        restored = TapToneMeasurement.from_dict(m.to_dict())

        assert restored.annotation_offsets is not None
        assert peak.id.upper() in restored.annotation_offsets
        stored = restored.annotation_offsets[peak.id.upper()]
        assert abs(stored[0] - 300.0) < 0.01
        assert abs(stored[1] - (-45.0)) < 0.01

    def test_empty_annotation_offsets_round_trip(self):
        """Empty annotation_offsets encodes as [] and decodes to None."""
        m = TapToneMeasurement.create(peaks=[], annotation_offsets=None)
        d = m.to_dict()
        assert d["peakAnnotationOffsets"] == []
        restored = TapToneMeasurement.from_dict(d)
        assert restored.annotation_offsets is None

    def test_mode_overrides_round_trip(self):
        """per-peak mode overrides survive a JSON round-trip."""
        peak = _make_peak()
        overrides = {peak.id: "Top"}
        m = TapToneMeasurement.create(peaks=[peak], peak_mode_overrides=overrides)
        restored = TapToneMeasurement.from_dict(m.to_dict())
        assert restored.peak_mode_overrides is not None
        assert restored.peak_mode_overrides.get(peak.id) == "Top"


# ---------------------------------------------------------------------------
# Annotation offsets on TapToneMeasurement (moved from test_annotation_state.py)
# Mirrors Swift TapToneMeasurementCodableTests: annotationOffsets_roundTrip_preserved
# ---------------------------------------------------------------------------


def _round_trip(m: TapToneMeasurement) -> TapToneMeasurement:
    """Serialise to JSON then decode, producing an independent copy."""
    return TapToneMeasurement.from_dict(json.loads(json.dumps(m.to_dict())))


class TestAnnotationOffsets:
    """TapToneMeasurement annotation-offset storage and JSON round-trip.

    Moved from test_annotation_state.py — tests TapToneMeasurement fields,
    not live TapToneAnalyzer state. Mirrors Swift AnnotationStateTests D1–D2.
    """

    def test_D1_offsets_stored_per_peak(self):
        """D1: annotation_offsets keyed by peak UUID can store different positions per peak."""
        p1 = _make_peak(freq=200.0)
        p2 = _make_peak(freq=300.0)
        offsets = {
            p1.id.upper(): [200.0, -40.0],
            p2.id.upper(): [300.0, -35.0],
        }
        m = TapToneMeasurement.create(peaks=[p1, p2], annotation_offsets=offsets)
        assert m.annotation_offsets is not None
        assert m.annotation_offsets[p1.id.upper()] == [200.0, -40.0]
        assert m.annotation_offsets[p2.id.upper()] == [300.0, -35.0]

    def test_D2_annotation_offsets_survive_json_round_trip(self):
        """D2: annotation_offsets are preserved across a JSON round-trip."""
        p = _make_peak(freq=440.0)
        offsets = {p.id.upper(): [440.0, -25.0]}
        m = TapToneMeasurement.create(peaks=[p], annotation_offsets=offsets)
        restored = _round_trip(m)
        assert restored.annotation_offsets is not None
        stored = restored.annotation_offsets.get(p.id.upper())
        assert stored is not None, "Offset should survive round-trip"
        assert abs(stored[0] - 440.0) < 0.01
        assert abs(stored[1] - (-25.0)) < 0.01


# ---------------------------------------------------------------------------
# Peak selection on TapToneMeasurement (moved from test_annotation_state.py)
# Mirrors Swift TapToneRatioTests: tapToneRatio_usesSelectedPeaksWhenSet
# ---------------------------------------------------------------------------

class TestPeakSelection:
    """TapToneMeasurement selected_peak_ids storage and tap_tone_ratio filtering.

    Moved from test_annotation_state.py — tests TapToneMeasurement fields.
    Mirrors Swift AnnotationStateTests D3/D3b.
    """

    def test_D3_selected_peak_ids_stored(self):
        """D3: selected_peak_ids is stored and round-trips through JSON."""
        p1 = _make_peak(freq=95.0)
        p2 = _make_peak(freq=195.0)
        m = TapToneMeasurement.create(
            peaks=[p1, p2],
            selected_peak_ids=[p1.id],
            selected_peak_frequencies=[95.0],
        )
        restored = _round_trip(m)
        assert restored.selected_peak_ids == [p1.id]
        assert restored.selected_peak_frequencies == [95.0]

    def test_D3b_tap_tone_ratio_uses_only_selected_peaks(self):
        """D3b: tap_tone_ratio skips deselected peaks."""
        air = _make_peak(freq=95.0, mag=-25.0)
        top = _make_peak(freq=195.0, mag=-28.0)
        noise = _make_peak(freq=500.0, mag=-50.0)
        m = TapToneMeasurement.create(
            peaks=[air, top, noise],
            selected_peak_ids=[air.id, top.id],
            guitar_type="Classical",
        )
        ratio = m.tap_tone_ratio
        assert ratio is not None
        assert abs(ratio - (195.0 / 95.0)) < 0.1

    def test_selected_peak_ids_none_uses_all_peaks(self):
        """When selected_peak_ids is None, all peaks contribute to tap_tone_ratio."""
        air = _make_peak(freq=95.0, mag=-25.0)
        top = _make_peak(freq=195.0, mag=-28.0)
        m = TapToneMeasurement.create(
            peaks=[air, top], selected_peak_ids=None, guitar_type="Classical",
        )
        assert m.tap_tone_ratio is not None


# ---------------------------------------------------------------------------
# Annotation visibility mode on TapToneMeasurement (moved from test_annotation_state.py)
# Mirrors Swift TapToneMeasurementCodableTests: annotationVisibilityMode field
# ---------------------------------------------------------------------------

class TestAnnotationVisibilityMode:
    """TapToneMeasurement annotation_visibility_mode storage and round-trip.

    Moved from test_annotation_state.py. Mirrors Swift AnnotationStateTests D4–D6.
    """

    def test_D4_visibility_mode_stored_as_string(self):
        """D4: annotation_visibility_mode is stored and round-trips."""
        m = TapToneMeasurement.create(peaks=[], annotation_visibility_mode="showAll")
        restored = _round_trip(m)
        assert restored.annotation_visibility_mode == "showAll"

    def test_D5_all_visibility_values_survive_round_trip(self):
        """D5: All three visibility mode strings encode/decode correctly."""
        for mode in ("showAll", "showSelected", "hideAll"):
            m = TapToneMeasurement.create(peaks=[], annotation_visibility_mode=mode)
            restored = _round_trip(m)
            assert restored.annotation_visibility_mode == mode, (
                f"Visibility mode '{mode}' did not survive round-trip"
            )

    def test_D6_none_visibility_mode_not_written(self):
        """D6: When annotation_visibility_mode is None, key absent from JSON."""
        m = TapToneMeasurement.create(peaks=[], annotation_visibility_mode=None)
        d = m.to_dict()
        assert "annotationVisibilityMode" not in d

    def test_CI5_visibility_mode_cycle(self):
        """CI5: All three visibility mode strings can be stored on the measurement."""
        modes = ["showAll", "showSelected", "hideAll"]
        for mode in modes:
            m = TapToneMeasurement.create(peaks=[], annotation_visibility_mode=mode)
            assert m.annotation_visibility_mode == mode


# ---------------------------------------------------------------------------
# Mode overrides on TapToneMeasurement (moved from test_annotation_state.py)
# Mirrors Swift TapToneMeasurementCodableTests: peakModeOverrides round-trip
# ---------------------------------------------------------------------------

class TestModeOverrides:
    """TapToneMeasurement peak_mode_overrides storage and round-trip.

    Moved from test_annotation_state.py. Mirrors Swift AnnotationStateTests D7–D8.
    """

    def test_D7_mode_overrides_stored_per_peak(self):
        """D7: peak_mode_overrides keyed by peak UUID stores custom mode labels."""
        p = _make_peak(freq=200.0)
        overrides = {p.id: "Top"}
        m = TapToneMeasurement.create(peaks=[p], peak_mode_overrides=overrides)
        assert m.peak_mode_overrides is not None
        assert m.peak_mode_overrides[p.id] == "Top"

    def test_D8_mode_overrides_survive_json_round_trip(self):
        """D8: peak_mode_overrides are preserved across JSON round-trip."""
        p = _make_peak(freq=200.0)
        overrides = {p.id: "Dipole"}
        m = TapToneMeasurement.create(peaks=[p], peak_mode_overrides=overrides)
        restored = _round_trip(m)
        assert restored.peak_mode_overrides is not None
        assert restored.peak_mode_overrides.get(p.id) == "Dipole"

    def test_empty_overrides_not_written(self):
        """Empty peak_mode_overrides should not write the key to JSON."""
        m = TapToneMeasurement.create(peaks=[], peak_mode_overrides=None)
        d = m.to_dict()
        assert "peakModeOverrides" not in d

    def test_auto_type_entries_not_decoded(self):
        """Entries with type=='auto' in the JSON are ignored on decode (no override)."""
        p = _make_peak()
        d = TapToneMeasurement.create(peaks=[p]).to_dict()
        d["peakModeOverrides"] = {p.id: {"type": "auto", "label": "Air (Helmholtz)"}}
        restored = TapToneMeasurement.from_dict(d)
        assert restored.peak_mode_overrides is None or p.id not in (restored.peak_mode_overrides or {})


# ---------------------------------------------------------------------------
# selected_peak_ids / selected_peak_frequencies JSON fields
# (moved from test_annotation_state.py)
# Mirrors Swift TapToneMeasurementCodableTests: selectedPeakIDs field round-trip
# ---------------------------------------------------------------------------

class TestPeakSelectionTracking:
    """TapToneMeasurement selected_peak_ids + selected_peak_frequencies JSON fields.

    Moved from test_annotation_state.py. Mirrors Swift AnnotationStateTests PS1–PS6
    data-layer subset.
    """

    def test_PS1_selected_peak_ids_list_stored(self):
        """PS1: selected_peak_ids is stored as a list of UUID strings."""
        peaks = [_make_peak() for _ in range(3)]
        ids = [peaks[0].id, peaks[1].id]
        m = TapToneMeasurement.create(peaks=peaks, selected_peak_ids=ids)
        assert m.selected_peak_ids == ids

    def test_PS2_selected_peak_frequencies_parallel_to_ids(self):
        """PS2: selected_peak_frequencies is parallel to selected_peak_ids."""
        peaks = [_make_peak(freq=200.0), _make_peak(freq=300.0)]
        m = TapToneMeasurement.create(
            peaks=peaks,
            selected_peak_ids=[peaks[0].id],
            selected_peak_frequencies=[200.0],
        )
        assert m.selected_peak_frequencies == [200.0]

    def test_PS3_both_none_means_all_selected(self):
        """PS3: None selected_peak_ids means all peaks are treated as selected."""
        peaks = [_make_peak() for _ in range(3)]
        m = TapToneMeasurement.create(peaks=peaks, selected_peak_ids=None)
        assert m.selected_peak_ids is None

    def test_PS4_selected_peak_ids_round_trip(self):
        """PS4: selected_peak_ids survives JSON round-trip."""
        p = _make_peak()
        m = TapToneMeasurement.create(peaks=[p], selected_peak_ids=[p.id])
        restored = _round_trip(m)
        assert restored.selected_peak_ids == [p.id]

    def test_PS5_selected_peak_frequencies_round_trip(self):
        """PS5: selected_peak_frequencies survives JSON round-trip."""
        p = _make_peak(freq=440.0)
        m = TapToneMeasurement.create(
            peaks=[p], selected_peak_ids=[p.id], selected_peak_frequencies=[440.0],
        )
        restored = _round_trip(m)
        assert restored.selected_peak_frequencies == [440.0]

    def test_PS6_empty_selection_list_round_trips_to_none(self):
        """PS6: An empty selected_peak_ids list is treated as 'not set' on decode."""
        m = TapToneMeasurement.create(peaks=[], selected_peak_ids=[])
        assert m.selected_peak_ids is None


# ---------------------------------------------------------------------------
# Spectrum snapshot storage on TapToneMeasurement (moved from test_frozen_peak_recalculation.py)
# Mirrors Swift MeasurementCodableTests SpectrumSnapshotOnMeasurement suite
# ---------------------------------------------------------------------------

class TestLiveTapPath:
    """TapToneMeasurement spectrum_snapshot storage — moved from test_frozen_peak_recalculation.py.

    These tests belong here because they test TapToneMeasurement data fields,
    not recalculation logic. Mirrors Swift SpectrumSnapshotOnMeasurement.
    """

    def test_spectrumSnapshot_newMeasurement_isNil(self):
        """A freshly created measurement with no snapshot has spectrum_snapshot == None."""
        m = TapToneMeasurement.create(peaks=[], spectrum_snapshot=None)
        assert m.spectrum_snapshot is None, (
            "New measurement should not have a spectrum snapshot"
        )

    def test_spectrumSnapshot_withSnapshot_stored(self):
        """A measurement created with a snapshot stores it correctly."""
        snap = SpectrumSnapshot(frequencies=[100.0, 200.0], magnitudes=[-40.0, -35.0])
        m = TapToneMeasurement.create(peaks=[], spectrum_snapshot=snap)
        assert m.spectrum_snapshot is snap


# ---------------------------------------------------------------------------
# TapToneRatio
# ---------------------------------------------------------------------------

class TestTapToneRatio:
    """Mirrors Swift TapToneRatioTests."""

    def test_ratio_is_none_when_no_peaks(self):
        m = TapToneMeasurement.create(peaks=[], guitar_type="Classical")
        assert m.tap_tone_ratio is None

    def test_ratio_computed_for_air_and_top(self):
        """With an Air peak at 95 Hz and Top peak at 190 Hz, ratio ≈ 2.0."""
        air = _make_peak(freq=95.0, mag=-25.0)   # in classical Air range (80-110)
        top = _make_peak(freq=190.0, mag=-28.0)  # in classical Top range (170-230)
        m = TapToneMeasurement.create(
            peaks=[air, top],
            guitar_type="Classical",
        )
        ratio = m.tap_tone_ratio
        assert ratio is not None, "tap_tone_ratio should not be None"
        assert abs(ratio - 2.0) < 0.1, f"Expected ratio ~2.0; got {ratio:.3f}"

    def test_ratio_is_none_when_air_missing(self):
        """Without an Air peak, ratio cannot be computed → None."""
        top = _make_peak(freq=195.0, mag=-28.0)
        m = TapToneMeasurement.create(peaks=[top], guitar_type="Classical")
        assert m.tap_tone_ratio is None

    def test_ratio_uses_selected_peaks_when_set(self):
        """tap_tone_ratio uses only selectedPeakIDs when present."""
        air = _make_peak(freq=95.0, mag=-25.0)
        top = _make_peak(freq=190.0, mag=-28.0)
        # Select only the Air peak — ratio cannot be computed
        m = TapToneMeasurement.create(
            peaks=[air, top],
            guitar_type="Classical",
            selected_peak_ids=[air.id],
        )
        # With only Air selected, Top is excluded → ratio = None
        assert m.tap_tone_ratio is None, (
            "ratio should be None when Top peak is not in selected peaks"
        )


# ---------------------------------------------------------------------------
# with_() method
# ---------------------------------------------------------------------------

class TestWithMethod:
    """Mirrors Swift UpdateMeasurementTests."""

    def test_with_updates_tap_location(self):
        m = TapToneMeasurement.create(peaks=[], tap_location="Old")
        updated = m.with_(tap_location="New", notes=None)
        assert updated.tap_location == "New"
        assert updated.id == m.id          # ID preserved

    def test_with_updates_notes(self):
        m = TapToneMeasurement.create(peaks=[], notes="old notes")
        updated = m.with_(tap_location=None, notes="new notes")
        assert updated.notes == "new notes"

    def test_with_clears_tap_location_with_none(self):
        m = TapToneMeasurement.create(peaks=[], tap_location="Bridge")
        updated = m.with_(tap_location=None, notes=None)
        assert updated.tap_location is None

    def test_with_preserves_other_fields(self):
        peak = _make_peak()
        snap = _make_snapshot()
        m = TapToneMeasurement.create(
            peaks=[peak],
            spectrum_snapshot=snap,
            decay_time=0.5,
            tap_location="Bridge",
        )
        updated = m.with_(tap_location="Neck", notes=None)
        assert updated.peaks == [peak]
        assert updated.spectrum_snapshot == snap
        assert updated.decay_time == 0.5


# ---------------------------------------------------------------------------
# ComparisonEntry and TapToneMeasurement with comparisonEntries (Phase 2)
# Mirrors Swift ComparisonEntryCodableTests
# ---------------------------------------------------------------------------

class TestComparisonEntryCodable:
    """JSON round-trip tests for ComparisonEntry and TapToneMeasurement.comparisonEntries.

    Mirrors Swift ComparisonEntryCodableTests.
    """

    def _make_entry(
        self,
        label: str = "Bridge",
        guitar_type: str | None = "Classical",
    ):
        """Create a minimal ComparisonEntry for testing."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        snap = _make_snapshot()
        peak = _make_peak()
        return ComparisonEntry(
            id=str(uuid.uuid4()),
            label=label,
            color_components=[0.2, 0.4, 0.8, 1.0],
            snapshot=snap,
            peaks=[peak],
            guitar_type=guitar_type,
            source_measurement_id=None,
        )

    def test_comparison_entry_to_dict_has_required_keys(self):
        """ComparisonEntry.to_dict() should include id, label, colorComponents, snapshot, peaks."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        entry = self._make_entry()
        d = entry.to_dict()
        assert "id" in d
        assert "label" in d
        assert "colorComponents" in d
        assert "snapshot" in d
        assert "peaks" in d

    def test_comparison_entry_round_trip_preserves_id(self):
        """ComparisonEntry id survives to_dict() / from_dict() round-trip."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        entry = self._make_entry()
        restored = ComparisonEntry.from_dict(entry.to_dict())
        assert restored.id == entry.id

    def test_comparison_entry_round_trip_preserves_label(self):
        """ComparisonEntry label survives round-trip."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        entry = self._make_entry(label="Neck Joint")
        restored = ComparisonEntry.from_dict(entry.to_dict())
        assert restored.label == "Neck Joint"

    def test_comparison_entry_round_trip_preserves_color_components(self):
        """color_components [r,g,b,a] survive round-trip."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        entry = self._make_entry()
        restored = ComparisonEntry.from_dict(entry.to_dict())
        for orig, rt in zip(entry.color_components, restored.color_components):
            assert abs(orig - rt) < 1e-9

    def test_comparison_entry_round_trip_preserves_guitar_type(self):
        """guitar_type string survives round-trip."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        entry = self._make_entry(guitar_type="Acoustic")
        restored = ComparisonEntry.from_dict(entry.to_dict())
        assert restored.guitar_type == "Acoustic"

    def test_comparison_entry_none_guitar_type_omitted_from_dict(self):
        """guitar_type=None should not write the 'guitarType' key to the dict."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        entry = self._make_entry(guitar_type=None)
        d = entry.to_dict()
        assert "guitarType" not in d

    def test_comparison_entry_round_trip_preserves_peak_count(self):
        """Peak list length is preserved through round-trip."""
        from guitar_tap.models.tap_tone_measurement import ComparisonEntry
        snap = _make_snapshot()
        peaks = [_make_peak(freq=100.0 + i * 50.0) for i in range(3)]
        entry = ComparisonEntry(
            id=str(uuid.uuid4()), label="Multi",
            color_components=[0.0, 0.0, 1.0, 1.0],
            snapshot=snap, peaks=peaks, guitar_type="Classical",
            source_measurement_id=None,
        )
        restored = ComparisonEntry.from_dict(entry.to_dict())
        assert len(restored.peaks) == 3

    def test_tap_tone_measurement_round_trip_with_comparison_entries(self):
        """A TapToneMeasurement with comparisonEntries serialises and deserialises correctly."""
        entry1 = self._make_entry(label="Bridge")
        entry2 = self._make_entry(label="Neck")
        m = TapToneMeasurement.create(
            peaks=[],
            tap_location="My Comparison",
            comparison_entries=[entry1, entry2],
        )
        restored = _round_trip(m)
        assert restored.is_comparison
        assert restored.comparison_entries is not None
        assert len(restored.comparison_entries) == 2
        labels = [e.label for e in restored.comparison_entries]
        assert "Bridge" in labels
        assert "Neck" in labels

    def test_measurement_without_comparison_entries_has_none(self):
        """A regular measurement (no comparisonEntries key in JSON) decodes with None."""
        m = TapToneMeasurement.create(peaks=[])
        d = m.to_dict()
        assert "comparisonEntries" not in d
        restored = TapToneMeasurement.from_dict(d)
        assert restored.comparison_entries is None
        assert not restored.is_comparison

    def test_is_comparison_property_true_for_comparison_record(self):
        """is_comparison returns True when comparison_entries is not None."""
        m = TapToneMeasurement.create(peaks=[], comparison_entries=[self._make_entry()])
        assert m.is_comparison

    def test_is_comparison_property_false_for_regular_measurement(self):
        """is_comparison returns False for a regular tap measurement."""
        m = TapToneMeasurement.create(peaks=[])
        assert not m.is_comparison


# ---------------------------------------------------------------------------
# Fixture loading (skipped if file not present)
# ---------------------------------------------------------------------------

class TestFixtureLoading:
    """Mirrors Swift FixtureLoadingTests — skipped when fixture not found."""

    def test_fixture_loads_and_decodes(self):
        fixture_name = "contreras-classical-1774731564.guitartap"
        # Mirror Swift: look next to the test file (same directory as __file__),
        # mirroring `URL(fileURLWithPath: #file).deletingLastPathComponent()`.
        here = os.path.dirname(os.path.abspath(__file__))
        fixture_path_candidate = os.path.join(here, fixture_name)
        fixture_path = fixture_path_candidate if os.path.exists(fixture_path_candidate) else None

        if fixture_path is None:
            pytest.skip(f"Fixture '{fixture_name}' not found; skipping fixture test")

        with open(fixture_path, encoding="utf-8") as f:
            raw = json.load(f)

        measurements = [TapToneMeasurement.from_dict(d) for d in raw]
        assert len(measurements) > 0, "Fixture should contain at least one measurement"
        for m in measurements:
            for peak in m.peaks:
                assert 0 < peak.frequency < 20000, (
                    f"Peak frequency {peak.frequency} Hz out of valid audio range"
                )
