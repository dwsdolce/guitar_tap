# @parity test/session-pre-roll
"""Pin the bounded pre-roll for the session WAV.

The head is trimmed to ~2 s ONLY before the first tap; everything after — subsequent taps, plate
phases, and the gaps between them — is completely live. How Dump Capture Audio decides whether the
recording is saved, and what changing it does, are the shared cases in session-pre-roll.json
(SR1–SR11). Three-way with Swift SessionPreRollTests.swift and web session-pre-roll.test.ts.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

CHUNK = [0.0] * 1024  # one ~21 ms chunk at 48 kHz


def _armed() -> TapToneAnalyzer:
    a = TapToneAnalyzer()
    a._session_recording_sample_rate = 48000.0
    a._is_session_recording = True
    a._is_session_recording_enabled = True
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


# ── Dump Capture Audio — the shared cases in session-pre-roll.json (SR1–SR11) ──

with open(os.path.join(os.path.dirname(__file__), "session-pre-roll.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("case", DATA["cases"], ids=[c["id"] for c in DATA["cases"]])
def test_dump_capture_audio(case):
    from guitar_tap.models.tap_display_settings import TapDisplaySettings

    saved_dump = TapDisplaySettings.dump_capture_audio()
    try:
        a = TapToneAnalyzer.for_testing()
        samples = np.full(DATA["chunk"], 0.1, dtype=np.float32)
        for step in case["steps"]:
            if "start" in step:
                TapDisplaySettings.set_dump_capture_audio(step["start"])
                a.start_tap_sequence()
                a._session_recording_sample_rate = float(DATA["rate"])
                a._gated_capture_active = False
            elif "chunks" in step:
                for _ in range(step["chunks"]):
                    a._maintain_session_recording(samples)
            elif "tap" in step:
                a._gated_capture_active = True
                a._maintain_session_recording(samples)
            elif "dump" in step:
                TapDisplaySettings.set_dump_capture_audio(step["dump"])
                a.apply_dump_capture_audio_setting()
            elif "pause" in step:
                a.pause_tap_detection()
            elif "resume" in step:
                a.resume_tap_detection()
        e = case["expect"]
        assert a._is_session_recording_enabled is e["saved"], "saved"
        assert a._is_session_recording is e["recording"], "recording"
        assert len(a._session_recording_buffer) == e["samples"], "samples"
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved_dump)


# The capture probe's records follow the recording: a sequence saved because Dump Capture Audio was
# turned on before its first tap has its probe file too. Runs only with the probe on.
from guitar_tap.models import capture_probe as _capture_probe  # noqa: E402


@pytest.mark.skipif(not _capture_probe.LIVE_PROBE, reason="the capture probe is switched off")
def test_capture_probe_follows_the_recording():
    from guitar_tap.models.tap_display_settings import TapDisplaySettings

    saved_dump = TapDisplaySettings.dump_capture_audio()
    saved_session = _capture_probe.live_session
    try:
        a = TapToneAnalyzer.for_testing()
        TapDisplaySettings.set_dump_capture_audio(False)
        a.start_tap_sequence()
        assert _capture_probe.live_session is False
        TapDisplaySettings.set_dump_capture_audio(True)
        a.apply_dump_capture_audio_setting()
        assert _capture_probe.live_session is True, "turned on before the first tap"
        TapDisplaySettings.set_dump_capture_audio(False)
        a.apply_dump_capture_audio_setting()
        assert _capture_probe.live_session is False, "turned off"
        a._gated_capture_active = True
        a._maintain_session_recording(np.full(1024, 0.1, dtype=np.float32))
        TapDisplaySettings.set_dump_capture_audio(True)
        a.apply_dump_capture_audio_setting()
        assert _capture_probe.live_session is False, "turned on after the first tap"
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved_dump)
        _capture_probe.live_session = saved_session
