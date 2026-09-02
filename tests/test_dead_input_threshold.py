"""Dead-input threshold calibration.

@parity dead-input-threshold — paired with Swift GuitarTapTests/DeadInputThresholdTests.swift
and web test/dead-input-threshold.test.ts.  All three pin the SAME calibration table.

Why this test exists: the dead-input watchdog decides "the stream is dead" from a level
threshold, and that threshold is a field calibration, not a derivation.  Set it too low
and a genuinely dead stream (measured at ~-100 dBFS, NOT digital zero) is never detected;
too high and a quiet room is mistaken for a dead input and the stream is restarted
mid-measurement.  The UMIK-1 is an unusually quiet microphone and can sit near -90 dBFS
in a silent room, which is what makes the upper bound real.

Source of the numbers: hub docs/AUDIO-WATCHDOG-SILENT-STREAM.md (incidents 2026-07-16).
"""

from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

THRESHOLD = RealtimeFFTAnalyzer._DEAD_INPUT_RMS_THRESHOLD


def amp(dbfs: float) -> float:
    """Amplitude (linear RMS) for a level in dBFS."""
    return 10.0 ** (dbfs / 20.0)


def carries_signal(rms: float) -> bool:
    return rms > THRESHOLD


def test_dead_stream_carries_no_signal():
    assert not carries_signal(0.0)          # digital silence
    assert not carries_signal(amp(-120))    # far below anything real
    assert not carries_signal(amp(-100))    # the measured dead-device level


def test_quiet_umik1_in_a_silent_room_carries_signal():
    # The regression this test exists for: -90 dBFS is quiet, not dead.
    assert carries_signal(amp(-90))
    assert carries_signal(amp(-95))


def test_room_floor_and_tap_carry_signal():
    assert carries_signal(amp(-70))         # room noise floor
    assert carries_signal(amp(-63))         # UMIK-1 Air peak
    assert carries_signal(amp(-20))         # a tap


def test_keeps_at_least_10db_margin_under_the_quiet_room_level():
    # Guards against someone "tightening" the threshold back up toward -90 dBFS.
    assert THRESHOLD <= amp(-100)
    assert amp(-90) / THRESHOLD >= 3.16


def test_dwell_is_long_enough_to_outlast_a_quiet_passage():
    # A short dwell would let an ordinary silent moment between taps trip the watchdog.
    sut = RealtimeFFTAnalyzer.for_testing()
    assert sut._watchdog_dead_input_threshold >= 10.0
    assert sut._watchdog_dead_input_threshold > sut._watchdog_silence_threshold
