# @parity test/wav-dump-folder
"""Pin the shared WAV-dump-folder logic.

Default folder, reachability, the acquire/release write helper, and a custom folder that is in
place, renamed, or deleted. The custom folder is stored in the isolated test settings. The folder
picker is checked by hand. Two-way with Swift WavDumpFolderTests.swift (the web has no counterpart
— a page can only download to Downloads).
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from PySide6 import QtWidgets

from guitar_tap.models.wav_dump_folder import WavDumpFolder


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _clean_slate():
    """No custom folder, so the shared assertions are deterministic."""
    WavDumpFolder.use_default_folder()
    yield
    WavDumpFolder.use_default_folder()


def test_default_folder_ends_in_guitartap():
    assert WavDumpFolder.default_folder().name == "GuitarTap"


def test_no_custom_folder_is_reachable_and_current_is_default():
    assert WavDumpFolder.is_reachable() is True
    assert WavDumpFolder.current_folder() == WavDumpFolder.default_folder()


def test_has_custom_folder_false_by_default():
    assert WavDumpFolder.has_custom_folder() is False


def test_acquire_with_no_custom_folder_returns_the_default():
    acquired = WavDumpFolder.acquire_dump_folder()
    assert acquired is not None
    folder, release = acquired
    assert folder.name == "GuitarTap"
    release()  # no-op with no custom folder; must not raise


def _make_folder() -> Path:
    """A fresh folder beside the test's default folder."""
    folder = WavDumpFolder.default_folder().parent / f"Captures-{uuid.uuid4()}"
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def folder():
    made = _make_folder()
    yield made
    shutil.rmtree(made, ignore_errors=True)


def test_custom_folder_is_reachable_and_is_current_and_acquired(folder):
    assert WavDumpFolder.set_custom_folder(folder) is True
    assert WavDumpFolder.has_custom_folder() is True
    assert WavDumpFolder.is_reachable() is True
    assert WavDumpFolder.current_folder() == folder
    acquired = WavDumpFolder.acquire_dump_folder()
    assert acquired is not None and acquired[0] == folder
    acquired[1]()


def test_renamed_custom_folder_is_unreachable_and_acquire_skips(folder):
    # The folder must stay where the user put it: a renamed folder is not followed.
    renamed = folder.parent / f"Renamed-{uuid.uuid4()}"
    WavDumpFolder.set_custom_folder(folder)
    folder.rename(renamed)
    try:
        assert WavDumpFolder.has_custom_folder() is True
        assert WavDumpFolder.is_reachable() is False
        assert WavDumpFolder.acquire_dump_folder() is None
        assert WavDumpFolder.current_folder() == folder
    finally:
        shutil.rmtree(renamed, ignore_errors=True)


def test_deleted_custom_folder_is_unreachable_and_acquire_skips(folder):
    WavDumpFolder.set_custom_folder(folder)
    shutil.rmtree(folder)
    assert WavDumpFolder.is_reachable() is False
    assert WavDumpFolder.acquire_dump_folder() is None


def test_open_folder_with_a_renamed_custom_folder_opens_the_default_not_a_new_one(folder):
    renamed = folder.parent / f"Renamed-{uuid.uuid4()}"
    WavDumpFolder.set_custom_folder(folder)
    folder.rename(renamed)
    try:
        assert WavDumpFolder.folder_to_open() == WavDumpFolder.default_folder()
        assert not folder.exists()
    finally:
        shutil.rmtree(renamed, ignore_errors=True)


def test_use_default_folder_forgets_the_custom_folder(folder):
    WavDumpFolder.set_custom_folder(folder)
    WavDumpFolder.use_default_folder()
    assert WavDumpFolder.has_custom_folder() is False
    assert WavDumpFolder.current_folder() == WavDumpFolder.default_folder()


# Arming with Dump Capture Audio on checks the folder first: an unreachable folder is flagged for
# the prompt and nothing is armed.

@pytest.fixture
def dump_on():
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    saved = TapDisplaySettings.dump_capture_audio()
    TapDisplaySettings.set_dump_capture_audio(True)
    yield
    TapDisplaySettings.set_dump_capture_audio(saved)


def test_request_start_with_an_unreachable_folder_flags_it_and_does_not_arm(folder, dump_on):
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    WavDumpFolder.set_custom_folder(folder)
    shutil.rmtree(folder)
    sut = TapToneAnalyzer.for_testing()
    flagged: list = []
    sut.dumpFolderUnreachable.connect(lambda: flagged.append(True))
    assert sut.request_start_tap_sequence() is False
    assert flagged == [True]
    assert sut.is_detecting is False


def test_request_start_with_a_reachable_folder_arms(folder, dump_on):
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    WavDumpFolder.set_custom_folder(folder)
    sut = TapToneAnalyzer.for_testing()
    flagged: list = []
    sut.dumpFolderUnreachable.connect(lambda: flagged.append(True))
    assert sut.request_start_tap_sequence() is True
    assert flagged == []
    assert sut.is_detecting is True


# A recording that can't be written when its measurement finishes is held, not dropped: the user is
# asked, and choosing a folder saves it.

def _wavs(label: str, folder: Path) -> list:
    return sorted(folder.glob(f"python_{label}_*.wav")) if folder.is_dir() else []


def _held_sut(gone: Path):
    import numpy as np

    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    WavDumpFolder.set_custom_folder(gone)
    shutil.rmtree(gone)
    sut = TapToneAnalyzer.for_testing()
    flagged: list = []
    sut.captureRecordingHeld.connect(lambda: flagged.append(True))
    sut._dump_capture_wav(np.array([0.1, -0.1, 0.2], dtype=np.float32), 48000, "held")
    return sut, flagged


def test_unwritable_recording_is_held_and_flagged(folder, dump_on):
    sut, flagged = _held_sut(folder)
    assert len(sut.held_capture_recordings) == 1
    assert flagged == [True]


def test_held_recording_is_saved_to_the_folder_the_user_chooses(folder, dump_on):
    sut, _ = _held_sut(folder)
    chosen = _make_folder()
    try:
        WavDumpFolder.set_custom_folder(chosen)
        sut.save_held_capture_recordings()
        assert sut.held_capture_recordings == []
        assert len(_wavs("held", chosen)) == 1
        assert sut.capture_audio_saved.startswith("python_held_")
    finally:
        shutil.rmtree(chosen, ignore_errors=True)


def test_held_recording_is_discarded_when_the_user_lets_it_go(folder, dump_on):
    sut, _ = _held_sut(folder)
    sut.discard_held_capture_recordings()
    assert sut.held_capture_recordings == []
    assert _wavs("held", WavDumpFolder.default_folder()) == []


# Recording is decided when a sequence starts, from the saving setting: with it off nothing is
# kept, and turning it on mid-sequence takes effect from the next sequence. A loaded measurement
# or comparison ends the sequence and its recording. Mirrors Swift WavDumpFolderTests.


def _chunk():
    import numpy as np
    return np.full(1024, 0.1, dtype=np.float32)


def test_saving_off_records_nothing():
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    saved = TapDisplaySettings.dump_capture_audio()
    TapDisplaySettings.set_dump_capture_audio(False)
    try:
        sut = TapToneAnalyzer.for_testing()
        sut.start_tap_sequence()
        sut._gated_capture_active = True
        for _ in range(10):
            sut._maintain_session_recording(_chunk())
        assert not sut._is_session_recording
        assert sut._session_recording_buffer == []
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved)


def test_saving_turned_on_after_arming_takes_effect_from_the_next_sequence():
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    saved = TapDisplaySettings.dump_capture_audio()
    TapDisplaySettings.set_dump_capture_audio(False)
    try:
        sut = TapToneAnalyzer.for_testing()
        sut.start_tap_sequence()
        TapDisplaySettings.set_dump_capture_audio(True)
        # A pause and resume does not start it either.
        sut.pause_tap_detection()
        sut.resume_tap_detection()
        sut._maintain_session_recording(_chunk())
        assert not sut._is_session_recording
        assert sut._session_recording_buffer == []
        folder = WavDumpFolder.default_folder()
        before = set(_wavs("session_Guitar_1tap", folder))
        sut.finish_session_recording("Guitar_1tap")
        assert set(_wavs("session_Guitar_1tap", folder)) - before == set()
        # The next sequence records.
        sut.start_tap_sequence()
        assert sut._is_session_recording
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved)


def test_loading_a_measurement_ends_the_recording():
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    import uuid

    from guitar_tap.models.tap_tone_measurement import TapToneMeasurement
    saved = TapDisplaySettings.dump_capture_audio()
    TapDisplaySettings.set_dump_capture_audio(True)
    try:
        sut = TapToneAnalyzer.for_testing()
        sut.start_tap_sequence()
        sut._gated_capture_active = True
        for _ in range(10):
            sut._maintain_session_recording(_chunk())
        assert sut._session_recording_buffer
        sut.load_measurement(TapToneMeasurement(
            id=str(uuid.uuid4()), timestamp="2026-01-01T00:00:00Z", peaks=[]))
        assert not sut._is_session_recording
        assert sut._session_recording_buffer == []
        # Audio after the load is not kept.
        sut._maintain_session_recording(_chunk())
        assert sut._session_recording_buffer == []
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved)


# A save is shown: the analyzer names the file it wrote, until dismissed or a new sequence starts.

def test_saved_notice_names_the_file_until_dismissed_or_a_new_sequence(dump_on):
    import numpy as np

    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    sut = TapToneAnalyzer.for_testing()
    shown: list = []
    sut.captureAudioSavedChanged.connect(shown.append)
    try:
        sut._dump_capture_wav(np.array([0.1, -0.1, 0.2], dtype=np.float32), 48000, "notice")
        assert sut.capture_audio_saved.startswith("python_notice_")
        sut.dismiss_capture_audio_saved()
        assert sut.capture_audio_saved is None

        sut._dump_capture_wav(np.array([0.1, -0.1, 0.2], dtype=np.float32), 48000, "notice")
        assert sut.capture_audio_saved is not None
        sut.start_tap_sequence()
        assert sut.capture_audio_saved is None
        assert shown[-1] is None and shown[0].startswith("python_notice_")
    finally:
        for path in _wavs("notice", WavDumpFolder.default_folder()):
            path.unlink()


def test_saved_notice_not_shown_when_saving_is_off():
    import numpy as np

    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    saved = TapDisplaySettings.dump_capture_audio()
    TapDisplaySettings.set_dump_capture_audio(False)
    try:
        sut = TapToneAnalyzer.for_testing()
        sut._dump_capture_wav(np.array([0.1, -0.1, 0.2], dtype=np.float32), 48000, "notice")
        assert sut.capture_audio_saved is None
    finally:
        TapDisplaySettings.set_dump_capture_audio(saved)
