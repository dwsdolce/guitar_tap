"""
Serialisable spectrum data — mirrors Swift SpectrumSnapshot.swift.

An immutable, serialisable copy of the frequency-domain data and all
display/analysis settings needed to faithfully reproduce a spectrum plot.

``SpectrumSnapshot`` serves two roles:

1. **Guitar measurements** — a single snapshot stores the averaged spectrum
   from all taps together with the chart axis ranges and guitar type in use
   at save time.

2. **Plate/brace material measurements** — three optional per-phase snapshots
   (longitudinal, cross, flc) each hold the spectrum from one tap
   orientation, enabling the material property calculations to be replayed
   after loading.

Fields that are not relevant to a particular measurement type are stored as
``None`` and simply ignored when the snapshot is later consumed.

Custom encode/decode mirrors Swift's Base64 binary encoding for compact file
sizes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpectrumSnapshot:
    """An immutable record of a complete frequency spectrum together with the chart settings
    and measurement parameters that were active when it was captured.

    A snapshot contains everything needed to recreate the spectrum chart exactly as it
    appeared at the time of saving.  Measurement-type-specific fields (plate dimensions,
    Gore thicknessing parameters, brace dimensions) are ``None`` when not applicable.

    Mirrors Swift SpectrumSnapshot struct (SpectrumSnapshot.swift).

    NOTE — Python vs Swift structural differences:
      - ``guitar_type`` and ``measurement_type`` are stored as raw strings in Python;
        Swift stores them as ``GuitarType`` and ``MeasurementType`` enum values.
      - ``to_dict()`` / ``from_dict()`` provide JSON serialisation; Swift uses ``Codable``.
      - ``to_dict()`` writes plain float arrays (not Base64); ``from_dict()`` decodes both
        the compact Base64 binary format and the legacy plain float-array format.
    """

    # MARK: - Spectrum Data

    # FFT frequency bins, in Hz, from low to high.
    # Parallel array with magnitudes; index i gives the frequency of bin i.
    # Mirrors Swift SpectrumSnapshot.frequencies.
    frequencies: list[float]

    # FFT magnitude values in dBFS, one per entry in frequencies.
    # Values are averaged across taps in linear power space before conversion back to dB,
    # so phase is discarded (appropriate for impulse-response averages).
    # Mirrors Swift SpectrumSnapshot.magnitudes.
    magnitudes: list[float]

    # MARK: - Chart Axis Ranges

    # Lower bound of the displayed frequency range, in Hz.
    # Mirrors Swift SpectrumSnapshot.minFreq.
    min_freq: float = 75.0

    # Upper bound of the displayed frequency range, in Hz.
    # Mirrors Swift SpectrumSnapshot.maxFreq.
    max_freq: float = 350.0

    # Lower bound of the displayed magnitude range, in dBFS.
    # Mirrors Swift SpectrumSnapshot.minDB.
    min_db: float = -90.0

    # Upper bound of the displayed magnitude range, in dBFS.
    # Mirrors Swift SpectrumSnapshot.maxDB.
    max_db: float = -20.0

    # True when the frequency axis was displayed on a logarithmic scale.
    # Mirrors Swift SpectrumSnapshot.isLogarithmic.
    is_logarithmic: bool = False

    # MARK: - Display Settings

    # Whether peaks classified as GuitarMode.unknown were shown in the chart annotations.
    # None in snapshots created before this field was added (treated as False on load).
    # Mirrors Swift SpectrumSnapshot.showUnknownModes.
    show_unknown_modes: bool | None = None

    # The guitar type classification (classical, flamenco, acoustic) active at save time.
    # Stored as a raw string (Swift raw value or combo-box text) in Python;
    # Swift stores as GuitarType enum.
    # Mirrors Swift SpectrumSnapshot.guitarType.
    guitar_type: str | None = None

    # The measurement type (guitar, plate, or brace) active at save time.
    # Stored as a raw string in Python; Swift stores as MeasurementType enum.
    # Mirrors Swift SpectrumSnapshot.measurementType.
    measurement_type: str | None = None

    # Maximum number of peaks that the analyzer was configured to detect and annotate.
    # None in older snapshots without this field.
    # Mirrors Swift SpectrumSnapshot.maxPeaks.
    max_peaks: int | None = None

    # MARK: - Plate Measurement Settings

    # Plate length along the grain direction, in mm.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.plateLength.
    plate_length: float | None = None

    # Plate width across the grain direction, in mm.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.plateWidth.
    plate_width: float | None = None

    # Plate thickness, in mm.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.plateThickness.
    plate_thickness: float | None = None

    # Plate mass, in grams.
    # Combined with dimensions to compute density for the Young's modulus formula.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.plateMass.
    plate_mass: float | None = None

    # MARK: - Gore Thicknessing Settings

    # Guitar body length used for the Gore target-thickness calculation, in mm.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.guitarBodyLength.
    guitar_body_length: float | None = None

    # Guitar body width used for the Gore target-thickness calculation, in mm.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.guitarBodyWidth.
    guitar_body_width: float | None = None

    # The PlateStiffnessPreset (panel type) selected for the Gore calculation at save time.
    # Stored as a raw string (e.g. "Steel String Top"); Swift stores as PlateStiffnessPreset enum.
    # Populated only when measurement_type is plate.
    # Mirrors Swift SpectrumSnapshot.plateStiffnessPreset.
    plate_stiffness_preset: str | None = None

    # The custom target vibrational stiffness (f_vs) used when plate_stiffness_preset
    # is "Custom", in N·m.  None when a non-custom preset was in use.
    # Mirrors Swift SpectrumSnapshot.customPlateStiffness.
    custom_plate_stiffness: float | None = None

    # Whether the optional FLC (diagonal / shear) third tap was included in this plate measurement.
    # When True, a third tap at 45° to the grain was captured and stored in flcSnapshot.
    # Mirrors Swift SpectrumSnapshot.measureFlc.
    measure_flc: bool | None = None

    # MARK: - Brace Measurement Settings

    # Brace length along its main axis, in mm.
    # Populated only when measurement_type is brace.
    # Mirrors Swift SpectrumSnapshot.braceLength.
    brace_length: float | None = None

    # Brace width (cross-section dimension perpendicular to height), in mm.
    # Populated only when measurement_type is brace.
    # Mirrors Swift SpectrumSnapshot.braceWidth.
    brace_width: float | None = None

    # Brace height (cross-section dimension), in mm.
    # Populated only when measurement_type is brace.
    # Mirrors Swift SpectrumSnapshot.braceThickness.
    brace_thickness: float | None = None

    # Brace mass, in grams.
    # Combined with dimensions to compute density for the Young's modulus calculation.
    # Populated only when measurement_type is brace.
    # Mirrors Swift SpectrumSnapshot.braceMass.
    brace_mass: float | None = None

    # MARK: - Serialisation (Python-only)

    def to_dict(self) -> dict:
        """Encode this snapshot as a JSON-compatible dict using Swift field names.

        Writes plain float arrays for ``frequencies`` and ``magnitudes`` (not Base64).
        Swift reads these via the legacy ``frequencies``/``magnitudes`` fallback path.

        Python-only — Swift uses Codable with a custom encoder (Base64 binary blobs).
        """
        d: dict = {
            "frequencies": self.frequencies,
            "magnitudes": self.magnitudes,
            "minFreq": self.min_freq,
            "maxFreq": self.max_freq,
            "minDB": self.min_db,
            "maxDB": self.max_db,
            "isLogarithmic": self.is_logarithmic,
        }
        if self.show_unknown_modes is not None:
            d["showUnknownModes"] = self.show_unknown_modes
        if self.guitar_type is not None:
            d["guitarType"] = self.guitar_type
        if self.measurement_type is not None:
            d["measurementType"] = self.measurement_type
        if self.max_peaks is not None:
            d["maxPeaks"] = self.max_peaks
        if self.plate_length         is not None: d["plateLength"]           = self.plate_length
        if self.plate_width          is not None: d["plateWidth"]            = self.plate_width
        if self.plate_thickness      is not None: d["plateThickness"]        = self.plate_thickness
        if self.plate_mass           is not None: d["plateMass"]             = self.plate_mass
        if self.guitar_body_length   is not None: d["guitarBodyLength"]      = self.guitar_body_length
        if self.guitar_body_width    is not None: d["guitarBodyWidth"]       = self.guitar_body_width
        if self.plate_stiffness_preset  is not None: d["plateStiffnessPreset"]  = self.plate_stiffness_preset
        if self.custom_plate_stiffness  is not None: d["customPlateStiffness"]  = self.custom_plate_stiffness
        if self.measure_flc          is not None: d["measureFlc"]            = self.measure_flc
        if self.brace_length         is not None: d["braceLength"]           = self.brace_length
        if self.brace_width          is not None: d["braceWidth"]            = self.brace_width
        if self.brace_thickness      is not None: d["braceThickness"]        = self.brace_thickness
        if self.brace_mass           is not None: d["braceMass"]             = self.brace_mass
        return d

    @staticmethod
    def from_dict(d: dict) -> "SpectrumSnapshot":
        """Decode a Swift-format SpectrumSnapshot JSON object.

        Accepts both the compact Base64 binary format (``frequenciesData`` /
        ``magnitudesData``) written by Swift, and the legacy plain float-array
        format (``frequencies`` / ``magnitudes``) written by Python.

        Mirrors Swift SpectrumSnapshot custom Decodable.

        Python-only — Swift uses Codable.
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
            is_logarithmic=d.get("isLogarithmic", False),
            show_unknown_modes=d.get("showUnknownModes"),
            guitar_type=d.get("guitarType"),
            measurement_type=d.get("measurementType"),
            max_peaks=d.get("maxPeaks"),
            plate_length=d.get("plateLength"),
            plate_width=d.get("plateWidth"),
            plate_thickness=d.get("plateThickness"),
            plate_mass=d.get("plateMass"),
            guitar_body_length=d.get("guitarBodyLength"),
            guitar_body_width=d.get("guitarBodyWidth"),
            plate_stiffness_preset=d.get("plateStiffnessPreset"),
            custom_plate_stiffness=d.get("customPlateStiffness"),
            measure_flc=d.get("measureFlc"),
            brace_length=d.get("braceLength"),
            brace_width=d.get("braceWidth"),
            brace_thickness=d.get("braceThickness"),
            brace_mass=d.get("braceMass"),
        )
