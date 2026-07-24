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
from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.resonant_peak import ResonantPeak
from guitar_tap.models.tap_display_settings import TapDisplaySettings


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


def dots(peaks, is_guitar: bool = True, show_unknown_modes: bool = False,
         overridden_peak_ids=frozenset()):
    """Frequencies of the peaks that get a dot."""
    return [
        p.frequency
        for p in GuitarMode.peaks_in_display_range(
            peaks, MIN_FREQ, MAX_FREQ, is_guitar, show_unknown_modes,
            overridden_peak_ids, GuitarType.GENERIC
        )
    ]


def dots_with_overrides(sut, show_unknown_modes: bool = False):
    """The dot list as the chart actually computes it — the analyzer's peaks plus the analyzer's
    user-assigned labels, which is what fft_canvas passes through.

    Mirrors Swift ``dotsWithOverrides``.
    """
    return dots(
        sut.peaks_above_peak_min,
        show_unknown_modes=show_unknown_modes,
        overridden_peak_ids=sut.overridden_peak_ids,
    )


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
        sut.peaks_above_peak_min = [p1, p2, p3]
        sut.selected_peak_ids = {p2.id}              # only ONE peak selected

        expected_dots = [100, 200, 250]

        for mode in ("all", "selected", "none"):
            sut.annotation_visibility_mode = mode
            assert dots(sut.peaks_above_peak_min) == expected_dots, (
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
        """DL7: a freeform mode override makes peak_mode() report UNKNOWN, but the peak keeps its
        dot.

        The assertion predates Phase 4 and still holds — the REASON changed. It used to hold
        because the dot layer was purely positional and 200 Hz is in a band; it now holds because a
        user-named peak is known by definition. DL8 is the case that separates the two rules.
        """
        sut = _make_sut()
        p = _make_peak_live(200.0)                   # squarely inside top/back
        sut.peaks_above_peak_min = [p]
        sut.set_mode_override("My Custom Label", p.id)

        # The override takes effect on the assigned label...
        assert sut.effective_mode_label(p) == "My Custom Label"
        assert sut.has_manual_override(p.id)

        # ...but the peak keeps its dot.
        assert dots_with_overrides(sut) == [200], (
            "A freeform override must not remove the peak's dot"
        )


# ---------------------------------------------------------------------------
# Naming a peak makes it known (DL8-DL10) -- Phase 4
# ---------------------------------------------------------------------------
#
# One predicate now governs all three display surfaces: the results panel row, the chart dot, and
# the annotation badge. A peak is unknown only when auto-classification placed it in no band AND the
# user has not named it. Before Phase 4 the three surfaces disagreed -- the panel used the assigned
# mode while the dot layer and the badges used the positional test -- so a peak the user had
# explicitly labelled could lose its row while keeping its dot, or lose everything if it happened to
# sit outside every band.

# Generic bands leave 305 Hz in NO band (back ends at 300, dipole starts at 310).
_OUT_OF_BAND = 305.0


class TestDotLayerUserNamedPeaks:
    def test_dl8_freeform_label_makes_out_of_band_peak_known(self):
        """DL8: THE Phase 4 change. An out-of-band peak is hidden -- until the user names it, at
        which point it is known and appears. Pre-Phase-4 it stayed hidden no matter the label.
        """
        saved_mt = TapDisplaySettings.measurement_type()
        saved_pm = TapDisplaySettings.peak_min_threshold()
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        # Pin Peak Min low so the test peaks project through peaks_above_peak_min deterministically
        # (Swift relies on the default; QSettings state is less predictable under pytest).
        TapDisplaySettings.set_peak_min_threshold(-100.0)
        try:
            sut = _make_sut()
            named = _make_peak_live(_OUT_OF_BAND)
            sut.all_peaks = [_make_peak_live(100.0), named]

            assert dots_with_overrides(sut) == [100], (
                "precondition: an unnamed out-of-band peak is hidden"
            )
            assert sut.is_unknown(named), "precondition: it is unknown before being named"

            sut.set_mode_override("Wolf note", named.id)

            assert not sut.is_unknown(named), "naming a peak makes it known"
            assert dots_with_overrides(sut) == [100, 305], (
                "a user-named peak must be dotted even outside every band"
            )
        finally:
            TapDisplaySettings.set_measurement_type(saved_mt)
            TapDisplaySettings.set_peak_min_threshold(saved_pm)

    def test_dl9_known_mode_relabel_makes_out_of_band_peak_known(self):
        """DL9: relabelling an out-of-band peak to a REAL mode name is the same story by the other
        route -- peak_mode() resolves the label to that mode, so it is not unknown.
        """
        saved_mt = TapDisplaySettings.measurement_type()
        saved_pm = TapDisplaySettings.peak_min_threshold()
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        TapDisplaySettings.set_peak_min_threshold(-100.0)
        try:
            sut = _make_sut()
            named = _make_peak_live(_OUT_OF_BAND)
            sut.all_peaks = [named]
            sut.set_mode_override(GuitarMode.TOP.display_name, named.id)

            assert not sut.is_unknown(named), (
                "a peak relabelled to a real mode is known regardless of its frequency"
            )
            assert dots_with_overrides(sut) == [305]
        finally:
            TapDisplaySettings.set_measurement_type(saved_mt)
            TapDisplaySettings.set_peak_min_threshold(saved_pm)

    def test_dl10_table_dot_and_annotation_agree_on_a_user_named_peak(self):
        """DL10: all three surfaces agree. This is the whole point of the phase -- before it, the
        panel and the dot layer applied different criteria to the same peak.
        """
        saved_mt = TapDisplaySettings.measurement_type()
        saved_pm = TapDisplaySettings.peak_min_threshold()
        saved_unknown = TapDisplaySettings.show_unknown_modes()
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        TapDisplaySettings.set_peak_min_threshold(-100.0)
        TapDisplaySettings.set_show_unknown_modes(False)
        try:
            sut = _make_sut()
            named = _make_peak_live(_OUT_OF_BAND)
            sut.all_peaks = [named]
            sut.selected_peak_ids = {named.id}
            sut.annotation_visibility_mode = "all"
            sut.set_mode_override("Wolf note", named.id)

            # Dot layer.
            assert dots_with_overrides(sut) == [305], "dot: user-named peak is shown"
            # Annotation badges -- `all` admits every identified peak.
            assert [p.frequency for p in sut.visible_peaks] == [305], (
                "badge: user-named peak is annotated"
            )
            # The panel's criterion is `not analyzer.is_unknown(peak)`; assert the predicate
            # directly rather than reconstructing the view's filter.
            assert not sut.is_unknown(named), (
                "table: user-named peak is not filtered out as unknown"
            )
        finally:
            TapDisplaySettings.set_measurement_type(saved_mt)
            TapDisplaySettings.set_peak_min_threshold(saved_pm)
            TapDisplaySettings.set_show_unknown_modes(saved_unknown)