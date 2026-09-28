# @parity test/mic-selection
"""
Which input device the engine uses and which it saves: the rule input_device_to_use (MS1–MS5), the
engine driven through apply_input_device_list, choose_input_device and set_device (MS6–MS11), and a
measurement load switching to its recorded microphone (MS14–MS17), and choosing a calibration for the
selected device (MS18–MS20).

The rule: the saved choice when it is present, otherwise the system default input, otherwise the
first device. Only a choice — picked in Settings, or plugged in while the app runs — is saved; the
startup selection, a fallback and a loaded measurement's microphone are not.

The saved choice lives in AppSettings, which the test sandbox isolates. MS1–MS11 and MS14–MS20 are the
same list, ids and devices as Swift MicSelectionTests and web test/mic-selection.test.ts. MS12–MS13 are Python
only: which PortAudio default is the system default (Swift reads CoreAudio's; the browser resolves its
own).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models import realtime_fft_analyzer_device_management as dm
from guitar_tap.models.audio_device import AudioDevice
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
from guitar_tap.models.realtime_fft_analyzer_device_management import input_device_to_use
from guitar_tap.views.utilities.tap_settings_view import AppSettings

BUILT_IN = AudioDevice(name="MacBook Pro Microphone", index=1, sample_rate=48000)
BLACK_HOLE = AudioDevice(name="BlackHole 2ch", index=2, sample_rate=48000)
UMIK = AudioDevice(name="UMIK-1", index=3, sample_rate=48000)


def _saved() -> str | None:
    return AppSettings.selected_input_device_fingerprint()


def _make_sut(saved: AudioDevice | None) -> RealtimeFFTAnalyzer:
    """A fresh engine with *saved* as the saved choice (None: nothing saved)."""
    if saved is not None:
        AppSettings.set_audio_device(saved)
    else:
        AppSettings.set_selected_input_device_fingerprint(None)
        AppSettings._s().remove(AppSettings._DEVICE_NAME_KEY)
    return RealtimeFFTAnalyzer.for_testing()


# MARK: - The rule

def test_MS1_saved_present_wins():
    """MS1: The saved device wins when it is present — over the system default, and over any other
    device (the built-in mic is kept although a USB mic and BlackHole are listed)."""
    chosen = input_device_to_use([BLACK_HOLE, BUILT_IN, UMIK], BUILT_IN.fingerprint, UMIK.fingerprint)
    assert chosen == BUILT_IN


def test_MS2_saved_absent_uses_system_default():
    """MS2: The saved device is not connected — the system default."""
    chosen = input_device_to_use([BLACK_HOLE, BUILT_IN], UMIK.fingerprint, BUILT_IN.fingerprint)
    assert chosen == BUILT_IN


def test_MS3_nothing_saved_uses_system_default():
    """MS3: Nothing saved — the system default, not a device listed ahead of it (BlackHole)."""
    chosen = input_device_to_use([BLACK_HOLE, BUILT_IN], None, BUILT_IN.fingerprint)
    assert chosen == BUILT_IN


def test_MS4_no_default_uses_first_device():
    """MS4: No usable system default — the first device."""
    assert input_device_to_use([UMIK, BUILT_IN], None, None) == UMIK


def test_MS5_no_devices_selects_nothing():
    """MS5: No devices — nothing."""
    assert input_device_to_use([], BUILT_IN.fingerprint, BUILT_IN.fingerprint) is None


# MARK: - The engine: what is selected, and what is saved

def test_MS6_startup_selection_is_not_saved():
    """MS6: The startup selection is not saved: nothing saved, the default is selected, and nothing
    is saved afterwards."""
    sut = _make_sut(saved=None)
    sut.apply_input_device_list([BLACK_HOLE, BUILT_IN], BUILT_IN.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() is None


def test_MS7_choice_is_saved():
    """MS7: A device the user chooses is selected and saved."""
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.choose_input_device(UMIK)
    assert sut.selected_input_device == UMIK
    assert _saved() == UMIK.fingerprint


def test_MS8_plugged_in_is_selected_and_saved():
    """MS8: A device plugged in while running is switched to and saved."""
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN], BUILT_IN.fingerprint)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    assert sut.selected_input_device == UMIK
    assert _saved() == UMIK.fingerprint


def test_MS9_saved_unplugged_falls_back_without_saving():
    """MS9: The saved device unplugged — the system default for the session; the saved choice is
    still the unplugged device, so it comes back at the next launch."""
    sut = _make_sut(saved=UMIK)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    assert sut.selected_input_device == UMIK
    sut.apply_input_device_list([BUILT_IN], BUILT_IN.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == UMIK.fingerprint


def test_MS10_session_device_unplugged_returns_to_saved():
    """MS10: A device used for the session only (not the saved one) unplugged — back to the saved
    device, which is present."""
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, BLACK_HOLE, UMIK], BLACK_HOLE.fingerprint)
    sut.selected_input_device = UMIK
    sut.apply_input_device_list([BUILT_IN, BLACK_HOLE], BLACK_HOLE.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint


class _FakeStream:
    samplerate = 48000

    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


def test_MS11_load_switch_is_not_saved(monkeypatch):
    """MS11: The switch a measurement load makes to its recorded microphone (set_device) is not
    saved."""
    monkeypatch.setattr(dm.sd, "InputStream", _FakeStream)
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.set_device(UMIK)
    assert sut.selected_input_device == UMIK
    assert _saved() == BUILT_IN.fingerprint


# MARK: - Python only: which PortAudio default is the system default

def _input(name: str, index: int, hostapi: int) -> dict:
    return {"name": name, "index": index, "hostapi": hostapi, "max_input_channels": 1,
            "default_samplerate": 48000.0}


def test_MS12_system_default_is_the_listed_host_apis_default(monkeypatch):
    """MS12 (Python only): the system default is the default input of the host API the list uses
    (WASAPI on Windows), not PortAudio's global default, which belongs to another API (MME)."""
    from types import SimpleNamespace
    wasapi = 2
    inputs = [_input("Microphone Array", 10, wasapi), _input("UMIK-1", 11, wasapi)]
    monkeypatch.setattr(dm.sd, "query_hostapis", lambda: [
        {"name": "MME", "default_input_device": 1},
        {"name": "Windows DirectSound", "default_input_device": 5},
        {"name": "Windows WASAPI", "default_input_device": 11},
    ])
    monkeypatch.setattr(dm.sd, "default", SimpleNamespace(device=(1, 3)))
    assert dm._system_default_fingerprint(inputs) == "UMIK-1:48000"


def test_MS13_global_default_when_the_host_api_has_none(monkeypatch):
    """MS13 (Python only): when the list's host API reports no default input, PortAudio's global
    default is used if it is listed."""
    from types import SimpleNamespace
    inputs = [_input("MacBook Pro Microphone", 0, 0), _input("UMIK-1", 1, 0)]
    monkeypatch.setattr(dm.sd, "query_hostapis", lambda: [{"name": "Core Audio", "default_input_device": -1}])
    monkeypatch.setattr(dm.sd, "default", SimpleNamespace(device=(1, 2)))
    assert dm._system_default_fingerprint(inputs) == "UMIK-1:48000"


# MARK: - Loading a measurement recorded with another connected microphone

def _load(monkeypatch, mic: AudioDevice, calibration_name: str | None = None):
    """An analyzer on the built-in mic (saved) with a calibration, the USB mic connected, and a
    measurement recorded with *mic* and *calibration_name*, loaded."""
    import uuid

    from guitar_tap.models.microphone_calibration import MicrophoneCalibration
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

    monkeypatch.setattr(dm.sd, "InputStream", _FakeStream)
    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic._on_calibration_changed = sut._on_mic_calibration_changed  # as start() wires it
    sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.set_temporary_calibration(MicrophoneCalibration(
        id=str(uuid.uuid4()), name="Built-in room", sensitivity_factor=None, reference_level=None,
        correction_points=[{"frequency": 20.0, "correction": 0.0},
                           {"frequency": 20000.0, "correction": 0.0}],
        import_date=""))
    sut.load_measurement(TapToneMeasurement(
        id=str(uuid.uuid4()), timestamp="2026-01-01T00:00:00Z", peaks=[],
        measurement_name="Loaded", microphone_name=mic.name, microphone_uid=mic.fingerprint,
        calibration_name=calibration_name))
    return sut


def _load_recorded_with_usb_mic(monkeypatch):
    return _load(monkeypatch, UMIK)


def test_MS14_load_switch_is_in_place_when_the_load_returns(monkeypatch):
    """MS14: The load has switched to the recorded microphone by the time it returns."""
    sut = _load_recorded_with_usb_mic(monkeypatch)
    assert sut.mic.selected_input_device == UMIK


def test_MS15_load_check_reads_the_recorded_microphone(monkeypatch):
    """MS15: The calibration check compares the recorded microphone's calibration (none) — not that
    of the microphone switched away from ("Built-in room") — so no warning."""
    sut = _load_recorded_with_usb_mic(monkeypatch)
    assert sut._active_calibration_name is None
    assert sut.microphone_warning is None


def test_MS16_no_match_warns_and_keeps_the_input(monkeypatch):
    """MS16: No connected microphone matches — the not-found warning; the input is unchanged."""
    sut = _load(monkeypatch, AudioDevice(name="Absent Mic", index=9, sample_rate=48000))
    assert sut.mic.selected_input_device == BUILT_IN
    assert sut.microphone_warning.startswith(
        "Recorded with 'Absent Mic'. No connected microphone matches that name")


def test_MS17_same_microphone_different_calibration_warns(monkeypatch):
    """MS17: The recorded microphone is the current one but its calibration differs — the warning."""
    sut = _load(monkeypatch, BUILT_IN, calibration_name="Other")
    assert sut.microphone_warning == (
        "This measurement was recorded with a different calibration. A newly captured tap may not "
        "match the saved result.")



# MARK: - Choosing a calibration

def _analyzer_with_stored_calibration():
    """An analyzer on the built-in mic with the USB mic connected, an empty calibration store, and
    "Room" saved in it."""
    import uuid

    from guitar_tap.models.microphone_calibration import CalibrationStorage, MicrophoneCalibration
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    for cal in CalibrationStorage.load_all():
        CalibrationStorage.delete(cal)
    CalibrationStorage.set_active_calibration_id(None)
    for device in (BUILT_IN, UMIK):
        CalibrationStorage.set_calibration_for_device(device.name, None)
        CalibrationStorage.set_calibration_for_device(device.fingerprint, None)
    room = MicrophoneCalibration(
        id=str(uuid.uuid4()), name="Room", sensitivity_factor=None, reference_level=None,
        correction_points=[{"frequency": 20.0, "correction": 0.0},
                           {"frequency": 20000.0, "correction": 0.0}],
        import_date="")
    CalibrationStorage.save(room)
    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic._on_calibration_changed = sut._on_mic_calibration_changed  # as start() wires it
    sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    return sut, room, CalibrationStorage


def test_MS18_chosen_calibration_is_saved_for_the_device():
    """MS18: A calibration chosen for the selected device is saved for it (and as the last chosen);
    switching to another device and back restores it."""
    sut, room, storage = _analyzer_with_stored_calibration()
    sut.choose_calibration(room)
    assert storage.calibration_for_device(BUILT_IN.name).id == room.id
    assert storage.active_calibration_id() == room.id
    sut.mic.choose_input_device(UMIK)
    assert sut._calibration_profile is None
    sut.mic.choose_input_device(BUILT_IN)
    assert sut._calibration_profile.id == room.id


def test_MS19_choosing_none_removes_the_devices_calibration():
    """MS19: Choosing no calibration removes the device's: switching away and back gives none."""
    sut, room, storage = _analyzer_with_stored_calibration()
    sut.choose_calibration(room)
    sut.choose_calibration(None)
    assert storage.calibration_for_device(BUILT_IN.name) is None
    assert storage.active_calibration_id() is None
    sut.mic.choose_input_device(UMIK)
    sut.mic.choose_input_device(BUILT_IN)
    assert sut._calibration_profile is None


def test_MS20_temporary_calibration_saves_nothing():
    """MS20: A file playback's calibration (temporary) is applied but saves nothing."""
    sut, room, storage = _analyzer_with_stored_calibration()
    sut.set_temporary_calibration(room)
    assert sut._calibration_profile.id == room.id
    assert storage.calibration_for_device(BUILT_IN.name) is None
    assert storage.active_calibration_id() is None
