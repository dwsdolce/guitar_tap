# @parity test/input-level
"""
One contract, three mechanisms: an audio buffer's level is announced on the input level alone.

The level changes on every buffer, many times a second. Whatever announces it is redrawn that often, so
only the threshold meter may hear it: announced by the engine or the analyzer, every buffer would reach
every view that listens to them. The values were right all along when Swift's did that; only who was
told was wrong, so the value tests could not see it.

Swift checks ``objectWillChange`` on each object, Python which signals fire, the web which listeners and
callbacks are called. A private signal (a leading underscore) is the analyzer's own delivery path to
itself — the per-chunk level to detection — not an announcement, and is left out.

Mirrors: GuitarTapTests/InputLevelTests.swift · test/input-level.test.ts
"""

from __future__ import annotations

import time

import numpy as np
from PySide6 import QtCore, QtWidgets

from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer


def _app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _drain(app: QtWidgets.QApplication, seconds: float = 0.05) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()


def _count_public_signals(obj: QtCore.QObject, fired: list[str], label: str) -> None:
    """Connect a counter to every public signal ``obj``'s classes declare above ``QObject``'s own."""
    mo = obj.metaObject()
    for i in range(QtCore.QObject.staticMetaObject.methodCount(), mo.methodCount()):
        m = mo.method(i)
        if m.methodType() != QtCore.QMetaMethod.MethodType.Signal:
            continue
        name = bytes(m.name()).decode()
        if name.startswith("_"):
            continue
        getattr(obj, name).connect(lambda *_a, n=f"{label}.{name}": fired.append(n))


def _quiet_buffer() -> np.ndarray:
    """One 0.1 s buffer at 48 kHz of a quiet 1 kHz sine: well below any detection threshold, and far
    short of an FFT frame (65 536 samples)."""
    t = np.arange(4800) / 48000.0
    return (0.001 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)


def test_buffer_is_announced_on_the_input_level_alone():
    """IL1: a buffer, while the analyzer listens for a tap, is announced on the input level and by
    nothing else. Mirrors Swift buffer_isAnnouncedOnTheInputLevelAlone."""
    app = _app()
    TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
    sut = TapToneAnalyzer.for_testing(sample_rate=48000)
    sut.start_tap_sequence(skip_warmup=True)
    _drain(app)

    level: list[float] = []
    sut.mic.level.inputLevelChanged.connect(level.append)
    others: list[str] = []
    _count_public_signals(sut, others, "analyzer")
    _count_public_signals(sut.mic.proc_thread, others, "engine")

    sut.mic.process_raw_samples(_quiet_buffer())
    _drain(app)

    assert level, "the buffer's level must reach the input level, or the meter stands still"
    assert others == [], (
        f"REGRESSION: announced for one buffer: {sorted(set(others))} — every view listening is "
        "redrawn on every buffer")
