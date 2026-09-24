# @parity test/import-persistence
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

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
    sut.saved_measurements.clear()
    return sut


def _minimal_measurement_json() -> str:
    """Minimal valid JSON for a single-element [TapToneMeasurement] array."""
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    m = TapToneMeasurement.create(peaks=[], measurement_name="Test")
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
        assert len(sut.saved_measurements) == 1, "One measurement should be in saved_measurements"
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
        count_after_first = len(sut.saved_measurements)

        sut.import_measurements(json_str)
        count_after_second = len(sut.saved_measurements)

        assert count_after_second == count_after_first + 1, (
            f"Second import should append; count was {count_after_first}, "
            f"now {count_after_second}"
        )


# ---------------------------------------------------------------------------
# Update Measurement — the saved-measurement LIBRARY, addressed by index
# ---------------------------------------------------------------------------
#
# Tests update_measurement(at=...): editing an entry of the saved_measurements list. Filed here,
# with the library, because that is what it mutates — it lived under test/annotation-state until
# #17 F27, which is neither where it belongs nor where the web files its equivalent.
#
# The VALUE-level rules of an amendment — what with_() preserves, and that every amendment mints a
# new id — belong to test/measurement-amend and are not repeated here.
#
# Two of these have no web counterpart BY ARCHITECTURE, not by omission: the natives address the
# library by index, while web's store is a rowKey-addressed IndexedDB with no index API (F19b).


def _make_measurement(measurement_name=None, notes=None):
    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    return TapToneMeasurement.create(peaks=[], measurement_name=measurement_name, notes=notes)


def _make_analyzer_with_measurements(measurements):
    sut = _make_sut()
    sut.saved_measurements = list(measurements)
    return sut


class TestUpdateMeasurement:
    """Port of Swift UpdateMeasurementTests — update_measurement() on the live analyzer.

    Mirrors Swift @Suite("UpdateMeasurement — the library, by index") in ImportPersistenceTests.swift.
    """

    def test_update_by_index_changes_only_targeted_entry(self):
        """Updating by index changes only the targeted entry's measurement_name and notes."""
        m0 = _make_measurement(measurement_name="Bridge", notes="First")
        m1 = _make_measurement(measurement_name="Soundhole", notes="Second")
        sut = _make_analyzer_with_measurements([m0, m1])

        sut.update_measurement(at=0, measurement_name="Upper Bout", notes="Edited")

        assert sut.saved_measurements[0].measurement_name == "Upper Bout"
        assert sut.saved_measurements[0].notes == "Edited"
        assert sut.saved_measurements[1].measurement_name == "Soundhole", "Second entry must not be affected"
        assert sut.saved_measurements[1].notes == "Second", "Second entry must not be affected"

    def test_update_duplicate_import_only_edited_index_changes(self):
        """Editing one of two duplicates leaves the other unchanged, and the ids diverge.

        The edited entry is no longer the same dataset as its twin.
        """
        original = _make_measurement(measurement_name="Top", notes="Original")
        # Simulate importing the same file twice — both entries share the same id.
        sut = _make_analyzer_with_measurements([original, original])

        sut.update_measurement(at=1, measurement_name="Back", notes="Copy")

        assert sut.saved_measurements[0].measurement_name == "Top",  "First duplicate must not change"
        assert sut.saved_measurements[0].notes == "Original",    "First duplicate must not change"
        assert sut.saved_measurements[1].measurement_name == "Back", "Second duplicate should be updated"
        assert sut.saved_measurements[1].notes == "Copy",        "Second duplicate should be updated"
        assert sut.saved_measurements[0].id == original.id, \
            "the untouched duplicate keeps its id"
        assert sut.saved_measurements[0].id != sut.saved_measurements[1].id, \
            "the edited duplicate is different data, so it must no longer share the twin's id"

    def test_update_out_of_range_index_is_noop(self):
        """An out-of-range index is a no-op."""
        m = _make_measurement(measurement_name="Bridge")
        sut = _make_analyzer_with_measurements([m])

        sut.update_measurement(at=99, measurement_name="Changed", notes=None)

        assert sut.saved_measurements[0].measurement_name == "Bridge", "Out-of-range update must not modify array"
        assert len(sut.saved_measurements) == 1


# ---------------------------------------------------------------------------
# The import message: what the user is told
# ---------------------------------------------------------------------------

class TestImportMessage:
    """An import is a library operation and says nothing about microphones; a LOAD shows the user
    data, so a load warns. A single-file import also loads, so its one dialog carries the load's
    warning. These pin the OUTCOME — the message — not any edition's mechanism for clearing an
    acknowledged warning, so they hold however that mechanism changes (#17 F41).
    Port of Swift ImportMessageTests."""

    # A microphone no machine running the tests will have.
    ABSENT_MIC = "No Such Microphone (test)"

    @staticmethod
    def _file(*mics) -> bytes:
        from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
        ms = [TapToneMeasurement.create(peaks=[], measurement_name="Test", microphone_name=mic,
                                        microphone_uid=f"{mic}-uid" if mic else None)
              for mic in mics]
        return json.dumps([m.to_dict() for m in ms]).encode("utf-8")

    def test_a_library_import_says_nothing_about_microphones(self):
        sut = _make_sut()
        sut.microphone_warning = "a warning from an earlier load"  # nothing loads, so nothing clears it
        message = sut.import_and_load_measurements(self._file(self.ABSENT_MIC, self.ABSENT_MIC))
        assert message == "Successfully imported 2 measurements"
        assert sut.microphone_warning is None

    def test_a_single_file_import_carries_the_loads_warning_in_one_dialog(self):
        sut = _make_sut()
        message = sut.import_and_load_measurements(self._file(self.ABSENT_MIC))
        assert message.startswith(
            f"Successfully imported and loaded 1 measurement\n\n⚠️ Recorded with '{self.ABSENT_MIC}'"
        ), message
        assert sut.microphone_warning is None, "folded into the message, so no second dialog"

    def test_an_earlier_acknowledged_warning_never_rides_along(self):
        sut = _make_sut()
        sut.microphone_warning = "a warning from an earlier load"
        message = sut.import_and_load_measurements(self._file(None))
        assert message == "Successfully imported and loaded 1 measurement"
