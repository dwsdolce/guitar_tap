# @parity view/dot-layer
"""
Port of DotLayerTests.swift — pins the CHART DOT LIST rule,
GuitarMode.peaks_in_display_range(), the rule behind Swift SpectrumView.allPeaksInRange
and the Python scatter update in views/fft_canvas.py.

Why this suite exists: the dot list and the annotation list are DIFFERENT sets, and
conflating them is a bug that actually shipped (on the web, dots followed the selection --
with mode=selected only the chosen peaks were dotted).  Swift and Python were correct, but
nothing pinned the rule anywhere, so the drift was invisible.  These tests, with their Swift
and web twins, make the difference provable on all three platforms:

  dot list        = every peak in the visible frequency range   (annotation-independent)
  annotation list = visible_peaks -- narrowed by ALL/SELECTED/NONE (badges + report)

Mirrors Swift DotLayerTests covering DL1-DL7.
"""

from __future__ import annotations

import sys
import os

import uuid

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode
from guitar_tap.models.guitar_type import GuitarType
from guitar_tap.models.resonant_peak import ResonantPeak


_APP_LIVE: "QtWidgets.QApplication | None" = None


def _get_app_live():
    global _APP_LIVE
    if _APP_LIVE is None:
        _APP_LIVE = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP_LIVE


def _make_sut():
    _get_app_live()
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer()


def _make_peak_live(freq: float = 200.0, mag: float = -20.0) -> ResonantPeak:
    return ResonantPeak(
        id=str(uuid.uuid4()),
        frequency=freq,
        magnitude=mag,
        quality=10.0,
        bandwidth=freq / 10.0,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
#
# Generic guitar bands (GuitarType.mode_ranges): air 70-135, top 140-260,
# back 180-300, dipole 310-460, ring 580-880, upper 880+.
# A display range of 75-350 Hz therefore gives us, deliberately:
#
#    60 Hz - BELOW the range                       -> excluded by range
#    75 Hz - exactly the low edge, in air          -> included (boundary)
#   100 Hz - in air                                -> known, included
#   200 Hz - in top/back                           -> known, included
#   305 Hz - IN range but in NO band (300<305<310) -> the "unknown frequency" case
#   350 Hz - exactly the high edge, in dipole      -> included (boundary)
#   400 Hz - in dipole but ABOVE the range         -> excluded (range beats known)

MIN_FREQ = 75.0
MAX_FREQ = 350.0


def peak(freq: float, mag: float = -30.0) -> ResonantPeak:
    return ResonantPeak(frequency=freq, magnitude=mag)


def dots(peaks, is_guitar: bool = True, show_unknown_modes: bool = False):
    """Frequencies of the peaks that get a dot."""
    return [
        p.frequency
        for p in GuitarMode.peaks_in_display_range(
            peaks, MIN_FREQ, MAX_FREQ, is_guitar, show_unknown_modes, GuitarType.GENERIC
        )
    ]


# ---------------------------------------------------------------------------
# Range filtering (DL1-DL2)
# ---------------------------------------------------------------------------


class TestDotLayerRange:
    def test_dl1_excludes_out_of_range_peaks(self):
        """DL1: out-of-range peaks get no dot -- even 400 Hz, which IS in the dipole band.

        Range wins over "known".
        """
        assert dots([peak(60), peak(100), peak(200), peak(400)]) == [100, 200]

    def test_dl2_range_bounds_are_inclusive(self):
        """DL2: both edges of the visible range are inclusive."""
        assert dots([peak(MIN_FREQ), peak(200), peak(MAX_FREQ)]) == [75, 200, 350]


# ---------------------------------------------------------------------------
# Unknown-mode filtering (DL3-DL5)
# ---------------------------------------------------------------------------


class TestDotLayerUnknownModes:
    def test_dl3_hides_unknown_frequency_when_setting_off(self):
        """DL3: an in-range peak in NO band is dropped when unknown modes are hidden."""
        assert dots([peak(100), peak(305), peak(200)], show_unknown_modes=False) == [100, 200]

    def test_dl4_shows_unknown_frequency_when_setting_on(self):
        """DL4: the same peak is kept when the user asks to see unknown modes."""
        assert dots([peak(100), peak(305), peak(200)], show_unknown_modes=True) == [100, 305, 200]

    def test_dl5_material_skips_unknown_filter(self):
        """DL5: material (plate/brace) has no mode bands -- the unknown filter never applies."""
        assert dots([peak(100), peak(305)], is_guitar=False, show_unknown_modes=False) == [100, 305]


# ---------------------------------------------------------------------------
# The dot list is NOT the annotation list (DL6-DL7)
# ---------------------------------------------------------------------------


class TestDotLayerVsAnnotationList:
    def test_dl6_dot_list_is_independent_of_annotation_mode_and_selection(self):
        """DL6: THE regression guard.

        Cycling annotation visibility all -> selected -> none changes visible_peaks (the
        badges) but must leave the dot list completely untouched.
        """
        sut = _make_sut()
        p1, p2, p3 = _make_peak_live(100), _make_peak_live(200), _make_peak_live(250)
        sut.current_peaks = [p1, p2, p3]
        sut.selected_peak_ids = {p2.id}              # only ONE peak selected

        expected_dots = [100, 200, 250]

        for mode in ("all", "selected", "none"):
            sut.annotation_visibility_mode = mode
            assert dots(sut.current_peaks) == expected_dots, (
                f"Dot list must not change with annotation mode {mode!r}"
            )

        # ...while the annotation list genuinely does vary. If this half ever stops varying,
        # the assertions above have become vacuous.
        sut.annotation_visibility_mode = "all"
        assert len(sut.visible_peaks) == 3
        sut.annotation_visibility_mode = "selected"
        assert len(sut.visible_peaks) == 1, "selected -> only the one selected peak is annotated"
        sut.annotation_visibility_mode = "none"
        assert sut.visible_peaks == [], "none -> no annotations"

    def test_dl7_dot_list_ignores_mode_overrides(self):
        """DL7: the dot list is POSITIONAL.

        It asks "is this frequency in a band?", not "what mode did the classifier assign?".
        A freeform override makes the assigned mode UNKNOWN, but the peak keeps its dot
        because its frequency is still in a band.  This is the distinction the web got wrong
        (it filtered dots by assigned mode).
        """
        sut = _make_sut()
        p = _make_peak_live(200.0)                   # squarely inside top/back
        sut.current_peaks = [p]
        sut.set_mode_override("My Custom Label", p.id)

        # The override takes effect on the assigned label...
        assert sut.effective_mode_label(p) == "My Custom Label"
        assert sut.has_manual_override(p.id)

        # ...but the dot layer still dots it, because 200 Hz is in a band.
        assert dots(sut.current_peaks) == [200], (
            "A freeform override must not remove the peak's dot"
        )