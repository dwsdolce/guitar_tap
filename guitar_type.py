"""
    Guitar type definitions with per-type frequency ranges and decay thresholds.

    Mirrors the Swift GuitarType enum in GuitarType.swift, including
    description, mode_ranges (tighter per-mode frequency windows used for
    the in-range badge), and decay_thresholds (ring-out quality levels).
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


# ── supporting data classes ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ModeRanges:
    """Tighter frequency windows for the per-peak in-range badge.

    Mirrors Swift GuitarType.ModeRanges.  These are *not* the wide
    classification bands used for auto-assignment; they indicate whether a
    detected peak falls squarely within the expected zone for its mode.
    """
    air:         tuple[float, float]
    top:         tuple[float, float]
    back:        tuple[float, float]
    dipole:      tuple[float, float]
    ring_mode:   tuple[float, float]
    upper_modes: tuple[float, float]


@dataclass(frozen=True)
class DecayThresholds:
    """Ring-out time quality thresholds (seconds) for a guitar type.

    Mirrors Swift GuitarType.DecayThresholds.
    """
    very_short: float   # below this → "Very Short"
    short:      float   # below this → "Short"
    moderate:   float   # below this → "Moderate"
    good:       float   # at or above this → "Good", below → "Moderate"


# ── GuitarType enum ───────────────────────────────────────────────────────────

class GuitarType(Enum):
    """The guitar construction style.

    Mirrors Swift GuitarType enum (GuitarType.swift).
    """
    CLASSICAL = "Classical"
    FLAMENCO  = "Flamenco"
    ACOUSTIC  = "Acoustic"

    # ── description ──────────────────────────────────────────────────────────

    @property
    def description(self) -> str:
        return {
            GuitarType.CLASSICAL: "Nylon string, fan-braced, deep body",
            GuitarType.FLAMENCO:  "Nylon string, light bracing, shallow body",
            GuitarType.ACOUSTIC:  "Steel string, X-braced (Dreadnought, OM, etc.)",
        }[self]

    # ── mode_ranges ───────────────────────────────────────────────────────────

    @property
    def mode_ranges(self) -> ModeRanges:
        """Tighter per-mode frequency windows — mirrors Swift modeRanges."""
        return {
            GuitarType.CLASSICAL: ModeRanges(
                air=(80, 110), top=(170, 230), back=(190, 280),
                dipole=(330, 430), ring_mode=(580, 820), upper_modes=(820, 20000),
            ),
            GuitarType.FLAMENCO: ModeRanges(
                air=(85, 115), top=(190, 250), back=(180, 240),
                dipole=(350, 450), ring_mode=(600, 850), upper_modes=(850, 20000),
            ),
            GuitarType.ACOUSTIC: ModeRanges(
                air=(90, 120), top=(150, 210), back=(210, 290),
                dipole=(360, 460), ring_mode=(620, 880), upper_modes=(880, 20000),
            ),
        }[self]

    # ── decay_thresholds ──────────────────────────────────────────────────────

    @property
    def decay_thresholds(self) -> DecayThresholds:
        """Ring-out time quality thresholds — mirrors Swift decayThresholds."""
        return {
            GuitarType.CLASSICAL: DecayThresholds(
                very_short=0.15, short=0.35, moderate=0.60, good=1.0,
            ),
            GuitarType.FLAMENCO: DecayThresholds(
                very_short=0.08, short=0.20, moderate=0.35, good=0.55,
            ),
            GuitarType.ACOUSTIC: DecayThresholds(
                very_short=0.10, short=0.25, moderate=0.45, good=0.75,
            ),
        }[self]

    def decay_quality_label(self, decay_time: float) -> str:
        """Return a human-readable quality label for a measured ring-out time."""
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
