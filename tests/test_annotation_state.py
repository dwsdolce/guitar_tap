"""
Port of AnnotationStateTests.swift — live TapToneAnalyzer state:
annotation offsets, peak selection, visibility filtering, mode overrides,
plate peak selection, and update_measurement.

All tests operate on TapToneAnalyzer instance state directly.
TapToneMeasurement JSON round-trip tests live in test_measurement_codable.py.

Mirrors Swift AnnotationStateTests covering:
  D1–D2:   annotation offset storage on the live analyzer
  D3/D3b:  toggle/select/clear/reset on the live analyzer
  D4–D6:   visible_peaks on the live analyzer
  D7–D8:   mode overrides on the live analyzer
  CI5:     annotation_visibility_mode cycle on the live analyzer
  PS1–PS6: plate peak selection on the live analyzer
  UpdateMeasurement: update_measurement() on the live analyzer
"""

from __future__ import annotations

import sys
import os
import uuid

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.annotation_visibility_mode import AnnotationVisibilityMode
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Update Measurement — mirrors Swift @Suite("UpdateMeasurement") in
# AnnotationStateTests.swift. Tests update_measurement() on the live analyzer.
# ---------------------------------------------------------------------------


def _make_measurement(location=None, notes=None):
    return TapToneMeasurement.create(peaks=[], tap_location=location, notes=notes)


def _make_analyzer_with_measurements(measurements):
    sut = _make_sut()
    # update_measurement() reads/writes savedMeasurements (camelCase).
    sut.savedMeasurements = list(measurements)
    return sut


class TestUpdateMeasurement:
    """Port of Swift UpdateMeasurementTests — update_measurement() on the live analyzer.

    Mirrors Swift @Suite("UpdateMeasurement") in AnnotationStateTests.swift.
    """

    def test_update_by_index_changes_only_targeted_entry(self):
        """Updating by index changes only the targeted entry's location and notes."""
        m0 = _make_measurement(location="Bridge", notes="First")
        m1 = _make_measurement(location="Soundhole", notes="Second")
        sut = _make_analyzer_with_measurements([m0, m1])

        sut.update_measurement(at=0, tap_location="Upper Bout", notes="Edited")

        assert sut.savedMeasurements[0].tap_location == "Upper Bout"
        assert sut.savedMeasurements[0].notes == "Edited"
        assert sut.savedMeasurements[1].tap_location == "Soundhole", "Second entry must not be affected"
        assert sut.savedMeasurements[1].notes == "Second", "Second entry must not be affected"

    def test_update_duplicate_import_only_edited_index_changes(self):
        """Editing one of two duplicates (same id, different index) leaves the other unchanged."""
        original = _make_measurement(location="Top", notes="Original")
        # Simulate importing the same file twice — both entries share the same id.
        sut = _make_analyzer_with_measurements([original, original])

        sut.update_measurement(at=1, tap_location="Back", notes="Copy")

        assert sut.savedMeasurements[0].tap_location == "Top",  "First duplicate must not change"
        assert sut.savedMeasurements[0].notes == "Original",    "First duplicate must not change"
        assert sut.savedMeasurements[1].tap_location == "Back", "Second duplicate should be updated"
        assert sut.savedMeasurements[1].notes == "Copy",        "Second duplicate should be updated"
        assert sut.savedMeasurements[0].id == sut.savedMeasurements[1].id, \
            "id must be preserved through the update"

    def test_update_nil_values_clear_fields(self):
        """Passing None clears the fields."""
        m = _make_measurement(location="Bridge", notes="Some notes")
        sut = _make_analyzer_with_measurements([m])

        sut.update_measurement(at=0, tap_location=None, notes=None)

        assert sut.savedMeasurements[0].tap_location is None
        assert sut.savedMeasurements[0].notes is None

    def test_update_out_of_range_index_is_noop(self):
        """An out-of-range index is a no-op."""
        m = _make_measurement(location="Bridge")
        sut = _make_analyzer_with_measurements([m])

        sut.update_measurement(at=99, tap_location="Changed", notes=None)

        assert sut.savedMeasurements[0].tap_location == "Bridge", "Out-of-range update must not modify array"
        assert len(sut.savedMeasurements) == 1

    def test_update_preserves_id_and_other_fields(self):
        """The id and all other fields are preserved after an update."""
        from guitar_tap.models.resonant_peak import ResonantPeak
        peak = ResonantPeak(
            id=str(uuid.uuid4()),
            frequency=195.0, magnitude=-22.0, quality=10.0, bandwidth=19.5,
        )
        m = TapToneMeasurement.create(
            peaks=[peak], decay_time=0.5, tap_location="Old", notes="Old notes"
        )
        original_id = m.id
        sut = _make_analyzer_with_measurements([m])

        sut.update_measurement(at=0, tap_location="New", notes="New notes")

        updated = sut.savedMeasurements[0]
        assert updated.id == original_id, "id must be preserved"
        assert len(updated.peaks) == 1,   "peaks must be preserved"
        assert updated.decay_time == 0.5, "decay_time must be preserved"
        assert updated.tap_location == "New"
        assert updated.notes == "New notes"
