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

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode
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


# ---------------------------------------------------------------------------
# Live TapToneAnalyzer tests — mirrors Swift AnnotationStateTests driving the
# analyzer instance directly (not TapToneMeasurement data structures).
# ---------------------------------------------------------------------------

import sys
from PySide6 import QtWidgets

_APP_LIVE: "QtWidgets.QApplication | None" = None


def _get_app_live():
    global _APP_LIVE
    if _APP_LIVE is None:
        _APP_LIVE = (
            QtWidgets.QApplication.instance()
            or QtWidgets.QApplication(sys.argv)
        )
    return _APP_LIVE


def _make_sut():
    _get_app_live()
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer()


def _make_peak_live(freq: float = 200.0, mag: float = -20.0) -> ResonantPeak:
    return ResonantPeak(
        id=str(uuid.uuid4()),
        frequency=freq,
        magnitude=mag,
        quality=10.0,
        bandwidth=freq / 10.0,
    )


class TestAnnotationStateLive:
    """Port of Swift AnnotationStateTests driving TapToneAnalyzer state directly.

    Covers: D1–D2 (offsets), D3/D3b (toggle/select/clear/reset),
    D4–D6 (visible_peaks), D7–D8 (mode overrides), CI5 (cycle),
    PS1–PS6 (plate peak selection — on the analyzer instance).
    """

    # ── D1: updateAnnotationOffset stores offset by peak ID ──────────────

    def test_D1_update_annotation_offset_stores_by_id(self):
        """D1: update_annotation_offset stores (x,y) keyed by peak UUID."""
        sut = _make_sut()
        p = _make_peak_live()
        sut.update_annotation_offset(p.id, (10.0, 20.0))
        stored = sut.peak_annotation_offsets.get(p.id)
        assert stored is not None
        assert stored == (10.0, 20.0)

    def test_D1b_update_annotation_offset_overwrites_previous(self):
        """D1b: Updating an offset twice keeps the latest value."""
        sut = _make_sut()
        p = _make_peak_live()
        sut.update_annotation_offset(p.id, (1.0, 2.0))
        sut.update_annotation_offset(p.id, (99.0, 88.0))
        stored = sut.peak_annotation_offsets.get(p.id)
        assert stored == (99.0, 88.0)

    # ── D2: apply_annotation_offsets bulk-populates the dict ─────────────

    def test_D2_apply_annotation_offsets_populates_dictionary(self):
        """D2: apply_annotation_offsets bulk-replaces peak_annotation_offsets."""
        sut = _make_sut()
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        sut.apply_annotation_offsets({id1: (5.0, 10.0), id2: (15.0, 20.0)})
        assert sut.peak_annotation_offsets[id1] == (5.0, 10.0)
        assert sut.peak_annotation_offsets[id2] == (15.0, 20.0)

    # ── D3: togglePeakSelection inserts then removes ──────────────────────

    def test_D3_toggle_peak_selection_inserts_then_removes(self):
        """D3: Toggling same peak ID twice results in empty selected_peak_ids."""
        sut = _make_sut()
        pid = str(uuid.uuid4())

        sut.toggle_peak_selection(pid)
        assert pid in sut.selected_peak_ids, "After first toggle peak should be selected"

        sut.toggle_peak_selection(pid)
        assert pid not in sut.selected_peak_ids, "After second toggle peak should be deselected"

    def test_D3_select_all_peaks_selects_all_current_peaks(self):
        """selectAllPeaks populates selected_peak_ids with all current_peaks IDs."""
        sut = _make_sut()
        peaks = [_make_peak_live(100), _make_peak_live(200), _make_peak_live(300)]
        sut.current_peaks = peaks
        sut.select_all_peaks()
        for p in peaks:
            assert p.id in sut.selected_peak_ids, (
                f"Peak {p.frequency} Hz should be selected after select_all_peaks"
            )

    def test_D3_select_no_peaks_clears_all(self):
        """selectNoPeaks clears all selections."""
        sut = _make_sut()
        sut.current_peaks = [_make_peak_live(100), _make_peak_live(200)]
        sut.select_all_peaks()
        sut.select_no_peaks()
        assert len(sut.selected_peak_ids) == 0

    # ── D3b: userHasModifiedPeakSelection flag ────────────────────────────

    def test_D3b_toggle_peak_selection_sets_modified_flag(self):
        """toggle_peak_selection sets user_has_modified_peak_selection."""
        sut = _make_sut()
        assert not sut.user_has_modified_peak_selection
        sut.toggle_peak_selection(str(uuid.uuid4()))
        assert sut.user_has_modified_peak_selection

    def test_D3b_select_all_peaks_sets_modified_flag(self):
        """select_all_peaks sets user_has_modified_peak_selection."""
        sut = _make_sut()
        sut.current_peaks = [_make_peak_live()]
        sut.select_all_peaks()
        assert sut.user_has_modified_peak_selection

    def test_D3b_select_no_peaks_sets_modified_flag(self):
        """select_no_peaks sets user_has_modified_peak_selection."""
        sut = _make_sut()
        sut.select_no_peaks()
        assert sut.user_has_modified_peak_selection

    def test_D3b_reset_to_auto_selection_clears_flag_and_selects_best_per_mode(self):
        """reset_to_auto_selection clears the flag and auto-selects best per mode."""
        sut = _make_sut()
        # Two peaks in the acoustic Air range (90–120 Hz); louder one should win.
        quiet_air = _make_peak_live(freq=98.0, mag=-50.0)
        loud_air = _make_peak_live(freq=105.0, mag=-30.0)
        sut.current_peaks = [quiet_air, loud_air]
        sut.user_has_modified_peak_selection = True
        sut.selected_peak_ids = set()

        sut.reset_to_auto_selection()

        assert not sut.user_has_modified_peak_selection, (
            "Flag should be cleared after reset_to_auto_selection"
        )
        assert loud_air.id in sut.selected_peak_ids, (
            "Loudest Air peak should be auto-selected"
        )
        assert quiet_air.id not in sut.selected_peak_ids, (
            "Quieter Air peak should not be selected"
        )

    def test_D3b_reset_to_auto_selection_empty_peaks_is_noop(self):
        """reset_to_auto_selection on empty current_peaks is a no-op (no crash)."""
        sut = _make_sut()
        sut.user_has_modified_peak_selection = True
        sut.reset_to_auto_selection()
        assert not sut.user_has_modified_peak_selection
        assert len(sut.selected_peak_ids) == 0

    # ── D4–D6: visible_peaks ──────────────────────────────────────────────

    def test_D4_all_mode_returns_all_current_peaks(self):
        """D4: annotation_visibility_mode='all' → visible_peaks == current_peaks."""
        sut = _make_sut()
        sut.annotation_visibility_mode = "all"
        peaks = [_make_peak_live(100), _make_peak_live(200), _make_peak_live(300)]
        sut.current_peaks = peaks
        assert len(sut.visible_peaks) == 3

    def test_D5_selected_mode_filters_to_selected_peaks(self):
        """D5: annotation_visibility_mode='selected' → only selected peaks visible."""
        sut = _make_sut()
        sut.annotation_visibility_mode = "selected"
        p1 = _make_peak_live(100)
        p2 = _make_peak_live(200)
        p3 = _make_peak_live(300)
        sut.current_peaks = [p1, p2, p3]
        sut.selected_peak_ids = {p1.id, p3.id}

        visible = sut.visible_peaks
        assert len(visible) == 2
        assert any(abs(p.frequency - 100) < 1 for p in visible)
        assert any(abs(p.frequency - 300) < 1 for p in visible)
        assert not any(abs(p.frequency - 200) < 1 for p in visible)

    def test_D6_none_mode_returns_empty(self):
        """D6: annotation_visibility_mode='none' → visible_peaks is empty."""
        sut = _make_sut()
        sut.annotation_visibility_mode = "none"
        sut.current_peaks = [_make_peak_live(), _make_peak_live(300)]
        sut.select_all_peaks()
        assert sut.visible_peaks == []

    # ── D7–D8: Mode overrides ─────────────────────────────────────────────

    def test_D7_no_override_returns_auto_label(self):
        """D7: No override → label comes from GuitarMode.classify_peak."""
        sut = _make_sut()
        # 100 Hz is in the Air (Helmholtz) range for classical/acoustic.
        p = _make_peak_live(freq=100.0)
        label = sut.effective_mode_label(p)
        assert label == "Air (Helmholtz)", (
            f"Expected 'Air (Helmholtz)' for 100 Hz, got '{label}'"
        )

    def test_D8_assigned_override_returns_custom_label(self):
        """D8: set_mode_override with a label returns that label."""
        sut = _make_sut()
        p = _make_peak_live(freq=200.0)
        sut.set_mode_override("My Label", p.id)
        assert sut.effective_mode_label(p) == "My Label"

    def test_D8b_has_manual_override_true_for_assigned_false_for_auto(self):
        """has_manual_override is True only for assigned overrides."""
        sut = _make_sut()
        p = _make_peak_live()
        sut.set_mode_override("auto", p.id)
        assert not sut.has_manual_override(p.id), ".auto should not be a manual override"
        sut.set_mode_override("Test", p.id)
        assert sut.has_manual_override(p.id), "Assigned label should be a manual override"

    def test_D8c_clear_override_reverts_to_auto_label(self):
        """Clearing an override (set_mode_override None) reverts to auto-classification."""
        sut = _make_sut()
        p = _make_peak_live(freq=100.0)
        sut.set_mode_override("Temp", p.id)
        sut.set_mode_override(None, p.id)
        label = sut.effective_mode_label(p)
        assert label == "Air (Helmholtz)"

    # ── CI5: cycle_annotation_visibility ─────────────────────────────────

    def test_CI5_cycle_annotation_visibility_traverses_all_modes(self):
        """CI5: Three calls traverse all → selected → none → all."""
        sut = _make_sut()
        sut.annotation_visibility_mode = AnnotationVisibilityMode.ALL

        sut.cycle_annotation_visibility()
        assert sut.annotation_visibility_mode == AnnotationVisibilityMode.SELECTED

        sut.cycle_annotation_visibility()
        assert sut.annotation_visibility_mode == AnnotationVisibilityMode.NONE

        sut.cycle_annotation_visibility()
        assert sut.annotation_visibility_mode == AnnotationVisibilityMode.ALL

    # ── PS1–PS6: Plate peak selection on the analyzer ────────────────────

    def test_PS1_select_longitudinal_peak_selects_new_peak(self):
        """PS1: selectLongitudinalPeak sets user_selected_longitudinal_peak_id."""
        sut = _make_sut()
        pid = str(uuid.uuid4())
        sut.select_longitudinal_peak(pid)
        assert sut.user_selected_longitudinal_peak_id == pid

    def test_PS2_select_longitudinal_peak_deselects_current(self):
        """PS2: Selecting the already-selected longitudinal peak deselects it."""
        sut = _make_sut()
        pid = str(uuid.uuid4())
        sut.user_selected_longitudinal_peak_id = pid
        sut.select_longitudinal_peak(pid)
        assert sut.user_selected_longitudinal_peak_id is None

    def test_PS3_select_longitudinal_peak_clears_cross_conflict(self):
        """PS3: selectLongitudinalPeak clears a conflicting cross assignment."""
        sut = _make_sut()
        shared = str(uuid.uuid4())
        sut.user_selected_cross_peak_id = shared
        sut.select_longitudinal_peak(shared)
        assert sut.user_selected_longitudinal_peak_id == shared
        assert sut.user_selected_cross_peak_id is None

    def test_PS4_select_longitudinal_peak_clears_flc_conflict(self):
        """PS4: selectLongitudinalPeak clears a conflicting FLC assignment."""
        sut = _make_sut()
        shared = str(uuid.uuid4())
        sut.user_selected_flc_peak_id = shared
        sut.select_longitudinal_peak(shared)
        assert sut.user_selected_longitudinal_peak_id == shared
        assert sut.user_selected_flc_peak_id is None

    def test_PS5_select_cross_peak_clears_longitudinal_conflict(self):
        """PS5: selectCrossPeak clears a conflicting longitudinal assignment."""
        sut = _make_sut()
        shared = str(uuid.uuid4())
        sut.user_selected_longitudinal_peak_id = shared
        sut.select_cross_peak(shared)
        assert sut.user_selected_cross_peak_id == shared
        assert sut.user_selected_longitudinal_peak_id is None

    def test_PS6_select_flc_peak_clears_cross_conflict(self):
        """PS6: selectFlcPeak clears a conflicting cross assignment."""
        sut = _make_sut()
        shared = str(uuid.uuid4())
        sut.user_selected_cross_peak_id = shared
        sut.select_flc_peak(shared)
        assert sut.user_selected_flc_peak_id == shared
        assert sut.user_selected_cross_peak_id is None
