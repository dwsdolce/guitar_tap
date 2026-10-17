# @parity test/measurement-codable
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
import uuid
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.utilities.new_uuid import new_uuid
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


def _create(**fields) -> TapToneMeasurement:
    """A measurement as the app saves one — with its spectrum — unless the test gives its own: a file
    holding a measurement without a spectrum cannot be read."""
    return TapToneMeasurement.create(**{"spectrum_snapshot": _make_snapshot(), **fields})


def _make_peak(
    freq: float = 200.0,
    mag: float = -30.0,
    quality: float = 10.0,
    pitch_note: str | None = None,
    pitch_cents: float | None = None,
    pitch_freq: float | None = None,
) -> ResonantPeak:
    return ResonantPeak(
        id=new_uuid(),
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

    def test_axis_ranges_preserved(self):
        """min/max freq/db round-trip exactly."""
        snap = _make_snapshot(min_freq=50.0, max_freq=1500.0, min_db=-100.0, max_db=0.0)
        restored = SpectrumSnapshot.from_dict(snap.to_dict())
        assert restored.min_freq == 50.0
        assert restored.max_freq == 1500.0
        assert restored.min_db == -100.0
        assert restored.max_db == 0.0

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
        m = _create(
            peaks=[peak],
            spectrum_snapshot=snap,
            measurement_name="Bridge",
            decay_time=0.45,
            number_of_taps=3,
            sample_rate=48000,
        )
        d = m.to_dict()
        raw_json = json.dumps(d)
        restored = TapToneMeasurement.from_dict(json.loads(raw_json))

        assert restored.id == m.id
        assert restored.measurement_name == "Bridge"
        assert abs(restored.decay_time - 0.45) < 0.001
        assert restored.number_of_taps == 3
        assert len(restored.peaks) == 1
        assert abs(restored.peaks[0].frequency - 200.0) < 0.001
        assert restored.sample_rate == 48000

    def test_annotation_offsets_round_trip(self):
        """Annotation offsets survive a JSON round-trip using the Swift flat-array format."""
        peak = _make_peak()
        offsets = {peak.id: [300.0, -45.0]}
        m = _create(peaks=[peak], annotation_offsets=offsets)
        restored = TapToneMeasurement.from_dict(m.to_dict())

        assert restored.annotation_offsets is not None
        assert peak.id in restored.annotation_offsets
        stored = restored.annotation_offsets[peak.id]
        assert abs(stored[0] - 300.0) < 0.01
        assert abs(stored[1] - (-45.0)) < 0.01

    def test_empty_annotation_offsets_round_trip(self):
        """None annotation_offsets omits the key (matches Swift encodeIfPresent(nil))
        and decodes back to None."""
        m = _create(peaks=[], annotation_offsets=None)
        d = m.to_dict()
        assert "peakAnnotationOffsets" not in d
        restored = TapToneMeasurement.from_dict(d)
        assert restored.annotation_offsets is None

    def test_explicit_empty_annotation_offsets_preserved(self):
        """A Swift file with an explicit empty [] (non-nil empty [UUID: …]) decodes
        to {} and re-encodes to [], preserving Swift's nil-vs-empty distinction."""
        src = {
            "id": "00000000-0000-0000-0000-0000000000EE",
            "timestamp": "2026-01-01T00:00:00Z",
            "peaks": [],
            "peakAnnotationOffsets": [],
            "spectrumSnapshot": _make_snapshot().to_dict(),
        }
        m = TapToneMeasurement.from_dict(src)
        assert m.annotation_offsets == {}
        d = m.to_dict()
        assert d["peakAnnotationOffsets"] == []

    def test_mode_overrides_round_trip(self):
        """per-peak mode overrides survive a JSON round-trip."""
        peak = _make_peak()
        overrides = {peak.id: "Top"}
        m = _create(peaks=[peak], peak_mode_overrides=overrides)
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
            p1.id: [200.0, -40.0],
            p2.id: [300.0, -35.0],
        }
        m = _create(peaks=[p1, p2], annotation_offsets=offsets)
        assert m.annotation_offsets is not None
        assert m.annotation_offsets[p1.id] == [200.0, -40.0]
        assert m.annotation_offsets[p2.id] == [300.0, -35.0]

    def test_D2_annotation_offsets_survive_json_round_trip(self):
        """D2: annotation_offsets are preserved across a JSON round-trip."""
        p = _make_peak(freq=440.0)
        offsets = {p.id: [440.0, -25.0]}
        m = _create(peaks=[p], annotation_offsets=offsets)
        restored = _round_trip(m)
        assert restored.annotation_offsets is not None
        stored = restored.annotation_offsets.get(p.id)
        assert stored is not None, "Offset should survive round-trip"
        assert abs(stored[0] - 440.0) < 0.01
        assert abs(stored[1] - (-25.0)) < 0.01


# ---------------------------------------------------------------------------
# Peak selection on TapToneMeasurement (moved from test_annotation_state.py)
# Mirrors Swift PeakSelectionOnMeasurementTests (D3)
# ---------------------------------------------------------------------------

class TestPeakSelection:
    """TapToneMeasurement selected_peak_ids storage.

    Moved from test_annotation_state.py — tests TapToneMeasurement fields.
    Mirrors Swift PeakSelectionOnMeasurementTests D3. The ratio over the selection is the shared
    cases (test_tap_tone_ratio).
    """

    def test_D3_selected_peak_ids_stored(self):
        """D3: selected_peak_ids is stored and round-trips through JSON."""
        p1 = _make_peak(freq=95.0)
        p2 = _make_peak(freq=195.0)
        m = _create(
            peaks=[p1, p2],
            selected_peak_ids=[p1.id],
            selected_peak_frequencies=[95.0],
        )
        restored = _round_trip(m)
        assert restored.selected_peak_ids == [p1.id]
        assert restored.selected_peak_frequencies == [95.0]


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
        m = _create(peaks=[], annotation_visibility_mode="showAll")
        restored = _round_trip(m)
        assert restored.annotation_visibility_mode == "showAll"

    def test_D5_all_visibility_values_survive_round_trip(self):
        """D5: All three visibility mode strings encode/decode correctly."""
        for mode in ("showAll", "showSelected", "hideAll"):
            m = _create(peaks=[], annotation_visibility_mode=mode)
            restored = _round_trip(m)
            assert restored.annotation_visibility_mode == mode, (
                f"Visibility mode '{mode}' did not survive round-trip"
            )

    def test_CI5_visibility_mode_cycle(self):
        """CI5: All three visibility mode strings can be stored on the measurement."""
        modes = ["showAll", "showSelected", "hideAll"]
        for mode in modes:
            m = _create(peaks=[], annotation_visibility_mode=mode)
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
        m = _create(peaks=[p], peak_mode_overrides=overrides)
        assert m.peak_mode_overrides is not None
        assert m.peak_mode_overrides[p.id] == "Top"

    def test_D8_mode_overrides_survive_json_round_trip(self):
        """D8: peak_mode_overrides are preserved across JSON round-trip."""
        p = _make_peak(freq=200.0)
        overrides = {p.id: "Dipole"}
        m = _create(peaks=[p], peak_mode_overrides=overrides)
        restored = _round_trip(m)
        assert restored.peak_mode_overrides is not None
        assert restored.peak_mode_overrides.get(p.id) == "Dipole"


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
        m = _create(peaks=peaks, selected_peak_ids=ids)
        assert m.selected_peak_ids == ids

    def test_PS2_selected_peak_frequencies_parallel_to_ids(self):
        """PS2: selected_peak_frequencies is parallel to selected_peak_ids."""
        peaks = [_make_peak(freq=200.0), _make_peak(freq=300.0)]
        m = _create(
            peaks=peaks,
            selected_peak_ids=[peaks[0].id],
            selected_peak_frequencies=[200.0],
        )
        assert m.selected_peak_frequencies == [200.0]

    def test_PS3_both_none_means_all_selected(self):
        """PS3: None selected_peak_ids means all peaks are treated as selected."""
        peaks = [_make_peak() for _ in range(3)]
        m = _create(peaks=peaks, selected_peak_ids=None)
        assert m.selected_peak_ids is None

    def test_PS4_selected_peak_ids_round_trip(self):
        """PS4: selected_peak_ids survives JSON round-trip."""
        p = _make_peak()
        m = _create(peaks=[p], selected_peak_ids=[p.id])
        restored = _round_trip(m)
        assert restored.selected_peak_ids == [p.id]

    def test_PS5_selected_peak_frequencies_round_trip(self):
        """PS5: selected_peak_frequencies survives JSON round-trip."""
        p = _make_peak(freq=440.0)
        m = _create(
            peaks=[p], selected_peak_ids=[p.id], selected_peak_frequencies=[440.0],
        )
        restored = _round_trip(m)
        assert restored.selected_peak_frequencies == [440.0]

    def test_PS6_empty_selection_round_trips_as_select_none(self):
        """PS6: An empty selection is Select None — it reads back empty, not as 'no selection saved'."""
        m = _create(peaks=[], selected_peak_ids=[])
        assert _round_trip(m).selected_peak_ids == []


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
# Fixture loading (skipped if file not present)
# ---------------------------------------------------------------------------

class TestFixtureLoading:
    """Mirrors Swift FixtureLoadingTests — skipped when fixture not found."""

    @staticmethod
    def _load_raw() -> list:
        """Load the Contreras fixture array, or skip when it is not present."""
        fixture_name = "contreras-classical-1774731564.guitartap"
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, fixture_name)
        if not os.path.exists(path):
            pytest.skip(f"Fixture '{fixture_name}' not found; skipping fixture test")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_contreras_round_trip_preserves_fields(self):
        """Decode -> re-encode -> re-decode preserves every modeled field, mapping the
        legacy keys on the way in. Pinned identically in the Swift FixtureLoadingTests
        and the GuitarTapWeb g5-measurement-codable suite so the three writers can't
        drift. The Contreras file is an OLD save, so it also exercises legacy decode."""
        raw = self._load_raw()
        m = TapToneMeasurement.from_dict(raw[0])

        # Field + legacy-decode assertions.
        assert len(m.peaks) == 44
        assert raw[0].get("peakThreshold") == -78 and "peakMinThreshold" not in raw[0]
        assert m.peak_min_threshold == -78          # legacy peakThreshold -> peak_min_threshold
        assert m.sample_rate is None                 # absent -> unknown
        assert m.measurement_name == "Contreras Classical"
        assert m.number_of_taps == 10
        s = m.spectrum_snapshot
        assert s.measurement_type == "Classical Guitar"
        assert s.guitar_type == "Classical"
        assert (s.min_freq, s.max_freq, s.min_db, s.max_db) == (75, 350, -100, 0)
        assert len(s.frequencies) == len(s.magnitudes) > 0
        p0 = m.peaks[0]
        assert p0.id == uuid.UUID("95037FB0-44FE-4163-9937-CBCD57BC1469")
        assert abs(p0.frequency - 212.24847) < 1e-3
        assert p0.pitch_note == "G#3"

        # Semantic round-trip: decode(encode(decode(file))) preserves the fields.
        again = TapToneMeasurement.from_dict(json.loads(json.dumps(m.to_dict())))
        assert len(again.peaks) == len(m.peaks)
        assert again.peak_min_threshold == m.peak_min_threshold
        assert again.sample_rate == m.sample_rate
        assert again.spectrum_snapshot.frequencies == m.spectrum_snapshot.frequencies
        assert again.spectrum_snapshot.magnitudes == m.spectrum_snapshot.magnitudes
        assert [p.frequency for p in again.peaks] == [p.frequency for p in m.peaks]

    def test_contreras_writer_emits_canonical_keys_only(self):
        """to_dict writes only current keys, never legacy ones (writer = minimal
        canonical; the reader owns backward compatibility)."""
        m = TapToneMeasurement.from_dict(self._load_raw()[0])
        d = m.to_dict()
        assert d["peakMinThreshold"] == -78
        assert "peakThreshold" not in d              # legacy key never written
        assert "hysteresisMargin" not in d           # unknown field dropped
        assert "maxPeaks" not in d["spectrumSnapshot"]
        assert d["measurementType"] == "Classical Guitar"
        assert d["guitarType"] == "Classical"
        assert d["peaks"][0]["modeLabel"] == "Top"   # convenience label, top-level peaks


# ---------------------------------------------------------------------------
# The measurement's logic — the shared cases in measurement-codable.json
#
# The tap-tone ratio (TR), the mode label each peak is written with (ML), and the selection heal on
# decode (SH): the same cases as Swift and the web. Mirrors Swift MeasurementLogicTests.
# ---------------------------------------------------------------------------

with open(os.path.join(os.path.dirname(__file__), "measurement-codable.json"), encoding="utf-8") as _f:
    LOGIC = json.load(_f)


def _case_measurement(row: dict) -> "tuple[TapToneMeasurement, dict]":
    """A case's measurement, and its peaks by the case's peak ids."""
    by_name = {p["id"]: ResonantPeak(id=new_uuid(), frequency=p["frequency"], magnitude=p["magnitude"])
               for p in row["peaks"]}
    peaks = [by_name[p["id"]] for p in row["peaks"]]
    selected = [by_name[n].id for n in row["selected"]] if row["selected"] is not None else None
    overrides = {by_name[n].id: label for n, label in row["overrides"].items()} or None
    material = row.get("material", False)
    guitar_type = None if material else LOGIC["guitarType"]
    measurement_type = None if material else LOGIC["measurementType"]
    snapshot = SpectrumSnapshot(frequencies=[100.0, 200.0], magnitudes=[-60.0, -60.0], min_freq=50, max_freq=500,
                                min_db=-100, max_db=0, guitar_type=guitar_type, measurement_type=measurement_type)
    m = TapToneMeasurement.create(
        peaks=peaks,
        spectrum_snapshot=None if material else snapshot,
        longitudinal_snapshot=snapshot if material else None,
        selected_peak_ids=selected,
        peak_mode_overrides=overrides,
        guitar_type=guitar_type,
        measurement_type=measurement_type,
    )
    return m, by_name


def _ratio_matches(ratio, expected) -> bool:
    if expected is None:
        return ratio is None
    return ratio is not None and abs(ratio - expected) <= LOGIC["ratioTolerance"]


@pytest.mark.parametrize("row", LOGIC["tapToneRatio"], ids=lambda r: r["id"])
def test_tap_tone_ratio(row):
    m, by_name = _case_measurement(row)
    assert _ratio_matches(m.tap_tone_ratio, row["expect"]), f"{row['id']}: saved ratio {m.tap_tone_ratio} — {row['note']}"
    if not row.get("live"):
        return
    from guitar_tap.models.guitar_mode import GuitarMode
    from guitar_tap.models.measurement_type import MeasurementType
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    saved_type = TapDisplaySettings.measurement_type()
    TapDisplaySettings.set_measurement_type(MeasurementType.CLASSICAL)
    try:
        from PySide6 import QtWidgets
        QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        sut = TapToneAnalyzer()
        sut.all_peaks = list(m.peaks)
        sut.reclassify_peaks()
        sut.selected_peak_ids = set(m.selected_peak_ids or [])
        for name, label in row["overrides"].items():
            sut.set_mode_override(label, by_name[name].id)
        live = sut.calculate_tap_tone_ratio()
        assert _ratio_matches(live, row["expect"]), f"{row['id']}: live ratio {live} — the saved and live ratios must agree"
    finally:
        TapDisplaySettings.set_measurement_type(saved_type)


@pytest.mark.parametrize("row", LOGIC["modeLabels"], ids=lambda r: r["id"])
def test_mode_labels(row):
    m, _ = _case_measurement(row)
    # A file whose peaks already carry `storedLabels`: written, the labels set, read back.
    d = m.to_dict()
    for peak, label in zip(d["peaks"], row["storedLabels"]):
        if label is None:
            peak.pop("modeLabel", None)
        else:
            peak["modeLabel"] = label
    read = TapToneMeasurement.from_dict(d)
    labels = [p.get("modeLabel") for p in read.to_dict()["peaks"]]
    assert labels == row["expect"], f"{row['id']}: written — {row['note']}"
    shown = read.peak_mode_labels
    assert [shown.get(p.id) for p in read.peaks] == row["expect"], f"{row['id']}: displayed — {row['note']}"


@pytest.mark.parametrize("row", LOGIC["selectionHeal"], ids=lambda r: r["id"])
def test_selection_heal(row):
    m, by_name = _case_measurement(row)
    d = m.to_dict()
    if row["selected"] is None:
        d.pop("selectedPeakIDs", None)
    read = TapToneMeasurement.from_dict(d)
    assert read.was_healed == row["expectHealed"], f"{row['id']}: healed — {row['note']}"
    assert set(read.selected_peak_ids or []) == {by_name[n].id for n in row["expectSelected"]}, \
        f"{row['id']}: selection — {row['note']}"


# ---------------------------------------------------------------------------
# The file format — the shared cases in measurement-codable.json
#
# The spectrum's bytes (SB), what a file reads to (DC), what the writer emits (WR), a comparison
# record (CR) and the real fixtures every edition carries: the same cases as Swift and the web.
# Mirrors Swift MeasurementCodecTests.
# ---------------------------------------------------------------------------

import re  # noqa: E402

import numpy as np  # noqa: E402

from guitar_tap.views.tap_analysis_results_view import measurements_from_json, measurements_to_json  # noqa: E402

_LEGACY_KEYS = ("tapLocation", "peakThreshold", "hysteresisMargin", "maxPeaks")


def _has_key(key: str, value) -> bool:
    """Whether ``key`` appears anywhere in a JSON document."""
    if isinstance(value, dict):
        return key in value or any(_has_key(key, v) for v in value.values())
    if isinstance(value, list):
        return any(_has_key(key, v) for v in value)
    return False


def _present(path: str, doc) -> bool:
    """``peaks[].k`` — the key on every peak of every measurement; otherwise the key anywhere."""
    if path.startswith("peaks[]."):
        k = path[len("peaks[]."):]
        peaks = [p for m in doc for p in m.get("peaks", [])]
        return bool(peaks) and all(k in p for p in peaks)
    return _has_key(path, doc)


def _f32(values) -> list:
    return [float(np.float32(v)) for v in values]


@pytest.mark.parametrize("row", LOGIC["snapshotBytes"], ids=lambda r: r["id"])
def test_snapshot_bytes(row):
    snap = SpectrumSnapshot(frequencies=row["frequencies"], magnitudes=row["magnitudes"],
                            min_freq=50, max_freq=500, min_db=-100, max_db=0)
    d = snap.to_dict()
    assert d["frequenciesData"] == row["frequenciesData"]
    assert d["magnitudesData"] == row["magnitudesData"]
    assert "frequencies" not in d and "magnitudes" not in d
    back = SpectrumSnapshot.from_dict(d)
    assert _f32(back.frequencies) == _f32(row["frequencies"])
    assert _f32(back.magnitudes) == _f32(row["magnitudes"])


_UUID_TEXT = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


@pytest.mark.parametrize("row", LOGIC["ids"], ids=lambda r: r["id"])
def test_id_rule(row):
    if row.get("rejected"):
        with pytest.raises(Exception):
            measurements_from_json(json.dumps(row["file"]))
        return
    m = measurements_from_json(json.dumps(row["file"]))[0]
    freq = {p.id: str(round(p.frequency)) for p in m.peaks}
    for field, want in row["expect"].items():
        if field == "selectedFrequencies":
            got = [float(next(p.frequency for p in m.peaks if p.id == i)) for i in (m.selected_peak_ids or [])]
            assert got == want, f"{row['id']} {field}: {got}"
        elif field == "overrideLabels":
            got = {freq[k]: v for k, v in (m.peak_mode_overrides or {}).items() if k in freq}
            assert got == want, f"{row['id']} {field}: {got}"
        elif field == "offsets":
            got = {freq[k]: [float(v[0]), float(v[1])] for k, v in (m.annotation_offsets or {}).items() if k in freq}
            assert got == want, f"{row['id']} {field}: {got}"
        elif field == "writtenLowercaseIds":
            lower = [u for u in _UUID_TEXT.findall(measurements_to_json([m])) if u != u.upper()]
            assert len(lower) == want, f"{row['id']} {field}: {lower}"
        else:
            pytest.fail(f"{row['id']}: unknown field {field}")


@pytest.mark.parametrize("row", LOGIC["decode"], ids=lambda r: r["id"])
def test_decode(row):
    if row.get("rejected"):
        with pytest.raises(Exception):
            measurements_from_json(json.dumps(row["file"]))
        return
    m = measurements_from_json(json.dumps(row["file"]))[0]
    for field, want in row["expect"].items():
        if field == "measurementName":
            assert m.measurement_name == want, field
        elif field == "peakMinThreshold":
            assert m.peak_min_threshold == want, field
        elif field == "sampleRate":
            assert m.sample_rate == want, field
        elif field == "frequencies":
            assert _f32(m.spectrum_snapshot.frequencies) == _f32(want), field
        elif field == "magnitudes":
            assert _f32(m.spectrum_snapshot.magnitudes) == _f32(want), field
        elif field == "overrides":
            assert dict(m.peak_mode_overrides or {}) == {uuid.UUID(k): v for k, v in want.items()}, field
        elif field == "peakCount":
            assert len(m.peaks) == want, field
        elif field == "pitchNote":
            assert m.peaks[0].pitch_note == want, field
        elif field == "annotationVisibilityMode":
            assert m.annotation_visibility_mode == want, field
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", LOGIC["write"], ids=lambda r: r["id"])
def test_write(row):
    text = measurements_to_json(measurements_from_json(json.dumps(row["file"])))
    doc = json.loads(text)
    for key in row.get("present", []):
        assert _present(key, doc), f"{key} written"
    for key in row.get("absent", []):
        assert not _has_key(key, doc), f"{key} not written"
    for key, number in row.get("text", {}).items():
        found = re.search(rf'"{re.escape(key)}":\s*([^,}}\]\s]+)', text)
        assert found and found.group(1) == number, f"{key} written as {number}"
    compact = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    for s in row.get("contains", []):
        assert s in compact, f"contains {s}"


@pytest.mark.parametrize("row", LOGIC["comparison"], ids=lambda r: r["id"])
def test_comparison(row):
    from guitar_tap.models.guitar_mode import GuitarMode
    first = measurements_from_json(json.dumps(row["file"]))[0]
    m, doc = first, None
    if row.get("roundTrip"):
        text = measurements_to_json([first])
        doc = json.loads(text)
        m = measurements_from_json(text)[0]
    for field, want in row["expect"].items():
        if field == "isComparison":
            assert m.is_comparison == want, field
        elif field == "healed":
            assert first.was_healed == want, field
        elif field == "entries":
            if want is None:
                assert m.comparison_entries is None, field
                continue
            assert len(m.comparison_entries) == len(want), f"{field}: count"
            for e, w in zip(m.comparison_entries, want):
                for key, value in w.items():
                    if key == "id":
                        assert e.id == uuid.UUID(value), "entry id"
                    elif key == "label":
                        assert e.label == value, "entry label"
                    elif key == "colorComponents":
                        assert list(e.color_components) == value, "entry colour"
                    elif key == "guitarType":
                        assert e.guitar_type == value, "entry guitarType"
                    elif key == "peakCount":
                        assert len(e.peaks) == value, "entry peakCount"
                    elif key == "modePeakIds":
                        assert dict(e.mode_peak_ids or {}) == {k: uuid.UUID(v) for k, v in value.items()}, "entry modePeakIds"
                    else:
                        pytest.fail(f"unknown entry field {key}")
        elif field == "modeFrequency":
            e = m.comparison_entries[0]
            for name, hz in want.items():
                assert e.mode_frequency(GuitarMode(name)) == hz, f"{field} {name}"
        elif field == "absent":
            assert doc is not None, "absent needs roundTrip"
            for key in want:
                assert not _has_key(key, doc), f"{key} not written"
        else:
            pytest.fail(f"unknown field {field}")


@pytest.mark.parametrize("row", LOGIC["fixtures"], ids=lambda r: r["file"])
def test_fixture(row):
    with open(os.path.join(os.path.dirname(__file__), row["file"]), encoding="utf-8") as f:
        ms = measurements_from_json(f.read())
    assert len(ms) == row["measurements"]
    m = ms[0]
    assert m.measurement_name == row["measurementName"]
    assert len(m.peaks) == row["peakCount"]
    assert m.sample_rate == row["sampleRate"]
    assert m.is_comparison == row["isComparison"]
    assert sorted((m.peak_mode_overrides or {}).values()) == sorted(row["overrideLabels"])
    peak_ids = {p.id for p in m.peaks}
    for peak_id in (m.peak_mode_overrides or {}):
        assert peak_id in peak_ids, "the override names a peak the file contains"

    text = measurements_to_json(ms)
    doc = json.loads(text)
    for legacy in _LEGACY_KEYS:
        assert not _has_key(legacy, doc), f"{legacy} not written"
    with open(os.path.join(os.path.dirname(__file__), row["file"]), encoding="utf-8") as f:
        original = json.load(f)
    for written, read in zip(doc, original):
        read_snap = read.get("spectrumSnapshot") or {}
        if "frequenciesData" not in read_snap:
            continue
        for key in ("frequenciesData", "magnitudesData"):
            assert written["spectrumSnapshot"][key] == read_snap[key], f"{key} written as read"
    again = measurements_from_json(text)
    assert len(again) == len(ms)
    for a, b in zip(again, ms):
        assert _f32(p.frequency for p in a.peaks) == _f32(p.frequency for p in b.peaks)
        sa, sb = a.spectrum_snapshot, b.spectrum_snapshot
        assert (sa is None) == (sb is None)
        if sa is not None:
            assert _f32(sa.frequencies) == _f32(sb.frequencies)
            assert _f32(sa.magnitudes) == _f32(sb.magnitudes)
