# @parity diagnostics/slack-probe
"""
A diagnostic: how much time the main thread has to spare while audio runs. Off unless the environment variable
``GT_SLACK_PROBE`` is ``1``. Every 5 s it prints one line, in the same form in every edition:

- **lag** — a timer asks the main thread for a call every 5 ms; each call's lateness is the time the thread was
  busy with something else.
- **latency** — from the audio thread handing a chunk to the main thread to the main thread taking it.
- **busy time** per kind of work: the main thread's per-chunk work (``main/chunk``), the capture filling within
  it (``accumulate``), the FFT (``fft``), the work on each FFT frame (``frame``).

Mirrors Swift ``SlackProbe`` and the web's ``slackProbe``.
"""

from __future__ import annotations

import collections
import os
import threading
import time
from contextlib import contextmanager

ENABLED = os.environ.get("GT_SLACK_PROBE") == "1"

_INTERVAL = 0.005
_REPORT_EVERY = 5.0
_KINDS = ("main/chunk", "accumulate", "fft", "frame")

_lock = threading.Lock()
_samples: dict[str, list[float]] = collections.defaultdict(list)
_handovers: collections.deque[float] = collections.deque()
_chunk_period_ms = 0.0
_timer = None
_expected = 0.0
_window_start = 0.0


def now() -> float:
    return time.perf_counter()


def record(kind: str, ms: float) -> None:
    """Record one duration (ms) of a kind of work; safe from any thread."""
    if not ENABLED:
        return
    with _lock:
        _samples[kind].append(ms)


@contextmanager
def timed(kind: str):
    """Time the block and record it as ``kind``."""
    if not ENABLED:
        yield
        return
    start = now()
    try:
        yield
    finally:
        record(kind, (now() - start) * 1000)


def set_chunk_period(count: int, sample_rate: float) -> None:
    global _chunk_period_ms
    if ENABLED and sample_rate > 0:
        _chunk_period_ms = count / sample_rate * 1000


def hand_over() -> None:
    """On the audio thread, as a chunk is handed to the main thread."""
    if ENABLED:
        _handovers.append(now())


def taken() -> None:
    """On the main thread, as it takes the chunk handed over first (Qt delivers them in order)."""
    if ENABLED and _handovers:
        record("latency", (now() - _handovers.popleft()) * 1000)


def start() -> None:
    """Start the lag timer and the 5 s report, on the main thread. Does nothing when the probe is off."""
    global _timer, _expected, _window_start
    if not ENABLED or _timer is not None:
        return
    from PySide6 import QtCore

    _timer = QtCore.QTimer()
    _timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
    _timer.setInterval(int(_INTERVAL * 1000))
    _expected = now() + _INTERVAL
    _window_start = now()
    _timer.timeout.connect(_tick)
    _timer.start()


def _tick() -> None:
    global _expected, _window_start
    t = now()
    record("lag", max(0.0, (t - _expected) * 1000))
    _expected = max(_expected + _INTERVAL, t)
    if t - _window_start >= _REPORT_EVERY:
        _report(t - _window_start)
        _window_start = t


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int((len(s) - 1) * p))]


def _report(seconds: float) -> None:
    with _lock:
        window = dict(_samples)
        _samples.clear()
    lag = window.get("lag", [])
    lat = window.get("latency", [])
    parts = [
        f"⏱ slack {seconds:.1f}s: chunk {_chunk_period_ms:.2f} ms",
        f"lag p50 {_pct(lag, .5):.2f} p95 {_pct(lag, .95):.2f} p99 {_pct(lag, .99):.2f} max {max(lag, default=0):.2f}",
        f"latency p50 {_pct(lat, .5):.2f} p95 {_pct(lat, .95):.2f} max {max(lat, default=0):.2f}",
    ]
    busy = 0.0
    for kind in _KINDS:
        v = window.get(kind, [])
        total = sum(v)
        if kind != "accumulate":  # accumulate is within main/chunk
            busy += total
        parts.append(f"{kind} avg {total / len(v) if v else 0:.2f} max {max(v, default=0):.2f} n {len(v)}")
    parts.append(f"main busy {busy / (seconds * 1000) * 100:.1f}%")
    print(" | ".join(parts), flush=True)
