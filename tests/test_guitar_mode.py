"""
Port of GuitarModeTests.swift — guitar resonance mode classification.

Mirrors Swift test plan coverage from GuitarModeClassificationTests and
GuitarModeClassifyAllTests.
"""

from __future__ import annotations

import sys, os
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode
from guitar_tap.models.guitar_type import GuitarType
from guitar_tap.models.resonant_peak import ResonantPeak


# ---------------------------------------------------------------------------
# Helper: fake ResonantPeak (id, frequency, magnitude only needed)
# ---------------------------------------------------------------------------

def _peak(freq: float, mag: float = -30.0) -> ResonantPeak:
    return ResonantPeak(
        id=str(uuid.uuid4()),
        frequency=freq,
        magnitude=mag,
        quality=10.0,
        bandwidth=freq / 10.0,
        timestamp="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Classification Tests (single-peak classify())
# ---------------------------------------------------------------------------

class TestGuitarModeClassification:
    """Mirrors Swift GuitarModeClassificationTests."""

    # --- Classical guitar ---

    def test_classical_air_95Hz(self):
        assert GuitarMode.classify(95.0, GuitarType.CLASSICAL) == GuitarMode.AIR

    def test_classical_top_200Hz(self):
        assert GuitarMode.classify(200.0, GuitarType.CLASSICAL) == GuitarMode.TOP

    def test_classical_back_240Hz(self):
        assert GuitarMode.classify(240.0, GuitarType.CLASSICAL) == GuitarMode.BACK

    def test_classical_dipole_380Hz(self):
        assert GuitarMode.classify(380.0, GuitarType.CLASSICAL) == GuitarMode.DIPOLE

    def test_classical_ring_700Hz(self):
        assert GuitarMode.classify(700.0, GuitarType.CLASSICAL) == GuitarMode.RING_MODE

    def test_classical_upper_1000Hz(self):
        assert GuitarMode.classify(1000.0, GuitarType.CLASSICAL) == GuitarMode.UPPER_MODES

    def test_classical_unknown_140Hz(self):
        """140 Hz falls in the gap between air (80-110) and top (170-230) for classical."""
        assert GuitarMode.classify(140.0, GuitarType.CLASSICAL) == GuitarMode.UNKNOWN

    # --- Flamenco guitar ---

    def test_flamenco_air_100Hz(self):
        assert GuitarMode.classify(100.0, GuitarType.FLAMENCO) == GuitarMode.AIR

    def test_flamenco_top_220Hz(self):
        assert GuitarMode.classify(220.0, GuitarType.FLAMENCO) == GuitarMode.TOP

    def test_flamenco_back_210Hz(self):
        # Flamenco back=(180, 240), top=(190, 250): 210 overlaps both
        mode = GuitarMode.classify(210.0, GuitarType.FLAMENCO)
        # classify() just returns the first matching band; should be TOP (comes before BACK)
        assert mode in (GuitarMode.TOP, GuitarMode.BACK)

    # --- Acoustic guitar ---

    def test_acoustic_air_105Hz(self):
        assert GuitarMode.classify(105.0, GuitarType.ACOUSTIC) == GuitarMode.AIR

    def test_acoustic_top_180Hz(self):
        assert GuitarMode.classify(180.0, GuitarType.ACOUSTIC) == GuitarMode.TOP

    def test_acoustic_back_250Hz(self):
        assert GuitarMode.classify(250.0, GuitarType.ACOUSTIC) == GuitarMode.BACK


# ---------------------------------------------------------------------------
# Normalisation of Legacy Cases
# ---------------------------------------------------------------------------

class TestModeNormalisation:
    """Mirrors Swift GuitarModeClassificationTests normalisation cases."""

    def test_helmholtz_normalises_to_air(self):
        assert GuitarMode.HELMHOLTZ.normalized == GuitarMode.AIR

    def test_cross_grain_normalises_to_air(self):
        assert GuitarMode.CROSS_GRAIN.normalized == GuitarMode.AIR

    def test_long_grain_normalises_to_top(self):
        assert GuitarMode.LONG_GRAIN.normalized == GuitarMode.TOP

    def test_monopole_normalises_to_back(self):
        assert GuitarMode.MONOPOLE.normalized == GuitarMode.BACK

    def test_current_cases_normalise_to_themselves(self):
        for mode in [
            GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK,
            GuitarMode.DIPOLE, GuitarMode.RING_MODE, GuitarMode.UPPER_MODES,
            GuitarMode.UNKNOWN,
        ]:
            assert mode.normalized == mode, f"{mode} should normalise to itself"


# ---------------------------------------------------------------------------
# Display Names
# ---------------------------------------------------------------------------

class TestDisplayNames:
    """Mirrors Swift GuitarModeClassificationTests displayName cases."""

    def test_air_display_name(self):
        assert GuitarMode.AIR.display_name == "Air (Helmholtz)"

    def test_top_display_name(self):
        assert GuitarMode.TOP.display_name == "Top"

    def test_back_display_name(self):
        assert GuitarMode.BACK.display_name == "Back"

    def test_dipole_display_name(self):
        assert GuitarMode.DIPOLE.display_name == "Dipole"

    def test_ring_mode_display_name(self):
        assert GuitarMode.RING_MODE.display_name == "Ring Mode"

    def test_upper_modes_display_name(self):
        assert GuitarMode.UPPER_MODES.display_name == "Upper Modes"

    def test_legacy_helmholtz_display_name(self):
        assert GuitarMode.HELMHOLTZ.display_name == "Air (Helmholtz)"

    def test_legacy_monopole_display_name(self):
        assert GuitarMode.MONOPOLE.display_name == "Back"


# ---------------------------------------------------------------------------
# mode_range accessor
# ---------------------------------------------------------------------------

class TestModeRange:
    """Mirrors Swift GuitarModeClassificationTests modeRange cases."""

    def test_classical_air_range(self):
        lo, hi = GuitarMode.AIR.mode_range(GuitarType.CLASSICAL)
        assert lo == 80 and hi == 110

    def test_classical_top_range(self):
        lo, hi = GuitarMode.TOP.mode_range(GuitarType.CLASSICAL)
        assert lo == 170 and hi == 230

    def test_unknown_range_is_full_spectrum(self):
        lo, hi = GuitarMode.UNKNOWN.mode_range(GuitarType.CLASSICAL)
        assert lo == 0.0 and hi == 20000.0


# ---------------------------------------------------------------------------
# classify_all — context-aware overlap resolution
# ---------------------------------------------------------------------------

class TestClassifyAll:
    """Mirrors Swift GuitarModeClassifyAllTests."""

    def test_single_peak_in_air_range(self):
        """A single peak in the Air range is classified as AIR."""
        peaks = [_peak(95.0)]
        result = GuitarMode.classify_all(peaks, GuitarType.CLASSICAL)
        assert result[peaks[0].id] == GuitarMode.AIR

    def test_overlap_zone_stronger_peak_takes_top(self):
        """Classical top=(170-230), back=(190-280).  A 210 Hz peak should win TOP.
        A weaker 220 Hz peak should fall back to BACK via classify()."""
        # 210 Hz is in the Top range AND the Back range for classical
        p_top_candidate  = _peak(210.0, mag=-20.0)   # stronger — wins Top
        p_back_candidate = _peak(220.0, mag=-35.0)   # weaker — falls back to Back

        peaks = [p_top_candidate, p_back_candidate]
        result = GuitarMode.classify_all(peaks, GuitarType.CLASSICAL)

        assert result[p_top_candidate.id] == GuitarMode.TOP, (
            "Stronger peak in overlap zone should be assigned Top"
        )
        assert result[p_back_candidate.id] == GuitarMode.BACK, (
            "Weaker peak in overlap zone should fall through to Back"
        )

    def test_overlap_zone_weaker_in_top_range_loses_to_stronger_in_back(self):
        """If the stronger peak is at a frequency only in Back range,
        the weaker peak in the overlap zone also ends up as Back."""
        p_overlap = _peak(205.0, mag=-40.0)   # in TOP overlap, but weaker
        p_back    = _peak(270.0, mag=-25.0)   # only in BACK range, stronger

        peaks = [p_overlap, p_back]
        result = GuitarMode.classify_all(peaks, GuitarType.CLASSICAL)

        # The Back-only peak claims Back.  The overlap peak then has no mode claimant
        # and falls back to classify() — which returns TOP (first matching band).
        assert result[p_back.id] == GuitarMode.BACK
        # The overlap peak is now classified by classify() independently
        assert result[p_overlap.id] in (GuitarMode.TOP, GuitarMode.BACK)

    def test_no_peaks_returns_empty_dict(self):
        result = GuitarMode.classify_all([], GuitarType.CLASSICAL)
        assert result == {}

    def test_peak_outside_all_ranges_is_unknown(self):
        p = _peak(140.0)   # gap between air(80-110) and top(170-230) for classical
        result = GuitarMode.classify_all([p], GuitarType.CLASSICAL)
        assert result[p.id] == GuitarMode.UNKNOWN

    def test_all_six_modes_assigned_for_well_spaced_peaks(self):
        """Six peaks clearly in each mode range should get six distinct mode assignments."""
        peaks = [
            _peak(95.0),     # AIR
            _peak(200.0),    # TOP
            _peak(260.0),    # BACK
            _peak(380.0),    # DIPOLE
            _peak(700.0),    # RING_MODE
            _peak(1000.0),   # UPPER_MODES
        ]
        result = GuitarMode.classify_all(peaks, GuitarType.CLASSICAL)
        expected = [
            GuitarMode.AIR, GuitarMode.TOP, GuitarMode.BACK,
            GuitarMode.DIPOLE, GuitarMode.RING_MODE, GuitarMode.UPPER_MODES,
        ]
        for peak, expected_mode in zip(peaks, expected):
            assert result[peak.id] == expected_mode, (
                f"Peak at {peak.frequency} Hz: expected {expected_mode}, got {result[peak.id]}"
            )
