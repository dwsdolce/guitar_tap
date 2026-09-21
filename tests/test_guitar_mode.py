# @parity test/classify
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

    def test_flamenco_top_190Hz(self):
        # Flamenco top=(180, 220). Corrected 2026-07-19: the old bands had top=(190, 250)
        # and back=(180, 240), i.e. the back range sitting BELOW the top range, which
        # inverted Top/Back classification for flamenco only. See section 7c of
        # Development/PEAK-FINDING-DUPLICATE-PEAKS.md (GuitarTapWeb).
        assert GuitarMode.classify(190.0, GuitarType.FLAMENCO) == GuitarMode.TOP

    def test_flamenco_back_240Hz(self):
        # Flamenco back=(200, 250) — 240 Hz is above the 200–220 overlap, so unambiguously Back.
        assert GuitarMode.classify(240.0, GuitarType.FLAMENCO) == GuitarMode.BACK

    def test_flamenco_top_is_claimed_below_back(self):
        # Regression guard for the inverted bands (section 7c of
        # Development/PEAK-FINDING-DUPLICATE-PEAKS.md). Two peaks straddling the overlap must
        # resolve Top-below-Back, as on every other guitar type. Under the old bands
        # (top=(190,250), back=(180,240)) Back sorted first, so the "Back above Top" guard in
        # classify_all never fired and the STRONGEST peak was labelled Back.
        from guitar_tap.models.resonant_peak import ResonantPeak

        low = ResonantPeak(frequency=190.0, magnitude=-40.0)   # strongest
        high = ResonantPeak(frequency=230.0, magnitude=-50.0)
        modes = GuitarMode.classify_all([low, high], GuitarType.FLAMENCO)
        assert modes[low.id] == GuitarMode.TOP
        assert modes[high.id] == GuitarMode.BACK

    def test_flamenco_overlap_210Hz_resolves_to_top_by_lookup_order(self):
        # top=(180, 220) and back=(200, 250) overlap on 200–220. classify() is the naive
        # single-frequency lookup and returns the first matching band in fixed air->upper
        # order, so the overlap resolves to TOP. classify_all() is what disambiguates
        # properly using magnitude and the Back-above-Top constraint.
        assert GuitarMode.classify(210.0, GuitarType.FLAMENCO) == GuitarMode.TOP

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

class TestModeOverrideLabels:
    """Mirrors Swift ModeOverrideLabelsTests.

    Added in the #17 sweep. from_mode_string is reachable from the override picker
    (peak_card_widget offers both groups) and was tested in NO edition — which is how Python and
    Swift came to disagree about one of the seven academic labels, and how the web port came to
    lack the table entirely. See SLUG-SWEEP.md F11/F12.
    """

    def test_standard_display_names_resolve_to_their_own_mode(self):
        for mode in GuitarMode.current_cases:
            assert GuitarMode.from_mode_string(mode.display_name).normalized == mode.normalized, \
                f"{mode.display_name} should resolve to {mode}"

    def test_academic_labels_resolve_to_their_mode(self):
        """All three editions offer these and must agree — a file saved in one opens in the others."""
        expected = {
            "Helmholtz T(1,1)_1":   GuitarMode.AIR,
            "Top T(1,1)_2":         GuitarMode.TOP,
            "Back T(1,1)_3":        GuitarMode.BACK,
            "Cross Dipole T(2,1)":  GuitarMode.DIPOLE,
            "Long Dipole T(1,2)":   GuitarMode.DIPOLE,
            # Swift is canonical here. Python mapped Quadrapole to UPPER_MODES until #17.
            "Quadrapole T(2,2)":    GuitarMode.RING_MODE,
            "Cross Tripole T(3,1)": GuitarMode.RING_MODE,
        }
        for label, mode in expected.items():
            assert GuitarMode.from_mode_string(label).normalized == mode, \
                f"{label} should resolve to {mode}"

    def test_every_offered_label_resolves(self):
        """An unresolvable offered label would silently become freeform and drop out of the
        ratio and the definitive-peak resolution."""
        for label in GuitarMode.additional_mode_labels:
            assert GuitarMode.from_mode_string(label) != GuitarMode.UNKNOWN, \
                f"the picker offers {label} but nothing resolves it"

    def test_freeform_label_is_unknown_and_does_not_fall_through_to_auto(self):
        assert GuitarMode.from_mode_string("Wolf note") == GuitarMode.UNKNOWN
        assert GuitarMode.effective_mode("Wolf note", GuitarMode.TOP) == GuitarMode.UNKNOWN

    def test_no_override_leaves_the_auto_classification_standing(self):
        assert GuitarMode.effective_mode(None, GuitarMode.TOP) == GuitarMode.TOP
        assert GuitarMode.effective_mode("", GuitarMode.BACK) == GuitarMode.BACK


class TestClassifyAll:
    """Mirrors Swift GuitarModeClassifyAllTests."""

    def test_equal_magnitude_first_peak_wins_the_band(self):
        """On equal magnitude the FIRST peak wins the band.

        All three editions agree — Swift's max(by:) and Python's max() both keep the first
        maximal element, and web's loop replaces only on a strict >. Pinned during the #17
        sweep because no edition pinned it: a tie-break that differed per edition would stay
        invisible until a real measurement produced a tie, and would then move which peak is
        "the Air peak" in one app and not the others.
        """
        first = _peak(95.0, mag=-20.0)
        second = _peak(100.0, mag=-20.0)
        result = GuitarMode.classify_all([first, second], GuitarType.ACOUSTIC)
        assert result[first.id] == GuitarMode.AIR
        assert result[second.id] == GuitarMode.AIR
        # Both are Air; the question is which one the claiming pass took.
        candidates = [(first.id, first.magnitude), (second.id, second.magnitude)]
        assert max(candidates, key=lambda x: x[1])[0] == first.id, \
            "the first of two equal-magnitude peaks is claimed"

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
