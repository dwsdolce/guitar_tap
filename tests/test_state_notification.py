# @parity test/notification
"""
One contract, three mechanisms: when the model's readiness changes, the view layer is told.

Python satisfies it with an explicit signal (this file), Swift with ``@Published`` (observed via
``objectWillChange``), web by putting the field on the snapshot and calling ``notify()``. Every one
of those can be broken by an ordinary edit — drop the ``@Published``, forget to add the signal,
leave the field off the snapshot — and in Python it simply never existed, so the button row went
stale for the whole route-change settle and New Tap never greyed out (#17 F32).

These cases were first parked in ``test_wi10_qtimer_slots.py``, tagged ``@parity none``, on the
grounds that signal plumbing is PySide6-specific and has no counterpart. It does have one. The
contract is not "does Qt emit" but "does a state change reach the UI", which all three implement and
all three can break — and ``none`` is the one home where ``--check`` can never report a missing
edition. PARITY-TEST-METHOD rule 4: an "n/a" that rests on the view layer is a finding, not a
difference.

Mirrors: GuitarTapTests/StateNotificationTests.swift · test/state-notification.test.ts
"""

from __future__ import annotations

import os
import sys

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

_APP: "QtWidgets.QApplication | None" = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


def _make_sut() -> TapToneAnalyzer:
    _get_app()
    return TapToneAnalyzer()


class TestStateNotification:
    """Mirrors Swift StateNotificationTests N1-N3."""

    def test_N1_readiness_cleared_notifies_observers(self):
        sut = _make_sut()
        seen: list[bool] = []
        sut.readyForDetectionChanged.connect(seen.append)

        sut.is_ready_for_detection = False

        assert seen == [False], (
            "REGRESSION: a readiness change must reach the view layer, or New Tap stays clickable "
            "while the input is reinitialising."
        )

    def test_N2_readiness_restored_notifies_observers(self):
        sut = _make_sut()
        sut.is_ready_for_detection = False
        seen: list[bool] = []
        sut.readyForDetectionChanged.connect(seen.append)

        sut.is_ready_for_detection = True

        assert seen == [True], "restoring readiness must notify, or New Tap never re-enables"

    def test_N3_route_change_restart_clears_readiness_and_notifies(self):
        """The production path — a route-change restart stands readiness down and says so."""
        sut = _make_sut()
        seen: list[bool] = []
        sut.readyForDetectionChanged.connect(seen.append)

        sut.handle_route_change_restart()

        assert sut.is_ready_for_detection is False, (
            "a route-change restart must stand readiness down"
        )
        assert seen and seen[0] is False, "and must notify the view layer that it did"

    # N4: the settle must not throw away a result announcement. A completed measurement's status
    # ("Analysis complete! N peaks…") is not re-derivable, so the derivation declines to speak.
    def test_N4_settle_restores_a_complete_measurements_status(self):
        sut = _make_sut()
        sut.number_of_taps = 1
        sut.current_tap_count = 1
        sut.is_measurement_complete = True
        announced = "Analysis complete! 12 peaks identified (from 1 averaged taps)."

        assert sut._status_after_settle() is None, (
            "a completed measurement's status is not derivable"
        )
        assert sut._restored_status(announced) == announced, (
            "REGRESSION: the settle must PUT BACK the result announcement. Asserting only that it "
            "does not say 'Tap again' passed while the 'Audio device changed - reinitializing…' "
            "transient stayed up forever."
        )

    # N5: mid-sequence the settle reports what was captured — not the opening instruction, which is
    # what the old two-branch guess said once a tap was already in hand.
    def test_N5_settle_mid_sequence_reports_progress(self):
        from guitar_tap.models.detection_state import DetectionState

        sut = _make_sut()
        sut.number_of_taps = 3
        sut.detection_state = DetectionState.LISTENING
        sut.current_tap_count = 1

        assert sut._status_after_settle() == "Tap 1/3 captured. Tap again..."

    # N6: idle and nothing captured — "Ready".
    def test_N6_settle_idle_is_ready(self):
        assert _make_sut()._status_after_settle() == "Ready"

    # N7: a COMPLETED measurement survives a device change. The settle blanks the chart while the
    # new device's audio is not yet valid, but only when a LIVE spectrum is on screen. The old guard
    # asked display_mode == LIVE, which is still true of a finished measurement because no
    # completion path sets FROZEN — so a device change wiped the result (#17 F35).
    def test_N7_route_change_leaves_a_completed_measurement_intact(self):
        import numpy as np
        from guitar_tap.models.resonant_peak import ResonantPeak

        sut = _make_sut()
        sut.set_frozen_spectrum(np.array([100.0, 200.0]), np.array([-40.0, -50.0]))
        sut.all_peaks = [ResonantPeak(frequency=100.0, magnitude=-40.0)]
        sut.is_measurement_complete = True

        sut.handle_route_change_restart()

        assert sut.is_settling is False, (
            "a completed measurement is not a live spectrum — nothing to blank"
        )
        assert len(sut.all_peaks) == 1, (
            "REGRESSION: the settle wiped a finished measurement's peaks"
        )

    # N8: mid-sequence, with a live spectrum on screen, the settle DOES blank.
    def test_N8_route_change_blanks_a_live_spectrum(self):
        from guitar_tap.models.detection_state import DetectionState

        sut = _make_sut()
        sut.detection_state = DetectionState.LISTENING

        sut.handle_route_change_restart()

        assert sut.is_settling is True, "a live spectrum is blanked for the settle"
