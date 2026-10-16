# @parity tooling/synthetic-tap
"""A synthetic tap: a decaying sinusoid with a single resonance, at 48 kHz — the ring-out a capture
finish is handed in place of microphone audio.

Mirrors Swift GuitarTapTests/SyntheticTap.swift and web test/syntheticTap.ts.
"""
from __future__ import annotations

import numpy as np


def synthetic_tap(hz: float, seconds: float) -> np.ndarray:
    """``seconds`` of a tap ringing at ``hz``: 0.5 · e^(−6t) · sin(2π·hz·t), sampled at 48 kHz."""
    sample_rate = 48000.0
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return (0.5 * np.exp(-t * 6.0) * np.sin(2.0 * np.pi * hz * t)).astype(np.float64)
