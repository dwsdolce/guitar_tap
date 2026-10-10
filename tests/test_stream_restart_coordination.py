# @parity none
"""
How the PortAudio stream is restarted after a close hangs, and how the watchdog's recovery and the hot-plug
refresh share the stream. Python only: PortAudio must be re-initialised to see device changes, and
terminating it while a stream close is stuck waits forever.

SR1–SR3: a re-initialise skipped for a pending close is owed, and asked for again once no close is pending —
when the stuck close finishes, or on a watchdog tick.
SR4–SR6: the recovery follows Swift's ordering — it closes the stream when it schedules its restart; a refresh
while the restart is pending only updates the selection; the restart opens the selected device at its rate.
SR7: a route change's restore, three seconds later, finds no stream when the microphone has been released
meanwhile — Swift's analyzer always exists, Python's can be gone — and does nothing.
"""

from __future__ import annotations

import os
import sys
import threading

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
from guitar_tap.views.utilities.tap_settings_view import AppSettings

BUILT_IN = AudioDevice(name="MacBook Pro Microphone", index=1, sample_rate=44100)
UMIK = AudioDevice(name="UMIK-1", index=3, sample_rate=48000)


class _FakeStream:
    """An InputStream stand-in that runs at the rate it was opened with."""

    def __init__(self, samplerate=48000, **_kwargs):
        self.samplerate = samplerate

    def start(self):
        pass


class _StuckStream:
    """A stream whose abort blocks until released — a close that outlives its timeout."""

    def __init__(self):
        self.release = threading.Event()

    def abort(self):
        self.release.wait()

    def close(self):
        pass


def _mic() -> RealtimeFFTAnalyzer:
    AppSettings.set_audio_device(BUILT_IN)
    return RealtimeFFTAnalyzer.for_testing()


# MARK: - A skipped re-initialise is retried

def test_SR1_owed_reinit_waits_for_the_pending_close():
    """SR1: an owed re-initialise is not asked for while the close is still pending, and is asked for
    once it is not."""
    mic = _mic()
    asked: list = []
    mic._on_devices_changed = lambda: asked.append("refresh")
    stuck = threading.Event()
    pending = threading.Thread(target=stuck.wait, daemon=True)
    pending.start()
    mic._pending_stream_close = pending
    mic._portaudio_reinit_owed = True
    assert mic._retry_owed_reinit() is False
    assert asked == []
    stuck.set()
    pending.join()
    assert mic._retry_owed_reinit() is True
    assert asked == ["refresh"]


def test_SR2_a_stuck_close_that_finishes_asks_for_the_skipped_reinit(monkeypatch):
    """SR2: a close that timed out makes the re-initialise wait; when it finally finishes, it asks for
    the device refresh that re-initialises PortAudio."""
    terminated: list = []
    monkeypatch.setattr(dm.sd, "_terminate", lambda: terminated.append("terminate"))
    monkeypatch.setattr(dm.sd, "_initialize", lambda: None)
    mic = _mic()
    asked: list = []
    mic._on_devices_changed = lambda: asked.append("refresh")
    stream = _StuckStream()
    mic.stream = stream
    mic._close_stream_only()                      # times out after 2 s; the close keeps running
    pending = mic._pending_stream_close
    assert pending is not None and pending.is_alive()
    assert mic.terminate_and_reinitialize_portaudio() is False
    assert terminated == []
    assert mic._portaudio_reinit_owed is True
    stream.release.set()
    pending.join(timeout=5)
    assert asked == ["refresh"]
    assert mic._pending_stream_close is None


def test_SR3_the_watchdog_tick_retries_an_owed_reinit():
    """SR3: the watchdog's tick asks for an owed re-initialise when no close is pending — the fallback
    if the stuck close's own request was lost."""
    mic = _mic()
    asked: list = []
    mic._on_devices_changed = lambda: asked.append("refresh")
    mic._portaudio_reinit_owed = True
    mic._check_buffer_watchdog()
    assert asked == ["refresh"]


# MARK: - The recovery follows Swift's ordering

def test_SR4_scheduling_a_recovery_closes_the_stream(monkeypatch):
    """SR4: scheduling a recovery restart closes the stream at once, as Swift's recovery stops the
    engine; the restart is scheduled."""
    from PySide6 import QtCore

    mic = _mic()
    events: list = []
    monkeypatch.setattr(mic, "_close_stream_only", lambda: events.append("close"))
    monkeypatch.setattr(QtCore.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: events.append("restart scheduled")))
    mic._is_recovering = True
    mic._attempt_watchdog_recovery()
    assert events == ["close", "restart scheduled"]


def test_SR5_a_refresh_during_a_pending_restart_only_updates_the_selection(monkeypatch):
    """SR5: a hot-plug refresh while a watchdog restart is pending selects the new device but opens no
    stream — the pending restart opens it."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    AppSettings.set_audio_device(BUILT_IN)
    sut = TapToneAnalyzer.for_testing()
    sut.mic.apply_input_device_list([BUILT_IN], BUILT_IN.fingerprint)
    opened: list = []
    monkeypatch.setattr(sut, "set_device", lambda device: opened.append(device))
    monkeypatch.setattr(sut.mic, "_close_stream_only", lambda: None)
    monkeypatch.setattr(sut.mic, "terminate_and_reinitialize_portaudio", lambda: True)
    monkeypatch.setattr(sut.mic, "load_available_input_devices",
                        lambda: sut.mic.apply_input_device_list([BUILT_IN, UMIK], BUILT_IN.fingerprint))
    sut.mic._is_recovering = True
    sut._on_devices_refreshed_impl()
    assert sut.mic.selected_input_device == UMIK
    assert opened == []


def test_SR6_the_restart_opens_the_selected_device_at_its_rate(monkeypatch):
    """SR6: the watchdog's restart opens the selected device — changed by a refresh while it was
    pending — at that device's rate, and reports the reopen so the analyzer re-reads it."""
    monkeypatch.setattr(dm.sd, "_terminate", lambda: None)
    monkeypatch.setattr(dm.sd, "_initialize", lambda: None)
    monkeypatch.setattr(dm.sd, "InputStream", _FakeStream)
    mic = _mic()
    mic._selected_input_device = UMIK
    mic.rate = 44100
    monkeypatch.setattr(mic, "_listed_device", lambda fingerprint: UMIK)
    reopened: list = []
    mic._on_stream_reopened = lambda: reopened.append(mic.rate)
    mic.reinitialize_portaudio()
    assert mic.device_index == UMIK.index
    assert mic.rate == 48000
    assert reopened == [48000]


def test_SR7_the_route_change_restore_does_nothing_once_the_microphone_is_released():
    """SR7: the restore a route change schedules returns quietly when, by the time it runs, the analyzer
    has no microphone — as Swift's returns when the stream is not running."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    sut = TapToneAnalyzer()
    sut.mic = None
    before = sut.is_detecting
    sut._restore_detection_after_route_change(True, True)
    assert sut.is_detecting == before
