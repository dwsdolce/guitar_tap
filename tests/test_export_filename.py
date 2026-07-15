# @parity test/export-filename
"""Pin the shared export-filename rule (FILE-PATHS-AND-NAMES-SPEC §2b).

One stem function, per-artifact default word, integer-second discriminator, name slugged
(spaces and "/" → "-", lowercased). Three-way with Swift ExportFilenameTests.swift and web
export-filename.test.ts.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.export_filename import export_stem
from guitar_tap.models.tap_tone_measurement import TapToneMeasurement

TS = 1784060789  # a fixed instant, so the discriminator is deterministic


# ── The core rule: named vs the per-artifact default word ───────────────────

def test_named_uses_the_name_for_every_artifact():
    assert export_stem("Martin 000-28", TS, "measurement") == "martin-000-28-1784060789"
    assert export_stem("Martin 000-28", TS, "report") == "martin-000-28-1784060789"
    assert export_stem("Martin 000-28", TS, "spectrum") == "martin-000-28-1784060789"


def test_unnamed_uses_the_artifact_word_never_an_infix():
    assert export_stem(None, TS, "measurement") == "measurement-1784060789"
    assert export_stem(None, TS, "report") == "report-1784060789"
    assert export_stem(None, TS, "spectrum") == "spectrum-1784060789"


def test_empty_name_falls_back_to_the_word():
    # None or "" → the word. (Whitespace-only is prevented at input by the required-name rule, Step 3.)
    assert export_stem("", TS, "measurement") == "measurement-1784060789"


# ── Slugging: spaces AND slashes → "-", lowercased ──────────────────────────

def test_slugging_spaces_and_slashes_lowercased():
    assert export_stem("Bridge/Plate Top", TS, "report") == "bridge-plate-top-1784060789"
    assert export_stem("RAMÍREZ 1975", TS, "measurement") == "ramírez-1975-1784060789"


# ── The concrete artifact wires the right default word ──────────────────────

def test_measurement_base_filename_uses_measurement_word():
    named = TapToneMeasurement.create(peaks=[], measurement_name="Martin")
    # timestamp is "now"; assert the name half and that it ends in an integer.
    assert named.base_filename.startswith("martin-")
    assert named.base_filename.rsplit("-", 1)[1].isdigit()

    unnamed = TapToneMeasurement.create(peaks=[], measurement_name=None)
    assert unnamed.base_filename.startswith("measurement-")


def test_measurement_export_stem_for_switches_the_word():
    m = TapToneMeasurement.create(peaks=[], measurement_name=None)
    assert m.export_stem_for("report").startswith("report-")
    assert m.export_stem_for("spectrum").startswith("spectrum-")