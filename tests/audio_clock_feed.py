# @parity tooling/audio-clock-feed
"""Advance the analyzer's AUDIO clock the way audio does.

Chunk by chunk through the production entry point, ``_on_chunk_level(level_db, audio_time)``.
The tap lifecycle's rests, the FLC hold and the capture window run on that clock (#19), so a test
that used to wait out a wall-clock delay now feeds the audio that delay covers — the same path
playback and the microphone take.

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
