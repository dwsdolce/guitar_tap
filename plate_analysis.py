"""
    Plate and brace acoustic material-property calculations.

    Based on Trevor Gore's Contemporary Acoustic Guitar Design and Build
    methodology (Eq. 4.5-7 and surrounding derivations).

    The longitudinal standing-wave formula for a free-free bar is used
    to calculate Young's moduli from tap-tone frequencies:

        E = 4 · L² · f² · ρ

    where L is the bar length in the tapped direction, f is the first
    free-free longitudinal resonance frequency, and ρ is the density.
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

    def is_valid(self) -> bool:
        return (
            self.length_mm > 0
            and self.width_mm > 0
            and self.thickness_mm > 0
            and self.mass_g > 0
        )


@dataclass
class MaterialProperties:
    """Calculated acoustic material properties."""

    density_kg_m3: float         # kg/m³
    E_long_GPa: float            # Young's modulus along grain (GPa)
    E_cross_GPa: float           # Young's modulus cross-grain (GPa)
    c_long_m_s: float            # Speed of sound along grain (m/s)
    c_cross_m_s: float           # Speed of sound cross-grain (m/s)
    specific_modulus_m2s2: float # Specific modulus EL/ρ (m²/s² × 10⁶)
    radiation_ratio: float       # √EL / ρ  (×10⁻³ for display)
    anisotropy_ratio: float      # EL / EC
    quality_rating: str          # Excellent / Very Good / Good / Average / Poor
    target_thickness_mm: float   # Gore target thickness relative to Sitka spruce


# Reference Sitka spruce properties for target thickness
_REF_E_LONG_PA: float = 10.0e9   # Pa
_REF_THICKNESS_MM: float = 2.7   # mm


def _quality_rating(c_long_m_s: float) -> str:
    if c_long_m_s >= 5500:
        return "Excellent"
    if c_long_m_s >= 5000:
        return "Very Good"
    if c_long_m_s >= 4500:
        return "Good"
    if c_long_m_s >= 4000:
        return "Average"
    return "Poor"


def calculate_properties(
    dims: PlateDimensions,
    f_long_hz: float,
    f_cross_hz: float,
) -> MaterialProperties:
    """Calculate acoustic material properties from tap-tone frequencies.

    Args:
        dims:       Physical dimensions of the specimen.
        f_long_hz:  First resonance frequency along the long-grain (L) axis (Hz).
        f_cross_hz: First resonance frequency along the cross-grain (W) axis (Hz).

    Returns:
        MaterialProperties dataclass.

    Raises:
        ValueError: if dimensions are invalid or frequencies are non-positive.
    """
    if not dims.is_valid():
        raise ValueError("Plate dimensions must all be positive.")
    if f_long_hz <= 0 or f_cross_hz <= 0:
        raise ValueError("Tap frequencies must be positive.")

    rho = dims.density_kg_m3()
    L = dims.length_m()
    W = dims.width_m()

    # Young's moduli from longitudinal standing-wave formula: E = 4·L²·f²·ρ
    E_L = 4.0 * L**2 * f_long_hz**2 * rho   # Pa
    E_C = 4.0 * W**2 * f_cross_hz**2 * rho  # Pa

    # Speeds of sound: c = √(E/ρ)
    c_L = math.sqrt(E_L / rho)
    c_C = math.sqrt(E_C / rho)

    # Specific modulus (EL/ρ), expressed in units of 10⁶ m²/s²
    specific_mod = (E_L / rho) / 1e6

    # Radiation ratio: √EL / ρ  (expressed × 10⁻³ to keep numbers human-scale)
    rad_ratio = math.sqrt(E_L) / rho / 1e3

    # Anisotropy ratio: EL / EC
    aniso = E_L / E_C if E_C > 0 else 0.0

    # Gore target thickness to match bending stiffness of reference spruce:
    #   D = E·t³/12 = const  →  t_target = t_ref·(E_ref/E_actual)^(1/3)
    target_t = _REF_THICKNESS_MM * (_REF_E_LONG_PA / E_L) ** (1.0 / 3.0)

    return MaterialProperties(
        density_kg_m3=rho,
        E_long_GPa=E_L / 1e9,
        E_cross_GPa=E_C / 1e9,
        c_long_m_s=c_L,
        c_cross_m_s=c_C,
        specific_modulus_m2s2=specific_mod,
        radiation_ratio=rad_ratio,
        anisotropy_ratio=aniso,
        quality_rating=_quality_rating(c_L),
        target_thickness_mm=target_t,
    )
