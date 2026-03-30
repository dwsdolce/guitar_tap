"""
    Plate and brace acoustic material-property calculations.

    Based on the Euler-Bernoulli free-free beam equation (Haines / Coates):

        E = 48 × π² × ρ × f² × L⁴ / (βL × t)²

    where (βL)² = 22.37 for plates (rounded), 22.37332 for braces (precise),
    corresponding to the first free-free bending mode.

    Mirrors Swift's MaterialProperties.swift (BraceProperties / PlateProperties).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PlateDimensions:
    """Physical dimensions of a plate or brace specimen (user units)."""

    length_mm: float    # L — long-grain direction (mm)
    width_mm: float     # W — cross-grain direction (mm)
    thickness_mm: float # T — thickness (mm)
    mass_g: float       # m — mass (g)

    def length_m(self) -> float:
        return self.length_mm / 1000.0

    def width_m(self) -> float:
        return self.width_mm / 1000.0

    def thickness_m(self) -> float:
        return self.thickness_mm / 1000.0

    def mass_kg(self) -> float:
        return self.mass_g / 1000.0

    def density_kg_m3(self) -> float:
        """Density in kg/m³."""
        vol = self.length_m() * self.width_m() * self.thickness_m()
        return self.mass_kg() / vol if vol > 0 else 0.0

    def density_g_cm3(self) -> float:
        """Density in g/cm³."""
        return self.density_kg_m3() / 1000.0

    def is_valid(self) -> bool:
        return (
            self.length_mm > 0
            and self.width_mm > 0
            and self.thickness_mm > 0
            and self.mass_g > 0
        )


# Quality colours match Swift's qualityColor() function
QUALITY_COLORS: dict[str, str] = {
    "Excellent": "#34C759",   # SwiftUI .green
    "Very Good": "#00C7BE",   # SwiftUI .mint
    "Good":      "#007AFF",   # SwiftUI .blue  (system accent)
    "Fair":      "#FF9500",   # SwiftUI .orange
    "Poor":      "#FF3B30",   # SwiftUI .red
}


def wood_quality_long(specific_modulus: float) -> str:
    """Quality rating for longitudinal specific modulus (GPa/(g/cm³)), spruce thresholds."""
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
    """Quality rating for cross-grain specific modulus (GPa/(g/cm³)), spruce thresholds."""
    if specific_modulus >= 1.5:
        return "Excellent"
    if specific_modulus >= 1.2:
        return "Very Good"
    if specific_modulus >= 0.9:
        return "Good"
    if specific_modulus >= 0.6:
        return "Fair"
    return "Poor"


def _euler_bernoulli_e(rho: float, f: float, L: float, t: float, beta_l_sq: float) -> float:
    """Young's modulus in Pascals from the free-free beam equation.

    E = 48 × π² × ρ × f² × L⁴ / (βL × t)²
    """
    return 48.0 * math.pi**2 * rho * f**2 * L**4 / (beta_l_sq * t) ** 2


@dataclass
class BraceProperties:
    """Calculated acoustic properties for a brace sample (single longitudinal tap)."""

    f_long: float           # Hz
    density_kg_m3: float
    E_long_GPa: float
    c_long_m_s: float
    specific_modulus: float # GPa/(g/cm³)  — primary quality metric
    radiation_ratio: float  # m⁴/(kg·s)   — c_L / ρ
    quality: str


@dataclass
class PlateProperties:
    """Calculated acoustic properties for a plate sample (two taps)."""

    f_long: float
    f_cross: float
    density_kg_m3: float
    E_long_GPa: float
    E_cross_GPa: float
    c_long_m_s: float
    c_cross_m_s: float
    specific_modulus_long: float    # GPa/(g/cm³)
    specific_modulus_cross: float   # GPa/(g/cm³)
    radiation_ratio_long: float     # m⁴/(kg·s)
    radiation_ratio_cross: float    # m⁴/(kg·s)
    quality_long: str
    quality_cross: str
    overall_quality: str
    cross_long_ratio: float         # E_C / E_L  (typical 0.04–0.08)
    long_cross_ratio: float         # E_L / E_C  (typical 12–25)


def calculate_brace_properties(dims: PlateDimensions, f_long_hz: float) -> BraceProperties:
    """Calculate acoustic properties for a brace from a single longitudinal tap.

    Uses the precise βL coefficient 22.37332 (vs 22.37 for plates), mirroring Swift.
    """
    if not dims.is_valid():
        raise ValueError("Brace dimensions must all be positive.")
    if f_long_hz <= 0:
        raise ValueError("Tap frequency must be positive.")

    rho     = dims.density_kg_m3()
    rho_g   = dims.density_g_cm3()
    L       = dims.length_m()
    t       = dims.thickness_m()

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
    dims: PlateDimensions,
    f_long_hz: float,
    f_cross_hz: float,
) -> PlateProperties:
    """Calculate acoustic properties for a plate from longitudinal and cross-grain taps.

    Uses βL coefficient 22.37 (rounded), mirroring Swift's PlateProperties.
    """
    if not dims.is_valid():
        raise ValueError("Plate dimensions must all be positive.")
    if f_long_hz <= 0 or f_cross_hz <= 0:
        raise ValueError("Tap frequencies must be positive.")

    rho     = dims.density_kg_m3()
    rho_g   = dims.density_g_cm3()
    L       = dims.length_m()
    W       = dims.width_m()
    t       = dims.thickness_m()

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

    # Overall quality: 70% longitudinal + 30% cross-grain (mirrors Swift)
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


@dataclass
class GoreThicknessResult:
    """Result of Gore Eq. 4.5-7 target thickness calculation."""

    thickness_mm: float
    body_length_mm: float
    body_width_mm: float
    fvs: float
    preset_name: str        # e.g. "Steel String Top"
    glc_pa: float | None    # shear modulus used (None → assumed 0)


def calculate_glc_from_flc(dims: PlateDimensions, f_flc_hz: float) -> float:
    """Calculate shear modulus G_LC (Pa) from the FLC diagonal-tap frequency.

    Formula: G_LC = (12/π²) × ρ × L² × W² × f_LC² / t²
    Mirrors Swift MaterialProperties.goreShearModulus.
    """
    rho = dims.density_kg_m3()
    L   = dims.length_m()
    W   = dims.width_m()
    t   = dims.thickness_m()
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

    Mirrors Swift MaterialProperties.goreTargetThickness.
    Returns None if any required parameter is zero or invalid.
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
