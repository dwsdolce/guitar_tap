"""
Port of ImportPersistenceTests.swift — IP1–IP3.

Tests that both import_measurements overloads persist measurements to disk.

Isolation: measurements_file() is automatically redirected to
$TMPDIR/com.guitartap.tests/saved_measurements.json when running under pytest
(via the PYTEST_CURRENT_TEST env-var check in tap_analysis_results_view.py).
The conftest.py session fixture clears that file before the suite starts.

Test plan coverage: IP1–IP3
"""

from __future__ import annotations

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

# PySide6 application — required for QObject (TapToneAnalyzer is a QObject).
from PySide6 import QtWidgets

_APP: "QtWidgets.QApplication | None" = None


def _get_app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    return _APP


def _make_sut():
    _get_app()
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer()
    # Clear any measurements loaded from disk on start().
    sut.savedMeasurements.clear()
    return sut


def _minimal_measurement_json() -> str:
    """Minimal valid JSON for a single-element [TapToneMeasurement] array."""
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    m = TapToneMeasurement.create(peaks=[], tap_location="Test")
    return json.dumps([m.to_dict()])


# ---------------------------------------------------------------------------
# IP1–IP3
# ---------------------------------------------------------------------------

class TestImportPersistence:
    """Port of Swift ImportPersistenceTests — IP1–IP3."""

    # IP1: import_measurements(json_str) must return True and persist to disk.
    def test_IP1_import_measurements_json_persists_to_disk(self):
        """IP1: import_measurements(json) returns True and writes saved_measurements.json."""
        from guitar_tap.views.tap_analysis_results_view import measurements_file
        sut = _make_sut()
        json_str = _minimal_measurement_json()

        result = sut.import_measurements(json_str)

        assert result is True, "import_measurements(json) should return True for valid JSON"
        assert len(sut.savedMeasurements) == 1, "One measurement should be in savedMeasurements"
        assert os.path.exists(measurements_file()), (
            "saved_measurements.json should exist on disk after import"
        )

    # IP2: import_measurements_from_data(bytes) must persist to disk.
    def test_IP2_import_measurements_data_persists_to_disk(self):
        """IP2: import_measurements_from_data(bytes) persists to disk."""
        from guitar_tap.views.tap_analysis_results_view import measurements_file
        sut = _make_sut()
        data = _minimal_measurement_json().encode("utf-8")

        sut.import_measurements_from_data(data)

        assert os.path.exists(measurements_file()), (
            "saved_measurements.json should exist on disk after import_measurements_from_data"
        )

    # IP3: import_measurements(json_str) appends to any previously saved measurements.
    def test_IP3_import_measurements_json_appends_to_existing(self):
        """IP3: Successive imports append rather than overwrite."""
        sut = _make_sut()
        json_str = _minimal_measurement_json()

        sut.import_measurements(json_str)
        count_after_first = len(sut.savedMeasurements)

        sut.import_measurements(json_str)
        count_after_second = len(sut.savedMeasurements)

        assert count_after_second == count_after_first + 1, (
            f"Second import should append; count was {count_after_first}, "
            f"now {count_after_second}"
        )
