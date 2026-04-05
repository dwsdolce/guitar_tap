"""Tests for models/material_properties.py.

Mirrors GuitarTapTests/PlatePropertiesTests.swift and BracePropertiesTests.swift.
Fixture values are derived from the same reference measurements used in the Swift tests.
"""

import math
import pytest

from models.material_properties import (
    BraceProperties,
    MaterialDimensions,
    PlateProperties,
    WoodQuality,
    calculate_gore_target_thickness,
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
# MaterialDimensions
# ---------------------------------------------------------------------------

class TestMaterialDimensions:
    """Mirrors Swift MaterialDimensionsTests."""

    def test_volume_correct_for_typical_plate(self):
        """Volume = length × width × thickness in m³."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=100)
        expected = 0.5 * 0.2 * 0.003
        assert abs(d.volume() - expected) < 1e-7

    def test_density_spruce_plate_in_expected_range(self):
        """Density ≈ 400 kg/m³ for a typical spruce plate."""
        # 500×200×3 mm, 120 g → volume=0.0003 m³ → ρ = 0.12/0.0003 = 400 kg/m³
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        assert abs(d.density() - 400) < 1

    def test_density_g_per_cm3_correct_conversion(self):
        """400 kg/m³ → 0.4 g/cm³."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        assert abs(d.density_g_per_cm3() - 0.4) < 0.001

    def test_zero_thickness_density_is_zero(self):
        """Guard: zero thickness → density = 0."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=0, mass_g=100)
        assert d.density() == 0.0


# ---------------------------------------------------------------------------
# Young's Modulus — PlateProperties
# ---------------------------------------------------------------------------

class TestPlateYoungsModulus:
    """Mirrors Swift YoungModulusTests."""

    def test_youngs_modulus_long_spruce_plate_physically_plausible(self):
        """EL should be in the 5–20 GPa range for a typical spruce plate."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        EL = props.youngsModulusLong
        assert 5e9 < EL < 20e9, f"EL ({EL/1e9:.2f} GPa) should be in 5–20 GPa range"

    def test_youngs_modulus_long_zero_thickness_returns_zero(self):
        """Guard: zero thickness → EL = 0."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=0, mass_g=120)
        props = PlateProperties(d, f_long=170, f_cross=100)
        assert props.youngsModulusLong == 0.0

    def test_youngs_modulus_long_higher_frequency_higher_modulus(self):
        """E ∝ f²: doubling fL should quadruple EL."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        lo = PlateProperties(d, f_long=100, f_cross=80)
        hi = PlateProperties(d, f_long=200, f_cross=80)
        ratio = hi.youngsModulusLong / lo.youngsModulusLong
        assert abs(ratio - 4.0) < 0.01, f"Doubling fL should quadruple EL (ratio={ratio:.4f})"

    def test_youngs_modulus_long_double_length_sixteen_x_modulus(self):
        """E ∝ L⁴ at constant density: doubling L → EL × 16."""
        # Keep density constant by doubling mass with length.
        d1 = MaterialDimensions(length_mm=250, width_mm=200, thickness_mm=3, mass_g=60)
        d2 = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        p1 = PlateProperties(d1, f_long=85, f_cross=50)
        p2 = PlateProperties(d2, f_long=85, f_cross=50)
        ratio = p2.youngsModulusLong / p1.youngsModulusLong
        assert abs(ratio - 16.0) < 0.1, f"Doubling L at constant ρ should give 16× EL (ratio={ratio:.4f})"

    def test_youngs_modulus_long_gpa_is_pa_divided_by_1e9(self):
        """youngsModulusLongGPa must equal youngsModulusLong / 1e9."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert abs(props.youngsModulusLongGPa - props.youngsModulusLong / 1e9) < 1e-6

    def test_youngs_modulus_cross_gpa_is_pa_divided_by_1e9(self):
        """youngsModulusCrossGPa must equal youngsModulusCross / 1e9."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert abs(props.youngsModulusCrossGPa - props.youngsModulusCross / 1e9) < 1e-6


# ---------------------------------------------------------------------------
# Speed of Sound — PlateProperties
# ---------------------------------------------------------------------------

class TestPlateSpeedOfSound:
    """Mirrors Swift SpeedOfSoundTests."""

    def test_speed_of_sound_long_spruce_in_expected_range(self):
        """Speed of sound should be in 3000–8000 m/s for spruce."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        c = props.c_long_m_s
        assert 3000 < c < 8000, f"Sound speed ({c:.0f} m/s) should be in 3000–8000 m/s"

    def test_speed_of_sound_long_proportional_to_frequency(self):
        """c ∝ f: doubling fL should double c."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        lo = PlateProperties(d, f_long=100, f_cross=80)
        hi = PlateProperties(d, f_long=200, f_cross=80)
        ratio = hi.c_long_m_s / lo.c_long_m_s
        assert abs(ratio - 2.0) < 0.05, f"Doubling fL should double c (ratio={ratio:.4f})"

    def test_speed_of_sound_equals_sqrt_e_over_rho(self):
        """c = √(E/ρ): verify against the Pa-based primary property."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        expected = math.sqrt(props.youngsModulusLong / props.density_kg_m3)
        assert abs(props.c_long_m_s - expected) < 0.01


# ---------------------------------------------------------------------------
# Specific Modulus — PlateProperties
# ---------------------------------------------------------------------------

class TestPlateSpecificModulus:
    """Mirrors Swift SpecificModulusTests."""

    def test_specific_modulus_long_matches_manual_calc(self):
        """specific_modulus_long = youngsModulusLongGPa / density_g_cm3."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=170, f_cross=100)
        expected = props.youngsModulusLongGPa / d.density_g_per_cm3()
        assert abs(props.specific_modulus_long - expected) < 0.001

    def test_specific_modulus_long_zero_density_returns_zero(self):
        """Guard: zero density → specific modulus = 0."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=0, mass_g=0)
        props = PlateProperties(d, f_long=170, f_cross=100)
        assert props.specific_modulus_long == 0.0


# ---------------------------------------------------------------------------
# Anisotropy ratios — PlateProperties
# ---------------------------------------------------------------------------

class TestPlateAnisotropyRatios:

    def test_cross_long_ratio_is_ec_over_el(self):
        """cross_long_ratio = E_C / E_L."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        expected = props.youngsModulusCross / props.youngsModulusLong
        assert abs(props.cross_long_ratio - expected) < 1e-6

    def test_long_cross_ratio_is_el_over_ec(self):
        """long_cross_ratio = E_L / E_C."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        expected = props.youngsModulusLong / props.youngsModulusCross
        assert abs(props.long_cross_ratio - expected) < 1e-6

    def test_ratios_are_reciprocals(self):
        """cross_long_ratio × long_cross_ratio ≈ 1."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert abs(props.cross_long_ratio * props.long_cross_ratio - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Gore target thickness — PlateProperties
# ---------------------------------------------------------------------------

class TestGoreTargetThickness:
    """Mirrors Swift GoreTargetThicknessTests."""

    def test_gore_thickness_spruce_top_is_plausible(self):
        """Result should be in the 1.5–6 mm range for a typical spruce top."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        t = calculate_gore_target_thickness(props, 490, 390, 75)
        assert t is not None, "Should return a thickness value"
        assert 1.5 < t < 6.0, f"Target thickness {t:.2f} mm should be in 1.5–6 mm range"

    def test_gore_thickness_zero_body_length_returns_none(self):
        """Guard: zero body length → None."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=170, f_cross=100)
        assert calculate_gore_target_thickness(props, 0, 390, 75) is None

    def test_gore_thickness_higher_target_thicker_plate(self):
        """Higher vibrational stiffness target → thicker plate."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=170, f_cross=100)
        t55 = calculate_gore_target_thickness(props, 490, 390, 55)
        t75 = calculate_gore_target_thickness(props, 490, 390, 75)
        assert t55 is not None and t75 is not None
        assert t75 > t55, f"Higher stiffness target should yield thicker plate: t55={t55:.2f}, t75={t75:.2f}"


# ---------------------------------------------------------------------------
# Quality Assessment — PlateProperties
# ---------------------------------------------------------------------------

class TestPlateQuality:

    def test_quality_long_excellent_for_high_specific_modulus(self):
        """Specific modulus ≥ 25 → Excellent longitudinal quality."""
        # Force a high EL: very stiff plate (high f, large L, thin, light)
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=2, mass_g=60)
        props = PlateProperties(d, f_long=200, f_cross=100)
        if props.specific_modulus_long >= 25:
            assert props.quality_long == "Excellent"

    def test_quality_uses_wood_quality_enum(self):
        """quality_long string must be a valid WoodQuality value."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        valid = {q.value for q in WoodQuality}
        assert props.quality_long in valid
        assert props.quality_cross in valid
        assert props.overall_quality in valid

    def test_overall_quality_uses_numeric_score(self):
        """overall_quality must be consistent with numeric_score-based weighting."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        # Recalculate manually using enum numeric_score — mirrors Swift exactly
        long_score  = WoodQuality(props.quality_long).numeric_score  * 0.7
        cross_score = WoodQuality(props.quality_cross).numeric_score * 0.3
        combined = long_score + cross_score
        if   combined >= 4.5: expected = "Excellent"
        elif combined >= 3.5: expected = "Very Good"
        elif combined >= 2.5: expected = "Good"
        elif combined >= 1.5: expected = "Fair"
        else:                 expected = "Poor"
        assert props.overall_quality == expected


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


# ---------------------------------------------------------------------------
# WoodQuality enum
# ---------------------------------------------------------------------------

class TestWoodQuality:

    def test_numeric_score_values(self):
        """Numeric scores must be 5/4/3/2/1 for Excellent…Poor."""
        assert WoodQuality.EXCELLENT.numeric_score == 5.0
        assert WoodQuality.VERY_GOOD.numeric_score == 4.0
        assert WoodQuality.GOOD.numeric_score      == 3.0
        assert WoodQuality.FAIR.numeric_score      == 2.0
        assert WoodQuality.POOR.numeric_score      == 1.0

    def test_color_values_are_hex_strings(self):
        """Every quality level must have a hex color string."""
        for q in WoodQuality:
            c = q.color
            assert c.startswith("#") and len(c) == 7, f"{q} color {c!r} is not a hex string"

    def test_evaluate_spruce_longitudinal_thresholds(self):
        """Spruce longitudinal thresholds: ≥25=Excellent, ≥22=VG, ≥19=Good, ≥16=Fair, <16=Poor."""
        D, T = WoodQuality.Direction, WoodQuality.WoodType
        assert WoodQuality.evaluate(25.0, D.LONGITUDINAL, T.SPRUCE) == WoodQuality.EXCELLENT
        assert WoodQuality.evaluate(22.0, D.LONGITUDINAL, T.SPRUCE) == WoodQuality.VERY_GOOD
        assert WoodQuality.evaluate(19.0, D.LONGITUDINAL, T.SPRUCE) == WoodQuality.GOOD
        assert WoodQuality.evaluate(16.0, D.LONGITUDINAL, T.SPRUCE) == WoodQuality.FAIR
        assert WoodQuality.evaluate(10.0, D.LONGITUDINAL, T.SPRUCE) == WoodQuality.POOR

    def test_evaluate_spruce_cross_thresholds(self):
        """Spruce cross-grain thresholds: ≥1.5=Excellent, ≥1.2=VG, ≥0.9=Good, ≥0.6=Fair, <0.6=Poor."""
        D, T = WoodQuality.Direction, WoodQuality.WoodType
        assert WoodQuality.evaluate(1.5, D.CROSS, T.SPRUCE) == WoodQuality.EXCELLENT
        assert WoodQuality.evaluate(1.2, D.CROSS, T.SPRUCE) == WoodQuality.VERY_GOOD
        assert WoodQuality.evaluate(0.9, D.CROSS, T.SPRUCE) == WoodQuality.GOOD
        assert WoodQuality.evaluate(0.6, D.CROSS, T.SPRUCE) == WoodQuality.FAIR
        assert WoodQuality.evaluate(0.3, D.CROSS, T.SPRUCE) == WoodQuality.POOR
