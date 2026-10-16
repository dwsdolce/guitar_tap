# @parity test/session-pre-roll
"""The session WAV: its head is trimmed to a 2 s pre-roll only before the first tap — everything after,
later taps and the gaps between them, is completely live — and Dump Capture Audio decides whether it
is saved. The shared cases in session-pre-roll.json (SR1-SR14), the same as Swift and the web; and the
capture probe's case, which runs only with the probe on.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

# ── The shared cases in session-pre-roll.json (SR1–SR14) ──

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
            elif "release" in step:
                a._gated_capture_active = False
            elif "dump" in step:
                TapDisplaySettings.set_dump_capture_audio(step["dump"])
                a.apply_dump_capture_audio_setting()
            elif "pause" in step:
                a.pause_tap_detection()
            elif "resume" in step:
                a.resume_tap_detection()
        e = case["expect"]
        if "saved" in e:
            assert a._is_session_recording_enabled is e["saved"], "saved"
        if "recording" in e:
            assert a._is_session_recording is e["recording"], "recording"
        if "samples" in e:
            assert len(a._session_recording_buffer) == e["samples"], f"samples: {len(a._session_recording_buffer)}"
        if "preRoll" in e:
            assert a._session_pre_roll_active is e["preRoll"], "preRoll"
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved_dump)


def test_pre_roll_length():
    """The pre-roll's length: the file's ``preRollSeconds``."""
    assert TapToneAnalyzer.SESSION_PRE_ROLL_DURATION == DATA["preRollSeconds"]


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
