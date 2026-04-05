"""
Phase state machine for a multi-tap material measurement sequence.

Mirrors Swift MaterialTapPhase enum (MaterialTapPhase.swift).

Accurate wood-property calculations from tap tones require separate
impulse-response captures in specific orientations.  The phases progress
linearly through a state machine managed by the tap-tone analyzer.

Plate Measurement State Machine (2 or 3 taps):

    NOT_STARTED
      └─▶ CAPTURING_LONGITUDINAL   (tap along grain)
            └─▶ WAITING_FOR_CROSS_TAP
                  └─▶ CAPTURING_CROSS          (tap across grain, plate rotated 90°)
                        ├─▶ WAITING_FOR_FLC_TAP  (if measure_flc == True)
                        │     └─▶ CAPTURING_FLC   (diagonal corner tap)
                        │           └─▶ COMPLETE
                        └─▶ COMPLETE           (if measure_flc == False)

Brace Measurement State Machine (1 tap):

    NOT_STARTED
      └─▶ CAPTURING_LONGITUDINAL
            └─▶ COMPLETE

The ``instruction`` and ``short_status`` computed properties supply UI strings
for each state so that views remain decoupled from the state logic.

NOTE — Architectural difference from Python PlateCapture.State:
  Swift uses MaterialTapPhase as a standalone top-level enum with 7 cases.
  Python's existing PlateCapture (tap_tone_analyzer_spectrum_capture.py) uses
  an inner enum State with 5 cases (IDLE, WAITING_L, WAITING_C, WAITING_FLC,
  COMPLETE) and emits UI strings via Qt signals rather than computed properties.
  This module provides the standalone Swift-equivalent type for use in contexts
  where the full Qt signal machinery is not needed (e.g. data analysis,
  serialisation, tests).
"""

from __future__ import annotations

from enum import Enum


class MaterialTapPhase(Enum):
    """The current phase of a multi-tap material measurement sequence (plate or brace).

    The analyzer drives transitions through these phases in response to detected
    tap events and gated-FFT capture completions.

    Mirrors Swift MaterialTapPhase enum (MaterialTapPhase.swift).
    """

    # MARK: - Cases

    # No tap sequence has been started yet.
    # The initial state after app launch, after a measurement is saved, or after a reset.
    # Mirrors Swift MaterialTapPhase.notStarted.
    NOT_STARTED = "Not Started"

    # A longitudinal (along-grain) gated FFT capture is actively accumulating samples.
    # Mirrors Swift MaterialTapPhase.capturingLongitudinal.
    CAPTURING_LONGITUDINAL = "Capturing Longitudinal"

    # The longitudinal capture is complete; the app is waiting for the user to
    # rotate the plate 90° and perform the cross-grain tap.
    # Mirrors Swift MaterialTapPhase.waitingForCrossTap.
    WAITING_FOR_CROSS_TAP = "Waiting for Cross-grain Tap"

    # A cross-grain gated FFT capture is actively accumulating samples.
    # Mirrors Swift MaterialTapPhase.capturingCross.
    CAPTURING_CROSS = "Capturing Cross-grain"

    # Both longitudinal and cross captures are complete; the app is waiting for the
    # optional FLC (diagonal / shear) tap.
    # Only entered when measure_flc is True.
    # Mirrors Swift MaterialTapPhase.waitingForFlcTap.
    WAITING_FOR_FLC_TAP = "Waiting for FLC Tap"

    # An FLC (diagonal) gated FFT capture is actively accumulating samples.
    # Mirrors Swift MaterialTapPhase.capturingFlc.
    CAPTURING_FLC = "Capturing FLC"

    # All required taps have been captured and processed.
    # Acoustic properties (Young's modulus, specific modulus, etc.) can now be
    # computed from the captured phase data.
    # Mirrors Swift MaterialTapPhase.complete.
    COMPLETE = "Complete"

    # MARK: - UI Strings

    @property
    def instruction(self) -> str:
        """Full instructional text appropriate for the current phase.

        Suitable for display in a full-size instructions area or tooltip.

        Mirrors Swift MaterialTapPhase.instruction.
        """
        return {
            MaterialTapPhase.NOT_STARTED:
                "Press New Tap to begin measurement",
            MaterialTapPhase.CAPTURING_LONGITUDINAL:
                "Processing longitudinal tap...",
            MaterialTapPhase.WAITING_FOR_CROSS_TAP:
                "Now rotate plate 90° and tap again for cross-grain",
            MaterialTapPhase.CAPTURING_CROSS:
                "Processing cross-grain tap...",
            MaterialTapPhase.WAITING_FOR_FLC_TAP:
                "Hold plate at the midpoint of one long edge. "
                "Tap near the opposite corner (~22% from both the end and the side)",
            MaterialTapPhase.CAPTURING_FLC:
                "Processing FLC tap...",
            MaterialTapPhase.COMPLETE:
                "Measurement complete",
        }[self]

    @property
    def short_status(self) -> str:
        """Abbreviated status string for display in compact UI elements such as the status bar.

        Mirrors Swift MaterialTapPhase.shortStatus.
        """
        return {
            MaterialTapPhase.NOT_STARTED:            "Ready",
            MaterialTapPhase.CAPTURING_LONGITUDINAL: "L tap...",
            MaterialTapPhase.WAITING_FOR_CROSS_TAP:  "Tap for C",
            MaterialTapPhase.CAPTURING_CROSS:        "C tap...",
            MaterialTapPhase.WAITING_FOR_FLC_TAP:    "Tap for FLC",
            MaterialTapPhase.CAPTURING_FLC:          "FLC tap...",
            MaterialTapPhase.COMPLETE:               "Done",
        }[self]
