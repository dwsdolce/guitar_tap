# @parity test/theme
"""The palette against the shared case file ``theme.json`` — every colour role with its light and
dark value, the opacities applied to other roles, and the Appearance setting with the scheme each
setting resolves to — the same cases the Swift and web suites run. Role names are Swift's. And what
only this edition needs: ``scheme_changed`` fires exactly when the resolved scheme changes."""

from __future__ import annotations

import json
import os
import sys

import pytest
from PySide6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.appearance import Appearance, Scheme
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.views.utilities import palette

with open(os.path.join(os.path.dirname(__file__), "theme.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)


@pytest.mark.parametrize("name,light,dark", DATA["roles"])
def test_role_and_its_values(name, light, dark):
    assert palette.pair(palette.Role(name)) == palette.ColorPair(light, dark)


def test_every_role_in_the_file_order():
    assert [r.value for r in palette.Role] == [row[0] for row in DATA["roles"]]


@pytest.mark.parametrize("name,light,dark", DATA["opacities"])
def test_opacity(name, light, dark):
    assert palette.OPACITIES[palette.Opacity(name)] == (light, dark)


def test_every_opacity_in_the_file_order():
    assert [o.value for o in palette.Opacity] == [row[0] for row in DATA["opacities"]]


def test_appearance_values_and_default():
    a = DATA["appearance"]
    assert [[x.value, x.label] for x in Appearance] == a["values"]
    TapDisplaySettings.set_appearance(Appearance(a["default"]))
    assert TapDisplaySettings.appearance().value == a["default"]
    TapDisplaySettings.set_appearance(Appearance.DARK)
    assert TapDisplaySettings.appearance() is Appearance.DARK
    TapDisplaySettings.set_appearance(Appearance.SYSTEM)


@pytest.mark.parametrize("appearance,os_reports,expected", DATA["resolve"])
def test_resolved_scheme(appearance, os_reports, expected):
    os_scheme = None if os_reports == "unknown" else Scheme(os_reports)
    assert Appearance(appearance).resolved(os_scheme).value == expected


def test_scheme_changed_fires_only_when_the_scheme_changes(monkeypatch):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    os_reports = {"scheme": Scheme.LIGHT}
    monkeypatch.setattr(palette, "os_scheme", lambda: os_reports["scheme"])
    monkeypatch.setattr(palette, "_apply_linux_fallback", lambda *_: None)
    palette.apply(Appearance.SYSTEM)
    seen: list[Scheme] = []
    palette.notifier().scheme_changed.connect(seen.append)
    try:
        os_reports["scheme"] = Scheme.DARK
        palette._on_os_scheme_changed(None)      # System follows the OS: dark
        palette._on_os_scheme_changed(None)      # the same again: nothing
        palette.apply(Appearance.DARK)           # forced dark, already dark: nothing
        assert palette.color(palette.Role.MODE_AIR).name() == "#64d2ff"
        os_reports["scheme"] = Scheme.LIGHT
        palette._on_os_scheme_changed(None)      # forced: the OS does not matter
        palette.apply(Appearance.LIGHT)          # forced light: light
        palette.apply(Appearance.SYSTEM)         # the OS is light too: nothing
        assert seen == [Scheme.DARK, Scheme.LIGHT]
        assert palette.color(palette.Role.MODE_AIR).name() == "#00b0dc"
    finally:
        palette.notifier().scheme_changed.disconnect(seen.append)


def test_peak_label_follows_the_scheme(monkeypatch):
    """A peak label is drawn in the scheme's chart roles: pitch, frequency and dB."""
    import numpy as np

    from guitar_tap.views.shared.peaks_model import PeaksModel

    QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    monkeypatch.setattr(palette, "os_scheme", lambda: Scheme.LIGHT)
    monkeypatch.setattr(palette, "_apply_linux_fallback", lambda *_: None)
    model = PeaksModel(np.zeros((0, 3)))
    try:
        for appearance, scheme in ((Appearance.DARK, "dark"), (Appearance.LIGHT, "light")):
            palette.apply(appearance)
            html = model.annotation_html(196.0, -32.0, "Top")
            for role in (
                palette.Role.PEAK_PITCH, palette.Role.CHART_TITLE, palette.Role.CHART_AXIS,
            ):
                assert getattr(palette.pair(role), scheme).lower() in html, (role, scheme)
            top = "rgb({},{},{})".format(*palette.rgb(palette.Role.MODE_TOP))
            assert top in html
    finally:
        palette.apply(Appearance.SYSTEM)


def test_series_slots():
    """The series are series.1 … series.10 in slot order, and slot 11 starts again at series.1."""
    assert [r.value for r in palette.SERIES_ROLES] == [f"series.{i}" for i in range(1, 11)]
    assert palette.series_role(10) is palette.Role.SERIES_1


@pytest.mark.parametrize("magnitude,role", DATA["magnitudeRoles"])
def test_magnitude_role(magnitude, role):
    assert palette.magnitude_role(magnitude).value == role
