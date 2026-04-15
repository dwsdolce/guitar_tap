"""
TapToneAnalyzer+DecayTracking — ring-out time measurement after a tap.

Mirrors Swift TapToneAnalyzer+DecayTracking.swift.  There is no separate
DecayTracker class in Swift; all state and logic lives directly on
TapToneAnalyzer.  This mixin puts all of that state and every method on
Python TapToneAnalyzer exactly the same way.

Architecture:
    The continuous FFT operates on a long window (≈ 400 ms), delivering
    only about 1 update per second — too coarse for accurate decay timing.
    Decay tracking uses per-chunk RMS level (track_decay_fast), which is
    called at ~10 Hz from on_fft_frame(), mirroring Swift's
    recentPeakLevelDB polling subscription.

Ring-Out Definition:
    Ring-out time is measured as the elapsed time from the post-tap peak
    level to when the signal first falls below peak − decay_threshold (dB).

Tracking Window:
    The tracking timer runs for 3 seconds after each tap.  If the signal
    has not decayed by decay_threshold dB within that window,
    current_decay_time remains None.  The history buffer retains at most
    5 seconds of samples.

Stored properties initialised in TapToneAnalyzer.__init__:
    self.peak_magnitude_history: list[tuple[float, float]]
        List of (monotonic_time, magnitude_dBFS) pairs.
    self.is_tracking_decay: bool
    self.current_decay_time: float | None   (seconds)
    self.decay_threshold: float             (dB, default 15.0)
    self._decay_tracking_timer             (threading.Timer | None)
"""

from __future__ import annotations

import threading
import time as _time
from PySide6 import QtCore
from PySide6.QtCore import Slot


class TapToneAnalyzerDecayTrackingMixin:
    """Decay (ring-out) tracking for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+DecayTracking.swift.
    """

    # ------------------------------------------------------------------ #
    # start_decay_tracking
    # Mirrors Swift startDecayTracking()
    # ------------------------------------------------------------------ #

    def start_decay_tracking(self) -> None:
        """Initialise decay tracking immediately after a tap is detected.

        Clears the magnitude history, seeds it with tap_peak_level as the
        time-zero reference, and starts a 3-second timer that calls
        stop_decay_tracking() when it fires.

        Mirrors Swift startDecayTracking().
        """
        now = _time.monotonic()

        # Clear previous decay history and seed with the tap peak level.
        # Mirrors Swift: peakMagnitudeHistory = [(time: now, magnitude: tapPeakLevel)]
        self.peak_magnitude_history = [(now, self.tap_peak_level)]
        self.current_decay_time = None

        # Enable decay tracking.
        self.is_tracking_decay = True

        # Cancel any existing timer before starting a new one.
        # Mirrors Swift: decayTrackingTimer?.invalidate()
        if self._decay_tracking_timer is not None:
            self._decay_tracking_timer.cancel()

        # Stop decay tracking after 3 seconds.
        # Mirrors Swift: Timer.scheduledTimer(withTimeInterval: 3.0, ...) which fires
        # on the main RunLoop.  threading.Timer fires on a background thread, so post
        # to the main thread via invokeMethod before touching any shared state.
        def _fire_stop() -> None:
            QtCore.QMetaObject.invokeMethod(
                self,
                "stop_decay_tracking",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )
        self._decay_tracking_timer = threading.Timer(3.0, _fire_stop)
        self._decay_tracking_timer.daemon = True
        self._decay_tracking_timer.start()

    # ------------------------------------------------------------------ #
    # stop_decay_tracking
    # Mirrors Swift stopDecayTracking()
    # ------------------------------------------------------------------ #

    @Slot()
    def stop_decay_tracking(self) -> None:
        """Finalise the decay-tracking window.

        Sets is_tracking_decay to False so that track_decay_fast() stops
        appending samples.  current_decay_time retains whatever value was
        established during the window (or None if none was).

        Mirrors Swift stopDecayTracking(), which always runs on the main thread
        (Swift's Timer fires on the RunLoop of the scheduling thread = main).
        Called directly from the main thread (e.g., on tap reset) or via
        QMetaObject.invokeMethod(QueuedConnection) from the threading.Timer
        callback in start_decay_tracking.
        """
        self.is_tracking_decay = False
        if self._decay_tracking_timer is not None:
            self._decay_tracking_timer.cancel()
            self._decay_tracking_timer = None

    # ------------------------------------------------------------------ #
    # track_decay_fast
    # Mirrors Swift trackDecayFast(inputLevel:)
    # ------------------------------------------------------------------ #

    def track_decay_fast(self, input_level: float) -> None:
        """Fast-path decay tracker called at ~10 Hz from on_fft_frame().

        Appends the current input_level to peak_magnitude_history and trims
        entries older than 5 seconds.  When enough history is present it
        calls measure_decay_time() to update current_decay_time.

        Mirrors Swift trackDecayFast(inputLevel:).

        Args:
            input_level: Current instantaneous input level in dBFS,
                         sourced from per-chunk RMS at ~10 Hz.
        """
        # Only track decay history if actively tracking after a tap.
        # Mirrors Swift: guard isTrackingDecay else { return }
        if not self.is_tracking_decay:
            return

        now = _time.monotonic()
        self.peak_magnitude_history.append((now, input_level))

        # Keep only recent history (5-second window).
        # Mirrors Swift: peakMagnitudeHistory.filter { now.timeIntervalSince($0.time) < 5.0 }
        decay_history_window_seconds: float = 5.0
        self.peak_magnitude_history = [
            (t, m)
            for (t, m) in self.peak_magnitude_history
            if (now - t) < decay_history_window_seconds
        ]

        # Calculate decay time if we have a tap time and enough history.
        # Mirrors Swift: if let tapTime = lastTapTime, peakMagnitudeHistory.count > 10
        minimum_decay_history_count = 10
        if (
            self.last_tap_time is not None
            and len(self.peak_magnitude_history) > minimum_decay_history_count
        ):
            self.current_decay_time = self.measure_decay_time(self.last_tap_time)

    # ------------------------------------------------------------------ #
    # measure_decay_time
    # Mirrors Swift measureDecayTime(tapTime:)
    # ------------------------------------------------------------------ #

    def measure_decay_time(self, tap_time: float) -> "float | None":
        """Measure the ring-out time from the post-tap peak to threshold crossing.

        Algorithm:
            1. Finds the maximum magnitude sample at or after tap_time.
            2. Defines decay_target = peak_mag − decay_threshold.
            3. Finds the first sample *after* the peak where the level
               drops below decay_target.
            4. Returns the elapsed time (seconds) between peak and crossing.

        Mirrors Swift measureDecayTime(tapTime:).

        Args:
            tap_time: Monotonic timestamp of the tap onset.

        Returns:
            Elapsed ring-out time in seconds, or None if the signal did not
            decay by decay_threshold dB within the history window.
        """
        # Find peak magnitude after tap.
        # Mirrors Swift: postTapHistory.max(by: { $0.magnitude < $1.magnitude })
        post_tap_history = [(t, m) for (t, m) in self.peak_magnitude_history if t >= tap_time]

        if not post_tap_history:
            return None

        peak_entry = max(post_tap_history, key=lambda x: x[1])
        peak_time, peak_mag = peak_entry

        decay_target = peak_mag - self.decay_threshold

        # Find when the signal crossed the threshold (first sample after peak).
        # Mirrors Swift: postTapHistory.first(where: { $0.magnitude < decayTarget && $0.time > peakEntry.time })
        for (t, m) in post_tap_history:
            if m < decay_target and t > peak_time:
                return t - peak_time

        return None
