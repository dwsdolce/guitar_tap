"""
Detected spectral peak — mirrors Swift ResonantPeak.swift.

A single resonant peak detected in the FFT spectrum, with frequency,
magnitude, quality factor, bandwidth, and optional pitch information.

Peaks are produced by parabolic interpolation across adjacent FFT bins,
giving sub-bin frequency accuracy roughly 10× finer than the raw bin
spacing.  The quality and bandwidth fields are derived from the -3 dB
points surrounding the peak centre.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ResonantPeak:
    """A single resonant peak detected in the frequency spectrum of an acoustic tap tone measurement.

    Peaks are produced by parabolic interpolation across adjacent FFT bins, giving sub-bin
    frequency accuracy that is roughly 10× finer than the raw bin spacing.  The ``quality`` and
    ``bandwidth`` fields are derived from the -3 dB points surrounding the peak centre.

    Mirrors Swift ResonantPeak struct (ResonantPeak.swift).

    NOTE — Python-only field: ``mode_label`` carries the resolved mode string injected at
    serialisation time by ``TapToneMeasurement``.  It is not part of the Swift struct.

    NOTE — Python-only methods: ``to_dict()`` and ``from_dict()`` handle JSON
    serialisation/deserialisation.  Swift uses ``Codable`` instead.
    """

    # MARK: - Stored Properties

    # Stable unique identifier — mirrors Swift ResonantPeak.id (UUID).
    # Stored as a string (UUID string) in Python; Swift uses UUID directly.
    id: str

    # Centre frequency of this resonance, in Hz.
    #
    # Determined by parabolic interpolation through the peak bin and its two neighbours,
    # yielding accuracy well below the FFT bin spacing.
    # Mirrors Swift ResonantPeak.frequency.
    frequency: float

    # Peak signal level, in dBFS (decibels relative to full scale).
    #
    # The parabolic interpolation also corrects the magnitude to reflect the true peak
    # amplitude rather than the sampled bin value.  Typical values range from roughly
    # -80 dB (weak overtone) to -20 dB (strong resonance).
    # Mirrors Swift ResonantPeak.magnitude.
    magnitude: float

    # Q factor (quality factor) — a dimensionless measure of resonance sharpness.
    #
    # Computed as Q = f₀ / Δf₋₃dB, where Δf₋₃dB is the bandwidth between the
    # two -3 dB points flanking the peak.  Higher Q values indicate a narrower,
    # more sustained resonance.  Values below ~3 typically indicate a broad impact
    # thud rather than a true structural resonance, and are filtered out during
    # gated-FFT analysis.
    # Mirrors Swift ResonantPeak.quality.
    quality: float

    # Bandwidth of this resonance at its -3 dB points, in Hz.
    #
    # Relates to quality by bandwidth = frequency / quality.
    # Mirrors Swift ResonantPeak.bandwidth.
    bandwidth: float

    # Wall-clock time at which this peak was detected, as an ISO-8601 string.
    # Swift stores this as Date; Python stores it as an ISO-8601 string.
    # Mirrors Swift ResonantPeak.timestamp.
    timestamp: str

    # MARK: - Pitch Information

    # The nearest equal-temperament note name, e.g. "A4" or "C#3".
    # None when pitch detection is unavailable or disabled.
    # Mirrors Swift ResonantPeak.pitchNote.
    pitch_note: str | None = None

    # Signed offset from the nearest equal-temperament pitch, in cents (1/100 semitone).
    # Ranges from -50 to +50.  Negative values mean the peak is flat; positive values
    # mean it is sharp.  None when pitch_note is None.
    # Mirrors Swift ResonantPeak.pitchCents.
    pitch_cents: float | None = None

    # Frequency of the nearest equal-temperament pitch, in Hz.
    # Useful for displaying the reference note alongside the measured frequency.
    # None when pitch_note is None.
    # Mirrors Swift ResonantPeak.pitchFrequency.
    pitch_frequency: float | None = None

    # Mode label injected at serialisation time by TapToneMeasurement.
    # Python-only — not present in Swift ResonantPeak struct.
    mode_label: str = ""

    # MARK: - Computed Properties

    @property
    def formatted_pitch(self) -> str:
        """A human-readable pitch string combining the note name and cents deviation.

        Returns a string in the form ``"A4 (+12 ¢)"`` or ``"C#3 (-5 ¢)"``.
        Returns ``"N/A"`` when pitch information is unavailable.

        Mirrors Swift ResonantPeak.formattedPitch.
        """
        if self.pitch_note is None or self.pitch_cents is None:
            return "N/A"
        sign = "+" if self.pitch_cents >= 0 else ""
        return f"{self.pitch_note} ({sign}{self.pitch_cents:.0f} ¢)"

    # MARK: - Serialisation (Python-only)

    def to_dict(self) -> dict:
        """Encode this peak as a JSON-compatible dict using Swift field names.

        Python-only — Swift uses Codable.
        """
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
        """Decode a Swift-format ResonantPeak JSON object.

        Python-only — Swift uses Codable.
        """
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
