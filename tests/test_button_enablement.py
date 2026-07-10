# @parity test/button-enablement
"""
Truth-table tests for Pause / New Tap / Cancel button enablement rules.

Mirror of GuitarTapTests/ButtonEnablementTests.swift.

The rule is a small pure function of the analyzer's published state plus a
few view-level inputs (fft running, comparison mode, ready-for-detection).
We mirror the rule here as a pure function and exercise it across the state
combinations that occur in the app.  If the view's rule changes, change this
function — and the Swift mirror — together with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from models.measurement_type import MeasurementType
from models.material_tap_phase import MaterialTapPhase


@dataclass
class ButtonState:
    is_detecting: bool
    is_detection_paused: bool
    is_measurement_complete: bool
    is_ready_for_detection: bool = True
    fft_is_running: bool = True
    display_mode_is_comparison: bool = False
    measurement_type: MeasurementType = MeasurementType.GENERIC
    material_tap_phase: MaterialTapPhase = MaterialTapPhase.NOT_STARTED
    current_tap_count: int = 0
    number_of_taps: int = 1


@dataclass
class ButtonOutput:
    pause_enabled: bool
    new_tap_disabled: bool
    cancel_enabled: bool


def button_rule(s: ButtonState) -> ButtonOutput:
    """Pure-function mirror of the Swift view's button rule.

    Keep this aligned with:
      - TapToneAnalysisView.swift: isInReviewPhase, pauseResumeButtonEnabled,
        newTapButtonDisabled, cancelButtonEnabled
      - GuitarTapTests/ButtonEnablementTests.swift: buttonRule(_)
    """
    is_guitar = s.measurement_type.is_guitar

    is_in_review_phase = (
        s.material_tap_phase in (
            MaterialTapPhase.REVIEWING_LONGITUDINAL,
            MaterialTapPhase.REVIEWING_CROSS,
            MaterialTapPhase.REVIEWING_FLC,
        )
        and not is_guitar
    )

    # New Tap starts a fresh measurement, so it's enabled only once one is complete (every
    # type-switch auto-arms into capturing — no disarmed idle state). Cancel restarts,
    # offered during a review phase (as "Redo") or an active multi-step sequence
    # (multi-tap or multi-phase = plate). Pause/Resume: review, detecting, or paused.
    if is_guitar:
        active = s.is_detecting or s.is_detection_paused
    else:
        active = (
            s.material_tap_phase != MaterialTapPhase.NOT_STARTED
            and not s.is_measurement_complete
        )
    multi_step = s.number_of_taps > 1 or s.measurement_type == MeasurementType.PLATE
    in_active_multi_step = active and multi_step

    if is_in_review_phase:
        pause_enabled = True
    else:
        pause_enabled = s.is_detecting or s.is_detection_paused

    if s.display_mode_is_comparison:
        new_tap_disabled = False
    elif not (s.fft_is_running and s.is_ready_for_detection):
        new_tap_disabled = True
    else:
        new_tap_disabled = not s.is_measurement_complete

    cancel_enabled = is_in_review_phase or in_active_multi_step

    return ButtonOutput(
        pause_enabled=pause_enabled,
        new_tap_disabled=new_tap_disabled,
        cancel_enabled=cancel_enabled,
    )


class TestButtonEnablement:
    """Python parity for Swift ButtonEnablementTests."""

    def test_B1_guitar_idle_all_disabled(self):
        s = ButtonState(is_detecting=False, is_detection_paused=False, is_measurement_complete=False)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=False, new_tap_disabled=True, cancel_enabled=False
        )

    def test_B2_guitar_single_tap_listening_pause_only(self):
        s = ButtonState(is_detecting=True, is_detection_paused=False, is_measurement_complete=False,
                        number_of_taps=1)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=False
        )

    def test_B3_guitar_single_tap_complete(self):
        s = ButtonState(is_detecting=False, is_detection_paused=False, is_measurement_complete=True,
                        number_of_taps=1)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=False, new_tap_disabled=False, cancel_enabled=False
        )

    def test_B4_guitar_impossible_state_lights_both_new_tap_and_pause(self):
        """StateInvariants forbids (detecting && complete); New Tap keys off complete and
        Pause off detecting, so this contradictory state lights up BOTH."""
        s = ButtonState(is_detecting=True, is_detection_paused=False, is_measurement_complete=True)
        out = button_rule(s)
        assert out.new_tap_disabled is False  # complete -> New Tap enabled
        assert out.pause_enabled is True       # detecting -> Pause enabled
        assert out.cancel_enabled is False

    def test_B5_guitar_mid_multi_tap(self):
        s = ButtonState(is_detecting=True, is_detection_paused=False, is_measurement_complete=False,
                        current_tap_count=1, number_of_taps=3)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B6_guitar_multi_tap_paused_cancel_still_enabled(self):
        s = ButtonState(is_detecting=False, is_detection_paused=True, is_measurement_complete=False,
                        current_tap_count=1, number_of_taps=3)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B7_plate_review_new_tap_disabled_cancel_pause_enabled(self):
        s = ButtonState(is_detecting=False, is_detection_paused=False, is_measurement_complete=False,
                        measurement_type=MeasurementType.PLATE,
                        material_tap_phase=MaterialTapPhase.REVIEWING_LONGITUDINAL)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B8_plate_capturing_new_tap_disabled_cancel_pause_enabled(self):
        s = ButtonState(is_detecting=True, is_detection_paused=False, is_measurement_complete=False,
                        measurement_type=MeasurementType.PLATE,
                        material_tap_phase=MaterialTapPhase.CAPTURING_LONGITUDINAL)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B9_fft_not_running_new_tap_disabled(self):
        s = ButtonState(is_detecting=False, is_detection_paused=False, is_measurement_complete=True,
                        fft_is_running=False)
        assert button_rule(s).new_tap_disabled is True

    def test_B10_comparison_mode_new_tap_enabled(self):
        s = ButtonState(is_detecting=False, is_detection_paused=False, is_measurement_complete=False,
                        display_mode_is_comparison=True)
        assert button_rule(s).new_tap_disabled is False

    def test_B11_brace_single_tap_capturing_pause_only(self):
        # Brace is single-phase; a 1-tap brace is not multi-step (like single-tap guitar):
        # not complete -> New Tap disabled; Pause on (threshold-setting); Cancel disabled.
        s = ButtonState(is_detecting=True, is_detection_paused=False, is_measurement_complete=False,
                        measurement_type=MeasurementType.BRACE,
                        material_tap_phase=MaterialTapPhase.CAPTURING_LONGITUDINAL,
                        number_of_taps=1)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=False
        )

    def test_B12_brace_multi_tap_capturing_cancel_enabled(self):
        # Multi-tap makes a brace multi-step: New Tap disabled, Cancel (restart) enabled.
        s = ButtonState(is_detecting=True, is_detection_paused=False, is_measurement_complete=False,
                        measurement_type=MeasurementType.BRACE,
                        material_tap_phase=MaterialTapPhase.CAPTURING_LONGITUDINAL,
                        number_of_taps=3)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )
