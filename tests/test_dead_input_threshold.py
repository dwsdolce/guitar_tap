"""Audio-liveness decisions: threshold calibration and the watchdog truth table.

@parity test/dead-input-threshold

Paired with Swift GuitarTapTests/DeadInputThresholdTests.swift and web
test/dead-input-threshold.test.ts.  All three pin the SAME table.

Why these exist: the threshold is a FIELD CALIBRATION, not a derivation.  Set it too
low and a genuinely dead stream (measured at ~-100 dBFS, NOT digital zero) is never
detected; too high and a quiet room is mistaken for a dead input and the stream is
restarted mid-measurement.  The UMIK-1 is an unusually quiet microphone and can sit
near -90 dBFS in a silent room, which is what makes the upper bound real.

Source of the numbers: the silent-input incidents of 2026-07-16 and 2026-08-21.
"""

import pytest

from guitar_tap.models.dead_input import (
    should_declare_permission_denied,
    windows_microphone_access_denied,
    BUFFER_DELIVERY_TIMEOUT,
    DEAD_INPUT_DWELL,
    DEAD_INPUT_RMS_THRESHOLD,
    WatchdogDecision,
    chunk_carries_signal,
    watchdog_decision,
)


def amp(dbfs: float) -> float:
    """Amplitude (linear RMS) for a level in dBFS."""
    return 10.0 ** (dbfs / 20.0)


# ---------------------------------------------------------------------------
# Threshold calibration
# ---------------------------------------------------------------------------

def test_digital_silence_reads_as_no_signal():
    assert not chunk_carries_signal(0.0)


def test_far_below_anything_real_reads_as_no_signal():
    assert not chunk_carries_signal(amp(-120))


def test_measured_dead_device_level_reads_as_no_signal():
    # The level a dead-but-present device was actually measured at.
    assert not chunk_carries_signal(amp(-100))


def test_quiet_umik1_in_a_silent_room_reads_as_alive():
    # The regression these tests exist for: -90 dBFS is quiet, not dead.
    assert chunk_carries_signal(amp(-90))
    assert chunk_carries_signal(amp(-95))


def test_room_floor_and_tap_read_as_alive():
    assert chunk_carries_signal(amp(-70))   # room noise floor
    assert chunk_carries_signal(amp(-63))   # UMIK-1 Air peak
    assert chunk_carries_signal(amp(-20))   # a tap


def test_keeps_at_least_10db_margin_under_the_quiet_room_level():
    # Guards against anyone "tightening" the threshold back up toward -90 dBFS.
    assert DEAD_INPUT_RMS_THRESHOLD <= amp(-100)
    assert amp(-90) / DEAD_INPUT_RMS_THRESHOLD >= 3.16


# ---------------------------------------------------------------------------
# Dwell
# ---------------------------------------------------------------------------

def test_dwell_outlasts_a_quiet_passage():
    # A short dwell would let an ordinary silent moment between taps trip the
    # watchdog.  The recorded incidents persisted for minutes, so patience is free.
    assert DEAD_INPUT_DWELL >= 10.0


def test_dwell_is_longer_than_the_delivery_timeout():
    # Content-based inference should always be more patient than the arrival-based
    # check it sits beside.
    assert DEAD_INPUT_DWELL > BUFFER_DELIVERY_TIMEOUT


# ---------------------------------------------------------------------------
# Watchdog decision truth table
# ---------------------------------------------------------------------------

NOW = 1000.0


def decide(buffers_ago: float, signal_ago: float, exhausted: bool = False) -> WatchdogDecision:
    return watchdog_decision(
        now=NOW,
        last_buffer_time=NOW - buffers_ago,
        last_signal_time=NOW - signal_ago,
        recovery_exhausted=exhausted,
    )


def test_signal_flowing_is_healthy():
    assert decide(0.02, 0.02) is WatchdogDecision.HEALTHY


def test_quiet_passage_shorter_than_the_dwell_is_still_healthy():
    # The case that must never restart the stream: a silent moment between taps.
    assert decide(0.02, DEAD_INPUT_DWELL - 1) is WatchdogDecision.HEALTHY


def test_no_buffers_at_all_is_starved():
    t = BUFFER_DELIVERY_TIMEOUT + 1
    assert decide(t, t) is WatchdogDecision.STARVED


def test_buffers_arriving_with_no_signal_is_dead_input():
    # The failure this whole mechanism exists for.
    assert decide(0.02, DEAD_INPUT_DWELL + 1) is WatchdogDecision.DEAD_INPUT


def test_starvation_outranks_dead_input():
    # A starved stream is trivially signal-less too; report the deeper failure.
    assert decide(BUFFER_DELIVERY_TIMEOUT + 1, DEAD_INPUT_DWELL + 1) is WatchdogDecision.STARVED


def test_dead_and_out_of_attempts_warns_without_restarting():
    assert decide(0.02, DEAD_INPUT_DWELL + 1, exhausted=True) is WatchdogDecision.DEAD_INPUT_EXHAUSTED


def test_signal_returning_after_exhaustion_is_healthy():
    # The regression from 2026-09-01: raising the input volume again must heal the
    # app rather than leave it deaf until relaunch.
    assert decide(0.02, 0.02, exhausted=True) is WatchdogDecision.HEALTHY


def test_exhausted_never_restarts_even_when_starved():
    d = decide(BUFFER_DELIVERY_TIMEOUT + 1, DEAD_INPUT_DWELL + 1, exhausted=True)
    assert d is WatchdogDecision.DEAD_INPUT_EXHAUSTED
    assert d is not WatchdogDecision.STARVED


# MARK: - Permission decision (mirrors Swift PermissionDecisionTests)

def test_tcc_denied_is_a_denial():
    assert should_declare_permission_denied(tcc_denied=True)


def test_authorized_is_not_a_denial_however_silent_the_input():
    # Silence on an authorized device is a dead or muted INPUT, which the dead-input watchdog
    # reports accurately and recovers from.
    assert should_declare_permission_denied(tcc_denied=False) is False


@pytest.mark.parametrize("device, desktop_apps, denied", [
    ("Allow", "Allow", False),
    ("Deny", "Allow", True),      # microphone access off for the device
    ("Allow", "Deny", True),      # "Let desktop apps access your microphone" off
    ("Deny", "Deny", True),
    (None, None, False),          # never set: Windows decides as it opens the device
    ("Allow", None, False),
])
def test_windows_consent(device, desktop_apps, denied):
    """Python only — Windows' microphone privacy settings, which no other edition runs under."""
    assert windows_microphone_access_denied(device, desktop_apps) is denied
