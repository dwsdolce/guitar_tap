# @parity test/measurement-type-name
"""Pin the Details-pane Measurement Type resolution (parity group `view/measurement-detail`).

The type is stored ONLY inside the SpectrumSnapshot — never as a top-level measurement field.
`TapToneMeasurement.create(...)` deliberately does not set `measurement_type` (see the comment in
tap_tone_analyzer_measurement_management.py), and `to_dict()` resolves it from the snapshot at save
time so the JSON matches Swift's format.

So the Details pane MUST resolve from the snapshot, mirroring Swift
MeasurementDetailView.measurementTypeName:

    let mt = measurement.spectrumSnapshot?.measurementType
        ?? measurement.longitudinalSnapshot?.measurementType
    return mt?.shortName ?? "—"

REGRESSION (2026-07-16, found in 1.0.2 run-review): `_type_name` read the top-level
`measurement_type` instead, so every measurement saved in the CURRENT SESSION showed "—" for
Measurement Type.  It rendered correctly only after an app restart, when `from_dict` populated the
top-level field from the file.  That session-scoped behaviour is exactly why no test caught it — a
round-trip test loads from a dict and always passes.  Hence the in-memory cases below.

Swift and the web already resolve from the snapshot correctly; this was a Python-only divergence.
Counterpart tests for Swift/web are deferred (Swift is on TestFlight for the 1.0.2 candidate and must
not be touched) — see Development/MATERIAL-MULTITAP-DISCREPANCIES.md §2.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.views.measurements.measurement_detail_view import _type_name


class _Snap:
    """Minimal SpectrumSnapshot stand-in — only the field the resolver reads."""

    def __init__(self, measurement_type):
        self.measurement_type = measurement_type


class _M:
    """Minimal measurement stand-in matching what create(...) produces in memory."""

    def __init__(self, spectrum_snapshot=None, longitudinal_snapshot=None,
                 measurement_type=None, guitar_type=None, is_comparison=False):
        self.spectrum_snapshot = spectrum_snapshot
        self.longitudinal_snapshot = longitudinal_snapshot
        # Top-level fields are None in memory — the state create(...) leaves them in.
        self.measurement_type = measurement_type
        self.guitar_type = guitar_type
        self.is_comparison = is_comparison


# ── THE REGRESSION: in-memory, exactly as create(...) builds it ──────────────


def test_material_type_resolves_from_snapshot_when_top_level_field_is_none():
    """A brace saved this session: top-level field None, type only in the snapshot.

    This is the exact shape that rendered "—" in the Details pane.
    """
    m = _M(longitudinal_snapshot=_Snap("Material (Brace)"))
    assert _type_name(m) == "Brace"


def test_plate_type_resolves_from_snapshot_when_top_level_field_is_none():
    m = _M(longitudinal_snapshot=_Snap("Material (Plate)"))
    assert _type_name(m) == "Plate"


def test_guitar_type_resolves_from_spectrum_snapshot_when_top_level_field_is_none():
    m = _M(spectrum_snapshot=_Snap("Classical Guitar"))
    assert _type_name(m) == "Classical"


# ── Resolution order + fallbacks (mirrors Swift's ?? chain) ──────────────────


def test_spectrum_snapshot_wins_over_longitudinal():
    """Swift: spectrumSnapshot?.measurementType ?? longitudinalSnapshot?.measurementType."""
    m = _M(spectrum_snapshot=_Snap("Generic Guitar"),
           longitudinal_snapshot=_Snap("Material (Brace)"))
    assert _type_name(m) == "Generic"


def test_comparison_short_circuits_before_any_snapshot_lookup():
    m = _M(spectrum_snapshot=_Snap("Generic Guitar"), is_comparison=True)
    assert _type_name(m) == "Comparison"


def test_no_snapshot_falls_back_to_em_dash_without_raising():
    """Swift returns "—" when neither snapshot carries a type. Must not raise."""
    assert _type_name(_M()) == "—"


def test_unrecognised_snapshot_type_falls_back_to_em_dash():
    assert _type_name(_M(spectrum_snapshot=_Snap("Ukulele"))) == "—"


def test_none_snapshot_type_falls_back_to_em_dash():
    assert _type_name(_M(spectrum_snapshot=_Snap(None))) == "—"


# ── The loaded-from-file path must keep working ─────────────────────────────


def test_loaded_measurement_still_resolves():
    """After from_dict the top-level field is set too, but the snapshot remains the source."""
    m = _M(longitudinal_snapshot=_Snap("Material (Brace)"),
           measurement_type="Material (Brace)", guitar_type="Classical")
    assert _type_name(m) == "Brace"