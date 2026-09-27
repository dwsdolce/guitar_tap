"""Drive the app's own Play File path from a test and wait for it.

There is no test-only copy of the pipeline: ``TapToneAnalyzer.play_file`` is what the view calls, so
every file-playback regression runs the path users take. Mirrors Swift
``GuitarTapTests/PlaybackTestSupport.swift``.
"""
from __future__ import annotations

import threading
import time

from PySide6 import QtWidgets

from guitar_tap.models.measurement_type import MeasurementType
from guitar_tap.models.tap_display_settings import TapDisplaySettings
from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer


def play_file_and_wait(sut: TapToneAnalyzer, path: str, measurement_type: MeasurementType,
                       number_of_taps: int = 1, calibration_path: "str | None" = None) -> None:
    """Play ``path`` through ``sut.play_file`` with the measurement type and tap count set as the
    user's settings would have them, then wait — pumping the Qt event loop, so the playback worker's
    queued main-thread work is delivered — until playback has ended and the measurement has completed
    (at most 5 s after the end; the last tap is averaged a capture window later).

    Mirrors Swift ``TapToneAnalyzer.playFileAndWait(url:measurementType:numberOfTaps:calibrationURL:)``.
    """
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    TapDisplaySettings.set_measurement_type(measurement_type)
    sut.number_of_taps = number_of_taps
    ended = threading.Event()
    sut.play_file(path, calibration_path=calibration_path, on_finished=ended.set)
    while not ended.is_set():
        app.processEvents()
        time.sleep(0.005)
    deadline = time.monotonic() + 5.0
    while not sut.is_measurement_complete and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
