# @parity test/peak-selection-persistence
"""Option 1 of PEAK-MIN-SEMANTICS.md (GuitarTapWeb): the manual/auto selection flag is persisted,
so a reloaded measurement behaves like a live one. An AUTOMATIC selection re-runs auto-selection
when Peak Min changes (a peak revealed by lowering Peak Min is selected as its mode winner); a
MANUAL one is carried forward. Files saved before the field default to manual (no regression).

Uses the real swift-mac capture: Air is at 97.26 Hz / -64.21 dB, so a Peak Min of -60 excludes it;
lowering to -70 reveals it, and whether it gets selected depends on the persisted flag.

Mirrors Swift PeakSelectionPersistenceTests.
"""
from __future__ import annotations

import base64
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from guitar_tap.models.spectrum_snapshot import SpectrumSnapshot  # noqa: E402
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS  # noqa: E402
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer  # noqa: E402
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement  # noqa: E402

STEM = "dws-2024-umik-1-swift-mac-1784225155"


def _fixture_spectrum():
    sn = json.load(open(os.path.join(os.path.dirname(__file__), STEM + ".guitartap")))[0]["spectrumSnapshot"]
    mags = np.frombuffer(base64.b64decode(sn["magnitudesData"]), dtype="<f4").astype(float).tolist()
    freqs = np.frombuffer(base64.b64decode(sn["frequenciesData"]), dtype="<f4").astype(float).tolist()
    return mags, freqs


def _make_measurement(user_modified):
    TDS.set_guitar_type("Generic")
    sut = TapToneAnalyzer.for_testing()
    sut.min_frequency = 30
    sut.max_frequency = 2000
    mags, freqs = _fixture_spectrum()
    full = sut.find_peaks(mags, freqs, min_hz=30, max_hz=2000, peak_min_override=-100)
    displayed60 = [p for p in full if p.magnitude >= -60]
    winners60 = sut.guitar_mode_selected_peak_ids(displayed60)
    snap = SpectrumSnapshot(
        frequencies=freqs, magnitudes=mags, min_freq=75.0, max_freq=350.0,
        min_db=-100.0, max_db=0.0, is_logarithmic=False,
        guitar_type="Generic", measurement_type="Generic Guitar",
    )
    m = TapToneMeasurement.create(
        peaks=full,
        spectrum_snapshot=snap,
        tap_detection_threshold=-49.0,
        number_of_taps=1,
        peak_min_threshold=-60,
        selected_peak_ids=list(winners60),
        selected_peak_frequencies=[p.frequency for p in displayed60 if p.id in winners60],
        user_modified_selection=user_modified,
    )
    air_selected_in_save = any(
        p.id in winners60 and abs(p.frequency - 97.26) < 1 for p in full
    )
    return m, air_selected_in_save


def _air_after_lowering(m):
    TDS.set_guitar_type("Generic")
    sut = TapToneAnalyzer.for_testing()
    sut.min_frequency = 30
    sut.max_frequency = 2000
    sut.load_measurement(m)
    sut.peak_min_threshold = -70
    sut.recalculate_frozen_peaks_if_needed()
    air = next((p for p in sut.peaks_above_peak_min if abs(p.frequency - 97.26) < 1), None)
    selected = air is not None and air.id in set(sut.selected_peak_ids)
    return air is not None, selected


class TestPeakSelectionPersistence:
    def test_automatic_selection_reselects_revealed_air(self):
        m, air_in_save = _make_measurement(user_modified=False)
        assert not air_in_save, "precondition: Air not selected in the saved (Peak Min -60) selection"
        revealed, selected = _air_after_lowering(m)
        assert revealed, "lowering Peak Min should reveal the Air peak"
        assert selected, "an AUTO measurement should auto-select the revealed Air winner (like live)"

    def test_manual_selection_does_not_reselect(self):
        m, _ = _make_measurement(user_modified=True)
        revealed, selected = _air_after_lowering(m)
        assert revealed, "lowering Peak Min should still reveal the Air peak"
        assert not selected, "a MANUAL measurement carries its selection forward — Air stays unselected"

    def test_legacy_file_defaults_to_manual(self):
        m, _ = _make_measurement(user_modified=None)
        sut = TapToneAnalyzer.for_testing()
        sut.load_measurement(m)
        assert sut.user_has_modified_peak_selection is True, "a legacy file (no flag) defaults to manual"

    def test_flag_round_trips(self):
        for value in (True, False):
            m, _ = _make_measurement(user_modified=value)
            back = TapToneMeasurement.from_dict(json.loads(json.dumps(m.to_dict())))
            assert back.user_modified_selection == value, f"userModifiedSelection must round-trip ({value})"
        m, _ = _make_measurement(user_modified=None)
        assert "userModifiedSelection" not in m.to_dict(), "a None flag is omitted from the JSON"