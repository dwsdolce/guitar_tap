# @parity tooling/parity-runner
"""Run every oracle case and report what THIS configuration computes.

The oracle declares each case's *inputs* — fixture, calibration, settings — and the
values the canonical Swift edition produced for them. This module reads only the
inputs, runs the full pipeline, and returns the values this edition produces in the
same shape. It never reads an expected value, so nothing it returns is contaminated
by what the answer is supposed to be.

Two callers share it, and that sharing is the point:

  * ``Tooling/mint-baseline.py`` writes the result to this configuration's committed
    self-baseline.
  * ``test_self_regression.py`` compares the result to that baseline at zero tolerance.

A mint and a check computed by two separate implementations could drift apart, and
the drift would look exactly like "no regression". One implementation cannot.
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from gated_signal import gated_magnitude_at, make_gated_test_signal
from parity_oracle import ORACLE, calibration, case, fixture, gated

# Oracle spellings of measurementType → the enum the analyzer takes.
_MEASUREMENT_TYPES = {
    "Generic Guitar": "GENERIC",
    "Material (Brace)": "BRACE",
    "Material (Plate)": "PLATE",
}


def _wav_rate(path: str) -> int:
    import soundfile as sf
    return int(sf.info(path).samplerate)


def _guitar_mode(role: str) -> Any:
    from guitar_tap.models.guitar_mode import GuitarMode
    return {"air": GuitarMode.AIR, "top": GuitarMode.TOP, "back": GuitarMode.BACK}[role]


def _guitar_peak(sut: Any, role: str) -> Any:
    """get_peak() — the API the Results panel uses, and the one the tests assert on."""
    return sut.get_peak(_guitar_mode(role))


def _material_peak(sut: Any, role: str) -> Any:
    """The peak the Results panel shows for a material role.

    Selected-first, dominant as the fallback: REG-P1/P2 assert against
    ``selected_*`` and REG-B1 against ``longitudinal_peaks[0]``, which are the same
    peak whenever a selection exists.
    """
    selected, series = {
        "longitudinal": ("selected_longitudinal_peak", "longitudinal_peaks"),
        "cross": ("selected_cross_peak", "cross_peaks"),
        "flc": ("selected_flc_peak", "flc_peaks"),
    }[role]
    peak = getattr(sut, selected)
    if peak is None:
        peaks = getattr(sut, series)
        peak = peaks[0] if peaks else None
    return peak


def _record(peak: Any, keys: list[str], name: str, role: str) -> dict[str, Any]:
    if peak is None:
        raise AssertionError(f"{name}: no {role!r} peak was produced")
    out: dict[str, Any] = {"role": role}
    for key in keys:
        out[key] = float(getattr(peak, {"frequency": "frequency",
                                        "magnitude": "magnitude",
                                        "q": "quality"}[key]))
    return out


def _play(name: str) -> Any:
    """Run one filePlayback case exactly as its regression test does."""
    from guitar_tap.models.measurement_type import MeasurementType
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    spec = case(name)
    settings = spec["settings"]
    path = fixture(name)

    sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(path))
    if "peakMinThreshold" in settings:
        sut.peak_min_threshold = settings["peakMinThreshold"]
    sut.tap_detection_threshold = settings["tapDetectionThreshold"]

    measure_flc = bool(settings.get("measureFlc", False))
    restore = TapDisplaySettings.measure_flc()
    TapDisplaySettings.set_measure_flc(measure_flc)
    try:
        sut.play_file_for_testing(
            path=path,
            measurement_type=getattr(
                MeasurementType, _MEASUREMENT_TYPES[settings["measurementType"]]
            ),
            number_of_taps=int(settings["numberOfTaps"]),
            calibration_path=calibration(name),
        )
    finally:
        TapDisplaySettings.set_measure_flc(restore)
    return sut


def compute_file_playback() -> dict[str, Any]:
    """Every filePlayback case, keyed and shaped as the oracle keys and shapes it."""
    out: dict[str, Any] = {}
    for name, spec in ORACLE["filePlayback"].items():
        sut = _play(name)
        guitar = spec["settings"]["measurementType"] == "Generic Guitar"
        lookup = _guitar_peak if guitar else _material_peak
        computed: dict[str, Any] = {}

        for block in ("peaks", "averagedPeaks"):
            if block not in spec:
                continue
            computed[block] = [
                _record(lookup(sut, p["role"]),
                        [k for k in ("frequency", "magnitude", "q") if k in p],
                        name, p["role"])
                for p in spec[block]
            ]

        if "perTap" in spec:
            # TapEntry.resolved_mode_peaks() — the path the comparison view and the
            # PDF export use, and the one the per-tap assertions read.
            rows = []
            for entry, expected in zip(sut.tap_entries, spec["perTap"], strict=True):
                mode_peaks = entry.resolved_mode_peaks()
                rows.append({
                    "tap": expected["tap"],
                    "peaks": [
                        _record(mode_peaks.get(_guitar_mode(p["role"])),
                                [k for k in ("frequency", "magnitude", "q") if k in p],
                                f"{name} tap {expected['tap']}", p["role"])
                        for p in expected["peaks"]
                    ],
                })
            computed["perTap"] = rows

        if "ringOutSec" in spec:
            if sut.current_decay_time is None:
                raise AssertionError(f"{name}: no ring-out was measured")
            computed["ringOutSec"] = float(sut.current_decay_time)

        out[name] = computed
    return out


def compute_gated_fft() -> dict[str, Any]:
    """Every gatedFft case, shaped as the oracle shapes it."""
    from guitar_tap.models.realtime_fft_analyzer import RealtimeFFTAnalyzer

    sample_rate = 48000.0
    duration = 0.4
    out: dict[str, Any] = {}

    for name in ORACLE["gatedFft"]:
        spec = gated(name)
        analyzer = RealtimeFFTAnalyzer.for_testing(sample_rate=int(sample_rate))

        # Silence is the signal with no tones. The same builder the GFFT tests use (#17 F49).
        tones = [] if spec.get("signal") == "silence" else spec["tones"]
        signal = make_gated_test_signal(tones, sample_rate, duration)

        mags, freqs = analyzer.compute_gated_fft(signal, sample_rate)
        computed: dict[str, Any] = {}

        if "expected" in spec:
            computed["expected"] = [
                {"hz": e["hz"], "db": gated_magnitude_at(float(e["hz"]), mags, freqs)}
                for e in spec["expected"]
            ]
            if "deltaDb" in spec:
                first, second = computed["expected"][0], computed["expected"][1]
                computed["deltaDb"] = second["db"] - first["db"]
        if "maxDb" in spec:
            computed["maxDb"] = float(max(mags))

        out[name] = computed
    return out


def compute_all() -> dict[str, Any]:
    """Everything this configuration computes, in the oracle's own shape."""
    return {"filePlayback": compute_file_playback(), "gatedFft": compute_gated_fft()}
