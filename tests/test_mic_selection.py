# @parity test/mic-selection
"""
Which input device the engine uses and what it saves: the launch rule input_device_to_use (MS1–MS5,
the shared cases in mic-selection.json), the engine driven through apply_input_device_list, a Settings
selection and set_device (MS6–MS11), a measurement load switching to its recorded microphone
(MS14–MS17), choosing a calibration for the selected device (MS18–MS20), the thresholds a load
restores, saved as a setting (MS21–MS22), and a device that cannot be opened (MS23–MS25).

The rules: at launch, the saved device when it is present, otherwise the system default input,
otherwise the first device; a device connected while running is selected; the device in use
disappearing selects the system default, otherwise the first device. Every selection is saved, so
what Settings shows is what the next launch uses.

The saved device lives in AppSettings, which the test sandbox isolates. MS1–MS11 and MS14–MS25 are the
same list, ids and devices as Swift MicSelectionTests and web test/mic-selection.test.ts. MS12–MS13 and MS26–MS28 are
Python only: which PortAudio default is the system default (Swift reads CoreAudio's; the browser resolves
its own), and PortAudio's device numbering and re-initialising.
"""

from __future__ import annotations

import json
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


from guitar_tap.utilities.new_uuid import new_uuid
from guitar_tap.models import realtime_fft_analyzer_device_management as dm
from guitar_tap.models import tap_tone_analyzer_measurement_management as mm
from guitar_tap.models.audio_device import AudioDevice
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
from guitar_tap.models.realtime_fft_analyzer_device_management import input_device_to_use
from guitar_tap.views.utilities.tap_settings_view import AppSettings

BUILT_IN = AudioDevice(name="MacBook Pro Microphone", index=1, sample_rate=48000)
BLACK_HOLE = AudioDevice(name="BlackHole 2ch", index=2, sample_rate=48000)
UMIK = AudioDevice(name="UMIK-1", index=3, sample_rate=48000)
USB2 = AudioDevice(name="USB Mic 2", index=4, sample_rate=48000)


def _device_table(*devices: AudioDevice):
    """A stand-in for sd.query_devices(index, kind) that describes *devices* by their index."""
    by_index = {d.index: d for d in devices}

    def query(index=None, kind=None):
        return {"name": by_index[index].name, "hostapi": 0}

    return query


@pytest.fixture(autouse=True)
def _fake_device_table(monkeypatch):
    """PortAudio's device table is this file's four devices, so a stream opened on one of their
    indices is on that device — the tests' streams are stand-ins, and the real table is the
    machine's."""
    monkeypatch.setattr(dm.sd, "query_devices", _device_table(BUILT_IN, BLACK_HOLE, UMIK, USB2))


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


# MARK: - The rule — the shared cases in mic-selection.json (MS1–MS5)

with open(os.path.join(os.path.dirname(__file__), "mic-selection.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

_DEVICES = {"builtIn": BUILT_IN, "blackHole": BLACK_HOLE, "umik": UMIK, "usb2": USB2}


def _device(key: "str | None") -> "AudioDevice | None":
    """This file's device for a case file's device key."""
    return _DEVICES[key] if key is not None else None


@pytest.mark.parametrize("row", [r for r in DATA["inputDeviceToUse"] if "python" in r.get("editions", ["python"])],
                         ids=lambda r: r["id"])
def test_input_device_to_use(row):
    saved, default = _device(row["saved"]), _device(row["default"])
    chosen = input_device_to_use([_device(k) for k in row["devices"]],
                                 saved.fingerprint if saved else None,
                                 default.fingerprint if default else None)
    assert chosen == _device(row["expect"]), f"{row['id']}: {row['note']}"


# MARK: - The engine: what is selected, and what is saved

def test_MS6_launch_selection_is_saved():
    """MS6: The launch selection is saved: nothing saved, the default is selected and saved."""
    sut = _make_sut(saved=None)
    sut.apply_input_device_list([BLACK_HOLE, BUILT_IN], BUILT_IN.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint


def test_MS7_settings_selection_is_saved():
    """MS7: A device selected in Settings is selected and saved."""
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.selected_input_device = UMIK
    assert _saved() == UMIK.fingerprint


def test_MS8_plugged_in_is_selected_and_saved():
    """MS8: A device plugged in while running is selected and saved."""
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN], BUILT_IN.fingerprint)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    assert sut.selected_input_device == UMIK
    assert _saved() == UMIK.fingerprint


def test_MS9_in_use_unplugged_falls_back_and_saves():
    """MS9: The device in use unplugged (or dropping out) — the system default, selected and saved,
    so the next launch is on what Settings shows."""
    sut = _make_sut(saved=UMIK)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    assert sut.selected_input_device == UMIK
    sut.apply_input_device_list([BUILT_IN], BUILT_IN.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint


def test_MS10_in_use_unplugged_falls_to_the_default_not_another_usb_mic():
    """MS10: The device in use unplugged falls to the system default, not to another connected USB
    mic."""
    sut = _make_sut(saved=USB2)
    sut.apply_input_device_list([BUILT_IN, UMIK, USB2], BUILT_IN.fingerprint)
    assert sut.selected_input_device == USB2
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint


class _FakeStream:
    samplerate = 48000

    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


def test_MS11_load_switch_is_saved(monkeypatch):
    """MS11: The switch a measurement load makes to its recorded microphone (set_device) is saved."""
    monkeypatch.setattr(dm.sd, "InputStream", _FakeStream)
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.set_device(UMIK)
    assert sut.selected_input_device == UMIK
    assert _saved() == UMIK.fingerprint


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

    from guitar_tap.models.microphone_calibration import MicrophoneCalibration
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

    monkeypatch.setattr(dm.sd, "InputStream", _FakeStream)
    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.mic.set_temporary_calibration(MicrophoneCalibration(
        id=new_uuid(), name="Built-in room", sensitivity_factor=None, reference_level=None,
        correction_points=[{"frequency": 20.0, "correction": 0.0},
                           {"frequency": 20000.0, "correction": 0.0}],
        import_date=""))
    sut.load_measurement(TapToneMeasurement(
        id=new_uuid(), timestamp="2026-01-01T00:00:00Z", peaks=[],
        measurement_name="Loaded", microphone_name=mic.name, microphone_uid=mic.fingerprint,
        calibration_name=calibration_name))
    return sut


def _load_recorded_with_usb_mic(monkeypatch):
    return _load(monkeypatch, UMIK)


def test_MS14_load_switch_is_in_place_when_the_load_returns(monkeypatch):
    """MS14: The load has switched to the recorded microphone, and saved it, by the time it
    returns."""
    sut = _load_recorded_with_usb_mic(monkeypatch)
    assert sut.mic.selected_input_device == UMIK
    assert _saved() == UMIK.fingerprint


def test_MS15_load_check_reads_the_recorded_microphone(monkeypatch):
    """MS15: The calibration check compares the recorded microphone's calibration (none) — not that
    of the microphone switched away from ("Built-in room") — so no warning."""
    sut = _load_recorded_with_usb_mic(monkeypatch)
    assert sut.mic.active_calibration is None
    assert sut.microphone_warning is None


def test_MS16_no_match_warns_and_keeps_the_input(monkeypatch):
    """MS16: No connected microphone matches — the not-found warning; the input is unchanged."""
    sut = _load(monkeypatch, AudioDevice(name="Absent Mic", index=9, sample_rate=48000))
    assert sut.mic.selected_input_device == BUILT_IN
    assert sut.microphone_warning_title == "Microphone Not Found"
    assert sut.microphone_warning == mm.microphone_not_found_message("Absent Mic", BUILT_IN.name)
    assert "you are still using 'MacBook Pro Microphone'" in sut.microphone_warning


def test_MS17_same_microphone_different_calibration_warns(monkeypatch):
    """MS17: The recorded microphone is the current one but its calibration differs — the warning."""
    sut = _load(monkeypatch, BUILT_IN, calibration_name="Other")
    assert sut.microphone_warning_title == "Recording Setup Differs"
    assert sut.microphone_warning == (
        "This measurement was made with a different setup from the current one:\n"
        "• Calibration: recorded with 'Other'; the current microphone uses 'Built-in room'.\n\n"
        "A tap captured now may not match the saved result. The sample rate is set outside Guitar "
        "Tap: in Audio MIDI Setup on a Mac, or Sound settings on Windows.")



# MARK: - Choosing a calibration

def _analyzer_with_stored_calibration():
    """An analyzer on the built-in mic with the USB mic connected, an empty calibration store, and
    "Room" saved in it."""

    from guitar_tap.models.microphone_calibration import CalibrationStorage, MicrophoneCalibration
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    for cal in CalibrationStorage.load_all():
        CalibrationStorage.delete(cal)
    CalibrationStorage.set_active_calibration_id(None)
    for device in (BUILT_IN, UMIK):
        CalibrationStorage.set_calibration_for_device(device.name, None)
        CalibrationStorage.set_calibration_for_device(device.fingerprint, None)
    room = MicrophoneCalibration(
        id=new_uuid(), name="Room", sensitivity_factor=None, reference_level=None,
        correction_points=[{"frequency": 20.0, "correction": 0.0},
                           {"frequency": 20000.0, "correction": 0.0}],
        import_date="")
    CalibrationStorage.save(room)
    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    return sut, room, CalibrationStorage


def test_MS18_chosen_calibration_is_saved_for_the_device():
    """MS18: A calibration chosen for the selected device is saved for it (and as the last chosen);
    switching to another device and back restores it."""
    sut, room, storage = _analyzer_with_stored_calibration()
    sut.mic.set_active_calibration(room)
    assert storage.calibration_for_device(BUILT_IN.name).id == room.id
    assert storage.active_calibration_id() == room.id
    sut.mic.selected_input_device = UMIK
    assert sut.mic.active_calibration is None
    sut.mic.selected_input_device = BUILT_IN
    assert sut.mic.active_calibration.id == room.id


def test_MS19_choosing_none_removes_the_devices_calibration():
    """MS19: Choosing no calibration removes the device's: switching away and back gives none."""
    sut, room, storage = _analyzer_with_stored_calibration()
    sut.mic.set_active_calibration(room)
    sut.mic.set_active_calibration(None)
    assert storage.calibration_for_device(BUILT_IN.name) is None
    assert storage.active_calibration_id() is None
    sut.mic.selected_input_device = UMIK
    sut.mic.selected_input_device = BUILT_IN
    assert sut.mic.active_calibration is None


def test_MS20_temporary_calibration_saves_nothing():
    """MS20: A file playback's calibration (temporary) is applied but saves nothing."""
    sut, room, storage = _analyzer_with_stored_calibration()
    sut.mic.set_temporary_calibration(room)
    assert sut.mic.active_calibration.id == room.id
    assert storage.calibration_for_device(BUILT_IN.name) is None
    assert storage.active_calibration_id() is None


# MARK: - A load restores settings as the user setting them would

def test_MS21_load_saves_the_thresholds_it_restores():
    """MS21: A load saves the thresholds it restores, so they are the settings at the next launch."""

    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

    TapDisplaySettings.set_tap_detection_threshold(-40.0)
    TapDisplaySettings.set_peak_min_threshold(-60.0)
    sut = TapToneAnalyzer.for_testing()
    sut.load_measurement(TapToneMeasurement(
        id=new_uuid(), timestamp="2026-01-01T00:00:00Z", peaks=[],
        measurement_name="Loaded", tap_detection_threshold=-30.0, peak_min_threshold=-50.0))
    assert TapDisplaySettings.tap_detection_threshold() == -30.0
    assert TapDisplaySettings.peak_min_threshold() == -50.0


def test_MS22_setting_a_threshold_saves_it():
    """MS22: Setting a threshold on the analyzer saves it."""
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    sut = TapToneAnalyzer.for_testing()
    sut.tap_detection_threshold = -35.0
    sut.peak_min_threshold = -45.0
    assert TapDisplaySettings.tap_detection_threshold() == -35.0
    assert TapDisplaySettings.peak_min_threshold() == -45.0


# MARK: - A device that cannot be opened

class _StreamFailingFor:
    """An InputStream stand-in that fails to open for the device indices given."""

    def __init__(self, failing: set):
        self.failing = failing

    def __call__(self, **kwargs):
        if kwargs.get("device") in self.failing:
            raise dm.sd.PortAudioError("cannot open")
        return _FakeStream()


def test_MS23_failed_open_keeps_the_previous_device(monkeypatch):
    """MS23: A switch whose device cannot be opened leaves the previous device selected and saved,
    and the failure is reported to the caller."""
    monkeypatch.setattr(dm.sd, "InputStream", _StreamFailingFor({UMIK.index}))
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    with pytest.raises(dm.InputDeviceOpenError):
        sut.set_device(UMIK)
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint


def test_MS24_failed_switch_while_running_reverts_and_reports(monkeypatch):
    """MS24: A device switched to while running (a plug-in, a fallback) that cannot be opened is
    reverted, and the failed-open message is reported for the alert."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    monkeypatch.setattr(dm.sd, "InputStream", _StreamFailingFor({UMIK.index}))
    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic.apply_input_device_list([BUILT_IN], BUILT_IN.fingerprint)
    sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    assert sut.mic.selected_input_device == UMIK
    reported: list = []
    sut.inputDeviceOpenFailed.connect(reported.append)
    sut._keep_previous_after_failed_open(BUILT_IN, dm.InputDeviceOpenError(UMIK.name))
    assert sut.mic.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint
    assert reported == [dm.failed_open_message(UMIK.name)]


def test_MS25_load_whose_switch_fails_keeps_the_input_and_says_so(monkeypatch):
    """MS25: A load whose recorded microphone is listed but cannot be opened keeps the current
    input (selected and saved) and its warning is the failed-open message."""

    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

    monkeypatch.setattr(dm.sd, "InputStream", _StreamFailingFor({UMIK.index}))
    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.load_measurement(TapToneMeasurement(
        id=new_uuid(), timestamp="2026-01-01T00:00:00Z", peaks=[],
        measurement_name="Loaded", microphone_name=UMIK.name, microphone_uid=UMIK.fingerprint))
    assert sut.mic.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint
    assert sut.microphone_warning == dm.failed_open_message(UMIK.name)


# MARK: - Python only: PortAudio's device numbering and re-initialising

def test_MS26_renumbered_device_keeps_its_selection_with_the_fresh_index():
    """MS26 (Python only): PortAudio renumbers devices when it is re-initialised; a selected device
    still present takes its fresh index (the stream is opened by index)."""
    sut = _make_sut(saved=BUILT_IN)
    listed = [AudioDevice(name=UMIK.name, index=0, sample_rate=48000),
              AudioDevice(name=BLACK_HOLE.name, index=1, sample_rate=48000),
              AudioDevice(name=BUILT_IN.name, index=2, sample_rate=48000)]
    sut.apply_input_device_list(listed, BUILT_IN.fingerprint)
    assert sut.selected_input_device.index == 2
    sut.apply_input_device_list(listed[1:2] + [AudioDevice(name=BUILT_IN.name, index=1,
                                                           sample_rate=48000)],
                                BUILT_IN.fingerprint)
    assert sut.selected_input_device == BUILT_IN
    assert sut.selected_input_device.index == 1


def test_MS27_portaudio_is_not_terminated_while_a_close_is_pending(monkeypatch):
    """MS27 (Python only): terminating PortAudio waits for every stream, so it is not done while a
    timed-out stream close is still pending."""
    import threading

    calls: list = []
    monkeypatch.setattr(dm.sd, "_terminate", lambda: calls.append("terminate"))
    monkeypatch.setattr(dm.sd, "_initialize", lambda: calls.append("initialize"))
    sut = _make_sut(saved=BUILT_IN)
    stuck = threading.Event()
    pending = threading.Thread(target=stuck.wait, daemon=True)
    pending.start()
    sut._pending_stream_close = pending
    try:
        assert sut.terminate_and_reinitialize_portaudio() is False
        assert calls == []
    finally:
        stuck.set()
        pending.join()
    assert sut.terminate_and_reinitialize_portaudio() is True
    assert calls == ["terminate", "initialize"]


def test_MS28_a_failed_watchdog_restart_retries():
    """MS28 (Python only): a watchdog restart that cannot open the device is a failed attempt and
    retries, as Swift's recovery does when start() throws — not a reported success."""
    sut = _make_sut(saved=BUILT_IN)
    attempts: list = []

    def failing_reinitialize():
        raise dm.InputDeviceOpenError(BUILT_IN.name)

    sut.reinitialize_portaudio = failing_reinitialize
    sut._attempt_watchdog_recovery = lambda: attempts.append("retry")
    sut._is_recovering = True
    sut._do_watchdog_restart()
    assert attempts == ["retry"]
    assert sut._is_recovering is True


# MARK: - The device opened is the device selected

class _StreamOn:
    """An InputStream stand-in that records the index it was opened on and whether it was closed."""

    samplerate = 48000
    opened: list = []

    def __init__(self, **kwargs):
        self.device = kwargs.get("device")
        self.closed = False
        _StreamOn.opened.append(self)

    def start(self):
        pass

    def close(self):
        self.closed = True


def test_MS32_a_stale_index_never_opens_another_device(monkeypatch):
    """MS32: PortAudio renumbered its devices, so the index a listed device carries now belongs to
    another device. Switching to the listed device does not leave the stream on that other
    device: the stream is closed, the previous device stays selected and saved, and the failure
    is reported."""
    _StreamOn.opened = []
    monkeypatch.setattr(dm.sd, "InputStream", _StreamOn)
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    # The UMIK's index (3) now belongs to BlackHole; the list the UMIK entry came from is stale.
    moved = AudioDevice(name=BLACK_HOLE.name, index=UMIK.index, sample_rate=48000)
    monkeypatch.setattr(dm.sd, "query_devices", _device_table(BUILT_IN, moved))

    with pytest.raises(dm.InputDeviceOpenError):
        sut.set_device(UMIK)

    on_umik_index = [s for s in _StreamOn.opened if s.device == UMIK.index]
    assert on_umik_index and all(s.closed for s in on_umik_index), \
        "REGRESSION: a stream was left open on another device's index"
    assert sut.selected_input_device == BUILT_IN
    assert _saved() == BUILT_IN.fingerprint


def test_MS33_the_index_of_the_selected_device_opens(monkeypatch):
    """MS33: With the list current, the device at the index is the device selected, and it opens."""
    _StreamOn.opened = []
    monkeypatch.setattr(dm.sd, "InputStream", _StreamOn)
    sut = _make_sut(saved=BUILT_IN)
    sut.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint)
    sut.set_device(UMIK)
    assert sut.selected_input_device == UMIK
    assert _StreamOn.opened[-1].device == UMIK.index and not _StreamOn.opened[-1].closed


def test_unreadable_calibrations_are_kept_aside_and_not_written_over(qapp):
    """The stored calibrations cannot be read: they are moved to a key of their own, the list starts
    empty, and a later save leaves them as they were. Mirrors Swift's test of the same."""
    from guitar_tap.models.microphone_calibration import CalibrationStorage, MicrophoneCalibration

    s = CalibrationStorage._s()

    def kept_keys() -> list[str]:
        return [k for k in s.allKeys() if k.startswith(f"{CalibrationStorage._STORAGE_KEY}-unreadable-")]

    for k in kept_keys():
        s.remove(k)
    damaged = json.dumps([{"id": "not-a-uuid", "name": "Room"}])
    s.setValue(CalibrationStorage._STORAGE_KEY, damaged)

    assert CalibrationStorage.load_all() == []
    kept = kept_keys()
    assert len(kept) == 1 and s.value(kept[0]) == damaged, "kept as it was"

    CalibrationStorage.save(MicrophoneCalibration(
        id=new_uuid(), name="Room", sensitivity_factor=None, reference_level=None,
        correction_points=[], import_date="2026-01-01T00:00:00Z"))
    assert len(CalibrationStorage.load_all()) == 1, "a new list is written"
    assert s.value(kept[0]) == damaged, "and the kept one is not touched"
    for k in kept_keys():
        s.remove(k)
    for c in CalibrationStorage.load_all():
        CalibrationStorage.delete(c)


# MARK: - Windows: the inputs listed (Python only — no other edition enumerates Windows' host APIs)

def _dev(index: int, name: str, api: int, api_name: "str | None") -> dict:
    d = {"index": index, "name": name, "hostapi": api, "max_input_channels": 2, "default_samplerate": 48000.0}
    if api_name is not None:
        d["_hostapi_name"] = api_name
    return d


def test_windows_lists_one_api_and_never_wdm_ks(monkeypatch):
    """WASAPI's inputs only: the same microphones under MME and DirectSound, and WDM-KS's capture pins
    ("PC Speaker …", "Microphone Array 1 ()"), are not listed."""
    from guitar_tap.models.audio_device import filter_input_devices
    monkeypatch.setattr("platform.system", lambda: "Windows")
    raw = [
        _dev(0, "Microphone (Realtek HD Audio Mic input)", 0, "MME"),
        _dev(1, "Microphone (Realtek HD Audio Mic input)", 1, "Windows DirectSound"),
        _dev(2, "Microphone (Realtek HD Audio Mic input)", 2, "Windows WASAPI"),
        _dev(3, "PC Speaker (Realtek HD Audio output with SST)", 3, "Windows WDM-KS"),
        _dev(4, "Microphone Array 1 ()", 3, "Windows WDM-KS"),
    ]
    assert [d["index"] for d in filter_input_devices(raw)] == [2]


def test_windows_never_lists_wdm_ks_when_no_api_is_preferred(monkeypatch):
    """With none of WASAPI, DirectSound or MME present, WDM-KS is still not listed."""
    from guitar_tap.models.audio_device import filter_input_devices
    monkeypatch.setattr("platform.system", lambda: "Windows")
    raw = [
        _dev(3, "PC Speaker (Realtek HD Audio output with SST)", 3, "Windows WDM-KS"),
        _dev(4, "Microphone Array 1 ()", 3, "Windows WDM-KS"),
        _dev(5, "Microphone (USB)", 5, "ASIO"),
    ]
    assert [d["index"] for d in filter_input_devices(raw)] == [5]
