"""
The Pause / New Tap / Cancel enablement rule — a pure function of the analyzer state,
shared by the tap-tone analysis view and the button-enablement test.

Mirrors Swift ``buttonRule`` (Models/ButtonEnablement.swift) and web ``buttonRule``
(state/buttonEnablement.ts).  If this rule changes, update the B1–B13 truth table on all
three platforms.

The rule used to live inline in ``_update_tap_buttons``, with a second copy in the test
file that the test asserted against — so the test could pass while the view drifted, which
is the one thing it existed to prevent.  One implementation, exercised by both.

@parity state/button-enablement  tests=test/button-enablement
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis_display_mode import AnalysisDisplayMode
from .detection_state import DetectionState
from .material_tap_phase import MaterialTapPhase
from .measurement_type import MeasurementType


@dataclass
class ButtonState:
    """Input state for the button rule — mirrors the fields the view reads."""

    # Whether the detector is listening, paused mid-sequence, or neither.
    #
    # One value rather than a detecting/paused boolean pair: the pair could express
    # "detecting AND paused", which the analyzer can no longer represent, so a fixture
    # built from two booleans would encode a contract the app no longer has.
    detection_state: DetectionState
    is_measurement_complete: bool
    # What the spectrum is showing. REQUIRED, and the mode itself rather than a boolean:
    # the rule reads the analyzer's display mode, so a defaulted boolean silently answers
    # for a state the caller never supplied — which is how New Tap came out DISABLED
    # during a comparison in web, trapping the user in it with no way back (#17 F24).
    display_mode: AnalysisDisplayMode
    is_ready_for_detection: bool = True
    fft_is_running: bool = True
    measurement_type: MeasurementType = MeasurementType.GENERIC
    material_tap_phase: MaterialTapPhase = MaterialTapPhase.NOT_STARTED
    number_of_taps: int = 1


@dataclass
class ButtonOutput:
    """Computed result of the button rule."""

    pause_enabled: bool
    new_tap_disabled: bool
    cancel_enabled: bool


def button_rule(s: ButtonState) -> ButtonOutput:
    """Compute the Pause / New Tap / Cancel enablement triple from the analyzer state."""
    is_guitar = s.measurement_type.is_guitar

    is_in_review_phase = (
        s.material_tap_phase in (
            MaterialTapPhase.REVIEWING_LONGITUDINAL,
            MaterialTapPhase.REVIEWING_CROSS,
            MaterialTapPhase.REVIEWING_FLC,
        )
        and not is_guitar
    )

    # A sequence is "in flight" when the analyzer is working toward a measurement: for
    # guitar, detecting or paused; for material, past NOT_STARTED and not complete. New Tap
    # is disabled while in flight and enabled otherwise (idle OR complete) — the honest
    # predicate, replacing the old `not is_measurement_complete` proxy that wrongly locked
    # New Tap in the disarmed-idle state the Dump Capture Audio folder guard can produce (§4b).
    # Cancel restarts, offered during a review phase (as "Redo") or an active multi-step
    # sequence (multi-tap or multi-phase = plate; brace is single-phase).
    is_detecting = s.detection_state is DetectionState.LISTENING
    is_detection_paused = s.detection_state is DetectionState.PAUSED
    if is_guitar:
        sequence_active = is_detecting or is_detection_paused
    else:
        sequence_active = (
            s.material_tap_phase != MaterialTapPhase.NOT_STARTED
            and not s.is_measurement_complete
        )
    multi_step = s.number_of_taps > 1 or s.measurement_type == MeasurementType.PLATE
    in_active_multi_step = sequence_active and multi_step

    if is_in_review_phase:
        pause_enabled = True
    else:
        pause_enabled = is_detecting or is_detection_paused

    if s.display_mode == AnalysisDisplayMode.COMPARISON:
        new_tap_disabled = False
    elif not (s.fft_is_running and s.is_ready_for_detection):
        new_tap_disabled = True
    else:
        new_tap_disabled = sequence_active

    cancel_enabled = is_in_review_phase or in_active_multi_step

    return ButtonOutput(
        pause_enabled=pause_enabled,
        new_tap_disabled=new_tap_disabled,
        cancel_enabled=cancel_enabled,
    )
