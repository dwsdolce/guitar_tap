"""
Serialisable spectrum data — mirrors Swift SpectrumSnapshot.swift.

Embeds the FFT frequency/magnitude arrays together with all display
settings so that a saved measurement is fully self-contained and
cross-compatible with the Swift GuitarTap app.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpectrumSnapshot:
    """Embedded spectrum data + display settings.

    Mirrors Swift SpectrumSnapshot struct (SpectrumSnapshot.swift).
    Custom encode/decode mirrors Swift's Base64 binary encoding for
    compact file sizes.
    """
    frequencies: list[float]
    magnitudes: list[float]

    # Chart display ranges — mirrors Swift SpectrumSnapshot fields
    min_freq: float = 75.0
    max_freq: float = 350.0
    min_db: float = -90.0
    max_db: float = -20.0

    # Display settings
    guitar_type: str = "Classical"
    measurement_type: str = "Classical Guitar"
    max_peaks: int = 20

    # Plate material dimensions — mirrors Swift SpectrumSnapshot CodingKeys
    plate_length:    float | None = None   # mm
    plate_width:     float | None = None   # mm
    plate_thickness: float | None = None   # mm
    plate_mass:      float | None = None   # g

    # Brace material dimensions
    brace_length:    float | None = None   # mm
    brace_width:     float | None = None   # mm
    brace_thickness: float | None = None   # mm
    brace_mass:      float | None = None   # g

    # Gore formula settings — mirrors Swift SpectrumSnapshot
    plate_stiffness_preset:  str   | None = None   # e.g. "Steel String Top"
    custom_plate_stiffness:  float | None = None   # only when preset == "Custom"
    guitar_body_length:      float | None = None   # mm — Gore body length (a)
    guitar_body_width:       float | None = None   # mm — Gore lower-bout width (b)

    def to_dict(self) -> dict:
        d: dict = {
            "frequencies": self.frequencies,
            "magnitudes": self.magnitudes,
            "minFreq": self.min_freq,
            "maxFreq": self.max_freq,
            "minDB": self.min_db,
            "maxDB": self.max_db,
            "isLogarithmic": False,
            "showUnknownModes": True,
            "guitarType": self.guitar_type,
            "measurementType": self.measurement_type,
            "maxPeaks": self.max_peaks,
        }
        if self.plate_length    is not None: d["plateLength"]    = self.plate_length
        if self.plate_width     is not None: d["plateWidth"]     = self.plate_width
        if self.plate_thickness is not None: d["plateThickness"] = self.plate_thickness
        if self.plate_mass      is not None: d["plateMass"]      = self.plate_mass
        if self.brace_length    is not None: d["braceLength"]    = self.brace_length
        if self.brace_width     is not None: d["braceWidth"]     = self.brace_width
        if self.brace_thickness is not None: d["braceThickness"] = self.brace_thickness
        if self.brace_mass              is not None: d["braceMass"]              = self.brace_mass
        if self.plate_stiffness_preset  is not None: d["plateStiffnessPreset"]  = self.plate_stiffness_preset
        if self.custom_plate_stiffness  is not None: d["customPlateStiffness"]  = self.custom_plate_stiffness
        if self.guitar_body_length      is not None: d["guitarBodyLength"]      = self.guitar_body_length
        if self.guitar_body_width       is not None: d["guitarBodyWidth"]       = self.guitar_body_width
        return d

    @staticmethod
    def from_dict(d: dict) -> "SpectrumSnapshot":
        """Decode a Swift-format SpectrumSnapshot JSON object.

        Mirrors Swift SpectrumSnapshot custom Decodable: tries compact
        Base64 binary first (frequenciesData / magnitudesData), then
        falls back to legacy plain float arrays.
        """
        import base64, struct

        if "frequenciesData" in d:
            raw = base64.b64decode(d["frequenciesData"])
            n = len(raw) // 4
            frequencies: list[float] = list(struct.unpack(f"<{n}f", raw))
        else:
            frequencies = d.get("frequencies", [])

        if "magnitudesData" in d:
            raw = base64.b64decode(d["magnitudesData"])
            n = len(raw) // 4
            magnitudes: list[float] = list(struct.unpack(f"<{n}f", raw))
        else:
            magnitudes = d.get("magnitudes", [])

        return SpectrumSnapshot(
            frequencies=frequencies,
            magnitudes=magnitudes,
            min_freq=d.get("minFreq", 75.0),
            max_freq=d.get("maxFreq", 350.0),
            min_db=d.get("minDB", -90.0),
            max_db=d.get("maxDB", -20.0),
            guitar_type=d.get("guitarType", "Classical"),
            measurement_type=d.get("measurementType", "Classical Guitar"),
            max_peaks=d.get("maxPeaks", 20),
            plate_length=d.get("plateLength"),
            plate_width=d.get("plateWidth"),
            plate_thickness=d.get("plateThickness"),
            plate_mass=d.get("plateMass"),
            brace_length=d.get("braceLength"),
            brace_width=d.get("braceWidth"),
            brace_thickness=d.get("braceThickness"),
            brace_mass=d.get("braceMass"),
            plate_stiffness_preset=d.get("plateStiffnessPreset"),
            custom_plate_stiffness=d.get("customPlateStiffness"),
            guitar_body_length=d.get("guitarBodyLength"),
            guitar_body_width=d.get("guitarBodyWidth"),
        )
