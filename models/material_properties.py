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

NOTE — Structural divergence from Swift:
  Swift's PlateProperties and BraceProperties store raw inputs (dimensions + frequencies)
  and expose results as computed properties.  Python stores pre-computed results in
  dataclass fields (calculated by calculate_plate_properties() and
  calculate_brace_properties() standalone functions).  Both produce identical numeric results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


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


# Quality colour hex codes — Python-only (view concern; no Swift equivalent).
# Used by the Python UI to tint result labels with the same colours as SwiftUI.
QUALITY_COLORS: dict[str, str] = {
    "Excellent": "#34C759",   # SwiftUI .green
    "Very Good": "#00C7BE",   # SwiftUI .mint
    "Good":      "#007AFF",   # SwiftUI .blue  (system accent)
    "Fair":      "#FF9500",   # SwiftUI .orange
    "Poor":      "#FF3B30",   # SwiftUI .red
}


# MARK: - PlateProperties

@dataclass
class PlateProperties:
    """Acoustic properties of a rectangular plate sample calculated from two or three tap-test
    fundamental frequencies.

    Two tap orientations are required for a full plate analysis (longitudinal and cross-grain);
    a third optional diagonal tap yields the shear modulus.

    NOTE — Structural divergence from Swift:
      Swift's PlateProperties stores raw inputs (dimensions + frequencies) and exposes results
      as computed ``var`` properties.  This Python version stores pre-computed results; the
      calculation is performed by calculate_plate_properties().  Both produce identical values.

    See Also: BraceProperties for single-tap longitudinal-only analysis.
    See Also: WoodQuality for quality assessment thresholds.

    Mirrors Swift PlateProperties struct (MaterialProperties.swift).
    """

    f_long: float               # Fundamental bending frequency, longitudinal tap (Hz).
    f_cross: float              # Fundamental bending frequency, cross-grain tap (Hz).
    density_kg_m3: float        # Density of the sample (kg/m³).
    E_long_GPa: float           # Young's modulus along the grain (GPa).
    E_cross_GPa: float          # Young's modulus across the grain (GPa).
    c_long_m_s: float           # Speed of sound along the grain (m/s).
    c_cross_m_s: float          # Speed of sound across the grain (m/s).
    specific_modulus_long: float    # Specific modulus along the grain (GPa/(g/cm³)).
    specific_modulus_cross: float   # Specific modulus across the grain (GPa/(g/cm³)).
    radiation_ratio_long: float     # Sound radiation ratio along the grain (m⁴/(kg·s)).
    radiation_ratio_cross: float    # Sound radiation ratio across the grain (m⁴/(kg·s)).
    quality_long: str               # WoodQuality raw value for the longitudinal direction.
    quality_cross: str              # WoodQuality raw value for the cross-grain direction.
    overall_quality: str            # Weighted (70% long + 30% cross) overall quality.
    cross_long_ratio: float         # E_C / E_L (typical 0.04–0.08).
    long_cross_ratio: float         # E_L / E_C (typical 12–25).


# MARK: - BraceProperties

@dataclass
class BraceProperties:
    """Acoustic properties of a rectangular brace strip calculated from a single longitudinal tap.

    Braces are analysed using only the along-grain (longitudinal) fundamental frequency
    because only the along-grain stiffness and speed of sound matter for their structural
    and acoustic function in the instrument.

    The formula used is the same Euler–Bernoulli free-free beam equation as for plates,
    but with the coefficient 22.37332 (more precise) rather than 22.37.

    NOTE — Structural divergence from Swift:
      Swift's BraceProperties stores raw inputs and exposes results as computed vars.
      Python stores pre-computed results; calculation is performed by
      calculate_brace_properties().

    See Also: PlateProperties for the full two-/three-tap plate analysis.

    Mirrors Swift BraceProperties struct (MaterialProperties.swift).
    """

    f_long: float           # Fundamental bending frequency, longitudinal tap (Hz).
    density_kg_m3: float    # Density of the sample (kg/m³).
    E_long_GPa: float       # Young's modulus along the grain (GPa).
    c_long_m_s: float       # Speed of sound along the grain (m/s).
    specific_modulus: float # Specific modulus along the grain (GPa/(g/cm³)) — primary quality metric.
    radiation_ratio: float  # Sound radiation ratio: c_L / ρ (m⁴/(kg·s)).
    quality: str            # WoodQuality raw value for the longitudinal direction.


# MARK: - GoreThicknessResult

@dataclass
class GoreThicknessResult:
    """Result of Gore Eq. 4.5-7 target thickness calculation.

    Mirrors Swift PlateProperties.goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:)
    return value (expressed as a standalone result object in Python).
    """

    thickness_mm: float     # Calculated target plate thickness (mm).
    body_length_mm: float   # Guitar body length used in the calculation (mm).
    body_width_mm: float    # Guitar lower-bout width used in the calculation (mm).
    fvs: float              # Vibrational stiffness target (f_vs) used.
    preset_name: str        # e.g. "Steel String Top"
    glc_pa: float | None    # Shear modulus G_LC used (None → treated as 0).


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


# MARK: - Legacy Quality Helpers (Python-only, kept for backward compatibility)
# These standalone functions predate WoodQuality.evaluate() and are retained for
# callers that have not yet migrated.

def wood_quality_long(specific_modulus: float) -> str:
    """Quality rating string for longitudinal specific modulus (GPa/(g/cm³)), spruce thresholds.

    Deprecated: use WoodQuality.evaluate(specific_modulus, WoodQuality.Direction.LONGITUDINAL,
    WoodQuality.WoodType.SPRUCE).value instead.
    """
    if specific_modulus >= 25:
        return "Excellent"
    if specific_modulus >= 22:
        return "Very Good"
    if specific_modulus >= 19:
        return "Good"
    if specific_modulus >= 16:
        return "Fair"
    return "Poor"


def wood_quality_cross(specific_modulus: float) -> str:
    """Quality rating string for cross-grain specific modulus (GPa/(g/cm³)), spruce thresholds.

    Deprecated: use WoodQuality.evaluate(specific_modulus, WoodQuality.Direction.CROSS,
    WoodQuality.WoodType.SPRUCE).value instead.
    """
    if specific_modulus >= 1.5:
        return "Excellent"
    if specific_modulus >= 1.2:
        return "Very Good"
    if specific_modulus >= 0.9:
        return "Good"
    if specific_modulus >= 0.6:
        return "Fair"
    return "Poor"


# MARK: - Calculation Functions

def calculate_brace_properties(dims: MaterialDimensions, f_long_hz: float) -> BraceProperties:
    """Calculate acoustic properties for a brace from a single longitudinal tap.

    Uses the precise βL coefficient 22.37332 (vs 22.37 for plates), mirroring Swift
    BraceProperties.youngsModulusLong.

    - Parameters:
      - dims: Physical dimensions and mass of the brace sample.
      - f_long_hz: Along-grain fundamental frequency in Hz.
    - Returns: Calculated BraceProperties.

    Mirrors Swift BraceProperties computed properties via calculate_brace_properties().
    """
    if not dims.is_valid():
        raise ValueError("Brace dimensions must all be positive.")
    if f_long_hz <= 0:
        raise ValueError("Tap frequency must be positive.")

    rho     = dims.density()
    rho_g   = dims.density_g_per_cm3()
    L       = dims.length()
    t       = dims.thickness()

    E_L     = _euler_bernoulli_e(rho, f_long_hz, L, t, 22.37332)
    E_L_GPa = E_L / 1e9
    c_L     = math.sqrt(E_L / rho)
    spec    = E_L_GPa / rho_g
    rad     = c_L / rho

    return BraceProperties(
        f_long=f_long_hz,
        density_kg_m3=rho,
        E_long_GPa=E_L_GPa,
        c_long_m_s=c_L,
        specific_modulus=spec,
        radiation_ratio=rad,
        quality=wood_quality_long(spec),
    )


def calculate_plate_properties(
    dims: MaterialDimensions,
    f_long_hz: float,
    f_cross_hz: float,
) -> PlateProperties:
    """Calculate acoustic properties for a plate from longitudinal and cross-grain taps.

    Uses βL coefficient 22.37 (rounded), mirroring Swift PlateProperties.youngsModulusLong/Cross.

    - Parameters:
      - dims: Physical dimensions and mass of the plate sample.
      - f_long_hz: Along-grain fundamental frequency in Hz.
      - f_cross_hz: Cross-grain fundamental frequency in Hz.
    - Returns: Calculated PlateProperties.

    Mirrors Swift PlateProperties computed properties via calculate_plate_properties().
    """
    if not dims.is_valid():
        raise ValueError("Plate dimensions must all be positive.")
    if f_long_hz <= 0 or f_cross_hz <= 0:
        raise ValueError("Tap frequencies must be positive.")

    rho     = dims.density()
    rho_g   = dims.density_g_per_cm3()
    L       = dims.length()
    W       = dims.width()
    t       = dims.thickness()

    E_L     = _euler_bernoulli_e(rho, f_long_hz, L, t, 22.37)
    E_C     = _euler_bernoulli_e(rho, f_cross_hz, W, t, 22.37)
    E_L_GPa = E_L / 1e9
    E_C_GPa = E_C / 1e9
    c_L     = math.sqrt(E_L / rho)
    c_C     = math.sqrt(E_C / rho)
    spec_L  = E_L_GPa / rho_g
    spec_C  = E_C_GPa / rho_g
    rad_L   = c_L / rho
    rad_C   = c_C / rho
    qual_L  = wood_quality_long(spec_L)
    qual_C  = wood_quality_cross(spec_C)

    # Overall quality: 70% longitudinal + 30% cross-grain (mirrors Swift PlateProperties.overallQuality).
    # Longitudinal is weighted more heavily as it dominates top-plate stiffness.
    _scores = {"Excellent": 5, "Very Good": 4, "Good": 3, "Fair": 2, "Poor": 1}
    combined = _scores[qual_L] * 0.7 + _scores[qual_C] * 0.3
    if   combined >= 4.5: overall = "Excellent"
    elif combined >= 3.5: overall = "Very Good"
    elif combined >= 2.5: overall = "Good"
    elif combined >= 1.5: overall = "Fair"
    else:                 overall = "Poor"

    return PlateProperties(
        f_long=f_long_hz,
        f_cross=f_cross_hz,
        density_kg_m3=rho,
        E_long_GPa=E_L_GPa,
        E_cross_GPa=E_C_GPa,
        c_long_m_s=c_L,
        c_cross_m_s=c_C,
        specific_modulus_long=spec_L,
        specific_modulus_cross=spec_C,
        radiation_ratio_long=rad_L,
        radiation_ratio_cross=rad_C,
        quality_long=qual_L,
        quality_cross=qual_C,
        overall_quality=overall,
        cross_long_ratio=E_C / E_L if E_L > 0 else 0.0,
        long_cross_ratio=E_L / E_C if E_C > 0 else 0.0,
    )


def calculate_glc_from_flc(dims: MaterialDimensions, f_flc_hz: float) -> float:
    """Calculate shear modulus G_LC (Pa) from the FLC diagonal-tap frequency.

    Formula: G_LC = (12/π²) × ρ × L² × W² × f_LC² / t²

    Mirrors Swift PlateProperties.goreShearModulus (computed property).
    """
    rho = dims.density()
    L   = dims.length()
    W   = dims.width()
    t   = dims.thickness()
    if t <= 0 or rho <= 0 or f_flc_hz <= 0:
        return 0.0
    return (12.0 / (math.pi ** 2)) * rho * L ** 2 * W ** 2 * f_flc_hz ** 2 / (t * t)


def calculate_gore_target_thickness(
    props: PlateProperties,
    body_length_mm: float,
    body_width_mm: float,
    fvs: float,
    preset_name: str,
    glc_pa: float | None = None,
) -> "GoreThicknessResult | None":
    """Calculate Gore target thickness (Eq. 4.5-7).

    Uses the Gore plate moduli (E_L, E_C, G_LC) together with the guitar body geometry
    and a target vibrational stiffness (f_vs) to calculate the optimal plate thickness.
    When G_LC is None it is treated as 0, which typically causes a slight over-estimate
    of the target thickness (about 5–7%).

    Numerator:   Coef₂ × f_vs × a² × √ρ
    Denominator: √(E_L + (a/b)⁴·E_C + (a/b)²·(Coef₃·E_L + Coef₄·G_LC))

    - Parameters:
      - props: Calculated plate properties (Young's moduli and density required).
      - body_length_mm: Guitar body length (neck joint to tail block) in mm.
      - body_width_mm: Guitar lower-bout width in mm.
      - fvs: Target vibrational stiffness (f_vs).
      - preset_name: Human-readable preset label stored in the result.
      - glc_pa: Shear modulus G_LC in Pa, or None to treat it as 0.
    - Returns: GoreThicknessResult, or None if any required parameter is zero or invalid.

    Mirrors Swift PlateProperties.goreTargetThickness(bodyLengthMm:bodyWidthMm:vibrationalStiffness:).
    """
    if body_length_mm <= 0 or body_width_mm <= 0 or fvs <= 0:
        return None

    # Poisson's ratio constants (Gore's recommended averages for softwoods)
    nu_cl         = 0.05
    nu_lc_nu_cl   = 0.02          # ν_LC × ν_CL

    a = body_length_mm / 1000.0   # m
    b = body_width_mm  / 1000.0   # m

    E_L   = props.E_long_GPa  * 1e9   # Pa
    E_C   = props.E_cross_GPa * 1e9   # Pa
    rho   = props.density_kg_m3
    G_LC  = glc_pa if glc_pa is not None else 0.0

    coef2 = math.pi * math.sqrt(12.0 * (1.0 - nu_lc_nu_cl) / 126.0)
    coef3 = 4.0 * nu_cl / 7.0
    coef4 = 4.0 * 12.0 * (1.0 - nu_lc_nu_cl) / 42.0

    numerator    = coef2 * fvs * a * a * math.sqrt(rho)
    ab           = a / b
    denom_pa     = E_L + ab**4 * E_C + ab**2 * (coef3 * E_L + coef4 * G_LC)

    if denom_pa <= 0:
        return None

    thickness_mm = (numerator / math.sqrt(denom_pa)) * 1000.0

    return GoreThicknessResult(
        thickness_mm=thickness_mm,
        body_length_mm=body_length_mm,
        body_width_mm=body_width_mm,
        fvs=fvs,
        preset_name=preset_name,
        glc_pa=glc_pa,
    )
