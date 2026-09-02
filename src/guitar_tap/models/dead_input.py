"""Audio-liveness decisions, as pure functions.

Mirrors Swift ``GuitarTap/Models/DeadInput.swift`` and web ``src/audio/deadInput.ts``.

These live apart from the engine because the engine cannot be driven by a test: the
behaviour is gated on a monotonic clock, a Qt timer and real audio hardware, so every
rule below used to be verifiable only by reproducing a hardware failure by hand.  The
defect found on 2026-09-01 — a watchdog that stopped watching after giving up, leaving
the app deaf until relaunch even after the user fixed the microphone — is a single row
of the truth table here, and a unit test would have caught it immediately.

Calibration and incident history: hub ``docs/AUDIO-WATCHDOG-SILENT-STREAM.md``.

@parity dead-input
"""

from enum import Enum

# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------

#: RMS below which a chunk counts as carrying no signal: 1e-5 = **-100 dBFS**.
#:
#: A field calibration, not a derivation.  A dead-but-present device was measured
#: pinned at ~-100 dBFS — it does NOT deliver digital zero — while a live room reads
#: ~-70 dBFS and a UMIK-1's Air peak ~-63 dBFS.  Deliberately at the BOTTOM of that
#: range: the UMIK-1 is an unusually quiet microphone and can sit near -90 dBFS in a
#: silent room, so a mid-range threshold would call a quiet workshop a dead input and
#: restart the stream mid-measurement.  A missed detection costs one more watchdog
#: cycle; a false positive interrupts real work.
DEAD_INPUT_RMS_THRESHOLD = 1e-5

#: Seconds with NO chunks arriving before the I/O counts as wedged.
BUFFER_DELIVERY_TIMEOUT = 2.5

#: Seconds with chunks but NO signal before the input counts as dead.  Much longer
#: than the delivery timeout: this one infers from content, a recorded incident
#: persisted for minutes, and there is real cost in fighting a user who has
#: legitimately muted their input.
DEAD_INPUT_DWELL = 15.0


def chunk_carries_signal(rms: float) -> bool:
    """True when a chunk carries enough level to prove the stream is alive."""
    return rms > DEAD_INPUT_RMS_THRESHOLD


# ---------------------------------------------------------------------------
# Watchdog decision
# ---------------------------------------------------------------------------

class WatchdogDecision(Enum):
    """What a single watchdog tick concludes about the input."""

    #: Signal is flowing: clear any warning, reset the attempt streak and the latch.
    HEALTHY = "healthy"
    #: Chunks stopped arriving at all — recover.
    STARVED = "starved"
    #: Chunks arriving but carrying nothing — warn and recover.
    DEAD_INPUT = "dead_input"
    #: Still dead and out of restart attempts: keep warning, attempt nothing.  The
    #: tick must keep running so the warning clears the moment signal returns.
    DEAD_INPUT_EXHAUSTED = "dead_input_exhausted"


def watchdog_decision(
    now: float,
    last_buffer_time: float,
    last_signal_time: float,
    recovery_exhausted: bool,
    silence_threshold: float = BUFFER_DELIVERY_TIMEOUT,
    dead_input_threshold: float = DEAD_INPUT_DWELL,
) -> WatchdogDecision:
    """Decide what a watchdog tick should do.

    Args:
        now: Monotonic now.
        last_buffer_time: Monotonic stamp of the last chunk to ARRIVE, whatever it held.
        last_signal_time: Monotonic stamp of the last chunk to carry SIGNAL.
        recovery_exhausted: Whether restart attempts have been used up.
        silence_threshold: Seconds with no chunks before the I/O counts as wedged.
        dead_input_threshold: Seconds with no signal before the input counts as dead.
    """
    dead = (now - last_signal_time) > dead_input_threshold

    # Out of attempts: never restart, but still report the state so the warning holds
    # while it is true and clears the instant signal returns.
    if recovery_exhausted:
        return WatchdogDecision.DEAD_INPUT_EXHAUSTED if dead else WatchdogDecision.HEALTHY

    # Starvation first: no chunks at all is the more fundamental failure, and a
    # starved stream is trivially also signal-less.
    if (now - last_buffer_time) > silence_threshold:
        return WatchdogDecision.STARVED
    return WatchdogDecision.DEAD_INPUT if dead else WatchdogDecision.HEALTHY
