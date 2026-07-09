# @parity test/brace
"""Tests for the brace side of models/material_properties.py.

Mirrors GuitarTapTests/BracePropertiesTests.swift.
Fixture values are derived from the same reference measurements used in the Swift tests.
"""

import math

from models.material_properties import (
    BraceProperties,
    MaterialDimensions,
    WoodQuality,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Real measured spruce brace blank — baseline for BraceProperties tests.
# Mirrors Swift: realBraceDimensions / realBraceFl in BracePropertiesTests.swift.
REAL_BRACE_DIM = MaterialDimensions(
    length_mm=556, width_mm=20.4, thickness_mm=29.4, mass_g=128
)
REAL_BRACE_FL: float = 512.3
# Known outputs (hand-calculated, confirmed by Swift tests):
#   ρ ≈ 383.8 kg/m³, EL ≈ 10.541 GPa, c ≈ 5240 m/s, specific modulus ≈ 27.46 → Excellent


# ---------------------------------------------------------------------------
# Young's Modulus — BraceProperties
# ---------------------------------------------------------------------------

class TestBraceYoungsModulus:
    """Mirrors Swift BraceYoungModulusTests."""

    def test_youngs_modulus_long_real_brace_physically_plausible(self):
        """EL from real measured blank should be in 8–16 GPa."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        EL = props.youngsModulusLong
        assert 8e9 < EL < 16e9, f"EL ({EL/1e9:.3f} GPa) should be in 8–16 GPa range"

    def test_youngs_modulus_long_real_brace_matches_known_value(self):
        """EL should be within 0.05 GPa of the hand-calculated 10.541 GPa."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        EL_GPa = props.youngsModulusLong / 1e9
        assert abs(EL_GPa - 10.541) < 0.05, f"EL should be ≈10.541 GPa, got {EL_GPa:.3f} GPa"

    def test_youngs_modulus_long_zero_thickness_returns_zero(self):
        """Guard: zero thickness → EL = 0."""
        d = MaterialDimensions(length_mm=556, width_mm=20.4, thickness_mm=0, mass_g=128)
        props = BraceProperties(d, REAL_BRACE_FL)
        assert props.youngsModulusLong == 0.0

    def test_youngs_modulus_long_zero_mass_returns_zero(self):
        """Guard: zero mass → density = 0 → EL = 0."""
        d = MaterialDimensions(length_mm=556, width_mm=20.4, thickness_mm=29.4, mass_g=0)
        props = BraceProperties(d, REAL_BRACE_FL)
        assert props.youngsModulusLong == 0.0

    def test_youngs_modulus_long_double_frequency_quadruples_modulus(self):
        """E ∝ f²: doubling fL should quadruple EL."""
        lo = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        hi = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL * 2)
        ratio = hi.youngsModulusLong / lo.youngsModulusLong
        assert abs(ratio - 4.0) < 0.01, f"Doubling fL should quadruple EL (ratio={ratio:.4f})"

    def test_youngs_modulus_long_double_length_sixteen_x_modulus(self):
        """E ∝ L⁴ at constant density: doubling L → EL × 16."""
        d2 = MaterialDimensions(length_mm=556 * 2, width_mm=20.4, thickness_mm=29.4, mass_g=128 * 2)
        p1 = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        p2 = BraceProperties(d2, REAL_BRACE_FL)
        ratio = p2.youngsModulusLong / p1.youngsModulusLong
        assert abs(ratio - 16.0) < 0.1, f"Doubling L at constant ρ should give 16× EL (ratio={ratio:.4f})"

    def test_youngs_modulus_long_uses_precise_beam_constant(self):
        """BraceProperties must use 22.37332, not the plate constant 22.37."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        rho = REAL_BRACE_DIM.density()
        f   = REAL_BRACE_FL
        L   = REAL_BRACE_DIM.length()
        t   = REAL_BRACE_DIM.thickness()
        with_precise = 48 * math.pi**2 * rho * f**2 * L**4 / (22.37332 * t)**2
        with_approx  = 48 * math.pi**2 * rho * f**2 * L**4 / (22.37    * t)**2
        assert abs(props.youngsModulusLong - with_precise) < 1.0
        assert abs(props.youngsModulusLong - with_approx)  > 1000.0

    def test_youngs_modulus_long_gpa_is_pa_divided_by_1e9(self):
        """youngsModulusLongGPa = youngsModulusLong / 1e9."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        assert abs(props.youngsModulusLongGPa - props.youngsModulusLong / 1e9) < 1e-6


# ---------------------------------------------------------------------------
# Speed of Sound — BraceProperties
# ---------------------------------------------------------------------------

class TestBraceSpeedOfSound:
    """Mirrors Swift BraceSpeedOfSoundTests."""

    def test_speed_of_sound_real_brace_in_expected_range(self):
        """Speed of sound should be in 4000–7000 m/s for quality spruce."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        c = props.c_long_m_s
        assert 4000 < c < 7000, f"Sound speed ({c:.0f} m/s) should be in 4000–7000 m/s"

    def test_speed_of_sound_real_brace_matches_known_value(self):
        """c should be within 10 m/s of the hand-calculated 5240 m/s."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        assert abs(props.c_long_m_s - 5240.4) < 10, f"c should be ≈5240 m/s, got {props.c_long_m_s:.1f} m/s"

    def test_speed_of_sound_proportional_to_frequency(self):
        """c ∝ f: doubling fL should double c."""
        lo = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        hi = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL * 2)
        ratio = hi.c_long_m_s / lo.c_long_m_s
        assert abs(ratio - 2.0) < 0.05, f"Doubling fL should double c (ratio={ratio:.4f})"

    def test_speed_of_sound_zero_density_returns_zero(self):
        """Guard: zero density → c = 0."""
        d = MaterialDimensions(length_mm=556, width_mm=20.4, thickness_mm=0, mass_g=0)
        props = BraceProperties(d, REAL_BRACE_FL)
        assert props.c_long_m_s == 0.0

    def test_speed_of_sound_equals_sqrt_e_over_rho(self):
        """c = √(E/ρ): verify against Pa-based primary property."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        expected = math.sqrt(props.youngsModulusLong / props.density_kg_m3)
        assert abs(props.c_long_m_s - expected) < 0.01


# ---------------------------------------------------------------------------
# Specific Modulus — BraceProperties
# ---------------------------------------------------------------------------

class TestBraceSpecificModulus:
    """Mirrors Swift BraceSpecificModulusTests."""

    def test_specific_modulus_real_brace_matches_known_value(self):
        """Specific modulus should be within 0.1 of the known 27.46 GPa/(g/cm³)."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        assert abs(props.specific_modulus - 27.46) < 0.1, \
            f"Specific modulus should be ≈27.46, got {props.specific_modulus:.3f}"

    def test_specific_modulus_matches_manual_calc(self):
        """specific_modulus = youngsModulusLongGPa / density_g_cm3."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        expected = props.youngsModulusLongGPa / REAL_BRACE_DIM.density_g_per_cm3()
        assert abs(props.specific_modulus - expected) < 0.001

    def test_specific_modulus_zero_density_returns_zero(self):
        """Guard: zero density → specific modulus = 0."""
        d = MaterialDimensions(length_mm=556, width_mm=20.4, thickness_mm=0, mass_g=0)
        props = BraceProperties(d, REAL_BRACE_FL)
        assert props.specific_modulus == 0.0

    def test_specific_modulus_higher_frequency_higher_value(self):
        """Higher fL → stiffer → higher specific modulus."""
        lo = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL / 2)
        hi = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        assert hi.specific_modulus > lo.specific_modulus


# ---------------------------------------------------------------------------
# Quality Assessment — BraceProperties
# ---------------------------------------------------------------------------

class TestBraceQuality:
    """Mirrors Swift BraceQualityTests."""

    def test_spruce_quality_real_brace_excellent(self):
        """Real brace with specific modulus ≈ 27.46 (≥ 25) → Excellent."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        assert props.quality == "Excellent", \
            f"Real brace should be Excellent, got {props.quality}"

    def test_spruce_quality_half_frequency_poor(self):
        """Half frequency → EL × ¼ → specific modulus ≈ 6.9 → Poor."""
        props = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL / 2)
        assert props.specific_modulus < 16, \
            f"Half fL should give specific modulus < 16, got {props.specific_modulus:.2f}"
        assert props.quality == "Poor"

    def test_spruce_quality_higher_frequency_better_or_equal(self):
        """Higher fL → equal or better quality rating."""
        lo = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL / 2)
        hi = BraceProperties(REAL_BRACE_DIM, REAL_BRACE_FL)
        lo_score = WoodQuality(lo.quality).numeric_score
        hi_score = WoodQuality(hi.quality).numeric_score
        assert hi_score >= lo_score