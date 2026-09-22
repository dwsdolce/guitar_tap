"""
The tap detector's state, held by the tap-tone analyzer as a single value.

Mirrors Swift DetectionState enum (DetectionState.swift).

    IDLE ──────▶ LISTENING ──────▶ IDLE
                    │   ▲            (tap captured, sequence cancelled,
                    ▼   │             measurement loaded, stop)
                 PAUSED ┘
           (pause/resume, mid-sequence)

This replaced an ``is_detecting`` / ``is_detection_paused`` boolean pair.  Two booleans
can express "detecting AND paused" — a state no code path intends, which every site that
touched either flag had to avoid by hand, and which the invariant suite existed partly to
catch after the fact.  One value makes it unrepresentable.

The two booleans survive as read-only properties on the analyzer, so call sites and tests
that only *ask* the question are unchanged; only the writes moved.

NOTE — why this is its own module rather than a nested type:
  The analyzer's mixins (``tap_tone_analyzer_control.py``,
  ``tap_tone_analyzer_tap_detection.py``, ``tap_tone_analyzer_spectrum_capture.py`` …)
  need this type, and are themselves imported by ``tap_tone_analyzer.py``.  Nesting it in
  the analyzer would make that a circular import.  Same split as ``MaterialTapPhase``,
  and Swift keeps its ``DetectionState`` top-level in its own file for the same reason of
  shape, so the three editions declare it the same way.
"""

from enum import Enum


class DetectionState(Enum):
    """Whether the analyzer is listening for taps, paused mid-sequence, or neither.

    Mirrors Swift DetectionState enum (DetectionState.swift).
    """

    # MARK: - Cases

    # Not listening.  The state before a sequence starts, after a tap is captured,
    # after the measurement completes, and after a measurement is loaded for review.
    # Mirrors Swift DetectionState.idle.
    IDLE = "idle"

    # Actively listening for taps.  The audio-queue level-crossing detector is armed.
    # Mirrors Swift DetectionState.listening.
    LISTENING = "listening"

    # The sequence is paused: detection is off but the tap count and captured taps are
    # preserved, and the spectrum stays live so the user can play freely.
    # Distinct from IDLE, which discards the in-progress sequence.
    # Mirrors Swift DetectionState.paused.
    PAUSED = "paused"
