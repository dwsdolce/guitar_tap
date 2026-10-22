# @parity test/calibration
"""
The engine's calibration corrections: the engine holds the active calibration and computes its
per-bin corrections from its own bins, at each bin's exact frequency, again when the sample rate
changes, and flat outside the file's range (CAL1–CAL3); and reading a calibration file — its points,
its header's Sens Factor and reference level, and a file with no data (CP1–CP9). The shared cases in
calibration.json.

The same list, ids and values as Swift CalibrationTests and web test/calibration.test.ts.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.microphone_calibration import CalibrationFileParser, MicrophoneCalibration
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


def test_corrections_for_all_bins_are_each_bins_correction():
    """Every bin's correction, computed for all the FFT's bins at once, is the one ``correction_at`` gives
    that bin alone — exactly, for the bins of 48 kHz and of 44.1 kHz and for unsorted frequencies. Mirrors
    Swift ``correctionsForAllBins_areEachBinsCorrection``."""
    calibration = MicrophoneCalibration.from_path(os.path.join(_HERE, DATA["calibrationFile"]))
    fft_size = DATA["fftSize"]
    for rate in (48000.0, 44100.0):
        bins = np.arange(fft_size // 2, dtype=np.float64) * rate / fft_size
        assert list(calibration.interpolate_to_bins(bins)) == [calibration.correction_at(f) for f in bins], rate
    unsorted = np.array([1000, 20, 5000, 20, 19000, 3], dtype=np.float64)
    assert list(calibration.interpolate_to_bins(unsorted)) == [calibration.correction_at(f) for f in unsorted]


@pytest.mark.parametrize("row", DATA["parse"], ids=lambda r: r["id"])
def test_calibration_parse(row):
    if "file" in row:
        with open(os.path.join(_HERE, row["file"]), encoding="utf-8") as fh:
            content = fh.read()
    else:
        content = row["content"]
    expect = row["expect"]
    try:
        cal = CalibrationFileParser.parse_content(content, row["id"])
    except CalibrationFileParser.ParseError:
        assert expect.get("error") is True, f"{row['id']}: the text did not parse"
        return
    assert "error" not in expect, f"{row['id']}: the text parsed, where an error was expected"
    points = [[p["frequency"], p["correction"]] for p in cal.correction_points]
    for field, want in expect.items():
        msg = f"{row['id']} {field}"
        if field == "pointCount":
            assert len(points) == want, f"{msg}: {len(points)}"
        elif field in ("first", "last"):
            assert points[0 if field == "first" else -1] == pytest.approx(want, abs=1e-3), msg
        elif field == "points":
            assert points == [pytest.approx(w, abs=1e-3) for w in want], f"{msg}: {points}"
        elif field in ("sensitivity", "referenceLevel"):
            got = cal.sensitivity_factor if field == "sensitivity" else cal.reference_level
            assert got == (None if want is None else pytest.approx(want, abs=1e-4)), f"{msg}: {got}"
        else:
            pytest.fail(f"{row['id']}: unknown field {field}")


@pytest.mark.parametrize("row", DATA["details"], ids=lambda r: r["id"])
def test_calibration_details(row):
    if "file" in row:
        with open(os.path.join(_HERE, row["file"]), encoding="utf-8") as fh:
            content = fh.read()
    else:
        content = row["content"]
    sensitivity, data_points, rng = CalibrationFileParser.parse_content(content, row["id"]).details
    expect = row["expect"]
    assert (sensitivity, data_points, rng) == (expect["sensitivity"], expect["dataPoints"], expect["range"])
