"""
Detected spectral peak — mirrors Swift ResonantPeak.swift.

A single resonant peak detected in the FFT spectrum, with frequency,
magnitude, quality factor, bandwidth, and optional pitch information.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ResonantPeak:
    """A single detected resonant peak.

    Mirrors Swift ResonantPeak struct (ResonantPeak.swift).
    The ``mode_label`` field carries the resolved mode string at serialisation
    time (injected by TapToneMeasurement) and is not part of the Swift struct.
    """
    id: str           # UUID string — mirrors Swift ResonantPeak.id
    frequency: float  # Hz
    magnitude: float  # dBFS
    quality: float    # Q factor
    bandwidth: float  # Hz = frequency / quality
    timestamp: str    # ISO-8601

    # Pitch info — mirrors Swift ResonantPeak.pitchNote / pitchCents / pitchFrequency
    pitch_note: str | None = None
    pitch_cents: float | None = None
    pitch_frequency: float | None = None

    # Mode label injected at serialisation (not in Swift ResonantPeak struct)
    mode_label: str = ""

    @property
    def formatted_pitch(self) -> str:
        """Human-readable pitch string, e.g. 'A4 +3¢'.

        Mirrors Swift ResonantPeak.formattedPitch.
        """
        if self.pitch_note is None:
            return ""
        if self.pitch_cents is not None:
            return f"{self.pitch_note} {self.pitch_cents:+.0f}¢"
        return self.pitch_note

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "frequency": self.frequency,
            "magnitude": self.magnitude,
            "quality": self.quality,
            "bandwidth": self.bandwidth,
            "timestamp": self.timestamp,
            "modeLabel": self.mode_label,
        }
        if self.pitch_note is not None:
            d["pitchNote"] = self.pitch_note
        if self.pitch_cents is not None:
            d["pitchCents"] = self.pitch_cents
        if self.pitch_frequency is not None:
            d["pitchFrequency"] = self.pitch_frequency
        return d

    @staticmethod
    def from_dict(d: dict) -> "ResonantPeak":
        """Decode a Swift-format ResonantPeak JSON object."""
        return ResonantPeak(
            id=d.get("id", str(uuid.uuid4())),
            frequency=d.get("frequency", 0.0),
            magnitude=d.get("magnitude", 0.0),
            quality=d.get("quality", 0.0),
            bandwidth=d.get("bandwidth", 0.0),
            timestamp=d.get("timestamp", _now_iso()),
            mode_label=d.get("modeLabel", ""),
            pitch_note=d.get("pitchNote"),
            pitch_cents=d.get("pitchCents"),
            pitch_frequency=d.get("pitchFrequency"),
        )
