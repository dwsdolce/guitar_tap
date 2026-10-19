# @parity dsp/calibration
"""
Microphone calibration support — mirrors Swift MicrophoneCalibration.swift.

Frequency-response correction for measurement microphones using externally-supplied
calibration data.

Most measurement microphones (e.g. MiniDSP UMIK-1) ship with a per-unit calibration file
that describes the deviation of the microphone's actual frequency response from a flat
0 dB reference.  Applying these corrections to the raw FFT magnitudes yields a spectrum
that more closely represents the true acoustic pressure at the microphone diaphragm.

Supported File Format (UMIK-1 / REW):

  "Sens Factor =-18.39dB, SESSION REF=94.0dBSPL, ..."
   20.0   0.12
   25.0  -0.05
   31.5   0.31
   ...
  20000  -2.14

Lines beginning with '"' or '*' are header/comment lines.  The optional header may contain
a 'Sens Factor' and a 'SESSION REF' value; both are stored but not currently applied
automatically — the correction array is used directly as additive dB offsets.

Columns are separated by tab, space, or comma.  Only frequencies in the range 1–24 000 Hz
are imported.

Interpolation Strategy:
  Corrections between data points are computed by linear interpolation.  Frequencies
  below the lowest calibrated point use the first correction value (flat extrapolation);
  frequencies above the highest use the last correction value.  This conservative strategy
  avoids introducing artefacts from extrapolation beyond the calibrated range.
"""

import json as _json
import re
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt
from PySide6 import QtCore
from guitar_tap.utilities.logging import gt_log
from guitar_tap.utilities.new_uuid import InvalidIdError, new_uuid, parse_uuid, uuid_text

# MARK: - CalibrationFileParser (module-level helpers)
# Mirrors Swift CalibrationFileParser struct.
# In Python these are module-level functions rather than a struct namespace.

class CalibrationFileParser:
    """Parses UMIK-1 style measurement-microphone calibration files.

    Supports both the standard UMIK-1 format (header line starting with '"') and the REW
    (Room EQ Wizard) format (comment lines starting with '*').  Data lines contain
    whitespace-, tab-, or comma-separated frequency–correction pairs.

    Mirrors Swift CalibrationFileParser struct (MicrophoneCalibration.swift).

    NOTE — Python-only: Swift uses a struct with static methods and throws typed ParseError.
    Python raises ValueError with a descriptive message on failure.
    """

    # MARK: - Errors

    class ParseError(Exception):
        """Errors that can occur while parsing a calibration file.

        Mirrors Swift CalibrationFileParser.ParseError enum.
        """

        # file_not_found: The file at the specified path could not be found or opened.
        # invalid_format: The file content does not match any recognised calibration format.
        # no_data_points: The file was parsed successfully but contained no valid data points.
        # read_error:     A low-level file-read error (message is the associated value).

        def __init__(self, kind: str, message: str = ""):
            self.kind = kind
            self.message = message
            super().__init__(message or kind)

    # MARK: - Parsing

    @staticmethod
    def parse(path: str, name: str | None = None) -> "MicrophoneCalibration":
        """Parse a UMIK-1/REW .cal file and return a MicrophoneCalibration.

        The file name (without extension) is used as the default display name for the
        resulting calibration unless overridden by the name parameter.

        - Parameters:
          - path: File path of the .cal calibration file.
          - name: Optional display name override.  Defaults to the filename stem.
        - Returns: A fully parsed MicrophoneCalibration ready for storage.
        - Raises: CalibrationFileParser.ParseError if the file cannot be read or
          contains no valid data points.

        Mirrors Swift CalibrationFileParser.parse(url:name:).
        """
        import os
        profile_name = name or os.path.splitext(os.path.basename(path))[0]

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError as e:
            raise CalibrationFileParser.ParseError("read_error", str(e)) from e

        return CalibrationFileParser.parse_content(content, name=profile_name)

    @staticmethod
    def parse_content(content: str, name: str) -> "MicrophoneCalibration":
        """Parse calibration data from a string.

        - Parameters:
          - content: The full calibration file content as a UTF-8 string.
          - name: Display name for the resulting calibration profile.
        - Returns: A fully parsed MicrophoneCalibration.
        - Raises: CalibrationFileParser.ParseError(no_data_points) if no valid
          frequency–correction pairs are found.

        Mirrors Swift CalibrationFileParser.parse(content:name:).
        """
        # The header names as Swift reads them: spelled as written, in any case.
        _SENS = re.compile(r"Sens Factor\s*=\s*([+-]?[\d.]+)\s*dB", re.IGNORECASE)
        _REF  = re.compile(r"SESSION REF\s*=\s*([\d.]+)\s*dBSPL", re.IGNORECASE)
        _SPL  = re.compile(r"SPL\s+([\d.]+)\s*dB", re.IGNORECASE)

        sensitivity: float | None = None
        reference: float | None = None
        correction_points: list[dict] = []

        for raw in content.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith('"') or line.startswith("*"):
                # Extract optional Sens Factor / reference SPL. Mirrors Swift: each match
                # OVERWRITES (last occurrence wins; on a line carrying both SESSION REF and
                # SPL, SPL wins) — no "first-only" guard.
                m = _SENS.search(line)
                if m:
                    sensitivity = float(m.group(1))
                # SESSION REF (UMIK-1), then SPL (REW) which overwrites if both are present.
                m2 = _REF.search(line)
                if m2:
                    reference = float(m2.group(1))
                m3 = _SPL.search(line)
                if m3:
                    reference = float(m3.group(1))
                continue
            # Data line: parse frequency and correction.
            # Accept tab, space, or comma separators (mirrors Swift).
            parts = re.split(r"[\t ,]+", line)
            parts = [p for p in parts if p]
            if len(parts) < 2:
                continue
            try:
                freq = float(parts[0])
                corr = float(parts[1])
                # Only include frequencies within the audible range (mirrors Swift).
                if 1.0 <= freq <= 24000.0:
                    correction_points.append({"frequency": freq, "correction": corr})
            except ValueError:
                continue

        if not correction_points:
            raise CalibrationFileParser.ParseError("no_data_points",
                "No calibration data points found in file")

        # Sort by frequency (required by interpolation; mirrors Swift's sorted init).
        correction_points.sort(key=lambda p: p["frequency"])

        return MicrophoneCalibration(
            id=new_uuid(),
            name=name,
            sensitivity_factor=sensitivity,
            reference_level=reference,
            correction_points=correction_points,
            import_date=datetime.now(timezone.utc).isoformat(),
        )


# MARK: - MicrophoneCalibration

@dataclass
class MicrophoneCalibration:
    """A parsed microphone calibration curve containing frequency-dependent dB corrections.

    After parsing a calibration file with CalibrationFileParser, store the result via
    CalibrationStorage and associate it with an input device so that the FFT analyzer
    can apply it automatically whenever that device is selected.

    See Also: CalibrationFileParser for parsing .cal files.
    See Also: CalibrationStorage for persistence and device-mapping.

    Mirrors Swift MicrophoneCalibration struct (MicrophoneCalibration.swift).
    """

    # MARK: - Properties

    id: _uuid.UUID                    # Mirrors Swift MicrophoneCalibration.id (UUID).
    name: str                         # Human-readable display name (filename stem by default).
    sensitivity_factor: float | None  # From "Sens Factor" header, in dB.  None if absent.
    reference_level: float | None     # From "SESSION REF" / "SPL" header, in dBSPL.  None if absent.
    correction_points: list           # [{"frequency": Hz, "correction": dB}, ...] sorted ascending.
    import_date: str                  # ISO-8601 timestamp of when the file was imported.

    # MARK: - Parsing

    @classmethod
    def from_path(cls, path: str, name: str | None = None) -> "MicrophoneCalibration":
        """Parse a UMIK-1/REW .cal file and return a named calibration profile.

        Delegates to CalibrationFileParser.parse().

        Mirrors Swift CalibrationFileParser.parse(url:name:).
        """
        return CalibrationFileParser.parse(path, name=name)

    # MARK: - Correction Interpolation

    def interpolate_to_bins(
        self, bin_freqs: "npt.NDArray[np.float64]"
    ) -> "npt.NDArray[np.float64]":
        """Interpolate this profile's corrections onto FFT bin frequencies.

        Uses flat extrapolation at the edges (matches Swift MicrophoneCalibration.correction(at:)
        behaviour where frequencies below/above the calibrated range use the first/last value).

        - Parameter bin_freqs: Array of FFT bin centre frequencies, in Hz.
        - Returns: Array of additive dB corrections, parallel to bin_freqs.

        Mirrors Swift MicrophoneCalibration.corrections(for:).
        """
        if not self.correction_points:
            return np.zeros(len(bin_freqs), dtype=np.float64)
        arr = np.array(
            [[p["frequency"], p["correction"]] for p in self.correction_points],
            dtype=np.float64,
        )
        return np.interp(
            bin_freqs, arr[:, 0], arr[:, 1],
            left=float(arr[0, 1]),    # flat extrapolation below calibrated range
            right=float(arr[-1, 1]), # flat extrapolation above calibrated range
        )

    @property
    def details(self) -> "tuple[str | None, str, str | None]":
        """The details Settings shows: (sensitivity, data points, range) — the sensitivity when the
        file gives one, the range when there are points. Mirrors Swift
        ``MicrophoneCalibration.details``."""
        sensitivity = (f"Sensitivity: {self.sensitivity_factor:.2f} dB"
                       if self.sensitivity_factor is not None else None)
        fr = self.freq_range
        rng = f"{fr[0]:.0f}-{fr[1]:.0f} Hz" if fr else None
        return sensitivity, f"Data points: {len(self.correction_points)}", rng

    @property
    def freq_range(self) -> "tuple[float, float] | None":
        """(min_hz, max_hz) of the correction data, or None if empty.

        Python-only helper property.
        """
        if not self.correction_points:
            return None
        return self.correction_points[0]["frequency"], self.correction_points[-1]["frequency"]

    # MARK: - Serialisation

    def to_dict(self) -> dict:
        """Encode this calibration as a JSON-serialisable dict.

        Mirrors Swift MicrophoneCalibration Codable conformance.
        """
        return {
            "id": uuid_text(self.id),
            "name": self.name,
            "sensitivityFactor": self.sensitivity_factor,
            "referenceLevel": self.reference_level,
            "correctionPoints": self.correction_points,
            "importDate": self.import_date,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MicrophoneCalibration":
        """Decode a MicrophoneCalibration from a JSON dict.

        Mirrors Swift MicrophoneCalibration Decodable conformance.
        """
        # Normalise correction_points: accept both dict and list forms.
        raw_points = d.get("correctionPoints", [])
        if raw_points and isinstance(raw_points[0], list):
            # Legacy list-of-lists format [freq, corr]
            correction_points = [{"frequency": p[0], "correction": p[1]} for p in raw_points]
        else:
            correction_points = raw_points

        return cls(
            id=parse_uuid(d.get("id"), "calibration id"),
            name=d["name"],
            sensitivity_factor=d.get("sensitivityFactor"),
            reference_level=d.get("referenceLevel"),
            correction_points=correction_points,
            import_date=d.get("importDate", ""),
        )


# MARK: - CalibrationStorage

class CalibrationStorage:
    """Persists and retrieves MicrophoneCalibration profiles using QSettings.

    Calibrations can be associated with specific audio input devices by their name,
    allowing the FFT analyzer to automatically apply the correct profile when the user
    selects a measurement microphone.

    The analyzer applies a device's profile whenever that device is selected: its mapping
    (set_calibration_for_device()), or no correction when it has none. The global
    active_calibration_id records the last calibration chosen.

    NOTE — Storage backend: Swift uses UserDefaults; Python uses QSettings.
    Both backends persist a JSON-encoded calibration array under the same logical keys.

    Mirrors Swift CalibrationStorage class (MicrophoneCalibration.swift).
    """

    # MARK: - Private Keys

    _ORG  = "Dolcesfogato"
    # Unified with the rest of the app's settings (AppSettings uses "guitar_tap"), mirroring Swift
    # where calibration + device + settings all live in the single UserDefaults.standard. This used
    # to be a SEPARATE QSettings domain ("GuitarTap" → com.dolcesfogato.GuitarTap.plist), which split
    # the calibration store off from every other setting — a straight divergence from Swift. The old
    # scope is migrated once (see _migrate_legacy_scope) so existing profiles + device associations
    # survive the change.
    _APP  = "guitar_tap"
    _LEGACY_APP = "GuitarTap"
    _STORAGE_KEY    = "storedCalibrations"    # JSON array of calibration dicts.
    _ACTIVE_KEY     = "activeCalibrationID"   # UUID string of the global active calibration.
    # JSON dict: deviceName → calibrationUUID.
    # Keys by device name rather than a stable hardware UID because PortAudio provides
    # no persistent device UID. Swift equivalent keys by CoreAudio UID (stable across
    # sessions and renames). Python uses device name as a best-effort substitute.
    _DEVICE_MAP_KEY = "deviceCalibrationMap"

    _migrated_scope = False

    @classmethod
    def _s(cls):
        import os
        # Isolate under pytest so tests never touch the user's real calibrations — the same redirect
        # AppSettings uses. (Previously CalibrationStorage had none, because it lived in its own domain.)
        from guitar_tap.models.settings_scope import settings_org  # noqa: PLC0415
        org = settings_org(cls._ORG)
        cls._migrate_legacy_scope(org)
        return QtCore.QSettings(org, cls._APP)

    @classmethod
    def _migrate_legacy_scope(cls, org: str) -> None:
        """One-time copy of calibrations from the pre-unification "GuitarTap" QSettings domain into
        the unified one, so existing profiles + device→calibration associations survive the scope
        change. Idempotent: runs only when the unified scope has no stored calibrations yet."""
        if cls._migrated_scope:
            return
        cls._migrated_scope = True
        try:
            unified = QtCore.QSettings(org, cls._APP)
            if unified.value(cls._STORAGE_KEY, None):
                return  # unified scope already populated — nothing to migrate
            legacy = QtCore.QSettings(org, cls._LEGACY_APP)
            moved = False
            for key in (cls._STORAGE_KEY, cls._ACTIVE_KEY, cls._DEVICE_MAP_KEY):
                val = legacy.value(key, None)
                if val is not None:
                    unified.setValue(key, val)
                    moved = True
            if moved:
                unified.sync()
        except Exception:
            pass

    # MARK: - CRUD

    @classmethod
    def save(cls, calibration: MicrophoneCalibration) -> None:
        """Save or replace a calibration profile (matched by id).

        If a calibration with the same id already exists it is replaced;
        otherwise the new entry is appended.

        Mirrors Swift CalibrationStorage.save(_:).
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
            cls._set_aside_unreadable(raw)
            return []

    @classmethod
    def _set_aside_unreadable(cls, raw) -> None:
        """The stored calibrations could not be read. They are moved to ``<key>-unreadable-<date and
        time>``, so no later save writes over them, and the list starts empty; a calibration can be
        imported again. Mirrors Swift ``setAsideUnreadableCalibrations(_:)``."""
        from datetime import datetime
        kept_key = f"{cls._STORAGE_KEY}-unreadable-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        s = cls._s()
        s.setValue(kept_key, raw)
        s.remove(cls._STORAGE_KEY)
        gt_log(f"❌ Stored calibrations could not be read — kept as {kept_key}; the list starts empty")

    @classmethod
    def delete(cls, calibration: MicrophoneCalibration) -> None:
        """Remove a calibration profile; clears active ID if it was the active one.

        Mirrors Swift CalibrationStorage.delete(_:).
        """
        cals = [c for c in cls.load_all() if c.id != calibration.id]
        cls._s().setValue(cls._STORAGE_KEY, _json.dumps([c.to_dict() for c in cals]))
        if cls.active_calibration_id() == calibration.id:
            cls.set_active_calibration_id(None)

    # MARK: - Global Active Calibration

    @classmethod
    def active_calibration_id(cls) -> "_uuid.UUID | None":
        """The UUID string of the global active calibration, persisted in QSettings.

        Mirrors Swift CalibrationStorage.activeCalibrationID.
        """
        return _uuid_or_none(cls._s().value(cls._ACTIVE_KEY, None))

    @classmethod
    def set_active_calibration_id(cls, cal_id: "_uuid.UUID | None") -> None:
        """Set or clear the global active calibration UUID.

        Mirrors Swift CalibrationStorage.activeCalibrationID setter.
        """
        s = cls._s()
        if cal_id:
            s.setValue(cls._ACTIVE_KEY, uuid_text(cal_id))
        else:
            s.remove(cls._ACTIVE_KEY)

    @classmethod
    def active_calibration(cls) -> "MicrophoneCalibration | None":
        """The global active MicrophoneCalibration object, loaded on demand.

        Returns None if no global active calibration is set or if the referenced ID
        is not found in storage.

        Mirrors Swift CalibrationStorage.activeCalibration.
        """
        cal_id = cls.active_calibration_id()
        if not cal_id:
            return None
        return next((c for c in cls.load_all() if c.id == cal_id), None)

    # MARK: - Device-Specific Calibration Mapping

    @classmethod
    def set_calibration_for_device(
        cls, device_name: str, cal_id: "_uuid.UUID | None"
    ) -> None:
        """Associate a calibration UUID with a device name (or clear it).

        Once set, the FFT analyzer automatically loads this calibration whenever
        the specified device is selected, taking priority over the global activeCalibration.

        Mirrors Swift CalibrationStorage.setCalibration(_:forDeviceUID:).
        """
        mapping = cls._load_device_map()
        if cal_id:
            mapping[device_name] = uuid_text(cal_id)
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
        cal_id = _uuid_or_none(mapping.get(device_name))
        if not cal_id:
            return None
        return next((c for c in cls.load_all() if c.id == cal_id), None)

    @classmethod
    def _load_device_map(cls) -> dict:
        """Load the raw {deviceName: calibrationUUIDString} dict from QSettings.

        Mirrors Swift CalibrationStorage.loadDeviceCalibrationMap().
        """
        raw = cls._s().value(cls._DEVICE_MAP_KEY, None)
        if not raw:
            return {}
        try:
            return _json.loads(raw)
        except Exception:
            return {}


def _uuid_or_none(value) -> "_uuid.UUID | None":
    """A stored calibration id read as a UUID — None when there is none or it is not one, as Swift's
    ``UUID(uuidString:)`` gives nil."""
    try:
        return parse_uuid(value, "calibration id")
    except InvalidIdError:
        return None
