# @parity dsp/decay tests=test/decay-tracking,test/guitar-capture-window
"""
TapToneAnalyzer+DecayTracking — the ring-out time of a guitar tap, from the samples of its FFT window.

Mirrors Swift TapToneAnalyzer+DecayTracking.swift.

Ring-Out Definition:
    The level is the mean square over a window of RING_OUT_WINDOW_SAMPLES samples, taken at every
    sample from the tap's onset. Ring-out time is the time from the window where that level is
    highest to the first window after it whose level is decay_threshold dB lower, interpolated
    between samples.

Why from the window:
    The guitar window starts a fixed distance before the tap's onset, and its audio ends a fixed
    distance after it, whichever chunk the trigger fired on. Measured on those samples, the ring-out
    depends on the tap alone — not on where the audio's chunk boundaries fell, which differs from one
    run, and one edition, to the next. Measured once per chunk, it could only come out in whole
    chunks, and the same tap read a chunk apart.

    The window's audio lasts about 1.16 s after the onset; a ring-out longer than that is not
    measured.
"""

from __future__ import annotations

import math

import numpy as np


class TapToneAnalyzerDecayTrackingMixin:
    """Ring-out time for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+DecayTracking.swift.
    """

    #: The number of samples the ring-out level is measured over. Mirrors Swift ringOutWindowSamples.
    RING_OUT_WINDOW_SAMPLES: int = 1024

    @classmethod
    def ring_out_time(cls, samples, start: int, end: int, sample_rate: float,
                      threshold: float) -> "float | None":
        """The ring-out time of the audio in samples[start:end].

        The algorithm:
          1. The energy of every RING_OUT_WINDOW_SAMPLES-sample window starting from start and ending
             by end, from a running sum of the squares (in float64, from start, one sample at a time).
          2. The peak is the first window with the most energy.
          3. The target is the peak's energy threshold dB lower; the crossing is the first window after
             the peak with less energy than the target.
          4. The crossing is interpolated in dB between the window before it and the crossing window.

        Mirrors Swift ringOutTime(_:from:to:sampleRate:threshold:).

        Args:
            samples: The audio — a guitar tap's FFT window.
            start: The first sample measured — the tap's onset in the window.
            end: One past the last sample measured — where the window's audio ends.
            sample_rate: The sample rate in Hz.
            threshold: How far below the peak the level must fall, in dB (decay_threshold).

        Returns:
            Seconds from the peak to the crossing, or None if there is too little audio, it is silent,
            or its level does not fall by threshold before end.
        """
        window = cls.RING_OUT_WINDOW_SAMPLES
        end = min(end, len(samples))
        if start < 0 or sample_rate <= 0 or end - start <= window:
            return None

        x = np.asarray(samples[start:end], dtype=np.float32).astype(np.float64)
        sums = np.concatenate(([0.0], np.cumsum(x * x)))   # cumsum adds in order, as Swift's loop does
        energy = sums[window:] - sums[:-window]

        peak = int(np.argmax(energy))                       # the first of equal maxima
        peak_energy = float(energy[peak])
        if peak_energy <= 0:
            return None

        target = peak_energy * math.pow(10.0, -float(threshold) / 10.0)
        below = np.flatnonzero(energy[peak + 1:] < target)
        if len(below) == 0:
            return None
        crossing = peak + 1 + int(below[0])

        before, after = float(energy[crossing - 1]), float(energy[crossing])
        fraction = ((math.log10(before) - math.log10(target)) / (math.log10(before) - math.log10(after))
                    if after > 0 else 0.0)
        return (crossing - 1 - peak + fraction) / float(sample_rate)
