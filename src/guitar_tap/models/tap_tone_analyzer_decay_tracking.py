# @parity dsp/decay tests=test/decay-tracking
"""
TapToneAnalyzer+DecayTracking — ring-out time measurement after a tap.

Mirrors Swift TapToneAnalyzer+DecayTracking.swift.  There is no separate
DecayTracker class in Swift; all state and logic lives directly on
TapToneAnalyzer.  This mixin puts all of that state and every method on
Python TapToneAnalyzer exactly the same way.

Architecture:
    The continuous FFT operates on a long window (≈ 400 ms), delivering
    only about 1 update per second — too coarse for accurate decay timing.
    Decay tracking uses the per-chunk RMS level: track_decay_fast() is
    called from _on_rms_level_changed() once per audio chunk (~43 Hz,
    every ~23 ms) — the SAME audio-thread RMS path that drives tap detection,
    which carries each chunk's audio-clock timestamp. The ring-out is therefore
    measured in audio time and does not drift when the main thread is starved
    under load (mirrors Swift, which routes decay through rmsLevelHandler).

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
        List of (audio_time, magnitude_dBFS) pairs (audio clock, seconds).
    self.decay_tap_audio_time: float | None
        Audio-clock time of the tap that started the current decay window.
    self.is_tracking_decay: bool
    self.current_decay_time: float | None   (seconds)
    self.decay_threshold: float             (dB, default 15.0)
    self._decay_tracking_timer             (QtCore.QTimer | None)
"""

from __future__ import annotations

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

    def start_decay_tracking(self, tap_audio_time: float) -> None:
        """Initialise decay tracking immediately after a tap is detected.

        Clears the magnitude history, seeds it with tap_peak_level at the tap's AUDIO time as the
        time-zero reference, and starts a 3-second timer that calls stop_decay_tracking() when it
        fires.

        Mirrors Swift startDecayTracking(tapAudioTime:).

        Args:
            tap_audio_time: Audio-clock time (seconds since engine start) of the tap onset, carried
                from the audio thread so the ring-out is measured in audio time (load-invariant).
        """
        # Clear previous decay history and seed with the tap peak level at the tap's AUDIO time.
        # Mirrors Swift: peakMagnitudeHistory = [(time: tapAudioTime, magnitude: tapPeakLevel)]
        self.peak_magnitude_history = [(tap_audio_time, self.tap_peak_level)]
        self.decay_tap_audio_time = tap_audio_time
        self.current_decay_time = None

        # Enable decay tracking.
        self.is_tracking_decay = True

        # Timer manipulation must happen on the main thread — the QTimer
        # carries the thread affinity of whichever thread creates it, and
        # stop()/destruction from a different thread triggers Qt's
        # "Timers cannot be stopped from another thread" warning.  In the
        # live UI this method runs from proc_thread (live mic) or the
        # FilePlayback worker (file playback), so we route the actual
        # create/start through a slot.  AutoConnection executes
        # synchronously when already on the main thread (tests, direct
        # UI calls) and queued otherwise.
        QtCore.QMetaObject.invokeMethod(
            self,
            "_arm_decay_tracking_timer",
            QtCore.Qt.ConnectionType.AutoConnection,
        )

    @Slot()
    def _arm_decay_tracking_timer(self) -> None:
        """Main-thread slot: stop any prior timer and arm a fresh 3-s one.

        Called via QMetaObject.invokeMethod from start_decay_tracking so the
        QTimer is always created on the main thread regardless of which
        thread detected the tap.
        """
        if self._decay_tracking_timer is not None:
            self._decay_tracking_timer.stop()
        self._decay_tracking_timer = QtCore.QTimer()
        self._decay_tracking_timer.setSingleShot(True)
        self._decay_tracking_timer.timeout.connect(self.stop_decay_tracking)
        self._decay_tracking_timer.start(3000)

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
        QTimer.singleShot from start_decay_tracking.
        """
        self.is_tracking_decay = False
        # Timer stop must run on the main thread (see _arm_decay_tracking_timer).
        QtCore.QMetaObject.invokeMethod(
            self,
            "_disarm_decay_tracking_timer",
            QtCore.Qt.ConnectionType.AutoConnection,
        )

    @Slot()
    def _disarm_decay_tracking_timer(self) -> None:
        """Main-thread slot: stop the timer and clear the reference."""
        if self._decay_tracking_timer is not None:
            self._decay_tracking_timer.stop()
            self._decay_tracking_timer = None

    # ------------------------------------------------------------------ #
    # track_decay_fast
    # Mirrors Swift trackDecayFast(inputLevel:)
    # ------------------------------------------------------------------ #

    def track_decay_fast(self, input_level: float, audio_time: float) -> None:
        """Fast-path decay tracker called once per audio chunk (~43 Hz) from
        _on_rms_level_changed().

        Appends the current input_level to peak_magnitude_history (stamped with the chunk's AUDIO
        time) and trims entries older than 5 seconds.  When enough history is present it calls
        measure_decay_time() to update current_decay_time.

        Mirrors Swift trackDecayFast(inputLevel:audioTime:).

        Args:
            input_level: Current instantaneous input level in dBFS, sourced from per-chunk RMS.
            audio_time: THIS chunk's audio-clock timestamp (seconds since engine start), carried
                from the audio thread. Stamping with this instead of a wall clock makes the ring-out
                invariant to when the main thread actually runs.
        """
        # Only track decay history if actively tracking after a tap.
        # Mirrors Swift: guard isTrackingDecay else { return }
        if not self.is_tracking_decay:
            return

        self.peak_magnitude_history.append((audio_time, input_level))

        # Keep only recent history (audio-time 5-second window).
        # Mirrors Swift: peakMagnitudeHistory.filter { audioTime - $0.time < 5.0 }
        decay_history_window_seconds: float = 5.0
        self.peak_magnitude_history = [
            (t, m)
            for (t, m) in self.peak_magnitude_history
            if (audio_time - t) < decay_history_window_seconds
        ]

        # Calculate decay time if we have a tap time and enough history.
        # Mirrors Swift: if let tapTime = decayTapAudioTime, peakMagnitudeHistory.count > 10
        minimum_decay_history_count = 10
        if (
            self.decay_tap_audio_time is not None
            and len(self.peak_magnitude_history) > minimum_decay_history_count
        ):
            self.current_decay_time = self.measure_decay_time(self.decay_tap_audio_time)

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
            tap_time: Audio-clock time (seconds since engine start) of the tap onset.

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
