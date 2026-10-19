# @parity test/buffer-watchdog
"""
The buffer watchdog's tick and recovery, against the shared cases in buffer-watchdog.json (BW1-BW14), the
same as Swift and the web: the start-up grace, the guards, a recovery for no buffers or for buffers with no
signal, the backoff between restarts, giving up while still watching, a restart that observes no signal, a
failed restart retrying, and a healthy tick clearing it all. The engine runs on a wall clock moved by hand,
with a stand-in for the recovery's restart; the tick runs at each whole second, as the 1 s timer does.

Mirrors: GuitarTapTests/BufferWatchdogTests.swift · test/buffer-watchdog.test.ts
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from audio_clock_feed import ManualWallClock  # noqa: E402

from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "buffer-watchdog.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

STEP = 0.5  # exact in binary, so every time the cases reach is exact in every edition


class _Run:
    """One case's engine, clock and restart stand-in."""

    def __init__(self) -> None:
        self.clock = ManualWallClock()
        self.mic = RealtimeFFTAnalyzer.for_testing()
        self.mic.wall_clock = self.clock
        self.restart_fails = False
        self.restart_times: list[float] = []
        self.mic.watchdog_restart = self._restart
        # The test host may not be authorized for the microphone (a CI runner is not).
        self.mic.microphone_authorized = lambda: True

    def _restart(self) -> None:
        """The stand-in for reopening the device: on success the stream is open again (closing it
        marked the engine stopped); the recovery re-arms the watchdog itself after it."""
        self.restart_times.append(self.clock.now())
        if self.restart_fails:
            raise OSError("the stand-in restart failed")
        self.mic.is_stopped = False

    def run(self, seconds: float, carried: str) -> None:
        for _ in range(round(seconds / STEP)):
            self.clock.advance(STEP)
            if carried != "none":
                self.mic._last_buffer_time = self.clock.now()
            if carried == "signal":
                self.mic._last_signal_time = self.clock.now()
            if self.clock.now() % 1 == 0:
                self.mic._check_buffer_watchdog()

    def check(self, fields: dict, case_id: str) -> None:
        mic = self.mic
        for field, want in fields.items():
            msg = f"{case_id} {field}"
            if field == "attempts":
                assert mic._watchdog_recovery_attempts == want, msg
            elif field == "recovering":
                assert mic._is_recovering is want, msg
            elif field == "givenUp":
                assert mic._watchdog_recovery_exhausted is want, msg
            elif field == "inputDead":
                assert mic.input_appears_dead is want, msg
            elif field == "couldNotRestart":
                assert mic.input_could_not_restart is want, msg
            elif field == "inputUnavailable":
                assert mic.input_unavailable is want, msg
            elif field == "notRunningMessage":
                assert mic.not_running_message == want, msg
            elif field == "inputOpen":
                assert mic.is_running is want, msg
            elif field == "permissionDenied":
                assert mic.microphone_permission_denied is want, msg
            elif field == "restarts":
                assert len(self.restart_times) == want, msg
            elif field == "restartTimes":
                assert self.restart_times == want, f"{msg}: {self.restart_times}"
            else:
                pytest.fail(f"{case_id}: unknown field {field}")


@pytest.mark.parametrize("row", [r for r in DATA["cases"] if r.get("only") != "web"],
                         ids=lambda r: r["id"])
def test_buffer_watchdog(row, qapp):
    run = _Run()
    for step in row["steps"]:
        if step.get("start"):
            run.mic.is_stopped = False
            run.mic._set_running(True)
            run.mic.start_buffer_watchdog()
        elif "run" in step:
            run.run(step["run"], step["input"])
        elif "restart" in step:
            run.restart_fails = step["restart"] == "fails"
        elif step.get("authorized") is False:
            run.mic.microphone_authorized = lambda: False
        elif step.get("permissionDenied"):
            run.mic._set_microphone_permission_denied(True)
        elif step.get("playFile"):
            run.mic.is_playing_file = True
        elif step.get("stop"):
            run.mic.is_stopped = True
        elif "check" in step:
            run.check(step["check"], row["id"])
        else:
            pytest.fail(f"{row['id']}: unknown step {step}")
    run.check(row["expect"], row["id"])


def test_a_refused_permission_stops_the_recovery_reopening_the_input(qapp, monkeypatch):
    """Python's own restart (no stand-in): with Windows' microphone access turned off while
    running, the recovery's restart checks the permission first, as Swift's restarts through
    start() — the flag goes up and the device is never reopened, so the status asks for the access,
    not the connection."""
    from guitar_tap.models import realtime_fft_analyzer_engine_control as engine_control

    monkeypatch.setattr(engine_control.platform, "system", lambda: "Windows")
    monkeypatch.setattr(engine_control, "_windows_microphone_consent", lambda: ("Allow", "Deny"))
    run = _Run()
    run.mic.watchdog_restart = None
    reopened: list[bool] = []
    monkeypatch.setattr(run.mic, "reinitialize_portaudio", lambda: reopened.append(True))
    run.mic.is_stopped = False
    run.mic.start_buffer_watchdog()
    run.run(5, "signal")
    run.run(4, "none")
    assert run.mic.microphone_permission_denied is True
    assert reopened == []
