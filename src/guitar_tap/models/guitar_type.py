"""
Guitar type definitions with per-type frequency ranges and decay thresholds.

Mirrors Swift GuitarType enum (GuitarType.swift).

The kind of guitar body determines mode frequency classification ranges.
Each guitar type has a distinct set of ModeRanges reflecting its typical
construction (body depth, bracing style, string tension), and separate
DecayThresholds calibrated to expected ring-out times.

See Also: GuitarMode for the resonance mode classification that uses these ranges.
See Also: MeasurementType for the broader type that includes plate/brace measurements.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


# MARK: - Supporting Data Classes

@dataclass(frozen=True)
class ModeRanges:
    """Frequency classification bands for each guitar body mode, in Hz.

    Used by GuitarMode.classify_all() to assign a mode label to each
    detected peak.  Bands are non-overlapping and cover the full audible
    spectrum via upper_modes.

    Mirrors Swift GuitarType.ModeRanges.
    """
    air:         tuple[float, float]   # Helmholtz air resonance band, in Hz.
    top:         tuple[float, float]   # Main top plate bending mode band, in Hz.
    back:        tuple[float, float]   # Back plate bending mode band, in Hz.
    dipole:      tuple[float, float]   # Dipole (top-plate out-of-phase) mode band, in Hz.
    ring_mode:   tuple[float, float]   # Ring mode band, in Hz.
    upper_modes: tuple[float, float]   # Upper harmonic modes band (extends to 20 kHz), in Hz.


@dataclass(frozen=True)
class DecayThresholds:
    """Ring-out time quality thresholds, in seconds.

    Used to convert a numeric ring-out time into a qualitative label.
    Thresholds differ between guitar types: flamenco guitars are expected
    to decay quickly (percussive playing), while classical guitars are
    expected to sustain longer.

    Mirrors Swift GuitarType.DecayThresholds.
    """
    very_short: float  # Ring-out times below this value are rated "Very Short".
    short:      float  # Ring-out times below this value are rated "Short".
    moderate:   float  # Ring-out times below this value are rated "Moderate".
    good:       float  # Ring-out times below this → "Good"; at or above → "Excellent".


# MARK: - GuitarType

class GuitarType(Enum):
    """The kind of guitar body, which determines mode frequency classification ranges.

    Mirrors Swift GuitarType enum (GuitarType.swift).
    """
    CLASSICAL = "Classical"
    FLAMENCO  = "Flamenco"
    ACOUSTIC  = "Acoustic"

    # MARK: - Description

    @property
    def description(self) -> str:
        """Human-readable description of the guitar type shown in the settings UI."""
        return {
            GuitarType.CLASSICAL: "Nylon string, fan-braced, deep body",
            GuitarType.FLAMENCO:  "Nylon string, light bracing, shallow body",
            GuitarType.ACOUSTIC:  "Steel string, X-braced (Dreadnought, OM, etc.)",
        }[self]

    # MARK: - Mode Ranges

    @property
    def mode_ranges(self) -> ModeRanges:
        """The frequency classification bands for this guitar type.

        Mirrors Swift GuitarType.modeRanges.
        """
        return {
            GuitarType.CLASSICAL: ModeRanges(
                air=(80, 110),          # Lower air resonance due to deeper body
                top=(170, 230),         # Main top resonance
                back=(190, 280),        # Back resonance (extended to 280 Hz to capture higher back modes)
                dipole=(330, 430),      # Dipole mode
                ring_mode=(580, 820),   # Ring mode
                upper_modes=(820, 20000),
            ),
            GuitarType.FLAMENCO: ModeRanges(
                air=(85, 115),          # Slightly higher due to shallower body
                top=(190, 250),         # Higher due to thinner, lighter top
                back=(180, 240),        # Cypress back, lighter construction
                dipole=(350, 450),      # Dipole mode
                ring_mode=(600, 850),   # Ring mode
                upper_modes=(850, 20000),
            ),
            GuitarType.ACOUSTIC: ModeRanges(
                air=(90, 120),          # Higher due to smaller/tighter body
                top=(150, 210),         # Lower due to stiffer X-bracing
                back=(210, 290),        # Back resonance
                dipole=(360, 460),      # Dipole mode
                ring_mode=(620, 880),   # Ring mode
                upper_modes=(880, 20000),
            ),
        }[self]

    # MARK: - Decay Thresholds

    @property
    def decay_thresholds(self) -> DecayThresholds:
        """The ring-out quality thresholds for this guitar type.

        Mirrors Swift GuitarType.decayThresholds.
        """
        return {
            GuitarType.CLASSICAL: DecayThresholds(
                # Classical guitars have longer sustain due to deeper body and heavier bracing
                very_short=0.15,
                short=0.35,
                moderate=0.60,
                good=1.0,
            ),
            GuitarType.FLAMENCO: DecayThresholds(
                # Flamenco guitars are designed for short, percussive decay
                # Quick decay is a feature for clear rasgueados and golpe
                very_short=0.08,
                short=0.20,
                moderate=0.35,
                good=0.55,
            ),
            GuitarType.ACOUSTIC: DecayThresholds(
                # Steel-string guitars have punchier, shorter decay
                very_short=0.10,
                short=0.25,
                moderate=0.45,
                good=0.75,
            ),
        }[self]

    def decay_quality_label(self, decay_time: float) -> str:
        """Return a human-readable quality label for a measured ring-out time.

        Mirrors Swift Float.decayQuality(for:) extension.
        """
        t = self.decay_thresholds
        if decay_time < t.very_short:
            return "Very Short"
        if decay_time < t.short:
            return "Short"
        if decay_time < t.moderate:
            return "Moderate"
        if decay_time < t.good:
            return "Good"
        return "Excellent"
