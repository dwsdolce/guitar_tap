# @parity none — sounddevice starts PortAudio as it is imported (audio_backend.py); Swift and the web have no import step that can fail.
"""
The app starts when PortAudio cannot, and reports the input unavailable as Swift and the web do.

Where PortAudio cannot start (on Linux, no sound server to reach), ``import sounddevice`` raises
``PortAudioError``. Each case runs in a fresh interpreter, where PortAudio's library is wrapped so that
starting it fails, with the same error, until the case lets it start: the app's modules load, no
device is listed, a start raises ``PortAudioError`` and leaves the input unavailable, and PortAudio
starts once it can.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

SRC = os.path.join(os.path.dirname(__file__), "..", "src")

# PortAudio's start fails while state["fail"], and no PortAudio library is found while state["missing"]
# (as on Linux without libportaudio2): sounddevice opens its library through _sounddevice.ffi.dlopen,
# which the wrapper replaces.
PRELUDE = textwrap.dedent("""
    import os, sys
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, {src!r})
    import _sounddevice
    state = {{"fail": True, "missing": False}}

    class Lib:
        def __init__(self, lib): self._real = lib
        def Pa_Initialize(self): return -9999 if state["fail"] else self._real.Pa_Initialize()
        def __getattr__(self, name): return getattr(self._real, name)

    class FFI:
        def __init__(self, ffi): self._real = ffi
        def dlopen(self, name):
            if state["missing"]:
                raise OSError("PortAudio library not found")
            return Lib(self._real.dlopen(name))
        def __getattr__(self, name): return getattr(self._real, name)

    _sounddevice.ffi = FFI(_sounddevice.ffi)
""")


def run(body: str) -> str:
    script = PRELUDE.format(src=os.path.abspath(SRC)) + textwrap.dedent(body)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_a_plain_import_fails_where_portaudio_cannot_start():
    """The failure itself, as on Linux with no sound server: the wrapper reproduces it."""
    out = run("""
        try:
            import sounddevice
            print("imported")
        except Exception as exc:
            print(type(exc).__name__)
    """)
    assert out.split() == ["PortAudioError"]


def test_the_app_modules_load_and_the_input_is_unavailable():
    """The audio modules load; PortAudio is not started; no device is listed; a start raises
    PortAudioError and leaves the input unavailable, as Swift's and the web's do."""
    out = run("""
        from guitar_tap.models import audio_backend
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        from guitar_tap.models.realtime_fft_analyzer_device_management import (
            _devices_with_host_api_names)
        print("loaded", audio_backend.start_error is not None, audio_backend.portaudio_started())
        try:
            _devices_with_host_api_names()
            print("listed")
        except audio_backend.sd.PortAudioError:
            print("not-listed")
        analyzer = RealtimeFFTAnalyzer.for_testing()
        analyzer.is_for_testing = False
        analyzer._check_microphone_permission = lambda: True
        try:
            analyzer.start()
            print("started")
        except audio_backend.sd.PortAudioError:
            print("start-failed")
        print(analyzer.input_unavailable, analyzer.not_running_message)
    """)
    assert out.splitlines() == ["loaded True False", "not-listed", "start-failed",
                                "True Audio input unavailable"]


def test_portaudio_starts_once_it_can():
    """Once PortAudio can start, the next device listing starts it and lists the devices."""
    out = run("""
        from guitar_tap.models import audio_backend
        from guitar_tap.models.realtime_fft_analyzer_device_management import (
            _devices_with_host_api_names)
        state["fail"] = False
        devices = _devices_with_host_api_names()
        print(audio_backend.portaudio_started(), audio_backend.start_error is None, type(devices).__name__)
    """)
    assert out.split() == ["True", "True", "list"]


def test_with_no_portaudio_library_the_input_is_unavailable():
    """No PortAudio library at all (Linux without libportaudio2): sounddevice fails before it defines
    anything; a stand-in takes its place, the app's modules load, and a start leaves the input
    unavailable — the app is not broken."""
    out = run("""
        state["missing"] = True
        from guitar_tap.models import audio_backend
        from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer
        print("loaded", audio_backend.portaudio_started(),
              audio_backend.NO_LIBRARY in str(audio_backend.start_error))
        analyzer = RealtimeFFTAnalyzer.for_testing()
        analyzer.is_for_testing = False
        analyzer._check_microphone_permission = lambda: True
        try:
            analyzer.start()
            print("started")
        except audio_backend.sd.PortAudioError:
            print("start-failed")
        print(analyzer.input_unavailable, analyzer.not_running_message)
    """)
    assert out.splitlines() == ["loaded False True", "start-failed", "True Audio input unavailable"]
