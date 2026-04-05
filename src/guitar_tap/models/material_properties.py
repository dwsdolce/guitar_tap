"""
Plate and brace acoustic material-property calculations.

Mirrors Swift MaterialProperties.swift.

Acoustic and mechanical properties of tonewoods derived from free-free beam tap tests.

Background — The Tap-Test Method:
  Suspending a rectangular plate at its nodal points and tapping it produces a resonant
  "ping" whose fundamental frequency depends on the plate's geometry, mass, and elastic
  moduli.  By measuring the fundamental frequency in the longitudinal (along-grain) and
  cross-grain directions, the Young's moduli E_L and E_C can be back-calculated using
  the Euler–Bernoulli free-free beam equation.  A third optional tap at 45° (the FLC or
  "diagonal" tap) yields the shear modulus G_LC.

Free-Free Beam Equation (Haines / Coates):

    E = 48 × π² × ρ × f² × L⁴ / (β × L)²

  where:
    ρ   = density (kg/m³)
    f   = fundamental bending frequency (Hz)
    L   = beam length (m) — use plate length for L-tap, plate width for C-tap
    (βL)² = 22.37 for the first free-free bending mode

Key Derived Properties:

  Specific modulus | E / ρ (GPa/(g/cm³)) | Primary quality indicator; higher = lighter, stiffer wood
  Speed of sound   | √(E/ρ) (m/s)        | Governs how quickly vibrations travel through the plate
  Radiation ratio  | c_L / ρ             | Efficiency of acoustic power radiation
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# MARK: - MaterialDimensions

@dataclass
class MaterialDimensions:
    """The physical dimensions and mass of a rectangular material sample (plate or brace).

    All stored values use millimetres and grams (the practical units when measuring
    guitar plates and braces with callipers and a digital scale).  Conversion methods
    return SI units for use in acoustic calculations.

    Mirrors Swift MaterialDimensions struct.

    NOTE — Naming: Swift stores SI units directly (length in metres, mass in kilograms)
    and provides mm/g initialisers.  Python stores in user units (mm/g) and provides
    conversion methods.  Numeric results are identical.
    """

    length_mm: float    # L — along-grain direction (mm)
    width_mm: float     # W — cross-grain direction (mm)
    thickness_mm: float # T — thickness (mm)
    mass_g: float       # m — mass (g)

    # MARK: - Unit Conversions

    def length(self) -> float:
        """Length of the sample in metres.

        For wood, orient the sample so that this dimension runs along the grain
        (longitudinal direction).
        """
        return self.length_mm / 1000.0

    def width(self) -> float:
        """Width of the sample in metres.

        For wood, this dimension runs across the grain (cross-grain direction).
        """
        return self.width_mm / 1000.0

    def thickness(self) -> float:
        """Thickness of the sample in metres."""
        return self.thickness_mm / 1000.0

    def mass(self) -> float:
        """Mass of the sample in kilograms."""
        return self.mass_g / 1000.0

    # MARK: - Derived Properties

    def volume(self) -> float:
        """Volume of the sample in m³."""
        return self.length() * self.width() * self.thickness()

    def density(self) -> float:
        """Density of the sample in kg/m³.

        Returns 0 when volume is zero to avoid division-by-zero.

        Mirrors Swift MaterialDimensions.density.
        """
        vol = self.volume()
        return self.mass() / vol if vol > 0 else 0.0

    def density_g_per_cm3(self) -> float:
        """Density in g/cm³, the unit conventionally used for wood density tables.

        Equals density / 1000.  Typical guitar-top spruce: 0.35–0.45 g/cm³.

        Mirrors Swift MaterialDimensions.densityGPerCm3.
        """
        return self.density() / 1000.0

    def is_valid(self) -> bool:
        """Return True when all dimensions and mass are positive."""
        return (
            self.length_mm > 0
            and self.width_mm > 0
            and self.thickness_mm > 0
            and self.mass_g > 0
        )


# Backward-compatible alias — existing callers that used PlateDimensions will continue to work.
PlateDimensions = MaterialDimensions


# MARK: - WoodQuality

class WoodQuality(Enum):
    """A subjective quality rating for a tonewood sample based on its specific modulus.

    Thresholds are calibrated against published ranges for instrument-grade tonewoods.
    The grading scales differ by wood species (spruce vs cedar) and measurement direction
    (longitudinal vs cross-grain) because the physical ranges are very different.

    Mirrors Swift WoodQuality enum (MaterialProperties.swift).
    """

    EXCELLENT = "Excellent"   # Exceptional instrument-grade material; master-grade or AAA.
    VERY_GOOD = "Very Good"   # High-quality material; AAA–AA classification.
    GOOD      = "Good"        # Good general-purpose instrument material; AA–A classification.
    FAIR      = "Fair"        # Below-average; usable but not ideal for fine instruments.
    POOR      = "Poor"        # Poor; not recommended for fine instrument use.

    # MARK: - Numeric Score

    @property
    def numeric_score(self) -> float:
        """Numeric score (1–5) for arithmetic quality averaging.

        Used internally by PlateProperties.overall_quality to blend longitudinal and
        cross-grain ratings into a single overall score.

        Mirrors Swift WoodQuality.numericScore.
        """
        return {
            WoodQuality.EXCELLENT: 5.0,
            WoodQuality.VERY_GOOD: 4.0,
            WoodQuality.GOOD:      3.0,
            WoodQuality.FAIR:      2.0,
            WoodQuality.POOR:      1.0,
        }[self]

    # MARK: - Color

    @property
    def color(self) -> str:
        """Hex display colour for quality labels and PDF report cells.

        Single source of truth — mirrors Swift WoodQuality.color.
        Hex values are the closest system-colour equivalents for:
          .green (#34C759), .mint (#00C7BE), .blue (#007AFF),
          .orange (#FF9500), .red (#FF3B30).
        """
        return {
            WoodQuality.EXCELLENT: "#34C759",   # SwiftUI .green
            WoodQuality.VERY_GOOD: "#00C7BE",   # SwiftUI .mint
            WoodQuality.GOOD:      "#007AFF",   # SwiftUI .blue
            WoodQuality.FAIR:      "#FF9500",   # SwiftUI .orange
            WoodQuality.POOR:      "#FF3B30",   # SwiftUI .red
        }[self]

    # MARK: - Supporting Enums

    class Direction(Enum):
        """The grain direction in which a measurement was taken.

        Mirrors Swift WoodQuality.Direction.
        """
        LONGITUDINAL = "longitudinal"  # Along the grain (parallel to the wood fibres).
        CROSS        = "cross"         # Across the grain (perpendicular to the wood fibres).

    class WoodType(Enum):
        """The species of wood being evaluated, used to select the appropriate grading thresholds.

        Mirrors Swift WoodQuality.WoodType.
        """
        SPRUCE   = "spruce"
        CEDAR    = "cedar"
        MAPLE    = "maple"
        ROSEWOOD = "rosewood"

    # MARK: - Evaluation

    @staticmethod
    def evaluate(
        specific_modulus: float,
        direction: "WoodQuality.Direction",
        wood_type: "WoodQuality.WoodType",
    ) -> "WoodQuality":
        """Evaluate the quality of a wood sample from its specific modulus value.

        Thresholds are based on published instrument-grade quality ranges:

          Species  Direction  Excellent  Very Good  Good  Fair  Poor
          -------  ---------  ---------  ---------  ----  ----  ----
          Spruce   Long.      ≥ 25       ≥ 22       ≥ 19  ≥ 16  < 16
          Spruce   Cross      ≥ 1.5      ≥ 1.2      ≥ 0.9 ≥ 0.6 < 0.6
          Cedar    Long.      ≥ 22       ≥ 19       ≥ 16  ≥ 13  < 13
          Cedar    Cross      ≥ 1.3      ≥ 1.0      ≥ 0.7 ≥ 0.5 < 0.5
          Others   —          ≥ 20       ≥ 16       ≥ 12  ≥ 8   < 8

        All specific-modulus values are in GPa/(g/cm³).

        - Parameters:
          - specific_modulus: Measured specific modulus in GPa/(g/cm³).
          - direction: Whether this is a longitudinal or cross-grain measurement.
          - wood_type: Species of wood being graded.
        - Returns: The appropriate WoodQuality rating.

        Mirrors Swift WoodQuality.evaluate(specificModulus:direction:woodType:).
        """
        D = WoodQuality.Direction
        T = WoodQuality.WoodType

        if wood_type == T.SPRUCE and direction == D.LONGITUDINAL:
            # Typical instrument-grade spruce E_L/ρ: 15–30 GPa/(g/cm³)
            # Master grade ≥ 25, AAA ≥ 22, AA ≥ 19, A ≥ 16, below-grade < 16
            if specific_modulus >= 25: return WoodQuality.EXCELLENT
            if specific_modulus >= 22: return WoodQuality.VERY_GOOD
            if specific_modulus >= 19: return WoodQuality.GOOD
            if specific_modulus >= 16: return WoodQuality.FAIR
            return WoodQuality.POOR

        if wood_type == T.SPRUCE and direction == D.CROSS:
            # Cross-grain specific modulus is much lower: 0.5–2.0 GPa/(g/cm³)
            if specific_modulus >= 1.5: return WoodQuality.EXCELLENT
            if specific_modulus >= 1.2: return WoodQuality.VERY_GOOD
            if specific_modulus >= 0.9: return WoodQuality.GOOD
            if specific_modulus >= 0.6: return WoodQuality.FAIR
            return WoodQuality.POOR

        if wood_type == T.CEDAR and direction == D.LONGITUDINAL:
            # Cedar is inherently less stiff than spruce; thresholds shifted down ~3 points
            if specific_modulus >= 22: return WoodQuality.EXCELLENT
            if specific_modulus >= 19: return WoodQuality.VERY_GOOD
            if specific_modulus >= 16: return WoodQuality.GOOD
            if specific_modulus >= 13: return WoodQuality.FAIR
            return WoodQuality.POOR

        if wood_type == T.CEDAR and direction == D.CROSS:
            if specific_modulus >= 1.3: return WoodQuality.EXCELLENT
            if specific_modulus >= 1.0: return WoodQuality.VERY_GOOD
            if specific_modulus >= 0.7: return WoodQuality.GOOD
            if specific_modulus >= 0.5: return WoodQuality.FAIR
            return WoodQuality.POOR

        # Generic thresholds for maple, rosewood, and other species not individually calibrated
        if specific_modulus >= 20: return WoodQuality.EXCELLENT
        if specific_modulus >= 16: return WoodQuality.VERY_GOOD
        if specific_modulus >= 12: return WoodQuality.GOOD
        if specific_modulus >=  8: return WoodQuality.FAIR
        return WoodQuality.POOR


# MARK: - PlateProperties

class PlateProperties:
    """Acoustic properties of a rectangular plate sample calculated from two or three tap-test
    fundamental frequencies.

    Stores raw inputs (dimensions + frequencies) and exposes all acoustic results as computed
    properties — exactly mirroring Swift's PlateProperties struct in MaterialProperties.swift.

    Two tap orientations are required for a full plate analysis (longitudinal and cross-grain);
    a third optional diagonal tap (f_flc) yields the shear modulus.

    See Also: BraceProperties for single-tap longitudinal-only analysis.
    See Also: WoodQuality for quality assessment thresholds.

    Mirrors Swift PlateProperties struct (MaterialProperties.swift).
    """

    def __init__(
        self,
        dimensions: "MaterialDimensions",
        f_long: float,
        f_cross: float,
        f_flc: Optional[float] = None,
    ) -> None:
        """Create a PlateProperties record from dimensions and measured fundamental frequencies.

        Mirrors Swift PlateProperties.init(dimensions:fundamentalFrequencyLong:fundamentalFrequencyCross:fundamentalFrequencyFlc:).

        - Parameters:
          - dimensions: Physical dimensions and mass of the plate.
          - f_long: Along-grain fundamental frequency in Hz. Mirrors Swift fundamentalFrequencyLong.
          - f_cross: Cross-grain fundamental frequency in Hz. Mirrors Swift fundamentalFrequencyCross.
          - f_flc: Optional FLC diagonal frequency in Hz. Mirrors Swift fundamentalFrequencyFlc.
        """
        self.dimensions = dimensions    # Mirrors Swift let dimensions: MaterialDimensions
        self.f_long = f_long            # Mirrors Swift let fundamentalFrequencyLong: Float
        self.f_cross = f_cross          # Mirrors Swift let fundamentalFrequencyCross: Float
        self.f_flc = f_flc              # Mirrors Swift let fundamentalFrequencyFlc: Float?

    # MARK: - Beam-Formula Young's Moduli

    @property
    def youngsModulusLong(self) -> float:
        """Young's modulus along the grain (E_L) in Pascals, from the free-free beam formula.

        Formula: E = 48 × π² × ρ × fL² × L⁴ / (22.37 × t)²

        Mirrors Swift PlateProperties.youngsModulusLong.
        """
        t = self.dimensions.thickness()
        if t <= 0 or self.dimensions.density() <= 0:
            return 0.0
        return _euler_bernoulli_e(self.dimensions.density(), self.f_long, self.dimensions.length(), t, 22.37)

    @property
    def youngsModulusCross(self) -> float:
        """Young's modulus across the grain (E_C) in Pascals, from the free-free beam formula.

        Formula: E = 48 × π² × ρ × fC² × W⁴ / (22.37 × t)²

        Mirrors Swift PlateProperties.youngsModulusCross.
        """
        t = self.dimensions.thickness()
        if t <= 0 or self.dimensions.density() <= 0:
            return 0.0
        return _euler_bernoulli_e(self.dimensions.density(), self.f_cross, self.dimensions.width(), t, 22.37)

    # MARK: - Convenience Unit Conversions

    @property
    def youngsModulusLongGPa(self) -> float:
        """Young's modulus along the grain in GPa. Mirrors Swift PlateProperties.youngsModulusLongGPa."""
        return self.youngsModulusLong / 1e9

    @property
    def youngsModulusCrossGPa(self) -> float:
        """Young's modulus across the grain in GPa. Mirrors Swift PlateProperties.youngsModulusCrossGPa."""
        return self.youngsModulusCross / 1e9

    # MARK: - Speed of Sound

    @property
    def c_long_m_s(self) -> float:
        """Speed of sound along the grain in m/s.

        Formula: c = √(E_L / ρ). Mirrors Swift PlateProperties.speedOfSoundLong.
        """
        rho = self.dimensions.density()
        if rho <= 0:
            return 0.0
        return math.sqrt(self.youngsModulusLong / rho)

    @property
    def c_cross_m_s(self) -> float:
        """Speed of sound across the grain in m/s.

        Formula: c = √(E_C / ρ). Mirrors Swift PlateProperties.speedOfSoundCross.
        """
        rho = self.dimensions.density()
        if rho <= 0:
            return 0.0
        return math.sqrt(self.youngsModulusCross / rho)

    # MARK: - Density

    @property
    def density_kg_m3(self) -> float:
        """Density of the sample in kg/m³. Mirrors Swift MaterialDimensions.density."""
        return self.dimensions.density()

    # MARK: - Specific Modulus

    @property
    def specific_modulus_long(self) -> float:
        """Specific modulus along the grain in GPa/(g/cm³).

        Mirrors Swift PlateProperties.specificModulusLong.
        """
        rho_g = self.dimensions.density_g_per_cm3()
        if rho_g <= 0:
            return 0.0
        return self.youngsModulusLongGPa / rho_g

    @property
    def specific_modulus_cross(self) -> float:
        """Specific modulus across the grain in GPa/(g/cm³).

        Mirrors Swift PlateProperties.specificModulusCross.
        """
        rho_g = self.dimensions.density_g_per_cm3()
        if rho_g <= 0:
            return 0.0
        return self.youngsModulusCrossGPa / rho_g

    # MARK: - Radiation Ratio

    @property
    def radiation_ratio_long(self) -> float:
        """Sound radiation ratio along the grain: c_L / ρ (m⁴/(kg·s)).

        Mirrors Swift PlateProperties.radiationRatioLong.
        """
        rho = self.dimensions.density()
        if rho <= 0:
            return 0.0
        return self.c_long_m_s / rho

    @property
    def radiation_ratio_cross(self) -> float:
        """Sound radiation ratio across the grain: c_C / ρ (m⁴/(kg·s)).

        Mirrors Swift PlateProperties.radiationRatioCross.
        """
        rho = self.dimensions.density()
        if rho <= 0:
            return 0.0
        return self.c_cross_m_s / rho

    # MARK: - Anisotropy Ratios

    @property
    def cross_long_ratio(self) -> float:
        """E_C / E_L (typical 0.04–0.08). Mirrors Swift PlateProperties.crossLongRatio."""
        e_l = self.youngsModulusLong
        return self.youngsModulusCross / e_l if e_l > 0 else 0.0

    @property
    def long_cross_ratio(self) -> float:
        """E_L / E_C (typical 12–25). Mirrors Swift PlateProperties.longCrossRatio."""
        e_c = self.youngsModulusCross
        return self.youngsModulusLong / e_c if e_c > 0 else 0.0

    # MARK: - Quality Assessment

    @property
    def quality_long(self) -> str:
        """WoodQuality raw value for the longitudinal direction (spruce thresholds).

        Mirrors Swift PlateProperties.spruceQualityLong.rawValue.
        """
        return WoodQuality.evaluate(
            self.specific_modulus_long,
            WoodQuality.Direction.LONGITUDINAL,
            WoodQuality.WoodType.SPRUCE,
        ).value

    @property
    def quality_cross(self) -> str:
        """WoodQuality raw value for the cross-grain direction (spruce thresholds).

        Mirrors Swift PlateProperties.spruceQualityCross.rawValue.
        """
        return WoodQuality.evaluate(
            self.specific_modulus_cross,
            WoodQuality.Direction.CROSS,
            WoodQuality.WoodType.SPRUCE,
        ).value

    @property
    def overall_quality(self) -> str:
        """Weighted (70% long + 30% cross) overall quality rating.

        Mirrors Swift PlateProperties.overallQuality.rawValue.
        """
        long_score  = WoodQuality.evaluate(
            self.specific_modulus_long,
            WoodQuality.Direction.LONGITUDINAL,
            WoodQuality.WoodType.SPRUCE,
        ).numeric_score * 0.7
        cross_score = WoodQuality.evaluate(
            self.specific_modulus_cross,
            WoodQuality.Direction.CROSS,
            WoodQuality.WoodType.SPRUCE,
        ).numeric_score * 0.3
        combined = long_score + cross_score
        if   combined >= 4.5: return WoodQuality.EXCELLENT.value
        elif combined >= 3.5: return WoodQuality.VERY_GOOD.value
        elif combined >= 2.5: return WoodQuality.GOOD.value
        elif combined >= 1.5: return WoodQuality.FAIR.value
        else:                 return WoodQuality.POOR.value

    # MARK: - Gore Plate Coefficients

    _vcl: float = 0.05          # Poisson's ratio ν_CL. Mirrors Swift PlateProperties.vcl.
    _vlc_vcl: float = 0.02      # Product ν_LC × ν_CL. Mirrors Swift PlateProperties.vlcVcl.

    @property
    def _gore_coef1(self) -> float:
        """Gore coefficient 1. Mirrors Swift PlateProperties.goreCoef1."""
        term = (math.pi / 2.0) ** 2 * (1.5 ** 4)
        return (1.0 / term) * 12.0 * (1.0 - PlateProperties._vlc_vcl)

    @property
    def _gore_coef2(self) -> float:
        """Gore coefficient 2. Mirrors Swift PlateProperties.goreCoef2."""
        return math.pi * math.sqrt(12.0 * (1.0 - PlateProperties._vlc_vcl) / 126.0)

    @property
    def _gore_coef3(self) -> float:
        """Gore coefficient 3. Mirrors Swift PlateProperties.goreCoef3."""
        return 4.0 * PlateProperties._vcl / 7.0

    @property
    def _gore_coef4(self) -> float:
        """Gore coefficient 4. Mirrors Swift PlateProperties.goreCoef4."""
        return 4.0 * 12.0 * (1.0 - PlateProperties._vlc_vcl) / 42.0

    # MARK: - Gore Young's Moduli

    @property
    def gore_E_long_pa(self) -> float:
        """Young's modulus along the grain using Gore's plate formula, in Pascals.

        Mirrors Swift PlateProperties.goreYoungsModulusLong.
        """
        t = self.dimensions.thickness()
        rho = self.dimensions.density()
        if t <= 0 or rho <= 0:
            return 0.0
        L = self.dimensions.length()
        return self._gore_coef1 * rho * L**4 * self.f_long**2 / (t * t)

    @property
    def gore_E_cross_pa(self) -> float:
        """Young's modulus across the grain using Gore's plate formula, in Pascals.

        Mirrors Swift PlateProperties.goreYoungsModulusCross.
        """
        t = self.dimensions.thickness()
        rho = self.dimensions.density()
        if t <= 0 or rho <= 0:
            return 0.0
        W = self.dimensions.width()
        return self._gore_coef1 * rho * W**4 * self.f_cross**2 / (t * t)

    @property
    def gore_shear_modulus(self) -> Optional[float]:
        """Shear modulus G_LC using Gore's formula, in Pascals.

        Returns None when the optional FLC tap was not performed (f_flc is None).

        Mirrors Swift PlateProperties.goreShearModulus.
        """
        if self.f_flc is None or self.f_flc <= 0:
            return None
        t = self.dimensions.thickness()
        rho = self.dimensions.density()
        if t <= 0 or rho <= 0:
            return None
        L = self.dimensions.length()
        W = self.dimensions.width()
        coef = 12.0 / (math.pi ** 2)
        return coef * rho * L**2 * W**2 * self.f_flc**2 / (t * t)


# MARK: - BraceProperties

class BraceProperties:
    """Acoustic properties of a rectangular brace strip calculated from a single longitudinal tap.

    Stores raw inputs (dimensions + f_long) and exposes all acoustic results as computed
    properties — exactly mirroring Swift's BraceProperties struct in MaterialProperties.swift.

    The formula used is the same Euler–Bernoulli free-free beam equation as for plates,
    but with the coefficient 22.37332 (more precise) rather than 22.37.

    See Also: PlateProperties for the full two-/three-tap plate analysis.

    Mirrors Swift BraceProperties struct (MaterialProperties.swift).
    """

    def __init__(self, dimensions: "MaterialDimensions", f_long: float) -> None:
        """Create a BraceProperties record from dimensions and the longitudinal tap frequency.

        Mirrors Swift BraceProperties.init(dimensions:fundamentalFrequencyLong:).

        - Parameters:
          - dimensions: Physical dimensions and mass of the brace.
          - f_long: Along-grain fundamental frequency in Hz. Mirrors Swift fundamentalFrequencyLong.
        """
        self.dimensions = dimensions    # Mirrors Swift let dimensions: MaterialDimensions
        self.f_long = f_long            # Mirrors Swift let fundamentalFrequencyLong: Float

    # MARK: - Calculated Properties

    @property
    def youngsModulusLong(self) -> float:
        """Young's modulus along the grain (E_L) in Pascals.

        Formula: E = 48 × π² × ρ × fL² × L⁴ / (22.37332 × t)²

        Uses the more precise βL coefficient 22.37332. Mirrors Swift BraceProperties.youngsModulusLong.
        """
        t = self.dimensions.thickness()
        if t <= 0 or self.dimensions.density() <= 0:
            return 0.0
        return _euler_bernoulli_e(self.dimensions.density(), self.f_long, self.dimensions.length(), t, 22.37332)

    @property
    def youngsModulusLongGPa(self) -> float:
        """Young's modulus along the grain in GPa. Mirrors Swift BraceProperties.youngsModulusLongGPa."""
        return self.youngsModulusLong / 1e9

    @property
    def c_long_m_s(self) -> float:
        """Speed of sound along the grain in m/s.

        Formula: c = √(E_L / ρ). Mirrors Swift BraceProperties.speedOfSoundLong.
        """
        rho = self.dimensions.density()
        if rho <= 0:
            return 0.0
        return math.sqrt(self.youngsModulusLong / rho)

    @property
    def density_kg_m3(self) -> float:
        """Density of the sample in kg/m³. Mirrors Swift MaterialDimensions.density."""
        return self.dimensions.density()

    @property
    def specific_modulus(self) -> float:
        """Specific modulus along the grain in GPa/(g/cm³) — primary quality metric.

        Mirrors Swift BraceProperties.specificModulusLong.
        """
        rho_g = self.dimensions.density_g_per_cm3()
        if rho_g <= 0:
            return 0.0
        return self.youngsModulusLongGPa / rho_g

    @property
    def radiation_ratio(self) -> float:
        """Sound radiation ratio: c_L / ρ (m⁴/(kg·s)).

        Mirrors Swift BraceProperties.radiationRatioLong.
        """
        rho = self.dimensions.density()
        if rho <= 0:
            return 0.0
        return self.c_long_m_s / rho

    @property
    def quality(self) -> str:
        """WoodQuality raw value for the longitudinal direction (spruce thresholds).

        Mirrors Swift BraceProperties.spruceQuality.rawValue.
        """
        return WoodQuality.evaluate(
            self.specific_modulus,
            WoodQuality.Direction.LONGITUDINAL,
            WoodQuality.WoodType.SPRUCE,
        ).value


# MARK: - TonewoodReference

class TonewoodReference:
    """Published reference values for common guitar tonewoods.

    These typical values can be used to contextualise measurements from tap tests, or as
    starting points when a reference sample is not available.  Values are approximate averages
    from the lutherie literature.

    Mirrors Swift TonewoodReference struct (MaterialProperties.swift).
    """

    # Typical acoustic properties of Sitka Spruce, the most common guitar-top wood.
    sitka_spruce_typical = dict(
        density=0.40,              # g/cm³
        speed_of_sound_long=5500,  # m/s
        specific_modulus_long=22,  # GPa/(g/cm³)
        radiation_ratio=12,        # m⁴/(kg·s)
    )

    # Typical acoustic properties of Engelmann Spruce.
    engelmann_spruce_typical = dict(
        density=0.38,
        speed_of_sound_long=5300,
        specific_modulus_long=21,
        radiation_ratio=12.5,
    )

    # Typical acoustic properties of European (German) Spruce, often considered premium.
    european_spruce_typical = dict(
        density=0.42,
        speed_of_sound_long=5800,
        specific_modulus_long=24,
        radiation_ratio=13,
    )

    # Typical acoustic properties of Western Red Cedar.
    western_red_cedar_typical = dict(
        density=0.35,
        speed_of_sound_long=4800,
        specific_modulus_long=18,
        radiation_ratio=11,
    )


# MARK: - Private Helpers

def _euler_bernoulli_e(rho: float, f: float, L: float, t: float, beta_l_sq: float) -> float:
    """Young's modulus in Pascals from the free-free beam equation.

    E = 48 × π² × ρ × f² × L⁴ / (βL × t)²
    """
    return 48.0 * math.pi**2 * rho * f**2 * L**4 / (beta_l_sq * t) ** 2


# MARK: - Calculation Functions

def calculate_brace_properties(dims: MaterialDimensions, f_long_hz: float) -> BraceProperties:
    """Create a BraceProperties from dimensions and a single longitudinal tap frequency.

    Thin constructor — validation only.  All acoustic results are computed lazily by
    BraceProperties as @property accessors, mirroring Swift BraceProperties.

    - Parameters:
      - dims: Physical dimensions and mass of the brace sample.
      - f_long_hz: Along-grain fundamental frequency in Hz.
    - Returns: BraceProperties instance.

    Mirrors Swift BraceProperties.init(dimensions:fundamentalFrequencyLong:).
    """
    if not dims.is_valid():
        raise ValueError("Brace dimensions must all be positive.")
    if f_long_hz <= 0:
        raise ValueError("Tap frequency must be positive.")
    return BraceProperties(dimensions=dims, f_long=f_long_hz)


def calculate_plate_properties(
    dims: MaterialDimensions,
    f_long_hz: float,
    f_cross_hz: float,
    f_flc_hz: Optional[float] = None,
) -> PlateProperties:
    """Create a PlateProperties from dimensions and tap frequencies.

    Thin constructor — validation only.  All acoustic results are computed lazily by
    PlateProperties as @property accessors, mirroring Swift PlateProperties.

    - Parameters:
      - dims: Physical dimensions and mass of the plate sample.
      - f_long_hz: Along-grain fundamental frequency in Hz.
      - f_cross_hz: Cross-grain fundamental frequency in Hz.
      - f_flc_hz: Optional FLC diagonal frequency in Hz.
    - Returns: PlateProperties instance.

    Mirrors Swift PlateProperties.init(dimensions:fundamentalFrequencyLong:fundamentalFrequencyCross:fundamentalFrequencyFlc:).
    """
    if not dims.is_valid():
        raise ValueError("Plate dimensions must all be positive.")
    if f_long_hz <= 0 or f_cross_hz <= 0:
        raise ValueError("Tap frequencies must be positive.")
    return PlateProperties(dimensions=dims, f_long=f_long_hz, f_cross=f_cross_hz, f_flc=f_flc_hz)


def calculate_gore_target_thickness(
    props: PlateProperties,
    body_length_mm: float,
    body_width_mm: float,
    fvs: float,
) -> float | None:
    """Calculate Gore target thickness (Eq. 4.5-7) in mm, or None if inputs are invalid.

    Mirrors Swift PlateProperties.goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:)
    exactly — same signature shape, same return type (Float? → float | None), same algorithm.

    G_LC is read exclusively from props.gore_shear_modulus (derived from the FLC tap);
    falls back to 0 when the tap was not performed — mirrors Swift's `(goreShearModulus ?? 0)`.

    Numerator:   Coef₂ × f_vs × a² × √ρ
    Denominator: √(E_L_GPa + (a/b)⁴·E_C_GPa + (a/b)²·(Coef₃·E_L_GPa + Coef₄·G_LC_GPa)) × √1e9

    - Parameters:
      - props: Plate properties (Gore plate moduli and density are used).
      - body_length_mm: Guitar body length (neck joint to tail block) in mm.
      - body_width_mm: Guitar lower-bout width in mm.
      - fvs: Target vibrational stiffness (f_vs).
    - Returns: Target plate thickness in mm, or None if any input is zero or invalid.
    """
    if body_length_mm <= 0 or body_width_mm <= 0 or fvs <= 0:
        return None
    if props.density_kg_m3 <= 0:
        return None

    a   = body_length_mm / 1000.0   # Guitar body length in metres
    b   = body_width_mm  / 1000.0   # Lower bout width in metres
    rho = props.density_kg_m3

    # Convert moduli to GPa for the denominator calculation; result is in Pa via ×10⁹.
    # Mirrors Swift lines 464-467.
    el_gpa  = props.gore_E_long_pa  / 1.0e9
    ec_gpa  = props.gore_E_cross_pa / 1.0e9
    glc_gpa = (props.gore_shear_modulus or 0.0) / 1.0e9

    # Numerator: scale target stiffness by body area and root-density.
    # Mirrors Swift line 470.
    numerator = props._gore_coef2 * fvs * a * a * math.sqrt(rho)

    # Denominator: anisotropic stiffness sum scaled by body aspect ratio.
    # Mirrors Swift lines 473-478.
    a_over_b  = a / b
    a_over_b2 = a_over_b  * a_over_b
    a_over_b4 = a_over_b2 * a_over_b2
    denominator_gpa = (
        el_gpa
        + a_over_b4 * ec_gpa
        + a_over_b2 * (props._gore_coef3 * el_gpa + props._gore_coef4 * glc_gpa)
    )
    if denominator_gpa <= 0:
        return None

    # Convert denominator GPa → Pa, then compute thickness in mm.
    # Mirrors Swift lines 482-483.
    denominator_pa = denominator_gpa * 1.0e9
    return numerator / math.sqrt(denominator_pa) * 1000.0
