"""
TapDetector and TapToneAnalyzerTapDetectionHandlerMixin.

Mirrors Swift TapToneAnalyzer+TapDetection.swift, which contains both
the TapDetector state machine and the TapToneAnalyzer coordinator methods
that handle tap events (do_capture_tap, on_tap_for_plate, on_fft_frame).

Guitar mode  — absolute threshold on the RMS input level.
    risingThreshold  = tapDetectionThreshold
    fallingThreshold = tapDetectionThreshold − hysteresisMargin

Plate/Brace mode — EMA-relative threshold on the RMS input level.
    noiseFloor = α × level + (1 − α) × noiseFloor   (α = 0.05, τ ≈ 190 ms at 10 Hz)
    headroom   = max(tapDetectionThreshold − noiseFloor, 10 dB)
    risingThreshold  = noiseFloor + headroom
    fallingThreshold = noiseFloor + max(headroom − hysteresisMargin, 4 dB)
    Motivation: long-window continuous FFT dilutes plate/brace tap
    transients by ~15 dB; adaptive thresholds reject small ambient
    spikes while catching real taps 12-30 dB above the noise floor.

Warmup and cooldown are measured in real time (seconds) so that
behaviour is independent of the audio block size or call rate.
"""

from __future__ import annotations

import time as _time

from PySide6 import QtCore
from utilities.logging import TAP_DEBUG

from .analysis_display_mode import AnalysisDisplayMode


# ── TapDetector ───────────────────────────────────────────────────────────────

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

    tapDetected: QtCore.Signal = QtCore.Signal()

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
        TAP_DEBUG("TapDetector.reset", "called from:\n" + "\n".join(
            "  " + line.strip() for line in _tb.format_stack()[:-1]
        ))
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
            TAP_DEBUG("detectTap",
                f"RELATIVE mode | "
                f"peakMag={level_db:.2f} noiseFloor={self._noise_floor_db:.2f} "
                f"headroom={getattr(self, '_last_headroom', 0.0):.2f} "
                f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                f"state={self._state}"
            )
        else:
            TAP_DEBUG("detectTap",
                f"ABSOLUTE mode | "
                f"peakMag={level_db:.2f} "
                f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                f"state={self._state}"
            )

        match self._state:
            case self._WARMUP:
                remaining = self.warmup_s - (now - self._state_entry_time)
                if remaining > 0:
                    TAP_DEBUG("detectTap",
                        f"WARMUP in progress | "
                        f"remaining={remaining:.2f}s peakMag={level_db:.2f}"
                    )
                else:
                    # Re-anchor to current level on warmup exit (Swift behaviour):
                    # don't fire immediately if signal is already above threshold.
                    if amplitude >= rising_amp:
                        self._state = self._TRIGGERED
                        TAP_DEBUG("detectTap",
                            f"WARMUP EXIT (already above) | "
                            f"peakMag={level_db:.2f} risingThresh={rising_db:.2f} "
                            f"→ state=TRIGGERED"
                        )
                    else:
                        self._state = self._IDLE
                        if self._mode == self.MODE_PLATE_BRACE:
                            TAP_DEBUG("detectTap",
                                f"WARMUP EXIT (relative) | "
                                f"peakMag={level_db:.2f} "
                                f"noiseFloorAnchored={self._noise_floor_db:.2f} "
                                f"risingAnchored={rising_db:.2f} isAboveThreshold=False"
                            )
                        else:
                            TAP_DEBUG("detectTap",
                                f"WARMUP EXIT (absolute) | "
                                f"peakMag={level_db:.2f} "
                                f"risingThresh={rising_db:.2f} isAboveThreshold=False"
                            )
                    self._state_entry_time = now

            case self._IDLE:
                now_above = amplitude >= rising_amp
                TAP_DEBUG("detectTap",
                    f"HYSTERESIS eval | "
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
                        TAP_DEBUG("detectTap",
                            f"COOLDOWN active | "
                            f"remaining={cooldown_remaining:.3f}s peakMag={level_db:.2f}"
                        )
                        # Signal is rising but still in cooldown — track as TRIGGERED
                        # without firing, so we wait for it to drop and re-arm.
                        self._state = self._TRIGGERED
                        self._state_entry_time = now
                    else:
                        TAP_DEBUG("detectTap",
                            f"RISING EDGE FIRED | "
                            f"peakMag={level_db:.2f} risingThresh={rising_db:.2f}"
                        )
                        self._last_tap_time = now
                        self._state = self._TRIGGERED
                        self._state_entry_time = now
                        self.tapDetected.emit()

            case self._TRIGGERED:
                now_above = amplitude >= falling_amp
                TAP_DEBUG("detectTap",
                    f"HYSTERESIS eval | "
                    f"peakMag={level_db:.2f} wasAbove=True nowAbove={now_above} "
                    f"risingThresh={rising_db:.2f} fallingThresh={falling_db:.2f} "
                    f"isDetecting=False currentTapCount=?"
                )
                if not now_above:
                    TAP_DEBUG("detectTap",
                        f"FALLING EDGE | "
                        f"peakMag={level_db:.2f} fallingThresh={falling_db:.2f} "
                        f"— signal settled, returning to IDLE"
                    )
                    self._state = self._IDLE
                    self._state_entry_time = now

            case _:
                pass


# ── TapToneAnalyzerTapDetectionHandlerMixin ───────────────────────────────────

class TapToneAnalyzerTapDetectionHandlerMixin:
    """FFT frame processing and tap capture for TapToneAnalyzer.

    Mirrors the TapToneAnalyzer extension methods in Swift
    TapToneAnalyzer+TapDetection.swift.
    """

    def do_capture_tap(self, mag_y_db, tap_amp: int) -> None:
        """Capture one tap spectrum; accumulate until tap_num reached then freeze.

        Mirrors Swift handleTapDetection — stores each tap's dB spectrum,
        averages when the required count is reached, and emits tapDetectedSignal.
        """
        import numpy as np

        TAP_DEBUG("handleTapDetection",
            f"ENTERED | "
            f"tap_amp={tap_amp} is_guitar={self._proc_thread._is_guitar if self._proc_thread else '?'} "
            f"captured_so_far={len(self._tap_spectra)} numberOfTaps={self._tap_num}"
        )
        if not np.any(mag_y_db):
            TAP_DEBUG("handleTapDetection", "SKIPPED — mag_y_db is all zeros")
            return
        self._tap_spectra.append(mag_y_db.copy())
        captured = len(self._tap_spectra)
        TAP_DEBUG("handleTapDetection",
            f"GUITAR TAP STORED | "
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
            # Re-arm for the next tap directly at IDLE (no warmup) so that the guitar
            # ring from the just-captured tap doesn't prevent the next rising edge from
            # firing.  cancel_tap_sequence_in_thread also clears _tap_pending.
            if self._proc_thread is not None:
                self._proc_thread.cancel_tap_sequence_in_thread()

    def on_tap_for_plate(self) -> None:
        """Forward tap events to the plate capture state machine when active."""
        if self.plate_capture.is_active and len(self._current_mag_y) > 0:
            self.plate_capture.on_tap(self._current_mag_y, self.saved_mag_y_db)

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

        Mirrors Swift TapToneAnalyzer+TapDetection.swift detectTap /
        handleTapDetection dispatch logic.
        """
        import numpy as np

        self._current_mag_y = mag_y

        if tap_fired:
            self.do_capture_tap(mag_y_db, tap_amp)
            self.on_tap_for_plate()

        # Emit spectrum for the view to draw.
        # Use _saved_freq (not self.freq) when emitting saved_mag_y_db: a measurement
        # loaded from Swift's gated FFT has 16 384 bins while the live self.freq has
        # 32 769 bins.  _saved_freq is always kept in sync with saved_mag_y_db.
        if self._display_mode == AnalysisDisplayMode.LIVE:
            if self.is_measurement_complete:
                self.spectrumUpdated.emit(self._saved_freq, self.saved_mag_y_db)
            else:
                _, peaks = self.find_peaks(mag_y_db)
                self.spectrumUpdated.emit(self.freq, mag_y_db)
        elif self._display_mode == AnalysisDisplayMode.FROZEN:
            self.spectrumUpdated.emit(self._saved_freq, self.saved_mag_y_db)
        # COMPARISON: skip spectrum update — only overlay curves shown

        self.framerateUpdate.emit(float(fps), float(sample_dt), float(processing_dt))
        self.levelChanged.emit(tap_amp)
        peak_idx = int(np.argmax(mag_y_db))
        if peak_idx < len(self.freq):
            self.peakInfoChanged.emit(float(self.freq[peak_idx]), float(mag_y_db[peak_idx]))
