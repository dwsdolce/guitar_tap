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

NOTE — Python vs Swift structural differences:
  Swift has ``id: UUID`` (transient SwiftUI Identifiable UUID) and ``uid: String``
  (platform-assigned UID: CoreAudio kAudioDevicePropertyDeviceUID on macOS,
  AVAudioSessionPortDescription.uid on iOS) as separate fields.
  Python combines both concepts into ``fingerprint`` (a best-effort persistent key).

  Swift also has ``deviceID: AudioDeviceID`` (macOS only) and
  ``port: AVAudioSessionPortDescription?`` (iOS only).
  Python has ``index: int`` (PortAudio device index, session-scoped).
  None of these platform-specific fields have cross-platform equivalents.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioDevice:
    """A platform-independent representation of an audio input device.

    Mirrors Swift AVAudioDevice (AVAudioDevice.swift).

    Equality is determined by ``fingerprint`` (the Python equivalent of Swift's
    ``uid``) so that the same physical device is considered equal across multiple
    discovery passes or application launches.

    - SeeAlso: RealtimeFFTAnalyzer which populates and manages the list of available devices.
    - SeeAlso: CalibrationStorage which maps device fingerprints to calibration profiles.

    NOTE — Python-only fields: ``index`` (PortAudio device index, session-scoped).
    NOTE — Swift-only fields: ``id`` (transient UUID), ``uid`` (platform-assigned UID),
      ``deviceID`` (macOS CoreAudio AudioDeviceID), ``port`` (iOS port description).
    """

    # MARK: - Stored Properties

    # Human-readable display name of the device (e.g. "MacBook Pro Microphone").
    # Mirrors Swift AVAudioDevice.name.
    name: str

    # PortAudio device index — valid for the current session only.
    # Do not persist this value across application restarts; use ``fingerprint`` instead.
    # Python-only — Swift uses ``deviceID: AudioDeviceID`` (macOS) or
    # ``port: AVAudioSessionPortDescription?`` (iOS) for platform-level identity.
    index: int

    # The nominal hardware sample rate reported by PortAudio, in Hz (e.g. 48000.0).
    # Used to inform audio capture configuration and FFT bin spacing.
    # Mirrors Swift AVAudioDevice.sampleRate.
    sample_rate: float

    # MARK: - Persistent Fingerprint (mirrors Swift AVAudioDevice.uid)

    @property
    def fingerprint(self) -> str:
        """Best-effort stable string that identifies this physical device across sessions.

        Format: ``"<name>:<sample_rate_hz>"``  e.g. ``"USB Audio Device:48000"``

        More discriminating than name alone (useful when two devices share a base name
        at different sample rates).  Used as the persistence key in AppSettings and
        the calibration-map key in CalibrationStorage.

        Mirrors the role of ``AVAudioDevice.uid`` in Swift.  Swift obtains a true
        platform UID (CoreAudio on macOS, AVAudioSession on iOS); Python synthesises
        this best-effort substitute from PortAudio metadata.
        """
        return f"{self.name}:{int(self.sample_rate)}"

    # MARK: - Hashable / Equatable

    def __eq__(self, other: object) -> bool:
        """Two devices are equal when their ``fingerprint`` values match.

        Mirrors Swift AVAudioDevice == (lhs:rhs:) which compares ``uid``.
        """
        if not isinstance(other, AudioDevice):
            return NotImplemented
        return self.fingerprint == other.fingerprint

    def __hash__(self) -> int:
        """Hashes the device using only ``fingerprint``.

        Mirrors Swift AVAudioDevice.hash(into:) which hashes ``uid``.
        """
        return hash(self.fingerprint)

    # MARK: - Factory Helpers (Python-only)

    @classmethod
    def from_sounddevice_dict(cls, d: dict) -> "AudioDevice":
        """Construct from a sounddevice device-info dictionary.

        Python-only — Swift uses platform-native APIs (CoreAudio on macOS,
        AVAudioSession on iOS) to enumerate devices.
        """
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

        Python-only — Swift restores devices by matching ``uid`` against the
        live device list returned by CoreAudio/AVAudioSession.
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

        Python-only — Swift resolves devices via CoreAudio/AVAudioSession enumeration.
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

    # MARK: - Convenience

    def __repr__(self) -> str:
        return (
            f"AudioDevice(name={self.name!r}, index={self.index}, "
            f"sample_rate={self.sample_rate})"
        )


def filter_input_devices(raw: "list[dict]") -> "list[dict]":
    """Return the subset of PortAudio devices that are real capture inputs.

    Keeps anything with ``max_input_channels > 0`` on macOS/Linux (the host APIs
    there don't produce the kind of duplicates/pseudo-devices we need to strip).

    On Windows, PortAudio enumerates each physical device under every host API
    it was built with (MME, DirectSound, WASAPI, WDM-KS), plus the Sound Mapper
    routing pseudo-devices and WASAPI loopback endpoints (which PortAudio
    exposes as capture devices even though they're really speaker outputs).
    Filter down to a single host API (preferring WASAPI, then DirectSound, then
    MME) and drop the pseudo / loopback entries.

    WDM-KS is always excluded regardless of API preference: PortAudio opens
    WDM-KS streams without error in shared mode but they deliver all-zero
    samples (-313 dB), making them indistinguishable from a working device.

    The ``raw`` list may contain a pre-annotated ``"_hostapi_name"`` key added
    by load_available_input_devices() before calling this function.  When
    present, it is used in preference to a fresh query_hostapis() call.  If
    query_hostapis() fails AND the annotation is absent, preferred_api stays
    None and ALL non-pseudo, non-loopback inputs are returned unchanged
    (matching the behaviour of the original code at commit 3598b90).
    """
    import platform
    import sounddevice as _sd

    inputs = [d for d in raw if int(d["max_input_channels"]) > 0]
    if platform.system() != "Windows":
        return inputs

    # Build a hostapi-index → name mapping.
    # Priority 1: pre-annotated "_hostapi_name" keys added by
    #   load_available_input_devices() (avoids a second query_hostapis() call
    #   during a Windows enumeration cascade when PortAudio may be unstable).
    # Priority 2: fresh query_hostapis() call (original behaviour).
    # If both fail, api_names stays empty and preferred_api stays None —
    # the filter then only strips pseudo/loopback entries, matching the
    # original safe fallback.
    api_names: "dict[int, str]" = {}
    for d in inputs:
        if "_hostapi_name" in d:
            api_names[int(d.get("hostapi", -1))] = str(d["_hostapi_name"])
    if not api_names:
        try:
            for i, a in enumerate(_sd.query_hostapis()):
                api_names[i] = str(a.get("name", ""))
        except Exception:
            pass

    preferred_api: "int | None" = None
    for preferred_name in ("Windows WASAPI", "Windows DirectSound", "MME"):
        for i, n in api_names.items():
            if n == preferred_name:
                preferred_api = i
                break
        if preferred_api is not None:
            break

    pseudo = ("microsoft sound mapper", "primary sound capture")
    out: list[dict] = []
    for d in inputs:
        name_l = str(d["name"]).lower()
        if any(p in name_l for p in pseudo):
            continue
        if "loopback" in name_l:
            continue
        if preferred_api is not None and int(d.get("hostapi", -1)) != preferred_api:
            continue
        out.append(d)

    return out
