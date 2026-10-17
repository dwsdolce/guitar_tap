# @parity tooling/audio-clock-feed
"""Advance the analyzer's AUDIO clock the way audio does.

Chunk by chunk through the production entry point, ``_on_chunk_level(level_db, audio_time)``.
The tap lifecycle's rests, the FLC hold and the capture window run on that clock, so a test feeds
the audio a delay covers rather than waiting out wall-clock time — the same path playback and the
microphone take. And a wall clock a test moves by hand, for the capture's safety timeout, which runs
on the wall clock.

Mirrors Swift GuitarTapTests/AudioClockFeed.swift and web test/audioClockFeed.ts.
"""

from __future__ import annotations

# One chunk's duration at the app's 1024-sample chunk and 48 kHz.
AUDIO_FEED_CHUNK_SECONDS = 1024.0 / 48000.0


def advance_audio(sut, seconds: float, level: float = -90.0) -> None:
    """Feed quiet chunks until the audio clock has advanced exactly *seconds* past where it is.

    An action due at that moment runs on the last chunk. The level is below every detection
    threshold, so feeding it cannot itself start a tap.
    """
    target = sut.last_audio_time + seconds
    t = sut.last_audio_time
    while t < target:
        t = min(t + AUDIO_FEED_CHUNK_SECONDS, target)
        sut._on_chunk_level(level, t)


class ManualWallClock:
    """A wall clock a test moves by hand: time stands still until ``advance``, which runs each action
    as its time comes, in time order — including one an action schedules within the advance."""

    def __init__(self) -> None:
        self._time = 0.0
        self._pending: list[tuple[float, int, object]] = []
        self._scheduled = 0

    def now(self) -> float:
        return self._time

    def after(self, seconds: float, action) -> None:
        self._scheduled += 1
        self._pending.append((self._time + seconds, self._scheduled, action))

    def advance(self, seconds: float) -> None:
        """Move the time on by *seconds*, running every action due by then."""
        target = self._time + seconds
        while due := [p for p in self._pending if p[0] <= target]:
            nxt = min(due, key=lambda p: (p[0], p[1]))
            self._pending.remove(nxt)
            self._time = nxt[0]
            nxt[2]()
        self._time = target
