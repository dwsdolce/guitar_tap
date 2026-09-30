# @parity none
"""
How the input stream is opened: on Windows, a WASAPI device is opened in RAW mode, which bypasses
the Windows audio effects that gate taps as noise; a device that refuses RAW is opened plainly.
Python only: Swift gets unprocessed input from the .measurement session mode on iOS and uses no
voice processing on macOS; the web turns off the browser's input processing.

The sounddevice and platform calls are replaced, so every case runs on any OS.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models import realtime_fft_analyzer_device_management as dm


class _Opened:
    """Records the keyword arguments of each InputStream open; refuses RAW if told to."""

    def __init__(self, refuse_raw: bool = False):
        self.calls: list[dict] = []
        self.refuse_raw = refuse_raw

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.refuse_raw and "extra_settings" in kwargs:
            raise dm.sd.PortAudioError("RAW refused")
        return object()


def _patch(monkeypatch, system: str, hostapi: str, opened: _Opened) -> None:
    monkeypatch.setattr(dm.platform, "system", lambda: system)
    monkeypatch.setattr(dm.sd, "query_devices", lambda device, kind: {"hostapi": 0})
    monkeypatch.setattr(dm.sd, "query_hostapis", lambda index: {"name": hostapi})
    monkeypatch.setattr(dm.sd, "InputStream", opened)


def _open(device_index=3):
    return dm._open_input_stream(device_index, 48000, 1024, lambda *a: None)


def test_not_windows_opens_without_raw(monkeypatch):
    opened = _Opened()
    _patch(monkeypatch, "Darwin", "Core Audio", opened)
    _open()
    assert len(opened.calls) == 1
    assert "extra_settings" not in opened.calls[0]


def test_a_windows_non_wasapi_device_opens_without_raw(monkeypatch):
    opened = _Opened()
    _patch(monkeypatch, "Windows", "MME", opened)
    _open()
    assert len(opened.calls) == 1
    assert "extra_settings" not in opened.calls[0]


def test_a_wasapi_device_opens_in_raw_mode(monkeypatch):
    opened = _Opened()
    _patch(monkeypatch, "Windows", "Windows WASAPI", opened)
    _open()
    assert len(opened.calls) == 1
    settings = opened.calls[0]["extra_settings"]
    assert settings._streaminfo.streamOption == dm.sd._lib.eStreamOptionRaw
    assert opened.calls[0]["device"] == 3 and opened.calls[0]["samplerate"] == 48000


def test_a_device_that_refuses_raw_is_opened_plainly(monkeypatch):
    opened = _Opened(refuse_raw=True)
    _patch(monkeypatch, "Windows", "Windows WASAPI", opened)
    _open()
    assert len(opened.calls) == 2
    assert "extra_settings" in opened.calls[0]
    assert "extra_settings" not in opened.calls[1]


def test_a_device_that_cannot_be_queried_is_opened_plainly(monkeypatch):
    # The plain open then reports the device's own error.
    opened = _Opened()
    _patch(monkeypatch, "Windows", "Windows WASAPI", opened)

    def unknown(device, kind):
        raise ValueError("No input device matching 3")

    monkeypatch.setattr(dm.sd, "query_devices", unknown)
    _open()
    assert len(opened.calls) == 1
    assert "extra_settings" not in opened.calls[0]


def test_a_plain_open_that_fails_raises(monkeypatch):
    def fails(**kwargs):
        raise dm.sd.PortAudioError("device unavailable")

    _patch(monkeypatch, "Darwin", "Core Audio", _Opened())
    monkeypatch.setattr(dm.sd, "InputStream", fails)
    with pytest.raises(dm.sd.PortAudioError):
        _open()
