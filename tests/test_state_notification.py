# @parity test/notification
"""
A device change and the settle after it, against the shared cases in notification.json (N1-N21), the
same as Swift and the web: detection stands down and New Tap greys out — and the view is told, which
Python does with an explicit signal (``readyForDetectionChanged``), Swift with ``@Published`` and the
web with its snapshot and ``notify()``, each of which an ordinary edit can break — a live chart is
blanked, and once 3 s of audio have passed since the last change and the next frame has arrived, the
latch is re-anchored, readiness and listening come back and the status is put back.

Mirrors: GuitarTapTests/StateNotificationTests.swift · test/state-notification.test.ts
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from analyzer_steps import make_steps_analyzer, run_analyzer_step  # noqa: E402

from guitar_tap.models.measurement_type import MeasurementType  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "notification.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.fixture(autouse=True)
def _restore_settings():
    """The type and Measure FLC are global; put them back afterwards."""
    saved = (TapDisplaySettings.measurement_type(), TapDisplaySettings.measure_flc())
    yield
    TapDisplaySettings.set_measurement_type(saved[0])
    TapDisplaySettings.set_measure_flc(saved[1])


class _Run:
    """What a case's run keeps between steps."""

    def __init__(self) -> None:
        self.noted_status: str | None = None
        self.noted_peaks: list = []
        self.readiness_notified = False


def _check(fields: dict, sut, run: _Run, case_id: str) -> None:
    for field, want in fields.items():
        msg = f"{case_id} {field}"
        if field == "ready":
            assert sut.is_ready_for_detection is want, msg
        elif field == "readinessNotified":
            assert run.readiness_notified is want, msg
        elif field == "settling":
            assert sut.is_settling is want, msg
        elif field == "statusMessage":
            assert sut.status_message == want, f"{msg}: {sut.status_message}"
        elif field == "statusAsNoted":
            assert (sut.status_message == run.noted_status) is want, f"{msg}: {sut.status_message} vs {run.noted_status}"
        elif field == "statusBeforeSettleAsNoted":
            assert (sut._status_before_settle == run.noted_status) is want, f"{msg}: {sut._status_before_settle}"
        elif field == "statusIsArmedPrompt":
            assert (sut.status_message == sut._armed_prompt()) is want, msg
        elif field == "statusIsMicrophoneAccessWarning":
            assert (sut.status_message == sut.MICROPHONE_ACCESS_STATUS) is want, f"{msg}: {sut.status_message}"
        elif field == "detecting":
            assert sut.is_detecting is want, msg
        elif field == "paused":
            assert sut.is_detection_paused is want, msg
        elif field == "complete":
            assert sut.is_measurement_complete is want, msg
        elif field == "phase":
            assert sut.material_tap_phase.value == want, f"{msg}: {sut.material_tap_phase}"
        elif field == "aboveThreshold":
            assert sut.is_above_threshold is want, msg
        elif field == "hasPeaks":
            assert bool(sut.all_peaks) is want, f"{msg}: {len(sut.all_peaks)}"
        elif field == "peaksAsNoted":
            assert ([p.id for p in sut.all_peaks] == run.noted_peaks) is want, msg
        else:
            pytest.fail(f"{case_id}: unknown field {field}")


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_notification(row, qapp):
    TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
    sut = make_steps_analyzer()
    run = _Run()
    for step in row["steps"]:
        if step.get("note"):
            run.noted_status = sut.status_message
            run.noted_peaks = [p.id for p in sut.all_peaks]
        elif step.get("watchNotifications"):
            sut.readyForDetectionChanged.connect(lambda _ready: setattr(run, "readiness_notified", True))
        elif "clipping" in step:
            sut._set_clipping(step["clipping"])
        elif "inputDead" in step:
            sut._set_input_appears_dead(step["inputDead"])
        elif "couldNotRestart" in step:
            sut._set_input_could_not_restart(step["couldNotRestart"])
        elif "couldNotStart" in step:
            sut._set_input_could_not_start(step["couldNotStart"])
        elif "permissionDenied" in step:
            sut._set_microphone_permission_denied(step["permissionDenied"])
        elif "check" in step:
            _check(step["check"], sut, run, row["id"])
        else:
            assert run_analyzer_step(step, sut), f"{row['id']}: unknown step {step}"
    _check(row["expect"], sut, run, row["id"])
