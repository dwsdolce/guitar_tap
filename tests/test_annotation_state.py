"""
Port of AnnotationStateTests.swift — annotation offsets, peak selection,
annotation visibility, and mode overrides stored on TapToneMeasurement.

Mirrors Swift AnnotationStateTests covering:
  D1–D2: annotation_offsets round-trip and storage
  D3/D3b: selected_peak_ids and tap_tone_ratio filtering
  D4–D6: annotation_visibility_mode values
  D7–D8: peak_mode_overrides round-trip
  CI5:   annotation_visibility_mode cycle
  PS1–PS6: selected_peak_ids / selected_peak_frequencies tracking

Python note: the Swift tests drive TapToneAnalyzer state directly; in Python
the equivalent state lives on TapToneMeasurement fields.  Tests here validate
that state is correctly stored, serialised, and round-tripped.
"""

from __future__ import annotations

import json
import sys, os
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _peak(freq: float = 200.0, mag: float = -30.0) -> ResonantPeak:
    return ResonantPeak(
        id=str(uuid.uuid4()),
        frequency=freq,
        magnitude=mag,
        quality=10.0,
        bandwidth=freq / 10.0,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _make_snapshot() -> SpectrumSnapshot:
    return SpectrumSnapshot(
        frequencies=[100.0, 200.0, 300.0],
        magnitudes=[-40.0, -35.0, -45.0],
    )


def _round_trip(m: TapToneMeasurement) -> TapToneMeasurement:
    """Serialise to JSON then decode, producing an independent copy."""
    return TapToneMeasurement.from_dict(json.loads(json.dumps(m.to_dict())))


# ---------------------------------------------------------------------------
# D1–D2: Annotation offsets
# ---------------------------------------------------------------------------

class TestAnnotationOffsets:
    """Mirrors Swift AnnotationStateTests D1–D2."""

    def test_D1_offsets_stored_per_peak(self):
        """D1: annotation_offsets keyed by peak UUID can store different positions per peak."""
        p1 = _peak(freq=200.0)
        p2 = _peak(freq=300.0)
        offsets = {
            p1.id.upper(): [200.0, -40.0],
            p2.id.upper(): [300.0, -35.0],
        }
        m = TapToneMeasurement.create(
            peaks=[p1, p2], annotation_offsets=offsets
        )
        assert m.annotation_offsets is not None
        assert m.annotation_offsets[p1.id.upper()] == [200.0, -40.0]
        assert m.annotation_offsets[p2.id.upper()] == [300.0, -35.0]

    def test_D2_annotation_offsets_survive_json_round_trip(self):
        """D2: annotation_offsets are preserved across a JSON round-trip."""
        p = _peak(freq=440.0)
        offsets = {p.id.upper(): [440.0, -25.0]}
        m = TapToneMeasurement.create(peaks=[p], annotation_offsets=offsets)
        restored = _round_trip(m)
        assert restored.annotation_offsets is not None
        stored = restored.annotation_offsets.get(p.id.upper())
        assert stored is not None, "Offset should survive round-trip"
        assert abs(stored[0] - 440.0) < 0.01
        assert abs(stored[1] - (-25.0)) < 0.01


# ---------------------------------------------------------------------------
# D3/D3b: Peak selection
# ---------------------------------------------------------------------------

class TestPeakSelection:
    """Mirrors Swift AnnotationStateTests D3/D3b."""

    def test_D3_selected_peak_ids_stored(self):
        """D3: selected_peak_ids is stored and round-trips through JSON."""
        p1 = _peak(freq=95.0)
        p2 = _peak(freq=195.0)
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
        air = _peak(freq=95.0, mag=-25.0)
        top = _peak(freq=195.0, mag=-28.0)
        noise = _peak(freq=500.0, mag=-50.0)

        # Select only air and top
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
        air = _peak(freq=95.0, mag=-25.0)
        top = _peak(freq=195.0, mag=-28.0)
        m = TapToneMeasurement.create(
            peaks=[air, top],
            selected_peak_ids=None,
            guitar_type="Classical",
        )
        ratio = m.tap_tone_ratio
        assert ratio is not None


# ---------------------------------------------------------------------------
# D4–D6: Annotation visibility mode
# ---------------------------------------------------------------------------

class TestAnnotationVisibilityMode:
    """Mirrors Swift AnnotationStateTests D4–D6."""

    def test_D4_visibility_mode_stored_as_string(self):
        """D4: annotation_visibility_mode is stored and round-trips."""
        m = TapToneMeasurement.create(
            peaks=[], annotation_visibility_mode="showAll"
        )
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
        """CI5: Cycling through visibility modes via saved state."""
        modes = ["showAll", "showSelected", "hideAll"]
        for mode in modes:
            m = TapToneMeasurement.create(peaks=[], annotation_visibility_mode=mode)
            assert m.annotation_visibility_mode == mode


# ---------------------------------------------------------------------------
# D7–D8: Mode overrides
# ---------------------------------------------------------------------------

class TestModeOverrides:
    """Mirrors Swift AnnotationStateTests D7–D8."""

    def test_D7_mode_overrides_stored_per_peak(self):
        """D7: peak_mode_overrides keyed by peak UUID stores custom mode labels."""
        p = _peak(freq=200.0)
        overrides = {p.id: "Top"}
        m = TapToneMeasurement.create(peaks=[p], peak_mode_overrides=overrides)
        assert m.peak_mode_overrides is not None
        assert m.peak_mode_overrides[p.id] == "Top"

    def test_D8_mode_overrides_survive_json_round_trip(self):
        """D8: peak_mode_overrides are preserved across JSON round-trip."""
        p = _peak(freq=200.0)
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
        p = _peak()
        d = TapToneMeasurement.create(peaks=[p]).to_dict()
        d["peakModeOverrides"] = {
            p.id: {"type": "auto", "label": "Air (Helmholtz)"},
        }
        restored = TapToneMeasurement.from_dict(d)
        # type=='auto' should not create an override entry
        assert restored.peak_mode_overrides is None or p.id not in (restored.peak_mode_overrides or {})


# ---------------------------------------------------------------------------
# PS1–PS6: selected_peak_ids / selected_peak_frequencies tracking
# ---------------------------------------------------------------------------

class TestPeakSelectionTracking:
    """Mirrors Swift AnnotationStateTests PS1–PS6."""

    def test_PS1_selected_peak_ids_list_stored(self):
        """PS1: selected_peak_ids is stored as a list of UUID strings."""
        peaks = [_peak() for _ in range(3)]
        ids = [peaks[0].id, peaks[1].id]
        m = TapToneMeasurement.create(peaks=peaks, selected_peak_ids=ids)
        assert m.selected_peak_ids == ids

    def test_PS2_selected_peak_frequencies_parallel_to_ids(self):
        """PS2: selected_peak_frequencies is parallel to selected_peak_ids."""
        peaks = [_peak(freq=200.0), _peak(freq=300.0)]
        m = TapToneMeasurement.create(
            peaks=peaks,
            selected_peak_ids=[peaks[0].id],
            selected_peak_frequencies=[200.0],
        )
        assert m.selected_peak_frequencies == [200.0]

    def test_PS3_both_none_means_all_selected(self):
        """PS3: None selected_peak_ids means all peaks are treated as selected."""
        peaks = [_peak() for _ in range(3)]
        m = TapToneMeasurement.create(peaks=peaks, selected_peak_ids=None)
        assert m.selected_peak_ids is None

    def test_PS4_selected_peak_ids_round_trip(self):
        """PS4: selected_peak_ids survives JSON round-trip."""
        p = _peak()
        m = TapToneMeasurement.create(peaks=[p], selected_peak_ids=[p.id])
        restored = _round_trip(m)
        assert restored.selected_peak_ids == [p.id]

    def test_PS5_selected_peak_frequencies_round_trip(self):
        """PS5: selected_peak_frequencies survives JSON round-trip."""
        p = _peak(freq=440.0)
        m = TapToneMeasurement.create(
            peaks=[p],
            selected_peak_ids=[p.id],
            selected_peak_frequencies=[440.0],
        )
        restored = _round_trip(m)
        assert restored.selected_peak_frequencies == [440.0]

    def test_PS6_empty_selection_list_round_trips_to_none(self):
        """PS6: An empty selected_peak_ids list is treated as 'not set' on decode."""
        # create() filters out empty lists
        m = TapToneMeasurement.create(peaks=[], selected_peak_ids=[])
        # create() converts empty list → None (via `or None`)
        assert m.selected_peak_ids is None
