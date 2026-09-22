# @parity test/button-enablement
"""
Truth-table tests for the Pause / New Tap / Cancel button enablement rule.

Mirror of GuitarTapTests/ButtonEnablementTests.swift.

The rule is a small pure function of the analyzer's state plus a few view-level inputs
(fft running, display mode, ready-for-detection).  It is the PRODUCTION rule —
``button_rule`` in ``guitar_tap/models/button_enablement.py``, the same function
``_update_tap_buttons`` calls.  It used to be retyped here, with the module docstring
explaining that the copy and the view had to be changed together.  They did not have to be:
the test asserted against the copy, so the view was free to drift and this suite would stay
green.  Mirrors web, where App.tsx and button-enablement.test.ts both import ``buttonRule``.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.analysis_display_mode import AnalysisDisplayMode
from guitar_tap.models.button_enablement import ButtonOutput, ButtonState, button_rule
from guitar_tap.models.detection_state import DetectionState
from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType


class TestButtonEnablement:
    """Python parity for Swift ButtonEnablementTests."""

    def test_B1_guitar_disarmed_idle_new_tap_enabled(self):
        # Disarmed-idle guitar — nothing complete, nothing in flight (the Dump Capture Audio
        # folder guard declined to arm, §4b, or the sub-frame before launch auto-arm). New
        # Tap is ENABLED so the user can re-arm; Pause and Cancel stay disabled.
        s = ButtonState(detection_state=DetectionState.IDLE, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=False, new_tap_disabled=False, cancel_enabled=False
        )

    def test_B2_guitar_single_tap_listening_pause_only(self):
        s = ButtonState(detection_state=DetectionState.LISTENING, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        number_of_taps=1)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=False
        )

    def test_B3_guitar_single_tap_complete(self):
        s = ButtonState(detection_state=DetectionState.IDLE, is_measurement_complete=True, display_mode=AnalysisDisplayMode.LIVE,
                        number_of_taps=1)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=False, new_tap_disabled=False, cancel_enabled=False
        )

    def test_B4_guitar_impossible_state_new_tap_disabled_pause_on(self):
        """StateInvariants forbids (detecting && complete). New Tap now keys off "sequence in
        flight" (detecting||paused) rather than "complete", so this contradictory state
        disables New Tap (detecting) while Pause is on — no longer lighting up both."""
        s = ButtonState(detection_state=DetectionState.LISTENING, is_measurement_complete=True, display_mode=AnalysisDisplayMode.LIVE)
        out = button_rule(s)
        assert out.new_tap_disabled is True   # in flight (detecting) -> New Tap disabled
        assert out.pause_enabled is True       # detecting -> Pause enabled
        assert out.cancel_enabled is False

    def test_B5_guitar_mid_multi_tap(self):
        s = ButtonState(detection_state=DetectionState.LISTENING, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        number_of_taps=3)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B6_guitar_multi_tap_paused_cancel_still_enabled(self):
        s = ButtonState(detection_state=DetectionState.PAUSED, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        number_of_taps=3)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B7_plate_review_new_tap_disabled_cancel_pause_enabled(self):
        s = ButtonState(detection_state=DetectionState.IDLE, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        measurement_type=MeasurementType.PLATE,
                        material_tap_phase=MaterialTapPhase.REVIEWING_LONGITUDINAL)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B8_plate_capturing_new_tap_disabled_cancel_pause_enabled(self):
        s = ButtonState(detection_state=DetectionState.LISTENING, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        measurement_type=MeasurementType.PLATE,
                        material_tap_phase=MaterialTapPhase.CAPTURING_LONGITUDINAL)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )

    def test_B13_plate_disarmed_idle_new_tap_enabled(self):
        # Disarmed-idle material (plate at launch, folder guard declined to arm) — phase
        # NOT_STARTED, nothing complete, nothing in flight. New Tap ENABLED to re-arm;
        # Pause/Cancel disabled. The material counterpart of B1.
        s = ButtonState(detection_state=DetectionState.IDLE, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        measurement_type=MeasurementType.PLATE,
                        material_tap_phase=MaterialTapPhase.NOT_STARTED)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=False, new_tap_disabled=False, cancel_enabled=False
        )

    def test_B9_fft_not_running_new_tap_disabled(self):
        s = ButtonState(detection_state=DetectionState.IDLE, is_measurement_complete=True, display_mode=AnalysisDisplayMode.LIVE,
                        fft_is_running=False)
        assert button_rule(s).new_tap_disabled is True

    def test_B10_comparison_mode_new_tap_enabled(self):
        s = ButtonState(detection_state=DetectionState.IDLE, is_measurement_complete=False,
                        display_mode=AnalysisDisplayMode.COMPARISON)
        assert button_rule(s).new_tap_disabled is False

    def test_B11_brace_single_tap_capturing_pause_only(self):
        # Brace is single-phase; a 1-tap brace is not multi-step (like single-tap guitar):
        # not complete -> New Tap disabled; Pause on (threshold-setting); Cancel disabled.
        s = ButtonState(detection_state=DetectionState.LISTENING, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        measurement_type=MeasurementType.BRACE,
                        material_tap_phase=MaterialTapPhase.CAPTURING_LONGITUDINAL,
                        number_of_taps=1)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=False
        )

    def test_B12_brace_multi_tap_capturing_cancel_enabled(self):
        # Multi-tap makes a brace multi-step: New Tap disabled, Cancel (restart) enabled.
        s = ButtonState(detection_state=DetectionState.LISTENING, is_measurement_complete=False, display_mode=AnalysisDisplayMode.LIVE,
                        measurement_type=MeasurementType.BRACE,
                        material_tap_phase=MaterialTapPhase.CAPTURING_LONGITUDINAL,
                        number_of_taps=3)
        assert button_rule(s) == ButtonOutput(
            pause_enabled=True, new_tap_disabled=True, cancel_enabled=True
        )
