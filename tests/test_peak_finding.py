# @parity test/peaks
"""Peak finding, near-duplicate removal, spectrum averaging, guitar auto-selection and the full-set save,
against the shared case file, ``peaks.json`` — the same cases the Swift and web suites run.

find_peaks must return one peak per spectral feature: the Top/Back overlap case (32768 bins, so peaks 7 Hz
apart can both be detected) pins three peaks for three features. A saved guitar measurement holds the full
set found down to the -100 dB floor, not just what Peak Min shows, so a reloaded measurement can reveal peaks
below its capture-time Peak Min; a loaded measurement is saved as it is."""

from __future__ import annotations

import base64
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode  # noqa: E402
from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "peaks.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

MODE_NAME = {
    GuitarMode.AIR: "air", GuitarMode.TOP: "top", GuitarMode.BACK: "back", GuitarMode.DIPOLE: "dipole",
    GuitarMode.RING_MODE: "ringMode", GuitarMode.UPPER_MODES: "upperModes", GuitarMode.UNKNOWN: "unknown",
}


def _close(actual, expected) -> bool:
    """|actual - expected| <= relative * |expected| + absolute."""
    tol = DATA["tolerance"]
    return actual is not None and abs(actual - expected) <= tol["relative"] * abs(expected) + tol["absolute"]


def _row(key: str, id_: str) -> dict:
    return next(r for r in DATA[key] if r["id"] == id_)


def _spectrum(s: dict) -> tuple[list[float], list[float]]:
    """A case's spectrum, built as the file describes it."""
    bins = s["binCount"]
    spacing = s["binSpacingHz"] if "binSpacingHz" in s else (s["sampleRate"] / 2) / (bins - 1)
    freqs = [i * spacing for i in range(bins)]
    if s["kind"] == "flat":
        return [float(s["value"])] * bins, freqs
    if s["kind"] == "triangle":
        return [s["peakDB"] - s["slopeDBPerBin"] * abs(i - s["peakBin"]) for i in range(bins)], freqs
    floor = s["noiseFloor"]
    mags = [float(floor)] * bins
    for p in s["peaks"]:
        sigma = p["halfWidthHz"] / 2.355
        for i, f in enumerate(freqs):
            d = f - p["peakHz"]
            mags[i] = max(mags[i], max(floor, p["peakDB"] + (-d * d / (2 * sigma * sigma))))
    return mags, freqs


def _find_peaks(row: dict) -> list:
    TDS.set_guitar_type("Generic")
    sut = TapToneAnalyzer.for_testing()
    sut.peak_min_threshold = row["peakMinThreshold"]
    sut.min_frequency = row["minFrequency"]
    sut.max_frequency = row["maxFrequency"]
    mags, freqs = _spectrum(row["spectrum"])
    return sut.find_peaks(mags, freqs, peak_min_override=row.get("peakMinOverride"))


@pytest.mark.parametrize("row", DATA["findPeaks"], ids=lambda r: r["id"])
def test_find_peaks(row):
    peaks = _find_peaks(row)
    expected = row["expect"]
    assert len(peaks) == len(expected), f"{len(peaks)} peaks {[p.frequency for p in peaks]}"
    for p, e in zip(peaks, expected):
        assert _close(p.frequency, e["frequency"]), f"frequency {p.frequency}"
        assert _close(p.magnitude, e["magnitude"]), f"magnitude {p.magnitude}"
        assert _close(p.quality, e["quality"]), f"quality {p.quality}"
        assert _close(p.bandwidth, e["bandwidth"]), f"bandwidth {p.bandwidth}"
        assert p.pitch_note == e["pitchNote"]
        assert _close(p.pitch_cents, e["pitchCents"]), f"pitch_cents {p.pitch_cents}"
        assert _close(p.pitch_frequency, e["pitchFrequency"]), f"pitch_frequency {p.pitch_frequency}"


@pytest.mark.parametrize("row", DATA["removeDuplicatePeaks"], ids=lambda r: r["id"])
def test_remove_duplicate_peaks(row):
    peaks = [ResonantPeak(frequency=p["frequency"], magnitude=p["magnitude"]) for p in row["peaks"]]
    kept = TapToneAnalyzer.for_testing().remove_duplicate_peaks(peaks)
    assert [next(i for i, p in enumerate(peaks) if p.id == k.id) for k in kept] == row["expect"]


@pytest.mark.parametrize("row", DATA["averageSpectra"], ids=lambda r: r["id"])
def test_average_spectra(row):
    taps = [(t["magnitudes"], t["frequencies"], 0.0) for t in row["taps"]]
    mags, freqs = TapToneAnalyzer.for_testing().average_spectra(taps)
    e = row["expect"]
    assert len(mags) == len(e["magnitudes"]) and len(freqs) == len(e["frequencies"])
    assert all(_close(float(a), b) for a, b in zip(mags, e["magnitudes"])), f"magnitudes {list(mags)}"
    assert all(_close(float(a), b) for a, b in zip(freqs, e["frequencies"])), f"frequencies {list(freqs)}"


@pytest.mark.parametrize("row", DATA["autoSelection"], ids=lambda r: r["id"])
def test_auto_selection(row):
    peaks = _find_peaks(_row("findPeaks", row["findPeaks"]))
    modes = GuitarMode.classify_all(peaks, TDS.guitar_type())
    selected = TapToneAnalyzer.for_testing().guitar_mode_selected_peak_ids(peaks)
    assert [MODE_NAME[modes[p.id]] for p in peaks] == row["expect"]["modes"]
    assert [i for i, p in enumerate(peaks) if p.id in selected] == row["expect"]["selected"]


@pytest.mark.parametrize("row", DATA["fullSetSave"], ids=lambda r: r["id"])
def test_full_set_save(row):
    TDS.set_guitar_type("Generic")
    with open(os.path.join(os.path.dirname(__file__), row["fixture"]), encoding="utf-8") as fh:
        sn = json.load(fh)[0]["spectrumSnapshot"]
    mags = np.frombuffer(base64.b64decode(sn["magnitudesData"]), dtype="<f4").astype(float).tolist()
    freqs = np.frombuffer(base64.b64decode(sn["frequenciesData"]), dtype="<f4").astype(float).tolist()

    sut = TapToneAnalyzer.for_testing()
    sut.set_frozen_spectrum(freqs, mags)
    sut.is_measurement_complete = True
    sut.min_frequency = row["minFrequency"]
    sut.max_frequency = row["maxFrequency"]
    sut.peak_min_threshold = row["peakMinThreshold"]
    sut.all_peaks = sut.find_peaks(mags, freqs, peak_min_override=sut.PEAK_DETECTION_FLOOR)

    def is_air(p):
        return abs(p.frequency - row["airHz"]) < 1

    displayed = list(sut.peaks_above_peak_min)
    sut.loaded_measurement_peaks = None
    saved = sut.guitar_full_save_peaks()
    e = row["expect"]
    assert len(displayed) == e["displayedCount"]
    assert len(saved) == e["savedCount"]
    assert any(is_air(p) for p in displayed) == e["airDisplayed"]
    assert any(is_air(p) for p in saved) == e["airSaved"]
    assert ({p.id for p in displayed} <= {p.id for p in saved}) == e["displayedAmongSaved"]
    assert (len({p.id for p in saved}) == len(saved)) == e["savedDistinctIds"]

    loaded = list(sut.all_peaks)[: row["loadedFirst"]]
    sut.all_peaks = loaded
    sut.loaded_measurement_peaks = loaded
    saved_loaded = sut.guitar_full_save_peaks()
    assert len(saved_loaded) == e["loadedSavedCount"]
    assert ([p.id for p in saved_loaded] == [p.id for p in loaded]) == e["loadedSavedSame"]
