# @parity test/calibration
"""
The engine's calibration corrections: the engine holds the active calibration and computes its per-bin
corrections from its own bins, at each bin's exact frequency, and again when the sample rate changes
(CAL1, CAL2 — the shared cases in calibration.json).

The same list, ids and values as Swift CalibrationTests and web test/calibration.test.ts.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.microphone_calibration import MicrophoneCalibration
from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "calibration.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("row", DATA["cases"], ids=lambda r: r["id"])
def test_calibration_corrections(row):
    engine = RealtimeFFTAnalyzer.for_testing(sample_rate=row.get("fromSampleRate", row["sampleRate"]))
    assert engine.fft_size == DATA["fftSize"]
    engine.set_temporary_calibration(MicrophoneCalibration.from_path(os.path.join(_HERE, DATA["calibrationFile"])))
    if "fromSampleRate" in row:
        assert engine.calibration_corrections is not None   # computed for the first rate
        engine.rate = row["sampleRate"]
    corrections = engine.calibration_corrections
    for index, expected in zip(row["bins"], row["expect"]):
        assert abs(float(corrections[index]) - expected) <= DATA["tolerance"], (
            f"{row['id']}: bin {index} — {float(corrections[index])} dB, expected {expected} — {row['note']}")
