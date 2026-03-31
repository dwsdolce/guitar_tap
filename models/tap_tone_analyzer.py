"""
Tap-tone analysis coordinator — mirrors Swift TapToneAnalyzer.swift.

The Swift TapToneAnalyzer class is split across nine Swift files:
  TapToneAnalyzer.swift                     — class declaration, stored properties, init
  TapToneAnalyzer+Control.swift             — start, stop, reset, FFT parameter changes
  TapToneAnalyzer+PeakAnalysis.swift        — findPeaks, parabolic interp, Q-factor
  TapToneAnalyzer+SpectrumCapture.swift     — gated FFT, 200 ms pre-roll, 400 ms gate, HPS
  TapToneAnalyzer+TapDetection.swift        — hysteresis tap detector state machine
  TapToneAnalyzer+DecayTracking.swift       — ring-out / decay time tracking
  TapToneAnalyzer+AnnotationManagement.swift — annotation offsets, display-mode toggling
  TapToneAnalyzer+ModeOverrideManagement.swift — per-peak UserAssignedMode overrides
  TapToneAnalyzer+MeasurementManagement.swift — build TapToneMeasurement, save/load
  TapToneAnalyzer+AnalysisHelpers.swift     — dominant peak query, tap-tone ratio, in-range

Python mapping:

  TapToneAnalyzer+TapDetection.swift  →  TapDetector (this file)
  TapToneAnalyzer+DecayTracking.swift →  DecayTracker (this file)
  TapToneAnalyzer+SpectrumCapture.swift → PlateCapture (this file)

  The remaining extensions are now implemented in TapToneAnalyzer (this file):
    +Control               → TapToneAnalyzer.start_analyzer / stop_analyzer / ...
    +PeakAnalysis          → TapToneAnalyzer.find_peaks / _apply_mode_priority / ...
    +AnnotationManagement  → delegated to fft_annotations.FftAnnotations (owned by FftCanvas)
    +ModeOverrideManagement → peaks_model.PeaksModel.set_mode_override (unchanged)
    +MeasurementManagement  → TapToneAnalyzer.set_measurement_complete / load_comparison / ...
    +AnalysisHelpers        → TapToneAnalyzer query methods

  FftCanvas is now a thin display widget that creates a TapToneAnalyzer,
  connects its signals, and delegates all analysis calls.
"""

from __future__ import annotations

# ── Imports ────────────────────────────────────────────────────────────────────

import time as _time
from enum import Enum, auto

import numpy.typing as npt
from PyQt6 import QtCore

from . import realtime_fft_analyzer as _rfa


# ── DecayTracker ───────────────────────────────────────────────────────────────
# Mirrors Swift TapToneAnalyzer+DecayTracking.swift

class DecayTracker(QtCore.QObject):
    """Measures ring-out time after a tap.

    Call start() when a tap is detected.
    Call update() on every subsequent RMS level sample.
    ringOutMeasured is emitted once when the level drops
    decay_threshold_db below the tap peak.

    Amplitude uses the 0–100 scale (dBFS + 100) used throughout the app.

    Mirrors Swift TapToneAnalyzer+DecayTracking.swift decay tracking logic.
    """

    ringOutMeasured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)  # seconds

    def __init__(
        self,
        decay_threshold_db: float = 15.0,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.decay_threshold_db = decay_threshold_db
        self._tracking: bool = False
        self._peak_amplitude: float = 0.0
        self._start_time: float = 0.0

    def start(self, amplitude: int) -> None:
        """Begin tracking from this tap's peak amplitude."""
        self._peak_amplitude = float(amplitude)
        self._start_time = _time.monotonic()
        self._tracking = True

    def update(self, amplitude: int) -> None:
        """Feed the current amplitude; emits ringOutMeasured if threshold crossed."""
        if not self._tracking:
            return
        if float(amplitude) <= self._peak_amplitude - self.decay_threshold_db:
            elapsed = _time.monotonic() - self._start_time
            self._tracking = False
            self.ringOutMeasured.emit(elapsed)

    def reset(self) -> None:
        self._tracking = False


# ── TapDetector ────────────────────────────────────────────────────────────────
# Mirrors Swift TapToneAnalyzer+TapDetection.swift
#
# Matches the Swift GuitarTap TapToneAnalyzer+TapDetection.swift
# implementation in both algorithm and timing:
#
# Guitar mode  — absolute threshold on the RMS input level.
#     risingThreshold  = tapDetectionThreshold
#     fallingThreshold = tapDetectionThreshold − hysteresisMargin
#
# Plate/Brace mode — EMA-relative threshold on the RMS input level.
#     noiseFloor = α × level + (1 − α) × noiseFloor   (α = 0.05, τ ≈ 190 ms at 10 Hz)
#     headroom   = max(tapDetectionThreshold − noiseFloor, 10 dB)
#     risingThreshold  = noiseFloor + headroom
#     fallingThreshold = noiseFloor + max(headroom − hysteresisMargin, 4 dB)
#     Motivation: long-window continuous FFT dilutes plate/brace tap
#     transients by ~15 dB; adaptive thresholds reject small ambient
#     spikes while catching real taps 12-30 dB above the noise floor.
#
# Warmup and cooldown are measured in real time (seconds) so that
# behaviour is independent of the audio block size or call rate.

class TapDetector(QtCore.QObject):
    """Hysteresis rising-edge tap detector with Guitar and Plate/Brace modes.

    The detector is fed RMS input levels (0-100 scale, 0 = -100 dBFS,
    100 = 0 dBFS) from small audio buffers (~85 ms at 48 kHz), matching
    the Swift implementation's fast `inputLevelDB` path.

    Guitar mode  uses a fixed absolute threshold.
    Plate/Brace  uses an EMA noise-floor tracker to produce adaptive
                 rising and falling thresholds, making it robust to slowly
                 varying ambient noise while still catching sharp tap transients.

    States:
        WARMUP    — ignoring input for `warmup_s` seconds after start/reset.
        IDLE      — waiting for a rising edge above the effective threshold.
                    Checks time-based cooldown (`cooldown_s`) from the last
                    fired tap before emitting (matches Swift tapCooldown).
        TRIGGERED — tap confirmed (or cooldown-blocked rise); waiting for
                    level to drop below the falling threshold before rearming.

    Mirrors Swift TapToneAnalyzer+TapDetection.swift.
    """

    MODE_GUITAR: str = "guitar"
    MODE_PLATE_BRACE: str = "plate_brace"

    tapDetected: QtCore.pyqtSignal = QtCore.pyqtSignal()

    _WARMUP = "WARMUP"
    _IDLE = "IDLE"
    _TRIGGERED = "TRIGGERED"
    _COOLDOWN = "COOLDOWN"
    _PAUSED = "PAUSED"

    def __init__(
        self,
        tap_threshold: int = 60,
        hysteresis_margin: float = 3.0,
        warmup_s: float = 0.5,          # matches Swift warm-up period
        cooldown_s: float = 0.4,        # matches Swift tap cooldown
        mode: str = MODE_GUITAR,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.tap_threshold: int = tap_threshold
        self.hysteresis_margin: float = hysteresis_margin
        self.warmup_s: float = warmup_s
        self.cooldown_s: float = cooldown_s

        self._mode: str = mode

        # EMA noise-floor state for Plate/Brace mode
        # α = 0.05 → τ ≈ 190 ms at 10 Hz update rate (matches Swift)
        self._ema_alpha: float = 0.05
        self._noise_floor_db: float = -80.0   # dBFS; reset on mode switch
        self._min_headroom_db: float = 10.0   # minimum headroom safety floor
        self._min_falling_db: float = 4.0     # minimum falling headroom

        self._state: str = self._WARMUP
        self._state_entry_time: float = _time.monotonic()
        self._pre_pause_state: str = self._WARMUP
        self._last_tap_time: float | None = None  # time of last fired tap (for cooldown)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def is_paused(self) -> bool:
        return self._state == self._PAUSED

    def set_mode(self, mode: str) -> None:
        """Switch between Guitar and Plate/Brace detection algorithms.

        Resets the EMA noise-floor estimate when entering Plate/Brace mode
        so it adapts quickly to current conditions (matches Swift behaviour
        of re-anchoring state on mode transitions).
        """
        if mode == self._mode:
            return
        self._mode = mode
        if mode == self.MODE_PLATE_BRACE:
            self._noise_floor_db = -80.0  # will catch up within ~2 s at α=0.05

    def reset(self) -> None:
        """Restart warmup (call after device change, new tap sequence, etc.)."""
        import traceback as _tb
        print("TAP_DEBUG [TapDetector.reset] called from:")
        for line in _tb.format_stack()[:-1]:
            print("  ", line.strip())
        self._state = self._WARMUP
        self._state_entry_time = _time.monotonic()
        self._last_tap_time = None

    def set_tap_threshold(self, value: int) -> None:
        self.tap_threshold = value

    def set_hysteresis_margin(self, value: float) -> None:
        self.hysteresis_margin = max(1.0, value)

    def pause(self) -> None:
        if self._state != self._PAUSED:
            self._pre_pause_state = self._state
            self._state = self._PAUSED

    def resume(self) -> None:
        if self._state == self._PAUSED:
            self._state = self._pre_pause_state

    def cancel(self) -> None:
        """Cancel the current sequence and return to IDLE (no warmup)."""
        self._state = self._IDLE
        self._state_entry_time = _time.monotonic()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _compute_thresholds(self, level_db: float) -> tuple[float, float]:
        """Return (rising_threshold_dBFS, falling_threshold_dBFS).

        Guitar mode: fixed thresholds from the user-set tap_threshold.
        Plate/Brace: EMA-adaptive thresholds tracking the noise floor.
        Both match the corresponding Swift algorithm exactly.
        """
        tap_db = float(self.tap_threshold) - 100.0   # 0-100 → dBFS

        if self._mode == self.MODE_GUITAR:
            self._last_headroom: float = 0.0
            return tap_db, tap_db - self.hysteresis_margin

        # --- Plate/Brace EMA adaptive threshold ---
        self._noise_floor_db = (
            self._ema_alpha * level_db
            + (1.0 - self._ema_alpha) * self._noise_floor_db
        )
        headroom = max(tap_db - self._noise_floor_db, self._min_headroom_db)
        self._last_headroom = headroom
        rising  = self._noise_floor_db + headroom
        falling = self._noise_floor_db + max(
            headroom - self.hysteresis_margin, self._min_falling_db
        )
        return rising, falling

    # ------------------------------------------------------------------ #
    # Core update — call for every RMS level sample (~10-12 Hz)
    # ------------------------------------------------------------------ #

    def update(self, amplitude: int) -> None:
        """Feed the latest RMS input level (0–100 scale).

        Emits tapDetected exactly once per confirmed tap.
        Safe to call at any rate; warmup/cooldown use the monotonic clock.
        """
        if self._state == self._PAUSED:
            return

        level_db = float(amplitude) - 100.0          # 0-100 → dBFS
        rising_db, falling_db = self._compute_thresholds(level_db)

        # Work in 0-100 scale to stay consistent with the rest of the app
        rising_amp  = rising_db  + 100.0
        falling_amp = falling_db + 100.0

        now = _time.monotonic()

        # TAP_DEBUG: mode/threshold print (every frame, mirrors Swift detectTap top-of-function)
        if self._mode == self.MODE_PLATE_BRACE:
            print(
                f"TAP_DEBUG [detectTap] RELATIVE mode | "
                f"peakMag={level_db:.2f} noiseFloor={self._noise_floor_db:.2f} "
                f"headroom={getattr(self, '_last_headroom', 0.0):.2f} "
                f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                f"state={self._state}"
            )
        else:
            print(
                f"TAP_DEBUG [detectTap] ABSOLUTE mode | "
                f"peakMag={level_db:.2f} "
                f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                f"state={self._state}"
            )

        match self._state:
            case self._WARMUP:
                remaining = self.warmup_s - (now - self._state_entry_time)
                if remaining > 0:
                    print(
                        f"TAP_DEBUG [detectTap] WARMUP in progress | "
                        f"remaining={remaining:.2f}s peakMag={level_db:.2f}"
                    )
                else:
                    # Re-anchor to current level on warmup exit (Swift behaviour):
                    # don't fire immediately if signal is already above threshold.
                    if amplitude >= rising_amp:
                        self._state = self._TRIGGERED
                        print(
                            f"TAP_DEBUG [detectTap] WARMUP EXIT (already above) | "
                            f"peakMag={level_db:.2f} risingThresh={rising_db:.2f} "
                            f"→ state=TRIGGERED"
                        )
                    else:
                        self._state = self._IDLE
                        if self._mode == self.MODE_PLATE_BRACE:
                            print(
                                f"TAP_DEBUG [detectTap] WARMUP EXIT (relative) | "
                                f"peakMag={level_db:.2f} "
                                f"noiseFloorAnchored={self._noise_floor_db:.2f} "
                                f"risingAnchored={rising_db:.2f} isAboveThreshold=False"
                            )
                        else:
                            print(
                                f"TAP_DEBUG [detectTap] WARMUP EXIT (absolute) | "
                                f"peakMag={level_db:.2f} "
                                f"risingThresh={rising_db:.2f} isAboveThreshold=False"
                            )
                    self._state_entry_time = now

            case self._IDLE:
                now_above = amplitude >= rising_amp
                print(
                    f"TAP_DEBUG [detectTap] HYSTERESIS eval | "
                    f"peakMag={level_db:.2f} wasAbove=False nowAbove={now_above} "
                    f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                    f"isDetecting=True currentTapCount=?"
                )
                if now_above:
                    # Check time-based cooldown from last tap (matches Swift tapCooldown)
                    cooldown_remaining = (
                        self.cooldown_s - (now - self._last_tap_time)
                        if self._last_tap_time is not None else 0.0
                    )
                    if cooldown_remaining > 0:
                        print(
                            f"TAP_DEBUG [detectTap] COOLDOWN active | "
                            f"remaining={cooldown_remaining:.3f}s peakMag={level_db:.2f}"
                        )
                        # Signal is rising but still in cooldown — track as TRIGGERED
                        # without firing, so we wait for it to drop and re-arm.
                        self._state = self._TRIGGERED
                        self._state_entry_time = now
                    else:
                        print(
                            f"TAP_DEBUG [detectTap] RISING EDGE FIRED | "
                            f"peakMag={level_db:.2f} risingThresh={rising_db:.2f}"
                        )
                        self._last_tap_time = now
                        self._state = self._TRIGGERED
                        self._state_entry_time = now
                        self.tapDetected.emit()

            case self._TRIGGERED:
                now_above = amplitude >= falling_amp
                print(
                    f"TAP_DEBUG [detectTap] HYSTERESIS eval | "
                    f"peakMag={level_db:.2f} wasAbove=True nowAbove={now_above} "
                    f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                    f"isDetecting=False currentTapCount=?"
                )
                if not now_above:
                    print(
                        f"TAP_DEBUG [detectTap] FALLING EDGE | "
                        f"peakMag={level_db:.2f} fallingThresh={falling_db:.2f} "
                        f"— signal settled, returning to IDLE"
                    )
                    self._state = self._IDLE
                    self._state_entry_time = now

            case _:
                pass


# ── PlateCapture ───────────────────────────────────────────────────────────────
# Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift
#
# State machine for plate / brace material tap analysis.
#
# Brace (1 tap):
#     IDLE → WAITING_L → COMPLETE
#     analysisComplete emits (f_long, 0.0, 0.0)
#
# Plate without FLC (2 taps):
#     IDLE → WAITING_L → WAITING_C → COMPLETE
#     analysisComplete emits (f_long, f_cross, 0.0)
#
# Plate with FLC (3 taps):
#     IDLE → WAITING_L → WAITING_C → WAITING_FLC → COMPLETE
#     analysisComplete emits (f_long, f_cross, f_flc)
#
# The caller feeds each detected tap's linear magnitude spectrum via on_tap().
# HPS is used to extract the dominant fundamental frequency from each tap.
# The dB magnitude spectrum for each phase is stored for snapshot persistence.

class PlateCapture(QtCore.QObject):
    """Plate / brace fundamental-frequency capture via HPS.

    Mirrors Swift TapToneAnalyzer+SpectrumCapture.swift.
    """

    stateChanged:    QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    fLCaptured:      QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    fCCaptured:      QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    fFLCCaptured:    QtCore.pyqtSignal = QtCore.pyqtSignal(float)       # Hz
    analysisComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)  # fL, fC, fFLC

    class State(Enum):
        IDLE        = auto()
        WAITING_L   = auto()
        WAITING_C   = auto()
        WAITING_FLC = auto()
        COMPLETE    = auto()

    def __init__(
        self,
        sample_freq: int = 48000,
        n_f: int = 65536,
        f_min: float = 50.0,
        f_max: float = 2000.0,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sample_freq = sample_freq
        self._n_f = n_f
        self._f_min = f_min
        self._f_max = f_max
        self._state = self.State.IDLE
        self._is_brace: bool = False
        self._measure_flc: bool = False
        self._f_long: float = 0.0
        self._f_cross: float = 0.0
        self._f_flc: float = 0.0
        self._long_mag_db:  npt.NDArray | None = None
        self._cross_mag_db: npt.NDArray | None = None
        self._flc_mag_db:   npt.NDArray | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self, is_brace: bool = False, measure_flc: bool = False) -> None:
        """Begin longitudinal tap capture.

        Args:
            is_brace:    True for brace (1 tap: longitudinal only).
                         False for plate (2 or 3 taps).
            measure_flc: True to add the FLC diagonal-tap phase (plate only).
        """
        self._is_brace    = is_brace
        self._measure_flc = measure_flc and not is_brace
        self._f_long  = 0.0
        self._f_cross = 0.0
        self._f_flc   = 0.0
        self._long_mag_db  = None
        self._cross_mag_db = None
        self._flc_mag_db   = None
        self._state = self.State.WAITING_L
        self.stateChanged.emit("Tap long-grain (L) direction…")

    def reset(self) -> None:
        """Return to idle and clear captured values."""
        self._state = self.State.IDLE
        self._f_long  = 0.0
        self._f_cross = 0.0
        self._f_flc   = 0.0
        self._long_mag_db  = None
        self._cross_mag_db = None
        self._flc_mag_db   = None
        self.stateChanged.emit("")

    def on_tap(
        self,
        mag_linear: npt.NDArray,
        mag_db: npt.NDArray | None = None,
    ) -> None:
        """Call this when the tap detector fires.

        Args:
            mag_linear: Linear-scale FFT magnitude spectrum (for HPS).
            mag_db:     dB-scale FFT magnitude spectrum (stored per-phase for
                        snapshot persistence).  May be None if unavailable.
        """
        if self._state not in (
            self.State.WAITING_L,
            self.State.WAITING_C,
            self.State.WAITING_FLC,
        ):
            return

        freq = _rfa.hps_peak_freq(
            mag_linear,
            self._sample_freq,
            self._n_f,
            f_min=self._f_min,
            f_max=self._f_max,
        )
        if freq <= 0:
            return

        if self._state == self.State.WAITING_L:
            self._f_long       = freq
            self._long_mag_db  = mag_db.copy() if mag_db is not None else None
            self.fLCaptured.emit(freq)
            if self._is_brace:
                self._state = self.State.COMPLETE
                self.stateChanged.emit(f"L: {freq:.1f} Hz — complete")
                self.analysisComplete.emit(self._f_long, 0.0, 0.0)
            else:
                self._state = self.State.WAITING_C
                self.stateChanged.emit(
                    f"L: {freq:.1f} Hz — rotate 90°, then tap cross-grain (C) direction…"
                )

        elif self._state == self.State.WAITING_C:
            self._f_cross      = freq
            self._cross_mag_db = mag_db.copy() if mag_db is not None else None
            self.fCCaptured.emit(freq)
            if self._measure_flc:
                self._state = self.State.WAITING_FLC
                self.stateChanged.emit(
                    f"L: {self._f_long:.1f} Hz  C: {freq:.1f} Hz"
                    " — now tap FLC (diagonal) direction…"
                )
            else:
                self._state = self.State.COMPLETE
                self.stateChanged.emit(
                    f"L: {self._f_long:.1f} Hz  C: {freq:.1f} Hz — complete"
                )
                self.analysisComplete.emit(self._f_long, self._f_cross, 0.0)

        else:  # WAITING_FLC
            self._f_flc      = freq
            self._flc_mag_db = mag_db.copy() if mag_db is not None else None
            self.fFLCCaptured.emit(freq)
            self._state = self.State.COMPLETE
            self.stateChanged.emit(
                f"L: {self._f_long:.1f} Hz  C: {self._f_cross:.1f} Hz"
                f"  FLC: {freq:.1f} Hz — complete"
            )
            self.analysisComplete.emit(self._f_long, self._f_cross, self._f_flc)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_active(self) -> bool:
        """True while waiting for any tap phase."""
        return self._state in (
            self.State.WAITING_L,
            self.State.WAITING_C,
            self.State.WAITING_FLC,
        )

    @property
    def f_long(self) -> float:
        return self._f_long

    @property
    def f_cross(self) -> float:
        return self._f_cross

    @property
    def f_flc(self) -> float:
        return self._f_flc

    @property
    def long_mag_db(self) -> npt.NDArray | None:
        """dB spectrum captured during the longitudinal tap phase."""
        return self._long_mag_db

    @property
    def cross_mag_db(self) -> npt.NDArray | None:
        """dB spectrum captured during the cross-grain tap phase."""
        return self._cross_mag_db

    @property
    def flc_mag_db(self) -> npt.NDArray | None:
        """dB spectrum captured during the FLC diagonal tap phase."""
        return self._flc_mag_db


# ── TapToneAnalyzer ────────────────────────────────────────────────────────────
# Mirrors the top-level Swift TapToneAnalyzer class and its extensions:
#   TapToneAnalyzer.swift                   — stored properties, init
#   TapToneAnalyzer+Control.swift           — start/stop/reset
#   TapToneAnalyzer+PeakAnalysis.swift      — findPeaks, _apply_mode_priority
#   TapToneAnalyzer+MeasurementManagement.swift — freeze/unfreeze, load_comparison
#   TapToneAnalyzer+AnalysisHelpers.swift   — dominant_peak, threshold helpers

class TapToneAnalyzer(QtCore.QObject):
    """Central analysis coordinator — owns all analysis state and business logic.

    Mirrors Swift's TapToneAnalyzer ObservableObject.  FftCanvas (the view)
    creates one of these, connects its signals to rendering slots, and delegates
    all analysis method calls to it.

    Emits Qt signals rather than Swift @Published properties so the view layer
    can respond to state changes without polling.
    """

    # ── Signals (Python equivalents of Swift @Published properties) ────────
    # New peak list emitted after every analysis frame and after threshold/range changes.
    peaksChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)          # ndarray (N, 3)
    # Full spectrum ready for the view to draw.
    spectrumUpdated: QtCore.pyqtSignal = QtCore.pyqtSignal(object, object)  # (freqs, mags_db)
    # A single tap has been fully captured (all required taps averaged).
    tapDetectedSignal: QtCore.pyqtSignal = QtCore.pyqtSignal()
    # Live tap count update: (captured, total).
    tapCountChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)
    # Ring-out time measured by DecayTracker (seconds).
    ringOutMeasured: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    # Input level 0-100 scale (dBFS + 100).
    levelChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    # FFT frame diagnostics: (fps, sample_dt, processing_dt).
    framerateUpdate: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)
    # Averaging: number of completed averages.
    averagesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int)
    # Emitted on every live FFT frame (for average-enable logic).
    newSample: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Display mode changed: emits the new DisplayMode enum value.
    displayModeChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(object)
    # Measurement complete state changed.
    measurementComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Hot-plug: list[str] of current input device names.
    devicesChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(list)
    # Hot-plug: name of the device that disappeared.
    currentDeviceLost: QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    # Plate/brace phase status text for display.
    plateStatusChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(str)
    # Plate analysis complete: (fL, fC, fFLC) Hz.
    plateAnalysisComplete: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float, float)
    # Tap detection pause state changed.
    tapDetectionPaused: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Emitted when comparison overlay data changes (True=entering, False=leaving).
    comparisonChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(bool)
    # Emitted when frequency range changes (fmin, fmax).
    freqRangeChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(int, int)
    # Peak info for status bar: (peak_hz, peak_db).
    peakInfoChanged: QtCore.pyqtSignal = QtCore.pyqtSignal(float, float)
    # Internal: fired from hotplug monitor thread → main thread (no-arg).
    _devicesRefreshed: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(
        self,
        parent_widget,
        fft_data,
        saved_device_index,
        saved_device_name: str,
        calibration_corrections,
        guitar_type,
    ) -> None:
        """
        Args:
            parent_widget:         The FftCanvas (QObject parent).
            fft_data:              FftData instance (sample_freq, n_f, window_fcn, …).
            saved_device_index:    Resolved input device index, or None for default.
            saved_device_name:     Human-readable name of that device (may be "").
            calibration_corrections: ndarray of per-bin dB corrections, or None.
            guitar_type:           GuitarType enum value for mode classification.
        """
        # Lazily import here to avoid a circular import: fft_canvas → models.tap_tone_analyzer
        # → fft_canvas.  These imports are only needed at runtime, not at module load.
        import sounddevice as _sd
        import numpy as _np
        from models.realtime_fft_analyzer import Microphone as _Mic
        from models import guitar_type as _gt
        from models import guitar_mode as _gm
        from models import measurement_type as _mt_mod
        from models import microphone_calibration as _mc_mod
        import app_settings as _as

        super().__init__(parent_widget)

        self._sd = _sd
        self._np = _np
        self._gm = _gm
        self._as = _as
        self._mc_mod = _mc_mod

        # ── Audio engine (mirrors Swift's analyzer: RealtimeFFTAnalyzer) ──
        self._devicesRefreshed.connect(self._on_devices_refreshed)
        self.mic: _Mic = _Mic(
            parent_widget,
            rate=fft_data.sample_freq,
            chunksize=4096,
            device_index=saved_device_index,
            on_devices_changed=self._devicesRefreshed.emit,
        )

        # ── FFT configuration ──────────────────────────────────────────────
        self.fft_data = fft_data
        import numpy as np
        x_axis = np.arange(0, fft_data.h_n_f + 1)
        self.freq = x_axis * fft_data.sample_freq // fft_data.n_f

        # ── Calibration ────────────────────────────────────────────────────
        self._calibration_corrections = calibration_corrections
        self._calibration_device_name: str = saved_device_name

        # ── Guitar/mode classification ─────────────────────────────────────
        self._guitar_type = guitar_type

        # ── Display mode (mirrors Swift AnalysisDisplayMode) ───────────────
        # Imported lazily from fft_canvas to avoid circular import at module load.
        # The DisplayMode enum lives in fft_canvas.py; we import it on first use.
        self._display_mode = None   # set to DisplayMode.LIVE by FftCanvas after import

        # ── Measurement state ──────────────────────────────────────────────
        self.is_measurement_complete: bool = False

        # ── Peak analysis state ────────────────────────────────────────────
        import numpy as np
        self.threshold: int = 60                          # 0-100 scale
        self.fmin: int = 0
        self.fmax: int = 1000
        self.n_fmin: int = 0
        self.n_fmax: int = 0
        self.saved_mag_y_db = np.array([])
        self.saved_peaks = np.zeros((0, 3))               # (freq, mag, Q)
        self.b_peaks_freq = np.array([])
        self.peaks_f_min_index: int = 0
        self.peaks_f_max_index: int = 0
        self._loaded_measurement_peaks = None             # ndarray or None
        self.selected_peak: float = 0.0
        self._mode_color_map: dict = {}                   # freq → RGB tuple

        # ── Averaging ──────────────────────────────────────────────────────
        self.avg_enable: bool = False
        self.max_average_count: int = 1
        self.mag_y_sum = []
        self.num_averages: int = 0

        # ── Multi-tap accumulator ─────────────────────────────────────────
        self._tap_num: int = 1
        self._tap_spectra: list = []

        # ── Auto-scale ────────────────────────────────────────────────────
        self._auto_scale_db: bool = False

        # ── Measurement type ──────────────────────────────────────────────
        self._measurement_type = _mt_mod.MeasurementType.CLASSICAL

        # ── Plate/brace capture ───────────────────────────────────────────
        self.plate_capture = PlateCapture(
            sample_freq=fft_data.sample_freq,
            n_f=fft_data.n_f,
            parent=self,
        )
        self.plate_capture.stateChanged.connect(self.plateStatusChanged)
        self.plate_capture.analysisComplete.connect(self.plateAnalysisComplete)
        self._current_mag_y = np.array([])

        # ── Comparison overlay data ───────────────────────────────────────
        self.comparison_labels: list = []        # list of (label, color) tuples
        # _comparison_data is for the analyzer's knowledge of what's being compared;
        # actual PlotDataItem curves live in FftCanvas.
        self._comparison_data: list = []

        # ── Processing thread (created/managed by FftCanvas) ─────────────
        # FftCanvas sets self._proc_thread after constructing TapToneAnalyzer.
        self._proc_thread = None

    # ------------------------------------------------------------------ #
    # display_mode property — kept in sync with FftCanvas.display_mode
    # ------------------------------------------------------------------ #

    @property
    def display_mode(self):
        return self._display_mode

    @display_mode.setter
    def display_mode(self, value) -> None:
        self._display_mode = value
        self.displayModeChanged.emit(value)

    @property
    def is_comparing(self) -> bool:
        """True when in COMPARISON display mode."""
        from fft_canvas import DisplayMode
        return self._display_mode == DisplayMode.COMPARISON

    # ------------------------------------------------------------------ #
    # Hot-plug (mirrors FftCanvas._on_devices_refreshed)
    # ------------------------------------------------------------------ #

    def _on_devices_refreshed(self) -> None:
        """Handle a hot-plug event (always on main thread)."""
        self.mic.reinitialize_portaudio()
        try:
            names: list = sorted(
                str(d["name"]) for d in self._sd.query_devices() if d["max_input_channels"] > 0
            )
        except Exception:
            names = []
        self.devicesChanged.emit(names)
        if (
            self._calibration_device_name
            and self._calibration_device_name not in names
        ):
            self.currentDeviceLost.emit(self._calibration_device_name)

    # ------------------------------------------------------------------ #
    # Calibration (mirrors TapToneAnalyzer+Control.swift device/cal methods)
    # ------------------------------------------------------------------ #

    def load_calibration(self, path: str) -> bool:
        """Load and interpolate a calibration file onto the FFT bin grid."""
        import models.microphone_calibration as _mc
        try:
            cal_data = _mc.parse_cal_file(path)
            self._calibration_corrections = _mc.interpolate_to_bins(cal_data, self.freq)
            if self._proc_thread is not None:
                self._proc_thread.set_calibration(self._calibration_corrections)
            return True
        except Exception:
            return False

    def load_calibration_from_profile(self, cal) -> None:
        """Apply a pre-parsed MicrophoneCalibration profile to the FFT pipeline."""
        self._calibration_corrections = cal.interpolate_to_bins(self.freq)
        if self._proc_thread is not None:
            self._proc_thread.set_calibration(self._calibration_corrections)

    def clear_calibration(self) -> None:
        """Remove the active calibration."""
        self._calibration_corrections = None
        if self._proc_thread is not None:
            self._proc_thread.set_calibration(None)

    def current_calibration_device(self) -> str:
        """Device name the active calibration is associated with."""
        return self._calibration_device_name

    def set_device(self, device_index: int) -> None:
        """Switch to a different input device and auto-load its calibration."""
        import app_settings as _as
        self.mic.set_device(device_index)
        try:
            dev_name = str(self._sd.query_devices(device_index)["name"])
        except Exception:
            dev_name = ""
        self._calibration_device_name = dev_name
        cal_path = _as.AppSettings.calibration_for_device(dev_name)
        if cal_path:
            self.load_calibration(cal_path)
        else:
            self.clear_calibration()

    # ------------------------------------------------------------------ #
    # Tap detector control (delegated to _proc_thread)
    # ------------------------------------------------------------------ #

    def reset_tap_detector(self) -> None:
        if self._proc_thread is not None:
            self._proc_thread.reset_tap_detector()

    def set_tap_threshold(self, value: int) -> None:
        if self._proc_thread is not None:
            self._proc_thread.set_tap_threshold(value)

    def set_hysteresis_margin(self, value: float) -> None:
        if self._proc_thread is not None:
            self._proc_thread.set_hysteresis_margin(value)

    def pause_tap_detection(self) -> None:
        if self._proc_thread is not None:
            self._proc_thread.pause_tap_detection()
        self.tapDetectionPaused.emit(True)

    def resume_tap_detection(self) -> None:
        if self._proc_thread is not None:
            self._proc_thread.resume_tap_detection()
        self.tapDetectionPaused.emit(False)

    def cancel_tap_sequence(self) -> None:
        self._tap_spectra.clear()
        if self._proc_thread is not None:
            self._proc_thread.cancel_tap_sequence_in_thread()
        self.tapCountChanged.emit(0, self._tap_num)

    # ------------------------------------------------------------------ #
    # Tap sequence management
    # ------------------------------------------------------------------ #

    def start_tap_sequence(self) -> None:
        """Begin a fresh tap sequence: clear accumulated spectra and restart warmup."""
        self._tap_spectra.clear()
        self.reset_tap_detector()
        self.tapCountChanged.emit(0, self._tap_num)

    def set_tap_num(self, n: int) -> None:
        """Set how many taps to accumulate before freezing."""
        self._tap_num = max(1, n)
        self._tap_spectra.clear()

    # ------------------------------------------------------------------ #
    # Measurement type
    # ------------------------------------------------------------------ #

    def set_measurement_type(self, measurement_type) -> None:
        """Switch between Guitar / Plate / Brace analysis modes."""
        import models.measurement_type as _mt_mod
        if isinstance(measurement_type, str):
            measurement_type = _mt_mod.MeasurementType.from_combo_values(measurement_type, "")
        self._measurement_type = measurement_type
        if self._proc_thread is not None:
            self._proc_thread.set_measurement_type(measurement_type.is_guitar)

    # ------------------------------------------------------------------ #
    # Measurement complete
    # ------------------------------------------------------------------ #

    def set_measurement_complete(self, is_complete: bool) -> None:
        """Freeze/unfreeze the spectrum and reset related state."""
        self.is_measurement_complete = is_complete
        if self._proc_thread is not None:
            self._proc_thread.set_measurement_complete(is_complete)
        if not is_complete:
            import numpy as np
            self._tap_spectra.clear()
            self._loaded_measurement_peaks = None
            # Clear comparison overlay when starting a new tap
            self._clear_comparison_state()
        self.measurementComplete.emit(is_complete)

    def _clear_comparison_state(self) -> None:
        """Clear the analyzer's comparison data (view curves cleared by FftCanvas)."""
        from fft_canvas import DisplayMode
        self._display_mode = DisplayMode.LIVE
        self.comparison_labels.clear()
        self._comparison_data.clear()

    # ------------------------------------------------------------------ #
    # Peak analysis (mirrors TapToneAnalyzer+PeakAnalysis.swift)
    # ------------------------------------------------------------------ #

    def set_threshold(self, threshold: int) -> None:
        """Set the peak-detection threshold (0-100 scale)."""
        self.threshold = threshold
        if self._loaded_measurement_peaks is not None:
            self._emit_loaded_peaks_at_threshold()
        else:
            self.find_peaks(self.saved_mag_y_db)

    def set_fmin(self, fmin: int) -> None:
        self.update_axis(fmin, self.fmax)

    def set_fmax(self, fmax: int) -> None:
        self.update_axis(self.fmin, fmax)

    def update_axis(self, fmin: int, fmax: int, init: bool = False) -> None:
        """Update the frequency analysis range."""
        if fmin < fmax:
            self.fmin = fmin
            self.fmax = fmax
            self.n_fmin = (self.fft_data.n_f * fmin) // self.fft_data.sample_freq
            self.n_fmax = (self.fft_data.n_f * fmax) // self.fft_data.sample_freq
            if not init:
                if self._loaded_measurement_peaks is not None:
                    self._emit_loaded_peaks_at_threshold()
                else:
                    self.find_peaks(self.saved_mag_y_db)

    def set_max_average_count(self, max_average_count: int) -> None:
        self.max_average_count = max_average_count

    def reset_averaging(self) -> None:
        self.num_averages = 0

    def set_avg_enable(self, avg_enable: bool) -> None:
        self.avg_enable = avg_enable

    def set_auto_scale(self, enabled: bool) -> None:
        self._auto_scale_db = enabled

    def _apply_mode_priority(self, peaks) -> "npt.NDArray":
        """Apply mode-priority selection and 2 Hz deduplication.

        Exact copy of FftCanvas._apply_mode_priority — all logic preserved.
        """
        import numpy as np
        from models import guitar_mode as gm

        if peaks.shape[0] == 0:
            return peaks

        freqs = peaks[:, 0]
        mags  = peaks[:, 1]

        known_modes = sorted(
            [gm.GuitarMode.AIR, gm.GuitarMode.TOP, gm.GuitarMode.BACK,
             gm.GuitarMode.DIPOLE, gm.GuitarMode.RING_MODE, gm.GuitarMode.UPPER_MODES],
            key=lambda m: m.mode_range(self._guitar_type)[0],
        )
        guaranteed: set = set()
        last_claimed_freq: float = -1.0

        for mode in known_modes:
            lo, hi = mode.mode_range(self._guitar_type)
            candidates = np.where(
                (freqs >= lo) & (freqs <= hi) & (freqs > last_claimed_freq)
            )[0]
            if candidates.size == 0:
                continue
            best = int(candidates[np.argmax(mags[candidates])])
            if any(abs(freqs[best] - freqs[g]) < 2.0 for g in guaranteed):
                continue
            guaranteed.add(best)
            last_claimed_freq = float(freqs[best])

        used = np.zeros(len(freqs), dtype=bool)
        kept: list = []
        for i in np.argsort(-mags):
            idx = int(i)
            if not used[idx]:
                kept.append(idx)
                used |= np.abs(freqs - freqs[idx]) < 2.0

        kept_set = set(kept)
        for g_idx in guaranteed:
            if g_idx not in kept_set:
                kept.append(g_idx)

        return peaks[sorted(kept, key=lambda i: freqs[i])]

    def find_peaks(self, mag_y_db) -> "tuple[bool, npt.NDArray]":
        """Detect, interpolate, and deduplicate peaks above threshold.

        Returns (triggered, peaks_array) where peaks_array has columns (freq, mag, Q).
        Emits peaksChanged with the in-viewport subset.

        Exact copy of FftCanvas.find_peaks — all logic preserved.
        """
        import numpy as np
        from models import realtime_fft_analyzer as f_a

        if not np.any(mag_y_db):
            return False, self.saved_peaks

        ploc = f_a.peak_detection(mag_y_db, self.threshold - 100)
        iploc, peaks_mag = f_a.peak_interp(mag_y_db, ploc)

        peaks_freq = (iploc * self.fft_data.sample_freq) / float(self.fft_data.n_f)

        if peaks_mag.size > 0:
            max_peaks_mag = np.max(peaks_mag)
            q_values = f_a.peak_q_factor(
                mag_y_db, ploc, iploc, peaks_mag,
                self.fft_data.sample_freq, self.fft_data.n_f,
            )
            peaks = np.column_stack((peaks_freq, peaks_mag, q_values))
            peaks = self._apply_mode_priority(peaks)
            if peaks.shape[0] > 0:
                peaks_freq = peaks[:, 0]
                max_peaks_mag = np.max(peaks[:, 1])
            else:
                peaks_freq = np.array([])
                max_peaks_mag = -100
        else:
            max_peaks_mag = -100
            peaks = np.zeros((0, 3))

        if max_peaks_mag > (self.threshold - 100):
            self.saved_mag_y_db = mag_y_db
            self.saved_peaks = peaks
            triggered = True

            self.peaks_f_min_index = 0
            self.peaks_f_max_index = 0
            b_peaks_f_indices = np.nonzero(
                (peaks_freq < self.fmax) & (peaks_freq > self.fmin)
            )
            if len(b_peaks_f_indices[0]) > 0:
                self.peaks_f_min_index = b_peaks_f_indices[0][0]
                self.peaks_f_max_index = b_peaks_f_indices[0][-1] + 1

            if self.peaks_f_max_index > 0:
                self.b_peaks_freq = peaks_freq[
                    self.peaks_f_min_index : self.peaks_f_max_index
                ]
                peaks_data = peaks[self.peaks_f_min_index : self.peaks_f_max_index]
                self.peaksChanged.emit(peaks_data)
            else:
                self.b_peaks_freq = []
                self.peaksChanged.emit(np.zeros((0, 3)))
        else:
            self.saved_peaks = np.zeros((0, 3))
            self.peaksChanged.emit(self.saved_peaks)
            triggered = False

        return triggered, peaks

    def _emit_loaded_peaks_at_threshold(self) -> None:
        """Filter loaded-measurement peaks by threshold/fmin/fmax and emit peaksChanged.

        Exact copy of FftCanvas._emit_loaded_peaks_at_threshold — all logic preserved.
        """
        import numpy as np

        assert self._loaded_measurement_peaks is not None
        threshold_db = self.threshold - 100
        peaks = self._loaded_measurement_peaks[
            self._loaded_measurement_peaks[:, 1] >= threshold_db
        ]

        empty = np.zeros((0, 3))
        if peaks.shape[0] == 0:
            self.saved_peaks = empty
            self.b_peaks_freq = np.array([], dtype=np.float64)
            self.peaksChanged.emit(empty)
            return

        self.saved_peaks = peaks
        peaks_freq = peaks[:, 0]

        b_indices = np.nonzero((peaks_freq < self.fmax) & (peaks_freq > self.fmin))
        if len(b_indices[0]) > 0:
            self.peaks_f_min_index = int(b_indices[0][0])
            self.peaks_f_max_index = int(b_indices[0][-1]) + 1
            self.b_peaks_freq = peaks_freq[self.peaks_f_min_index:self.peaks_f_max_index]
            self.peaksChanged.emit(peaks[self.peaks_f_min_index:self.peaks_f_max_index])
        else:
            self.peaks_f_min_index = 0
            self.peaks_f_max_index = 0
            self.b_peaks_freq = np.array([], dtype=np.float64)
            self.peaksChanged.emit(empty)

    def process_averages(self, mag_y) -> None:
        """Accumulate and average FFT linear magnitudes.

        Exact copy of FftCanvas.process_averages logic — all logic preserved.
        Emits newSample, averagesChanged, spectrumUpdated on each triggered frame.
        """
        import numpy as np

        if self.num_averages < self.max_average_count:
            if self.num_averages > 0:
                mag_y_sum = self.mag_y_sum + mag_y
            else:
                mag_y_sum = mag_y
            num_averages = self.num_averages + 1

            avg_mag_y = mag_y_sum / num_averages
            avg_mag_y[avg_mag_y < np.finfo(float).eps] = np.finfo(float).eps
            avg_mag_y_db = 20 * np.log10(avg_mag_y)

            avg_amplitude = np.max(avg_mag_y_db) + 100
            if avg_amplitude > self.threshold:
                triggered, avg_peaks = self.find_peaks(avg_mag_y_db)
                if triggered:
                    self.newSample.emit(self.is_measurement_complete)
                    self.mag_y_sum = mag_y_sum
                    self.num_averages = num_averages
                    self.averagesChanged.emit(int(self.num_averages))
                    self.saved_mag_y_db = avg_mag_y_db
                    self.saved_peaks = avg_peaks
                    self.spectrumUpdated.emit(self.freq, avg_mag_y_db)

        self.spectrumUpdated.emit(self.freq, self.saved_mag_y_db)

    # ------------------------------------------------------------------ #
    # Tap capture (mirrors TapToneAnalyzer+TapDetection.swift handleTapDetection)
    # ------------------------------------------------------------------ #

    def do_capture_tap(self, mag_y_db, tap_amp: int) -> None:
        """Capture one tap spectrum; accumulate until tap_num reached then freeze."""
        import numpy as np

        print(
            f"TAP_DEBUG [handleTapDetection] ENTERED | "
            f"tap_amp={tap_amp} is_guitar={self._proc_thread._is_guitar if self._proc_thread else '?'} "
            f"captured_so_far={len(self._tap_spectra)} numberOfTaps={self._tap_num}"
        )
        if not np.any(mag_y_db):
            print("TAP_DEBUG [handleTapDetection] SKIPPED — mag_y_db is all zeros")
            return
        self._tap_spectra.append(mag_y_db.copy())
        captured = len(self._tap_spectra)
        print(
            f"TAP_DEBUG [handleTapDetection] GUITAR TAP STORED | "
            f"currentTapCount={captured} numberOfTaps={self._tap_num} "
            f"tapProgress={captured/max(self._tap_num,1):.2f}"
        )
        self.tapCountChanged.emit(captured, self._tap_num)

        if captured >= self._tap_num:
            stacked = np.stack(self._tap_spectra)
            avg_db = 10.0 * np.log10(np.mean(np.power(10.0, stacked / 10.0), axis=0))
            self.saved_mag_y_db = avg_db
            _, peaks = self.find_peaks(avg_db)
            self._tap_spectra.clear()
            self.tapDetectedSignal.emit()
        else:
            self.reset_tap_detector()

    def on_tap_for_plate(self) -> None:
        """Forward tap events to the plate capture state machine when active."""
        if self.plate_capture.is_active and len(self._current_mag_y) > 0:
            self.plate_capture.on_tap(self._current_mag_y, self.saved_mag_y_db)

    # ------------------------------------------------------------------ #
    # FFT frame processing (main entry point from FftProcessingThread)
    # ------------------------------------------------------------------ #

    def on_fft_frame(
        self,
        mag_y_db,
        mag_y,
        tap_fired: bool,
        tap_amp: int,
        fps: float,
        sample_dt: float,
        processing_dt: float,
    ) -> None:
        """Receive a processed FFT frame (main thread slot).

        Called by FftCanvas._on_fft_frame_ready which connects to
        FftProcessingThread.fftFrameReady.  Updates analysis state,
        emits signals for the view to consume.
        """
        import numpy as np
        from fft_canvas import DisplayMode

        self._current_mag_y = mag_y

        if tap_fired:
            self.do_capture_tap(mag_y_db, tap_amp)
            self.on_tap_for_plate()

        # Emit spectrum for the view to draw
        if self._display_mode == DisplayMode.LIVE:
            if self.is_measurement_complete:
                self.spectrumUpdated.emit(self.freq, self.saved_mag_y_db)
            else:
                _, peaks = self.find_peaks(mag_y_db)
                self.spectrumUpdated.emit(self.freq, mag_y_db)
        elif self._display_mode == DisplayMode.FROZEN:
            self.spectrumUpdated.emit(self.freq, self.saved_mag_y_db)
        # COMPARISON: skip spectrum update — only overlay curves shown

        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))
        self.levelChanged.emit(tap_amp)
        peak_idx = int(np.argmax(mag_y_db))
        if peak_idx < len(self.freq):
            self.peakInfoChanged.emit(float(self.freq[peak_idx]), float(mag_y_db[peak_idx]))

    # ------------------------------------------------------------------ #
    # Selection helpers
    # ------------------------------------------------------------------ #

    def select_peak(self, freq: float) -> None:
        """Record the selected peak frequency."""
        self.selected_peak = freq

    def deselect_peak(self, _freq: float) -> None:
        """Clear the selected peak."""
        pass  # selection display handled by FftCanvas

    def clear_selected_peak(self) -> None:
        """Reset the selected peak."""
        self.selected_peak = -1.0

    # ------------------------------------------------------------------ #
    # Comparison overlay management
    # (mirrors TapToneAnalyzer+MeasurementManagement.swift loadComparison)
    # ------------------------------------------------------------------ #

    def load_comparison(self, measurements: list) -> list:
        """Prepare comparison data from measurements.

        Returns list of (label, color, freq_arr, mag_arr) tuples for FftCanvas
        to create PlotDataItem curves.  Mirrors loadComparison(measurements:) in Swift.
        """
        from datetime import datetime
        import numpy as np
        from fft_canvas import DisplayMode

        self._comparison_data.clear()
        self.comparison_labels.clear()

        _PALETTE = [
            (0,   122, 255),
            (255, 149,   0),
            (52,  199,  89),
            (175,  82, 222),
            (48,  176, 199),
        ]

        with_snapshots = [m for m in measurements if m.spectrum_snapshot is not None]
        result = []
        for idx, m in enumerate(with_snapshots):
            snap = m.spectrum_snapshot
            color = _PALETTE[idx % len(_PALETTE)]
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes,  dtype=np.float64)
            label = self._comparison_label(m)
            self.comparison_labels.append((label, color))
            self._comparison_data.append({
                "label": label, "color": color,
                "freqs": freq_arr, "mags": mag_arr,
            })
            result.append((label, color, freq_arr, mag_arr))

        if with_snapshots:
            snaps = [m.spectrum_snapshot for m in with_snapshots]
            min_freq = int(min(s.min_freq for s in snaps))
            max_freq = int(max(s.max_freq for s in snaps))
            min_db   = float(min(s.min_db for s in snaps))
            max_db   = float(max(s.max_db for s in snaps))
            self.update_axis(min_freq, max_freq)
            self._display_mode = DisplayMode.COMPARISON
            self.comparisonChanged.emit(True)

        return result

    def clear_comparison(self) -> None:
        """Clear comparison overlay state."""
        from fft_canvas import DisplayMode
        was_comparing = self.is_comparing
        self._display_mode = DisplayMode.LIVE
        self._comparison_data.clear()
        self.comparison_labels.clear()
        if was_comparing:
            self.comparisonChanged.emit(False)

    @staticmethod
    def _comparison_label(m) -> str:
        """Short label for the legend."""
        from datetime import datetime
        loc = getattr(m, "tap_location", None)
        if loc:
            return loc
        ts = getattr(m, "timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%b %-d %H:%M")
        except Exception:
            return ts[:16]

    # ------------------------------------------------------------------ #
    # Plate analysis (mirrors TapToneAnalyzer+SpectrumCapture.swift)
    # ------------------------------------------------------------------ #

    def start_plate_analysis(self) -> None:
        """Arm the plate capture state machine for the next tap(s)."""
        import app_settings as _as
        self.plate_capture.start(
            is_brace=self._measurement_type.is_brace,
            measure_flc=_as.AppSettings.measure_flc(),
        )

    def reset_plate_analysis(self) -> None:
        """Abort plate capture and return to idle."""
        self.plate_capture.reset()

    # ------------------------------------------------------------------ #
    # Guitar type bands
    # ------------------------------------------------------------------ #

    def set_guitar_type(self, guitar_type) -> None:
        """Update the guitar type used for mode classification."""
        self._guitar_type = guitar_type
