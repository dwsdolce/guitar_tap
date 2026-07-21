# @parity test/peaks
"""
D3 + D5 + D6 of Development/PEAK-FINDING-DUPLICATE-PEAKS.md (GuitarTapWeb).

Port of PeakFixtureRegressionTests.swift. Replays real captured spectra through
``find_peaks`` and pins the result against a golden baseline.

  D3 — no fixture may yield duplicate peaks.
  D5 — the peak set must equal the step-2 baseline with the spurious twin removed:
       same count, frequencies, magnitudes, Q, bandwidth, mode labels and selection.
       This is what proves the fix removed ONLY the duplicate and moved nothing else.
  D6 — peak-baseline-expected.json is byte-identical in all three repos, so all three
       platforms passing D5 is three-way parity. There is no separate test.

Fixtures are one physical tap captured by all three apps (Swift, Python, web), chosen
so one file per platform proves the shared algorithm's behaviour.

Authored against the UNFIXED code: D3 fails on every fixture (one duplicate each) and
D5 fails on peak count until detection stops being interleaved with classification.
"""

from __future__ import annotations

import base64
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from guitar_tap.models.guitar_mode import GuitarMode  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

TESTS_DIR = os.path.dirname(__file__)
MIN_HZ = 30.0
MAX_HZ = 2000.0
PEAK_PROXIMITY_HZ = 2.0
TOL = 1e-3

FIXTURES = [
    "dws-2024-umik-1-swift-mac-1784225155.guitartap",
    "dws-2024-umik-1-python-mac-1784225140.guitartap",
    "dws-2024-umik-1-web-mac-1784225174.guitartap",
]


def _mode_token(mode) -> str:
    """Canonical mode token, shared verbatim with the Swift and web expectations."""
    return {
        GuitarMode.AIR: "air",
        GuitarMode.TOP: "top",
        GuitarMode.BACK: "back",
        GuitarMode.DIPOLE: "dipole",
        GuitarMode.RING_MODE: "ring",
        GuitarMode.UPPER_MODES: "upper",
    }.get(mode, "unknown")


def _floats(b64: str) -> list[float]:
    return np.frombuffer(base64.b64decode(b64), dtype="<f4").astype(float).tolist()


def _replay(name: str):
    """Replays a fixture's own saved spectrum through the current find_peaks."""
    with open(os.path.join(TESTS_DIR, name)) as fh:
        m = json.load(fh)[0]
    sn = m["spectrumSnapshot"]

    freqs = _floats(sn["frequenciesData"])
    mags = _floats(sn["magnitudesData"])
    TDS.set_guitar_type(m.get("guitarType") or "Generic")

    sut = TapToneAnalyzer.for_testing()
    sut.peak_min_threshold = m.get("peakMinThreshold", -60)
    sut.min_frequency = MIN_HZ
    sut.max_frequency = MAX_HZ

    peaks = sut.find_peaks(mags, freqs, min_hz=MIN_HZ, max_hz=MAX_HZ)
    modes = GuitarMode.classify_all(peaks, TDS.guitar_type())
    selected = sut.guitar_mode_selected_peak_ids(peaks)
    return peaks, modes, selected


def _expected() -> dict:
    with open(os.path.join(TESTS_DIR, "peak-baseline-expected.json")) as fh:
        return json.load(fh)


class TestPeakFixtureRegression:
    """Mirrors Swift PeakFixtureRegressionTests."""

    @pytest.mark.parametrize("name", FIXTURES)
    def test_D3_fixture_has_no_duplicate_peaks(self, name):
        peaks, _, _ = _replay(name)
        assert peaks, f"{name}: no peaks replayed"

        offenders = []
        for i in range(len(peaks)):
            for j in range(i + 1, len(peaks)):
                delta = abs(peaks[i].frequency - peaks[j].frequency)
                if delta < PEAK_PROXIMITY_HZ:
                    offenders.append(
                        f"{peaks[i].frequency:.5f} Hz / {peaks[j].frequency:.5f} Hz "
                        f"({delta:.5f} apart)"
                    )
        assert not offenders, f"{name}: duplicate peaks — {'; '.join(offenders)}"

    @pytest.mark.parametrize("name", FIXTURES)
    def test_D5_fixture_matches_golden_baseline(self, name):
        expected = _expected().get(name)
        assert expected is not None, f"no expectation recorded for {name}"

        peaks, modes, selected = _replay(name)
        assert len(peaks) == expected["peakCount"], (
            f"{name}: expected {expected['peakCount']} peaks, got {len(peaks)}"
        )

        # Compare in frequency order so ordering changes don't masquerade as value changes.
        got = sorted(peaks, key=lambda p: p.frequency)
        want = sorted(expected["peaks"], key=lambda p: p["frequency"])

        for g, w in zip(got, want):
            assert abs(g.frequency - w["frequency"]) < TOL, (
                f"{name}: frequency {g.frequency} vs expected {w['frequency']}"
            )
            assert abs(g.magnitude - w["magnitude"]) < TOL, (
                f"{name}: magnitude at {w['frequency']} Hz — {g.magnitude} vs {w['magnitude']}"
            )
            assert abs(g.quality - w["quality"]) < TOL, (
                f"{name}: Q at {w['frequency']} Hz — {g.quality} vs {w['quality']}"
            )
            assert abs(g.bandwidth - w["bandwidth"]) < TOL, (
                f"{name}: bandwidth at {w['frequency']} Hz — {g.bandwidth} vs {w['bandwidth']}"
            )
            assert _mode_token(modes.get(g.id)) == w["mode"], (
                f"{name}: mode at {w['frequency']} Hz — "
                f"{_mode_token(modes.get(g.id))} vs {w['mode']}"
            )
            assert (g.id in selected) == w["selected"], (
                f"{name}: selection at {w['frequency']} Hz — "
                f"{g.id in selected} vs {w['selected']}"
            )