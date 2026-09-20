# @parity test/plate
"""Tests for the plate side of models/material_properties.py.

Mirrors GuitarTapTests/PlatePropertiesTests.swift. Also holds the shared
MaterialDimensions and WoodQuality suites (Swift keeps these in the plate file).

TWO fixtures, for two different jobs — mixing them is what let this suite drift.

REAL_PLATE_* is an actual measured sample, for every test that claims a result is
physically sensible. Dimensions and frequencies are read straight out of the hub's
committed measurement:

    guitar-tap-project/Tests/Plate/plate-umik-1-swift-mac-1778816330.guitartap

and the expected values are the ones GuitarTap itself reported for it, printed in the
.pdf beside that file. They are NOT numbers this suite produced — a suite that generates
its own expectations can never fail.

SYNTHETIC_PLATE_DIM is round numbers (density lands on exactly 400 kg/m³), for the
algebraic identities only: E ∝ f², E ∝ L⁴, c = √(E/ρ), the reciprocal ratios, the zero
guards. Those hold for any input, so being unphysical costs nothing and hand-checkable
arithmetic is worth more. It is NOT a plausible plate — its E_C/E_L is 0.0089 against the
0.04–0.08 the app's own UI calls typical — so no plausibility claim may rest on it.
"""

import math

from guitar_tap.models.material_properties import (
    MaterialDimensions,
    PlateProperties,
    WoodQuality,
    calculate_gore_target_thickness,
)

# Real measured plate — see the module docstring. rho 0.349 g/cm3, graded Fair.
REAL_PLATE_DIM = MaterialDimensions(
    length_mm=557.5, width_mm=220.5, thickness_mm=4.85, mass_g=208
)
REAL_PLATE_FL = 67.11537
REAL_PLATE_FC = 116.27016
REAL_PLATE_FLC = 35.353745
# Body outline saved with that measurement (guitarBodyLength / guitarBodyWidth).
REAL_PLATE_BODY_LENGTH_MM = 490
REAL_PLATE_BODY_WIDTH_MM = 390


def make_real_plate() -> PlateProperties:
    """The real measured plate. Mirrors Swift makeRealPlate()."""
    return PlateProperties(REAL_PLATE_DIM, REAL_PLATE_FL, REAL_PLATE_FC, REAL_PLATE_FLC)


# Synthetic plate — algebraic identities only. See the module docstring.
SYNTHETIC_PLATE_DIM = MaterialDimensions(
    length_mm=500, width_mm=200, thickness_mm=3, mass_g=120
)


# ---------------------------------------------------------------------------
# Real sample report — one test per number GuitarTap printed for the committed
# measurement. Mirrors Swift RealPlateReportTests.
# ---------------------------------------------------------------------------

class TestRealPlateReport:
    """Mirrors Swift RealPlateReportTests."""

    def test_density_matches_report(self):
        """The report prints 0.349 g/cm3."""
        assert abs(REAL_PLATE_DIM.density_g_per_cm3() - 0.349) < 0.001

    def test_youngs_modulus_matches_report(self):
        """The report prints E_L 6.11 GPa and E_C 0.45 GPa."""
        props = make_real_plate()
        assert abs(props.youngsModulusLongGPa - 6.11) < 0.01
        assert abs(props.youngsModulusCrossGPa - 0.45) < 0.01

    def test_speed_of_sound_matches_report(self):
        """The report prints c_L 4185 m/s and c_C 1134 m/s."""
        props = make_real_plate()
        assert abs(props.c_long_m_s - 4185) < 1
        assert abs(props.c_cross_m_s - 1134) < 1

    def test_specific_modulus_matches_report(self):
        """The report prints 17.5 (L) and 1.3 (C)."""
        props = make_real_plate()
        assert abs(props.specific_modulus_long - 17.5) < 0.1
        assert abs(props.specific_modulus_cross - 1.3) < 0.1

    def test_radiation_ratio_matches_report(self):
        """The report prints R (L) = 12.0."""
        props = make_real_plate()
        assert abs(props.radiation_ratio_long - 12.0) < 0.1

    def test_quality_is_fair_not_saturated(self):
        """A genuinely mid-grade plate — the only fixture that exercises the middle of the
        quality scale. Every synthetic one saturates at Excellent, where the assertion holds
        however far the thresholds move."""
        props = make_real_plate()
        assert props.quality_long == "Fair", f"17.5 should grade Fair, got {props.quality_long}"

    def test_overall_quality_blends_the_two_directions(self):
        """The real plate straddles two grades — Fair along the grain (17.5), Very Good across
        it (1.29) — so the 0.7/0.3 blend is doing real work: 0.7*2 + 0.3*4 = 2.6 -> Good."""
        props = make_real_plate()
        assert props.quality_long == "Fair"
        assert props.quality_cross == "Very Good"
        assert props.overall_quality == "Good", \
            f"0.7*Fair + 0.3*VeryGood should blend to Good, got {props.overall_quality}"

    def test_anisotropy_ratios_are_in_the_typical_band(self):
        """0.0734 and 13.6 — inside the 0.04-0.08 and 12-25 bands the app's UI calls typical."""
        props = make_real_plate()
        assert abs(props.cross_long_ratio - 0.0734) < 0.001
        assert abs(props.long_cross_ratio - 13.6) < 0.1
        assert 0.04 < props.cross_long_ratio < 0.08

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
        d = SYNTHETIC_PLATE_DIM
        assert abs(d.density() - 400) < 1

    def test_density_g_per_cm3_correct_conversion(self):
        """400 kg/m³ → 0.4 g/cm³."""
        d = SYNTHETIC_PLATE_DIM
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

    def test_youngs_modulus_real_plate_matches_reported_values(self):
        """Real measured plate: GuitarTap reported E_L 6.11 GPa and E_C 0.45 GPa.

        Pinned to the app's own report rather than to a band wide enough to admit anything.
        """
        props = make_real_plate()
        assert abs(props.youngsModulusLongGPa - 6.11) < 0.01
        assert abs(props.youngsModulusCrossGPa - 0.45) < 0.01

    def test_youngs_modulus_long_zero_thickness_returns_zero(self):
        """Guard: zero thickness → EL = 0."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=0, mass_g=120)
        props = PlateProperties(d, f_long=170, f_cross=100)
        assert props.youngsModulusLong == 0.0

    def test_youngs_modulus_long_higher_frequency_higher_modulus(self):
        """E ∝ f²: doubling fL should quadruple EL."""
        d = SYNTHETIC_PLATE_DIM
        lo = PlateProperties(d, f_long=100, f_cross=80)
        hi = PlateProperties(d, f_long=200, f_cross=80)
        ratio = hi.youngsModulusLong / lo.youngsModulusLong
        assert abs(ratio - 4.0) < 0.01, f"Doubling fL should quadruple EL (ratio={ratio:.4f})"

    def test_youngs_modulus_long_double_length_sixteen_x_modulus(self):
        """E ∝ L⁴ at constant density: doubling L → EL × 16."""
        # Keep density constant by doubling mass with length.
        d1 = MaterialDimensions(length_mm=250, width_mm=200, thickness_mm=3, mass_g=60)
        d2 = SYNTHETIC_PLATE_DIM
        p1 = PlateProperties(d1, f_long=85, f_cross=50)
        p2 = PlateProperties(d2, f_long=85, f_cross=50)
        ratio = p2.youngsModulusLong / p1.youngsModulusLong
        assert abs(ratio - 16.0) < 0.1, f"Doubling L at constant ρ should give 16× EL (ratio={ratio:.4f})"

    def test_youngs_modulus_long_gpa_is_pa_divided_by_1e9(self):
        """youngsModulusLongGPa must equal youngsModulusLong / 1e9."""
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert abs(props.youngsModulusLongGPa - props.youngsModulusLong / 1e9) < 1e-6

    def test_youngs_modulus_cross_gpa_is_pa_divided_by_1e9(self):
        """youngsModulusCrossGPa must equal youngsModulusCross / 1e9."""
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert abs(props.youngsModulusCrossGPa - props.youngsModulusCross / 1e9) < 1e-6


# ---------------------------------------------------------------------------
# Speed of Sound — PlateProperties
# ---------------------------------------------------------------------------

class TestPlateSpeedOfSound:
    """Mirrors Swift SpeedOfSoundTests."""

    def test_speed_of_sound_real_plate_matches_reported_values(self):
        """Real measured plate: GuitarTap reported c_L 4185 m/s and c_C 1134 m/s."""
        props = make_real_plate()
        assert abs(props.c_long_m_s - 4185) < 1
        assert abs(props.c_cross_m_s - 1134) < 1

    def test_speed_of_sound_long_proportional_to_frequency(self):
        """c ∝ f: doubling fL should double c."""
        d = SYNTHETIC_PLATE_DIM
        lo = PlateProperties(d, f_long=100, f_cross=80)
        hi = PlateProperties(d, f_long=200, f_cross=80)
        ratio = hi.c_long_m_s / lo.c_long_m_s
        assert abs(ratio - 2.0) < 0.05, f"Doubling fL should double c (ratio={ratio:.4f})"

    def test_speed_of_sound_equals_sqrt_e_over_rho(self):
        """c = √(E/ρ): verify against the Pa-based primary property."""
        d = SYNTHETIC_PLATE_DIM
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
        d = SYNTHETIC_PLATE_DIM
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
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=85, f_cross=50)
        expected = props.youngsModulusCross / props.youngsModulusLong
        assert abs(props.cross_long_ratio - expected) < 1e-6

    def test_long_cross_ratio_is_el_over_ec(self):
        """long_cross_ratio = E_L / E_C."""
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=85, f_cross=50)
        expected = props.youngsModulusLong / props.youngsModulusCross
        assert abs(props.long_cross_ratio - expected) < 1e-6

    def test_ratios_are_reciprocals(self):
        """cross_long_ratio × long_cross_ratio ≈ 1."""
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert abs(props.cross_long_ratio * props.long_cross_ratio - 1.0) < 1e-6

    def test_ratios_zero_density_return_zero_not_nan(self):
        """Zero density collapses both moduli to 0; the ratios must not divide 0 by 0."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=0, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert not math.isnan(props.cross_long_ratio)
        assert not math.isnan(props.long_cross_ratio)
        assert props.cross_long_ratio == 0.0
        assert props.long_cross_ratio == 0.0


# ---------------------------------------------------------------------------
# Radiation ratio — PlateProperties
#
# R = c/ρ is shown in the Results panel and in the exported image in all three
# editions and had no test in any of them until the #17 sweep, which is how the
# web port's inline copy came to be missing the zero-density guard.
# Mirrors Swift PlateRadiationRatioTests.
# ---------------------------------------------------------------------------

class TestPlateRadiationRatio:
    """Mirrors Swift PlateRadiationRatioTests."""

    @staticmethod
    def _plate() -> PlateProperties:
        d = SYNTHETIC_PLATE_DIM
        return PlateProperties(d, f_long=85, f_cross=50)

    def test_radiation_ratio_long_is_speed_over_density(self):
        """R_L = c_L / ρ."""
        props = self._plate()
        expected = props.c_long_m_s / props.dimensions.density()
        assert abs(props.radiation_ratio_long - expected) < 1e-6

    def test_radiation_ratio_cross_is_speed_over_density(self):
        """R_C = c_C / ρ."""
        props = self._plate()
        expected = props.c_cross_m_s / props.dimensions.density()
        assert abs(props.radiation_ratio_cross - expected) < 1e-6

    def test_radiation_ratio_long_exceeds_cross(self):
        """c_L > c_C at one density, so the plate radiates better along the grain."""
        props = self._plate()
        assert props.radiation_ratio_long > props.radiation_ratio_cross

    def test_radiation_ratio_zero_density_returns_zero_not_nan(self):
        """Zero density → c is 0 too, so the unguarded quotient would be 0/0."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=0, mass_g=120)
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert d.density() == 0
        assert not math.isnan(props.radiation_ratio_long)
        assert not math.isnan(props.radiation_ratio_cross)
        assert props.radiation_ratio_long == 0.0
        assert props.radiation_ratio_cross == 0.0

    def test_radiation_ratio_zero_mass_returns_zero_not_nan(self):
        """Zero mass reaches the same guard by the other route."""
        d = MaterialDimensions(length_mm=500, width_mm=200, thickness_mm=3, mass_g=0)
        props = PlateProperties(d, f_long=85, f_cross=50)
        assert not math.isnan(props.radiation_ratio_long)
        assert props.radiation_ratio_long == 0.0


# ---------------------------------------------------------------------------
# Gore target thickness — PlateProperties
# ---------------------------------------------------------------------------

class TestGoreTargetThickness:
    """Mirrors Swift GoreTargetThicknessTests."""

    def test_gore_thickness_real_plate_is_plausible(self):
        """Real measured plate, with the body outline saved alongside it (490 x 390 mm) and
        the Classical Top stiffness target (60) it was measured under."""
        props = make_real_plate()
        t = calculate_gore_target_thickness(
            props, REAL_PLATE_BODY_LENGTH_MM, REAL_PLATE_BODY_WIDTH_MM, 60
        )
        assert t is not None, "Should return a thickness value"
        assert 2.0 < t < 5.0, f"Target thickness {t:.2f} mm should be in the 2-5 mm range"

    def test_gore_thickness_zero_body_length_returns_none(self):
        """Guard: zero body length → None."""
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=170, f_cross=100)
        assert calculate_gore_target_thickness(props, 0, 390, 75) is None

    def test_gore_thickness_higher_target_thicker_plate(self):
        """Higher vibrational stiffness target → thicker plate."""
        d = SYNTHETIC_PLATE_DIM
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
        d = SYNTHETIC_PLATE_DIM
        props = PlateProperties(d, f_long=85, f_cross=50)
        valid = {q.value for q in WoodQuality}
        assert props.quality_long in valid
        assert props.quality_cross in valid
        assert props.overall_quality in valid

    def test_overall_quality_uses_numeric_score(self):
        """overall_quality must be consistent with numeric_score-based weighting."""
        d = SYNTHETIC_PLATE_DIM
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
# WoodQuality enum (shared; Swift keeps this in PlatePropertiesTests)
# ---------------------------------------------------------------------------

class TestWoodQuality:

    def test_numeric_score_values(self):
        """Numeric scores must be 5/4/3/2/1 for Excellent…Poor."""
        assert WoodQuality.EXCELLENT.numeric_score == 5.0
        assert WoodQuality.VERY_GOOD.numeric_score == 4.0
        assert WoodQuality.GOOD.numeric_score      == 3.0
        assert WoodQuality.FAIR.numeric_score      == 2.0
        assert WoodQuality.POOR.numeric_score      == 1.0

    # The colour rule is NOT tested here. It belongs to test_quality_colors.py, which owns the
    # model/quality-colors slug; asserting it here as well put the same rule under two slugs.
    # Mirrors the same removal from Swift PlatePropertiesTests.swift (#17).

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