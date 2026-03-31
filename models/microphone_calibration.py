"""
Microphone calibration support — mirrors Swift MicrophoneCalibration.swift.

The .cal file format used by miniDSP UMIK-1 microphones and REW
(Room EQ Wizard) consists of optional header lines (starting with
'"' or '*') followed by whitespace-separated (freq_hz, db_correction)
pairs, one per line.

Example:
    "UMIK-1 Calibration Data"
    * Serial Number: 1234567
    * Sensitivity @ 94dB SPL: -35.00 dBFS
    20.0    0.12
    25.0   -0.05
    ...
    20000.0  1.43
"""

import re
import uuid as _uuid
import json as _json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt


_SENS_RE = re.compile(r"([-+]?\d+\.?\d*)\s*dB", re.IGNORECASE)


# ── CalibrationFileParser (module-level helpers) ──────────────────────────────
# Mirrors Swift CalibrationFileParser struct.

def parse_cal_metadata(path: str) -> dict:
    """Return metadata from a calibration file without loading correction data.

    Returns a dict with keys:
      'sensitivity_db' : float | None  — from header (e.g. "Sens Factor = -18.39 dB")
      'data_points'    : int           — number of frequency/correction pairs
      'freq_min'       : float | None  — lowest frequency in the file
      'freq_max'       : float | None  — highest frequency in the file
    """
    sensitivity: float | None = None
    data_points = 0
    freq_min: float | None = None
    freq_max: float | None = None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith('"') or line.startswith("*"):
                lower = line.lower()
                if "sens" in lower:
                    m = _SENS_RE.search(line)
                    if m:
                        sensitivity = float(m.group(1))
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                freq = float(parts[0])
                float(parts[1])
                if freq > 0:
                    data_points += 1
                    if freq_min is None or freq < freq_min:
                        freq_min = freq
                    if freq_max is None or freq > freq_max:
                        freq_max = freq
            except ValueError:
                continue

    return {
        "sensitivity_db": sensitivity,
        "data_points": data_points,
        "freq_min": freq_min,
        "freq_max": freq_max,
    }


def parse_cal_file(path: str) -> npt.NDArray[np.float64]:
    """Parse a UMIK-1/REW calibration file.

    Returns an (N, 2) float64 array: column 0 = Hz, column 1 = dB correction.
    Raises ValueError if no valid data points are found.
    """
    points: list[tuple[float, float]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith('"') or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                freq = float(parts[0])
                db   = float(parts[1])
                if freq > 0:
                    points.append((freq, db))
            except ValueError:
                continue  # header text or malformed line

    if not points:
        raise ValueError(f"No calibration data found in '{path}'")

    arr = np.array(points, dtype=np.float64)
    # Sort by frequency (required by np.interp)
    arr = arr[arr[:, 0].argsort()]
    return arr


def interpolate_to_bins(
    cal_data: npt.NDArray[np.float64],
    bin_freqs: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Interpolate calibration corrections onto FFT bin frequencies.

    Frequencies below/above the calibration range are clamped to 0 dB
    (no correction applied outside the measured range).

    Returns a 1-D array of dB corrections, same length as *bin_freqs*.
    """
    return np.interp(
        bin_freqs,
        cal_data[:, 0],
        cal_data[:, 1],
        left=0.0,
        right=0.0,
    )


# ── MicrophoneCalibration ─────────────────────────────────────────────────────

@dataclass
class MicrophoneCalibration:
    """
    A stored microphone calibration profile.
    Mirrors Swift MicrophoneCalibration struct (MicrophoneCalibration.swift).
    """
    id: str                           # UUID string
    name: str                         # display name (filename stem by default)
    sensitivity_factor: float | None  # from "Sens Factor" header
    reference_level: float | None     # from "SESSION REF" / "SPL" header
    correction_points: list           # [[freq, correction], ...] sorted ascending
    import_date: str                  # ISO-8601

    # ── Parsing ───────────────────────────────────────────────────────────

    @classmethod
    def from_path(cls, path: str, name: str | None = None) -> "MicrophoneCalibration":
        """Parse a UMIK-1/REW .cal file and return a named calibration profile.

        Mirrors Swift CalibrationFileParser.parse(url:name:).
        """
        import os
        profile_name = name or os.path.splitext(os.path.basename(path))[0]

        _SENS = re.compile(r"Sens\s+Factor\s*=\s*([-+]?\d+\.?\d*)\s*dB", re.IGNORECASE)
        _REF  = re.compile(r"SESSION REF\s*=\s*([\d.]+)\s*dBSPL", re.IGNORECASE)
        _SPL  = re.compile(r"SPL\s+([\d.]+)\s*dB", re.IGNORECASE)

        sensitivity: float | None = None
        reference: float | None = None
        points: list = []

        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith('"') or line.startswith("*"):
                    if sensitivity is None:
                        m = _SENS.search(line)
                        if m:
                            sensitivity = float(m.group(1))
                    if reference is None:
                        m2 = _REF.search(line)
                        if m2:
                            reference = float(m2.group(1))
                        else:
                            m3 = _SPL.search(line)
                            if m3:
                                reference = float(m3.group(1))
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    freq = float(parts[0])
                    corr = float(parts[1])
                    if 1.0 <= freq <= 24000.0:
                        points.append([freq, corr])
                except ValueError:
                    continue

        if not points:
            raise ValueError(f"No calibration data found in '{path}'")

        points.sort(key=lambda p: p[0])
        return cls(
            id=str(_uuid.uuid4()),
            name=profile_name,
            sensitivity_factor=sensitivity,
            reference_level=reference,
            correction_points=points,
            import_date=datetime.now(timezone.utc).isoformat(),
        )

    # ── Correction interpolation ──────────────────────────────────────────

    def interpolate_to_bins(
        self, bin_freqs: "npt.NDArray[np.float64]"
    ) -> "npt.NDArray[np.float64]":
        """Interpolate this profile's corrections onto FFT bin frequencies.

        Uses flat extrapolation at the edges (matches Swift behaviour).
        Mirrors Swift MicrophoneCalibration.corrections(for:).
        """
        if not self.correction_points:
            return np.zeros(len(bin_freqs), dtype=np.float64)
        arr = np.array(self.correction_points, dtype=np.float64)
        return np.interp(
            bin_freqs, arr[:, 0], arr[:, 1],
            left=float(arr[0, 1]), right=float(arr[-1, 1]),
        )

    @property
    def freq_range(self) -> "tuple[float, float] | None":
        """(min_hz, max_hz) of the correction data, or None if empty."""
        if not self.correction_points:
            return None
        return self.correction_points[0][0], self.correction_points[-1][0]

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "sensitivityFactor": self.sensitivity_factor,
            "referenceLevel": self.reference_level,
            "correctionPoints": self.correction_points,
            "importDate": self.import_date,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MicrophoneCalibration":
        return cls(
            id=d["id"],
            name=d["name"],
            sensitivity_factor=d.get("sensitivityFactor"),
            reference_level=d.get("referenceLevel"),
            correction_points=d.get("correctionPoints", []),
            import_date=d.get("importDate", ""),
        )


# ── CalibrationStorage ────────────────────────────────────────────────────────

class CalibrationStorage:
    """
    Persists MicrophoneCalibration profiles in QSettings.
    Mirrors Swift CalibrationStorage singleton (MicrophoneCalibration.swift).

    Calibrations are stored as a JSON array under "storedCalibrations".
    The active calibration UUID is stored under "activeCalibrationID".
    Device→calibration UUID mapping lives under "deviceCalibrationMap".
    """

    _ORG  = "Dolcesfogato"
    _APP  = "GuitarTap"
    _STORAGE_KEY    = "storedCalibrations"
    _ACTIVE_KEY     = "activeCalibrationID"
    _DEVICE_MAP_KEY = "deviceCalibrationMap"

    @classmethod
    def _s(cls):
        from PyQt6 import QtCore
        return QtCore.QSettings(cls._ORG, cls._APP)

    # ── CRUD ──────────────────────────────────────────────────────────────

    @classmethod
    def save(cls, calibration: MicrophoneCalibration) -> None:
        """Save or replace a calibration profile (matched by id).

        Mirrors Swift CalibrationStorage.save().
        """
        cals = [c for c in cls.load_all() if c.id != calibration.id]
        cals.append(calibration)
        cls._s().setValue(cls._STORAGE_KEY, _json.dumps([c.to_dict() for c in cals]))

    @classmethod
    def load_all(cls) -> list:
        """Return all stored calibration profiles (empty list on failure).

        Mirrors Swift CalibrationStorage.loadAll().
        """
        raw = cls._s().value(cls._STORAGE_KEY, None)
        if not raw:
            return []
        try:
            return [MicrophoneCalibration.from_dict(d) for d in _json.loads(raw)]
        except Exception:
            return []

    @classmethod
    def delete(cls, calibration: MicrophoneCalibration) -> None:
        """Remove a calibration profile; clears active ID if it was the active one.

        Mirrors Swift CalibrationStorage.delete().
        """
        cals = [c for c in cls.load_all() if c.id != calibration.id]
        cls._s().setValue(cls._STORAGE_KEY, _json.dumps([c.to_dict() for c in cals]))
        if cls.active_calibration_id() == calibration.id:
            cls.set_active_calibration_id(None)

    @classmethod
    def delete_all(cls) -> None:
        """Remove all stored calibrations and all device mappings."""
        s = cls._s()
        s.remove(cls._STORAGE_KEY)
        s.remove(cls._ACTIVE_KEY)
        s.remove(cls._DEVICE_MAP_KEY)

    # ── Active calibration ─────────────────────────────────────────────────

    @classmethod
    def active_calibration_id(cls) -> "str | None":
        return cls._s().value(cls._ACTIVE_KEY, None) or None

    @classmethod
    def set_active_calibration_id(cls, id_str: "str | None") -> None:
        s = cls._s()
        if id_str:
            s.setValue(cls._ACTIVE_KEY, id_str)
        else:
            s.remove(cls._ACTIVE_KEY)

    @classmethod
    def active_calibration(cls) -> "MicrophoneCalibration | None":
        """Mirrors Swift CalibrationStorage.calibration(forDeviceUID:)."""
        cal_id = cls.active_calibration_id()
        if not cal_id:
            return None
        return next((c for c in cls.load_all() if c.id == cal_id), None)

    # ── Device mapping ─────────────────────────────────────────────────────

    @classmethod
    def set_calibration_for_device(
        cls, device_name: str, cal_id: "str | None"
    ) -> None:
        """Associate a calibration UUID with a device name (or clear it).

        Mirrors Swift CalibrationStorage.setCalibration(_:forDeviceUID:).
        """
        mapping = cls._load_device_map()
        if cal_id:
            mapping[device_name] = cal_id
        else:
            mapping.pop(device_name, None)
        cls._s().setValue(cls._DEVICE_MAP_KEY, _json.dumps(mapping))

    @classmethod
    def calibration_for_device(
        cls, device_name: str
    ) -> "MicrophoneCalibration | None":
        """Return the calibration associated with *device_name*, or None.

        Mirrors Swift CalibrationStorage.calibration(forDeviceUID:).
        """
        if not device_name:
            return None
        mapping = cls._load_device_map()
        cal_id = mapping.get(device_name)
        if not cal_id:
            return None
        return next((c for c in cls.load_all() if c.id == cal_id), None)

    @classmethod
    def _load_device_map(cls) -> dict:
        raw = cls._s().value(cls._DEVICE_MAP_KEY, None)
        if not raw:
            return {}
        try:
            return _json.loads(raw)
        except Exception:
            return {}
