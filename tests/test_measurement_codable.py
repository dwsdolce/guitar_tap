"""
Port of MeasurementCodableTests.swift — JSON round-trip, snapshot encoding,
tapToneRatio, export labels, updateMeasurement.

Mirrors Swift test suites:
  SpectrumSnapshotCodableTests
  ResonantPeakCodableTests
  TapToneMeasurementCodableTests
  TapToneRatioTests
  MeasurementExportModeLabelTests
  UpdateMeasurementTests
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
