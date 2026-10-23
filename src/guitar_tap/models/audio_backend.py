# @parity none — Python-only: sounddevice starts PortAudio as it is imported, and the import fails where PortAudio cannot start; Swift and the web have no import step that can fail
"""
``sounddevice``, loaded once for every module that uses it, so the app starts when PortAudio cannot.

``sounddevice`` starts PortAudio in the last statement of its own module. Where PortAudio cannot
start — on Linux, no sound server to reach — that statement raises ``PortAudioError`` and a plain
``import sounddevice`` fails, taking every module that imports it, and the app, with it. Everything
in the module is defined before that statement, so the module is loaded here and a failed start is
caught: the module is complete, with PortAudio not started. The input is then unavailable, as in
Swift and the web — no devices are listed, and a start raises ``PortAudioError``, which the
analyzer reports as "Audio input unavailable" — and PortAudio is started again
(``ensure_portaudio_started``) at each start and each device listing, so a later start or listing
finds it once it can start.

Where no PortAudio library can be found or loaded at all, ``sounddevice`` fails before it defines
anything; ``sd`` is then a stand-in whose every audio call raises ``PortAudioError``, so the input
is unavailable in the same way. The Linux app carries its own PortAudio (``libportaudio.so.2``
beside the bundled Python), and ``sounddevice``, which looks only where the system keeps its
libraries, is pointed at it.

Every module takes ``sd`` from here rather than importing ``sounddevice`` itself.
"""

from __future__ import annotations

import ctypes.util
import importlib.util
import os
import sys
from types import ModuleType

#: The error PortAudio gave the last time it could not start, or ``None``.
start_error: Exception | None = None


def _bundled_portaudio() -> str | None:
    """The PortAudio library a packaged Linux app carries beside its Python, or None."""
    if not sys.platform.startswith("linux") or not getattr(sys, "frozen", False):
        return None
    path = os.path.join(getattr(sys, "_MEIPASS", ""), "libportaudio.so.2")
    return path if os.path.exists(path) else None


def _stand_in(error: Exception) -> ModuleType:
    """``sounddevice``'s stand-in when no PortAudio library can be found: the names the app uses,
    every audio call raising ``PortAudioError`` — so the input is unavailable rather than the app
    broken."""
    module = ModuleType("sounddevice")

    class PortAudioError(Exception):
        """As ``sounddevice.PortAudioError``."""

    def unavailable(*_args, **_kwargs):
        raise PortAudioError(str(error))

    module.PortAudioError = PortAudioError
    module._initialized = 0
    module._initialize = unavailable
    module._terminate = unavailable
    module._exit_handler = lambda: None
    module._lib = None
    module.query_devices = unavailable
    module.query_hostapis = unavailable
    module.InputStream = unavailable
    module.WasapiSettings = unavailable
    module.default = type("default", (), {"device": [None, None]})()
    return module


def _load() -> ModuleType:
    """Load ``sounddevice``, keeping the module when only its PortAudio start fails, and standing
    in for it when no PortAudio library can be found or loaded. Any other failure is raised, as an
    import would."""
    global start_error
    existing = sys.modules.get("sounddevice")
    if existing is not None:
        return existing
    spec = importlib.util.find_spec("sounddevice")
    if spec is None or spec.loader is None:
        raise ImportError("sounddevice is not installed")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sounddevice"] = module
    bundled = _bundled_portaudio()
    system_find_library = ctypes.util.find_library
    if bundled is not None:
        # sounddevice asks find_library for "portaudio" as it loads; the packaged app's own copy
        # answers.
        ctypes.util.find_library = (
            lambda name: bundled if name == "portaudio" else system_find_library(name))
    try:
        spec.loader.exec_module(module)
    except OSError as exc:
        # sounddevice raises OSError only as it loads PortAudio: no library found, or one that
        # cannot be loaded (a library it needs missing).
        start_error = exc
        module = _stand_in(exc)
        sys.modules["sounddevice"] = module
    except Exception as exc:
        error_type = getattr(module, "PortAudioError", None)
        start_failed = error_type is not None and isinstance(exc, error_type)
        if not start_failed or not hasattr(module, "_initialize"):
            sys.modules.pop("sounddevice", None)
            raise
        start_error = exc
    finally:
        ctypes.util.find_library = system_find_library
    return module


sd = _load()

# GT_AUDIO_BACKEND_REPORT=1: say which PortAudio library was loaded and whether it started — what
# the packaged app's start test checks.
if os.environ.get("GT_AUDIO_BACKEND_REPORT") == "1":
    print(f"audio backend: library {getattr(sd, '_libname', None)}, started {sd._initialized > 0}, "
          f"error {start_error}", flush=True)


def portaudio_started() -> bool:
    """Whether PortAudio is started."""
    return sd._initialized > 0


def ensure_portaudio_started() -> None:
    """Start PortAudio if it is not started. Raises ``sd.PortAudioError`` when it still cannot."""
    global start_error
    if portaudio_started():
        return
    try:
        sd._initialize()
    except sd.PortAudioError as exc:
        start_error = exc
        raise
    start_error = None
