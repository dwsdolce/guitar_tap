"""
AudioDevice — a lightweight, platform-agnostic representation of an audio input device.

Mirrors Swift AVAudioDevice.swift.

Swift uses CoreAudio UIDs (on macOS) and AVAudioSessionPortDescription UIDs (on iOS)
as stable device identifiers.  PortAudio exposes no equivalent stable UID; it only
provides integer indices (unstable across reboots/reconnects) and device names
(mostly stable but can gain suffixes like " (2)" when two identical devices are present).

To make matching as robust as possible without a true UID, AudioDevice stores a
best-effort fingerprint:

    fingerprint = name + ":" + str(int(sample_rate))

e.g. "MacBook Pro Microphone:48000"

This fingerprint is used as the persistent storage key in AppSettings and as the
matching key in _restore_measurement, mirroring the role of AVAudioDevice.uid in
Swift's CalibrationStorage and loadMeasurement device-restore logic.  It is more
discriminating than name alone (useful when two devices share a base name at different
sample rates) while remaining human-readable.

Equality and hashing are based on ``fingerprint`` only, matching Swift's uid-based
Equatable/Hashable implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AudioDevice:
    """Platform-independent representation of an audio input device.

    Mirrors Swift AVAudioDevice (AVAudioDevice.swift).

    Attributes:
        name:        Human-readable device name (e.g. "MacBook Pro Microphone").
        index:       PortAudio device index — valid for the current session only;
                     do not persist this value across restarts.
        sample_rate: Nominal hardware sample rate reported by PortAudio (Hz).
    """

    name: str
    index: int
    sample_rate: float

    # ------------------------------------------------------------------ #
    # Best-effort persistent fingerprint (mirrors Swift AVAudioDevice.uid)
    # ------------------------------------------------------------------ #

    @property
    def fingerprint(self) -> str:
        """Stable-ish string that identifies this physical device across sessions.

        Format: ``"<name>:<sample_rate_hz>"``  e.g. ``"USB Audio Device:48000"``

        More discriminating than name alone; used as the persistence key in
        AppSettings and the calibration-map key in CalibrationStorage.
        Mirrors the role of ``AVAudioDevice.uid`` in Swift.
        """
        return f"{self.name}:{int(self.sample_rate)}"

    # ------------------------------------------------------------------ #
    # Equality and hashing — based on fingerprint only (mirrors Swift uid)
    # ------------------------------------------------------------------ #

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AudioDevice):
            return NotImplemented
        return self.fingerprint == other.fingerprint

    def __hash__(self) -> int:
        return hash(self.fingerprint)

    # ------------------------------------------------------------------ #
    # Factory helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def from_sounddevice_dict(cls, d: dict) -> "AudioDevice":
        """Construct from a sounddevice device-info dictionary."""
        return cls(
            name=str(d["name"]),
            index=int(d["index"]),
            sample_rate=float(d["default_samplerate"]),
        )

    @classmethod
    def from_fingerprint(
        cls, fingerprint: str, index: int = -1
    ) -> "AudioDevice | None":
        """Reconstruct a minimal AudioDevice from a stored fingerprint string.

        Returns None if the fingerprint cannot be parsed.
        The index defaults to -1 (unknown) since indices are not persistent;
        callers should resolve a real index via ``resolve()`` before use.
        """
        if ":" not in fingerprint:
            return None
        name, _, rate_str = fingerprint.rpartition(":")
        try:
            return cls(name=name, index=index, sample_rate=float(rate_str))
        except ValueError:
            return None

    def resolve(self, devices: "list[dict] | None" = None) -> "AudioDevice | None":
        """Look up the current PortAudio index for this device by fingerprint.

        Queries sounddevice if *devices* is not provided.  Returns a new
        AudioDevice with the correct live index, or None if the device is not
        currently available.
        """
        import sounddevice as _sd
        try:
            devs = devices if devices is not None else list(_sd.query_devices())
        except Exception:
            return None
        for d in devs:
            if int(d["max_input_channels"]) > 0:
                candidate = AudioDevice.from_sounddevice_dict(d)
                if candidate.fingerprint == self.fingerprint:
                    return candidate
        return None

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return (
            f"AudioDevice(name={self.name!r}, index={self.index}, "
            f"sample_rate={self.sample_rate})"
        )
