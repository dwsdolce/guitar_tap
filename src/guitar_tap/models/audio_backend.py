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

Every module takes ``sd`` from here rather than importing ``sounddevice`` itself.
"""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

#: The error PortAudio gave the last time it could not start, or ``None``.
start_error: Exception | None = None


def _load() -> ModuleType:
    """Load ``sounddevice``, keeping the module when only its PortAudio start fails. Any other
    failure (no PortAudio library, say) is raised, as an import would."""
    global start_error
    existing = sys.modules.get("sounddevice")
    if existing is not None:
        return existing
    spec = importlib.util.find_spec("sounddevice")
    if spec is None or spec.loader is None:
        raise ImportError("sounddevice is not installed")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sounddevice"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        error_type = getattr(module, "PortAudioError", None)
        start_failed = error_type is not None and isinstance(exc, error_type)
        if not start_failed or not hasattr(module, "_initialize"):
            sys.modules.pop("sounddevice", None)
            raise
        start_error = exc
    return module


sd = _load()


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
