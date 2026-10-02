# @parity none — pyqtgraph applies its own zoom gestures, so Python refuses a too-narrow zoom by
# wrapping the ViewBox's scaleBy; Swift's twin is GestureHandlers' minimum-span check
# (SpectrumViewGestureTests C3 and its magnitude case), the web's SpectrumChart's FREQ_MIN_SPAN /
# DB_MIN_SPAN.
"""A zoom gesture is refused when it would leave the chart's span narrower than 10 Hz / 10 dB (the
chart's limits, the same as Settings'); a range at the minimum can still be zoomed out."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.fft_canvas import DB_MIN_SPAN, FREQ_MIN_SPAN, zoom_keeps_minimum_span


def test_a_frequency_zoom_leaving_at_least_10_hz_is_allowed():
    assert zoom_keeps_minimum_span(100.0, 400.0, 0.5, FREQ_MIN_SPAN)      # 300 → 150 Hz
    assert zoom_keeps_minimum_span(20.0, 40.0, 0.5, FREQ_MIN_SPAN)        # 20 → 10 Hz


def test_a_frequency_zoom_leaving_less_than_10_hz_is_refused():
    assert not zoom_keeps_minimum_span(20.0, 30.0, 1 / 1.15, FREQ_MIN_SPAN)   # 10 → 8.7 Hz


def test_zooming_out_from_the_minimum_span_is_allowed():
    assert zoom_keeps_minimum_span(20.0, 30.0, 1.15, FREQ_MIN_SPAN)       # 10 → 11.5 Hz
    assert zoom_keeps_minimum_span(-55.0, -45.0, 1.15, DB_MIN_SPAN)       # 10 → 11.5 dB


def test_a_magnitude_zoom_leaving_less_than_10_db_is_refused():
    assert not zoom_keeps_minimum_span(-55.0, -45.0, 0.8, DB_MIN_SPAN)    # 10 → 8 dB
    assert zoom_keeps_minimum_span(-60.0, -30.0, 0.5, DB_MIN_SPAN)        # 30 → 15 dB
