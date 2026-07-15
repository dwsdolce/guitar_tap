# @parity test/session-pre-roll
"""Pin the bounded pre-roll for the session WAV (FILE-PATHS-AND-NAMES-SPEC §6).

The head is trimmed to ~2 s ONLY before the first tap; everything after — subsequent taps, plate
phases, and the gaps between them — is completely live. Three-way with Swift SessionPreRollTests.swift
and web session-pre-roll.test.ts.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

CHUNK = [0.0] * 1024  # one ~21 ms chunk at 48 kHz


def _armed() -> TapToneAnalyzer:
    a = TapToneAnalyzer()
    a._session_recording_sample_rate = 48000.0
    a._is_session_recording = True
    a._session_pre_roll_active = True
    a._gated_capture_active = False
    a._session_recording_buffer = []
    return a


# ── Before the first tap: the head is bounded ──────────────────────────────

def test_idle_before_first_tap_is_bounded():
    a = _armed()
    for _ in range(300):  # ~6.4 s of idle, well over the 2 s pre-roll
        a._maintain_session_recording(CHUNK)
    assert len(a._session_recording_buffer) <= a.session_pre_roll_samples
    assert len(a._session_recording_buffer) > a.session_pre_roll_samples - len(CHUNK)


# ── The first tap freezes the latch ────────────────────────────────────────

def test_first_tap_freezes_pre_roll():
    a = _armed()
    for _ in range(300):
        a._maintain_session_recording(CHUNK)
    assert a._session_pre_roll_active is True
    a._gated_capture_active = True
    a._maintain_session_recording(CHUNK)
    assert a._session_pre_roll_active is False


# ── THE INVARIANT: everything after the first tap is completely live ───────

def test_multi_tap_multi_phase_after_first_tap_is_fully_live():
    a = _armed()
    for _ in range(300):
        a._maintain_session_recording(CHUNK)
    a._gated_capture_active = True
    a._maintain_session_recording(CHUNK)  # freezes
    expected = len(a._session_recording_buffer)

    # Long multi-tap / multi-phase session with big idle GAPS between taps — none of it may be
    # trimmed now that the latch is frozen.
    for tap in range(5):
        a._gated_capture_active = False
        for _ in range(200):  # ~4 s gap, far more than the 2 s pre-roll
            a._maintain_session_recording(CHUNK)
            expected += len(CHUNK)
        a._gated_capture_active = tap % 2 == 0
        a._maintain_session_recording(CHUNK)
        expected += len(CHUNK)

    assert len(a._session_recording_buffer) == expected, (
        "After the first tap the session must be COMPLETELY LIVE — no chunk trimmed"
    )
    assert a._session_pre_roll_active is False


# ── The >= 0.5 s lead-in guarantee (playback fixtures) ─────────────────────

def test_pre_roll_exceeds_warmup():
    a = _armed()
    assert a.session_pre_roll_samples / a._session_recording_sample_rate >= 0.5
    assert TapToneAnalyzer.SESSION_PRE_ROLL_DURATION >= 0.5