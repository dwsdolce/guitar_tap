# @parity test/decay-tracking
"""
Ring-out time: ring_out_time on generated audio (DK1–DK8, the shared cases in decay-tracking.json),
and that a new sequence clears the last ring-out (DK9).

That a tap's ring-out is the same wherever the audio's chunk boundaries fall is
test_guitar_capture_window GW3.

The same list, ids and values as Swift DecayTrackingTests and web test/decay-tracking.test.ts.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6 import QtWidgets

_APP: QtWidgets.QApplication | None = None


def _get_app() -> QtWidgets.QApplication:
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    return _get_app()


from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer


def _make_sut() -> TapToneAnalyzer:
    _get_app()
    return TapToneAnalyzer()


with open(os.path.join(os.path.dirname(__file__), "decay-tracking.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


def _signal(spec: dict, sample_rate: float) -> np.ndarray:
    """A case's audio, from its ``signal`` (see decay-tracking.json's ``about``)."""
    n = np.arange(spec["length"]) - spec.get("onset", 0)
    after = np.maximum(n, 0)
    value = spec.get("amplitude", 0.5) * np.exp(-after / (spec["timeConstant"] * sample_rate))
    if spec.get("attack", 0):
        value = value * np.minimum(1.0, after / spec["attack"])
    return np.where(n >= 0, value, 0.0).astype(np.float32)


def test_default_threshold():
    assert _make_sut().decay_threshold == DATA["defaultThreshold"]


def test_window_samples():
    assert TapToneAnalyzer.RING_OUT_WINDOW_SAMPLES == DATA["windowSamples"]


@pytest.mark.parametrize("row", DATA["ringOutTime"], ids=lambda r: r["id"])
def test_ring_out_time(row):
    """ring_out_time on generated audio — the shared cases in ``decay-tracking.json`` (DK1–DK8)."""
    sample_rate = DATA["sampleRate"]
    t = TapToneAnalyzer.ring_out_time(_signal(row["signal"], sample_rate), row["start"], row["end"],
                                      sample_rate, row.get("threshold", DATA["defaultThreshold"]))
    if row["expect"] is None:
        assert t is None, f"{row['id']}: got {t}"
    else:
        assert t is not None and abs(t - row["expect"]) < DATA["tolerance"], f"{row['id']}: got {t}"


def test_DK9_a_new_sequence_clears_the_ring_out():
    sut = _make_sut()
    sut.current_decay_time = 0.1
    sut.start_tap_sequence()
    assert sut.current_decay_time is None


class TestRingOutReachesTheView:
    """The measured ring-out reaches the Ring-Out box. Python-only: Swift's view observes its
    `@Published currentDecayTime` and the web's its snapshot; Python's box listens to
    currentDecayTimeChanged, which the current_decay_time property emits.
    """

    def test_a_measured_ring_out_reaches_the_view_and_a_new_sequence_clears_it(self):
        sut = _make_sut()
        seen: list = []
        sut.currentDecayTimeChanged.connect(seen.append)

        sut.current_decay_time = 0.0761
        QtWidgets.QApplication.processEvents()
        assert seen and seen[-1] == 0.0761, "the measured ring-out reached the view"

        sut.start_tap_sequence()
        assert seen[-1] is None, "a new sequence puts the box back to Waiting…"
