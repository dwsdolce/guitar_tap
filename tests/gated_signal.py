# @parity tooling/gated-signal
"""The one place the gated-FFT test signal is built and read back.

Used by the GFFT parity tests (test_gated_fft_parity.py) and by the self-regression runner
(parity_runner.py), so both feed the transform the same samples by construction rather than by
two copies kept in step (#17 F49).

Mirrors Swift GuitarTapTests/GatedTestSignal.swift and web test/gatedSignal.ts.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np


def make_gated_test_signal(
    tones: Iterable[Sequence[float]],
    sample_rate: float = 48000.0,
    duration: float = 0.4,
) -> np.ndarray:
    """The gated-FFT test signal: a sum of sine tones as float32 PCM.

    Each tone is ``(hz, amplitude)``. The sum is evaluated in float64 and rounded to float32 once
    per sample: real audio arrives as float32 samples each correctly rounded from the true waveform,
    and accumulating in float32 would hand the transform something no microphone produces. No tones
    gives silence. The sample count is ``int(sample_rate * duration)``.
    """
    count = int(sample_rate * duration)
    t = np.arange(count) / sample_rate
    signal = np.zeros(count, dtype=np.float64)
    for hz, amplitude in tones:
        signal += amplitude * np.sin(2 * np.pi * hz * t)
    return signal.astype(np.float32)


def gated_magnitude_at(
    target_hz: float,
    magnitudes: Sequence[float],
    frequencies: Sequence[float],
) -> float | None:
    """The magnitude (dB) at the bin nearest ``target_hz``, or None for an empty spectrum."""
    if len(frequencies) == 0:
        return None
    best = min(range(len(frequencies)), key=lambda i: abs(frequencies[i] - target_hz))
    return float(magnitudes[best])
