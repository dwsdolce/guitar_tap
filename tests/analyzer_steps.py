# @parity tooling/analyzer-steps
"""The steps the shared scenario case files drive the analyzer with, each through the app's own path:
the settings Settings writes, the Taps control, New Tap, Pause, Resume, Cancel, a capture finished on
a synthetic tap, Accept, Redo, and audio fed through the analyzer's clock. A case file names its
steps; this runs one. Mirrors Swift GuitarTapTests/AnalyzerSteps.swift and web test/analyzerSteps.ts.
"""
from __future__ import annotations

from audio_clock_feed import AUDIO_FEED_CHUNK_SECONDS, advance_audio
from synthetic_tap import synthetic_tap

from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings as TDS
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

_MATERIAL_PHASES = {"L": MaterialTapPhase.CAPTURING_LONGITUDINAL, "C": MaterialTapPhase.CAPTURING_CROSS,
                    "FLC": MaterialTapPhase.CAPTURING_FLC}


def run_analyzer_step(step: dict, sut: TapToneAnalyzer) -> bool:
    """Run ``step`` on ``sut`` if it is one of the shared steps, and say whether it was.

    - ``{"settings": {"type": saved name, "measureFlc": bool}}`` — as Settings writes them
    - ``{"setTaps": n}`` — the Taps control
    - ``{"setThreshold": dB}`` — the Threshold control
    - ``{"setPeakMin": dB}`` — the Peak Min control
    - ``{"newTap": true}``, ``{"pause": true}``, ``{"resume": true}``, ``{"cancel": true}``
    - ``{"guitarTap": hz}`` — a guitar capture finished on a synthetic tap one capture long
    - ``{"materialTap": {"phase": "L" | "C" | "FLC", "hz": hz}}`` — a material capture on a 0.5 s tap
    - ``{"accept": true}``, ``{"redo": true}`` — the phase under review
    - ``{"advance": "tapCooldown" | "captureWindow" | "warmupPeriod" | seconds, "fraction"?: f, "extra"?: s,
      "level"?: dB}`` — that much audio (quiet unless ``level`` is given)
    - ``{"audioChunks": n, "level": dB}`` — n chunks of audio at that level (two loud ones are a tap)
    """
    if "settings" in step:
        settings = step["settings"]
        if "type" in settings:
            TDS.set_measurement_type(MeasurementType(settings["type"]))
        if "measureFlc" in settings:
            TDS.set_measure_flc(settings["measureFlc"])
    elif "setTaps" in step:
        sut.set_tap_num(step["setTaps"])
    elif "setThreshold" in step:
        sut.tap_detection_threshold = float(step["setThreshold"])
    elif "setPeakMin" in step:
        sut.peak_min_threshold = float(step["setPeakMin"])
    elif step.get("newTap"):
        sut.start_tap_sequence()
    elif step.get("pause"):
        sut.pause_tap_detection()
    elif step.get("resume"):
        sut.resume_tap_detection()
    elif step.get("cancel"):
        sut.cancel_tap_sequence()
    elif "guitarTap" in step:
        sut.finish_guitar_gated_capture(synthetic_tap(step["guitarTap"], sut.mic.fft_size / 48000.0), 48000.0)
    elif "materialTap" in step:
        tap = step["materialTap"]
        sut.finish_gated_fft_capture(synthetic_tap(tap["hz"], 0.5), 48000.0, _MATERIAL_PHASES[tap["phase"]])
    elif step.get("accept"):
        sut.accept_current_phase()
    elif step.get("redo"):
        sut.redo_current_phase()
    elif "advance" in step:
        advance = step["advance"]
        seconds = {"tapCooldown": sut.tap_cooldown, "captureWindow": sut.capture_window,
                   "warmupPeriod": sut.warmup_period}.get(advance, advance)
        advance_audio(sut, seconds * step.get("fraction", 1.0) + step.get("extra", 0.0), step.get("level", -90.0))
    elif "audioChunks" in step:
        advance_audio(sut, step["audioChunks"] * AUDIO_FEED_CHUNK_SECONDS, step["level"])
    else:
        return False
    return True


def make_steps_analyzer() -> TapToneAnalyzer:
    """A fresh analyzer as the shared scenario cases start one: threshold -40, Taps 1."""
    sut = TapToneAnalyzer.for_testing()
    sut.set_tap_num(1)
    sut.tap_detection_threshold = -40.0
    return sut
