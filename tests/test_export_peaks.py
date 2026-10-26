# @parity test/export-peaks
"""The peaks a saved measurement's report shows are the peaks it shows on screen, against the shared case file
``export-peaks.json`` — the same cases the Swift and web suites run. A guitar shows its peaks at or above its
Peak Min, so a selected peak below Peak Min is left out of its report as it is off its screen; a plate or brace
shows its identified peaks whatever the Peak Min. Each case reads a fixture with the Peak Min it names."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
from guitar_tap.views.tap_analysis_results_view import pdf_report_data_from_measurement

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "export-peaks.json"), encoding="utf-8") as _f:
    CASES = json.load(_f)["cases"]


def _measurement(row) -> TapToneMeasurement:
    with open(os.path.join(HERE, row["fixture"] + ".guitartap"), encoding="utf-8") as f:
        d = json.load(f)[0]
    if row["peakMinThreshold"] is not None:
        d["peakMinThreshold"] = row["peakMinThreshold"]
    return TapToneMeasurement.from_dict(d)


@pytest.mark.parametrize("row", CASES, ids=lambda r: f'{r["fixture"]}@{r["peakMinThreshold"]}')
def test_peaks_above_peak_min(row):
    m = _measurement(row)
    assert len(m.peaks_above_peak_min) == row["peaksAbovePeakMin"]
    # The export header's "Detected Peaks: N": the detected peaks in view (none for a plate or brace).
    assert len(m.detected_peaks_in_view) == row["detectedPeaksInView"]


@pytest.mark.parametrize("row", [r for r in CASES if r["reportRows"] is not None],
                         ids=lambda r: f'{r["fixture"]}@{r["peakMinThreshold"]}')
def test_report_rows_leave_out_peaks_below_peak_min(row):
    data = pdf_report_data_from_measurement(_measurement(row))
    rows = sorted(round(p.frequency, 1) for p in data.peaks if p.id in data.selected_peak_ids)
    assert rows == row["reportRows"]


@pytest.mark.parametrize("row", [r for r in CASES if r["reportRows"] is not None],
                         ids=lambda r: f'{r["fixture"]}@{r["peakMinThreshold"]}')
def test_report_peaks_are_the_report_rows(row):
    """The image's Selected Peaks Summary lists ``report_peaks``: the report table's rows."""
    assert [round(p.frequency, 1) for p in _measurement(row).report_peaks] == row["reportRows"]
