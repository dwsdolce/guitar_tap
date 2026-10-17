# @parity model/wall-clock tests=test/audio-clock-timers
"""
WallClock — the wall clock the analyzer reads the time from and schedules on.

The analyzer's timers mostly run on the AUDIO clock, which advances with the audio processed. The
capture's safety timeout cannot: it exists for when the audio stops, and the audio clock stops with
it. It runs on this clock instead. The app uses the system's; a test passes one it moves by hand.

Mirrors Swift ``WallClock`` (Models/WallClock.swift) and web ``WallClock``.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

from PySide6 import QtCore


class WallClock(Protocol):
    """A monotonic wall clock, in seconds, with a way to run an action later on the main thread."""

    def now(self) -> float:
        """The current time, in seconds since an arbitrary fixed point."""
        ...

    def after(self, seconds: float, action: Callable[[], None]) -> None:
        """Run *action* on the main thread *seconds* from now."""
        ...


class SystemWallClock(QtCore.QObject):
    """The system's wall clock: ``time.monotonic``, scheduled with ``QTimer.singleShot`` on the main
    thread — from any thread, as Swift's ``DispatchQueue.main.asyncAfter`` is."""

    # Delivered to the main thread (this object lives there), where the timer is started.
    _afterRequest: QtCore.Signal = QtCore.Signal(int, object)

    def __init__(self) -> None:
        super().__init__()
        self._afterRequest.connect(self._start_timer)

    def now(self) -> float:
        return time.monotonic()

    def after(self, seconds: float, action: Callable[[], None]) -> None:
        self._afterRequest.emit(int(seconds * 1000), action)

    @QtCore.Slot(int, object)
    def _start_timer(self, delay_ms: int, action) -> None:
        QtCore.QTimer.singleShot(delay_ms, action)
