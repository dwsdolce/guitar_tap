# @parity test/file-playback
"""
End-to-end regression tests for the full file-playback pipeline:
  WAV read → chunk pacing → RMS → tap detection → gated capture →
  FFT (rectangular window for the guitar capture, Hann for the material one) →
  peak selection → mode identification (guitar) / L→C→FLC phases (material)

The analyzer is created via ``TapToneAnalyzer.for_testing()`` (no audio
hardware) and fed via ``playback_support.play_file_and_wait``, which runs the app's own
``play_file`` (the Play File path).

What each regression case checks is the shared case file, file-playback.json; the expected
values are the shared oracle's (parity-oracle.json). Swift mints them from its pipeline and
asserts them at zero; Python reads the same files.

The playback rules (cancel, measurement-type change, the end-of-file step, provenance, session
recording, playback calibration) are sequences of actions and stay as code.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.material_tap_phase import MaterialTapPhase
from guitar_tap.models.measurement_type import MeasurementType

sys.path.insert(0, os.path.dirname(__file__))

from playback_support import play_file_and_wait  # noqa: E402
from parity_oracle import (  # noqa: E402  (follows the src path insert, like the imports above)
    TOLERANCES,
    calibration,
    case,
    fixture,
)


# ---------------------------------------------------------------------------
# What each REG case checks: the shared case file, file-playback.json (the same cases
# the Swift and web suites run). The expected values are the oracle's (parity-oracle.json):
# Swift mints them and asserts them at zero; Python asserts them at the cross-edition tolerances.
# ---------------------------------------------------------------------------

with open(os.path.join(os.path.dirname(__file__), "file-playback.json"), encoding="utf-8") as _f:
    PLAYBACK_CASES = json.load(_f)["cases"]

# The playback-rule tests below play these fixtures with these settings.
BRACE_WAV = fixture("REG-B1")
BRACE_TAP_THRESHOLD = case("REG-B1")["settings"]["tapDetectionThreshold"]
CALIBRATION_FILE = calibration("REG-B1")
assert CALIBRATION_FILE is not None  # REG-B1 declares 7108913.txt
G1_WAV = fixture("REG-G1")
G1_PEAK_MIN_THRESHOLD = case("REG-G1")["settings"]["peakMinThreshold"]
G1_TAP_THRESHOLD = case("REG-G1")["settings"]["tapDetectionThreshold"]
GUITAR_WAV = fixture("REG-G2")
GUITAR_PEAK_MIN_THRESHOLD = case("REG-G2")["settings"]["peakMinThreshold"]
GUITAR_TAP_THRESHOLD = case("REG-G2")["settings"]["tapDetectionThreshold"]

# A case-file field -> the tolerance it is compared at.
_FIELD_TOLERANCE = {"frequency": "freqHz", "magnitude": "magDb", "q": "q"}

def _wav_rate(path: str) -> int:
    """Sample rate of a WAV fixture. The harness derives the analyzer rate from the
    file itself rather than hardcoding 48 kHz, so a future non-48 kHz fixture stays
    consistent (mirrors Swift forTesting() taking the rate from the played file)."""
    import soundfile as sf
    return int(sf.info(path).samplerate)


@pytest.fixture
def brace_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(BRACE_WAV))


@pytest.fixture
def g1_analyzer():
    """Create a TapToneAnalyzer wired for testing (no audio hardware)."""
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
    return TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))


def _value(p, field: str) -> float:
    """A peak's field: an analyzer ResonantPeak (attribute; Q is `quality`) or an oracle peak (dict)."""
    if isinstance(p, dict):
        return float(p[field])
    return float(p.quality if field == "q" else getattr(p, field))


def _identified_peak(sut, role: str):
    """The peak the app identifies for a role: the selected fL / fC / fLC for a material,
    the peak for the mode for a guitar."""
    from guitar_tap.models.guitar_mode import GuitarMode
    material = {
        "longitudinal": "selected_longitudinal_peak",
        "cross": "selected_cross_peak",
        "flc": "selected_flc_peak",
    }
    if role in material:
        return getattr(sut, material[role])
    return sut.get_peak(GuitarMode[role.upper()])


def _assert_peak(label: str, actual, expected: dict, fields: list[str]) -> None:
    assert actual is not None, f"{label}: no peak identified"
    for field in fields:
        tol = TOLERANCES[_FIELD_TOLERANCE[field]]
        got, want = _value(actual, field), _value(expected, field)
        assert abs(got - want) <= tol, f"{label} {field}: expected {want} ±{tol}, got {got}"


def _by_role(peaks: list[dict]) -> dict[str, dict]:
    return {p["role"]: p for p in peaks}


@pytest.mark.parametrize("c", PLAYBACK_CASES, ids=lambda c: c["id"])
def test_playback(c):
    """Plays a case's file through the app's file-playback path and runs the case's checks."""
    from guitar_tap.models.guitar_mode import GuitarMode
    from guitar_tap.models.tap_display_settings import TapDisplaySettings
    from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer

    entry = case(c["oracle"])
    settings = entry["settings"]
    path = (
        os.path.join(os.path.dirname(__file__), c["fixture"]) if c.get("fixture")
        else fixture(c["oracle"])
    )
    assert os.path.exists(path), f"Test WAV not found: {path}"

    sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(path))
    if settings.get("peakMinThreshold") is not None:
        sut.peak_min_threshold = settings["peakMinThreshold"]
    sut.tap_detection_threshold = settings["tapDetectionThreshold"]
    original_measure_flc = TapDisplaySettings.measure_flc()
    if settings.get("measureFlc") is not None:
        TapDisplaySettings.set_measure_flc(settings["measureFlc"])
    try:
        play_file_and_wait(
            sut, path=path,
            measurement_type=MeasurementType(settings["measurementType"]),
            number_of_taps=settings.get("numberOfTaps", 1),
            calibration_path=calibration(c["oracle"]),
        )
    finally:
        TapDisplaySettings.set_measure_flc(original_measure_flc)

    for check in c["checks"]:
        kind = check["kind"]
        if kind == "materialPhaseComplete":
            assert sut.material_tap_phase == MaterialTapPhase.COMPLETE, (
                f"material_tap_phase should be COMPLETE, got {sut.material_tap_phase}"
            )
        elif kind == "measurementComplete":
            assert sut.is_measurement_complete, "is_measurement_complete should be True"
        elif kind == "capturedTaps":
            assert len(sut.captured_taps) == check["count"]
        elif kind == "tapEntries":
            assert len(sut.tap_entries) == check["count"]
        elif kind == "peaks":
            expected = _by_role(entry[check["expected"]])
            for role in check["roles"]:
                _assert_peak(role, _identified_peak(sut, role), expected[role], check["fields"])
        elif kind == "perTapPeaks":
            assert len(sut.tap_entries) == len(entry["perTap"])
            for index, (tap, row) in enumerate(zip(sut.tap_entries, entry["perTap"])):
                mode_peaks = tap.resolved_mode_peaks()
                expected = _by_role(row["peaks"])
                for role in check["roles"]:
                    _assert_peak(
                        f"Tap {index + 1} {role}", mode_peaks.get(GuitarMode[role.upper()]),
                        expected[role], check["fields"],
                    )
        elif kind == "ringOut":
            tol = TOLERANCES["ringOutSec"]
            assert sut.current_decay_time is not None, "No ring-out measured"
            assert abs(sut.current_decay_time - entry["ringOutSec"]) <= tol, (
                f"Ring-out: expected {entry['ringOutSec']} ±{tol}, got {sut.current_decay_time}"
            )
        elif kind == "phasesCaptured":
            captured = [
                s for s in (sut.longitudinal_spectrum, sut.cross_spectrum, sut.flc_spectrum)
                if s is not None
            ]
            assert len(captured) == check["count"], (
                f"captured {len(captured)} phases, noise_floor_estimate={sut.noise_floor_estimate:.1f} dBFS"
            )
        elif kind == "noiseFloorBetween":
            assert check["min"] < sut.noise_floor_estimate < check["max"], (
                f"noise_floor_estimate {sut.noise_floor_estimate:.1f} outside ({check['min']}, {check['max']})"
            )
        else:
            pytest.fail(f"unknown check kind {kind!r}")


# ---------------------------------------------------------------------------
# Playback rules — sequences of actions, in Swift's order (FilePlaybackRegressionTests)
# ---------------------------------------------------------------------------

class TestFilePlaybackRegression:
    """Full-pipeline file playback rule tests."""

    # ── Session recording ─────────────────────────────────────────────────────────────────────
    # With "save capture audio" on, a guitar measurement writes ONE session WAV labelled
    # "Guitar_<n>tap" covering the audio that flowed through the pipeline (arm → final tap); off, it
    # writes nothing. The dump folder is test-sandboxed (WavDumpFolder.default_folder), so the WAVs are
    # read back from there. Twins of the web's and Swift's session-recording cases.

    _SESSION_PREFIX = "python_session_"

    @classmethod
    def _session_wavs(cls):
        """The session WAVs in the sandboxed dump folder: (label, sample_rate, sample_count)."""
        import struct
        from guitar_tap.models.wav_dump_folder import WavDumpFolder
        folder = WavDumpFolder.default_folder()
        out = []
        if not folder.is_dir():
            return out
        for path in sorted(folder.glob(cls._SESSION_PREFIX + "*.wav")):
            data = path.read_bytes()
            if len(data) < 44:
                continue
            rate = struct.unpack_from("<I", data, 24)[0]
            nbytes = struct.unpack_from("<I", data, 40)[0]
            # "python_session_Guitar_1tap_<timestamp>.wav" → "Guitar_1tap"
            label = "_".join(path.name[len(cls._SESSION_PREFIX):].split("_")[:2])
            out.append((label, rate, nbytes // 4))
        return out

    @classmethod
    def _play_guitar_session(cls, path: str, number_of_taps: int, dump: bool):
        """Play a generic-guitar fixture with "save capture audio" set to ``dump``; return the
        session WAVs."""
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        from guitar_tap.models.wav_dump_folder import WavDumpFolder
        folder = WavDumpFolder.default_folder()
        if folder.is_dir():
            for old in folder.glob(cls._SESSION_PREFIX + "*.wav"):
                old.unlink()
        saved = TapDisplaySettings.dump_capture_audio()
        TapDisplaySettings.set_dump_capture_audio(dump)
        try:
            sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(path))
            sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
            sut.tap_detection_threshold = G1_TAP_THRESHOLD
            play_file_and_wait(
                sut, path=path, measurement_type=MeasurementType.GENERIC, number_of_taps=number_of_taps
            )
        finally:
            TapDisplaySettings.set_dump_capture_audio(saved)
        return cls._session_wavs()

    def test_REG_G1_session_recording_dump_on_writes_one_guitar_1tap_wav(self):
        import soundfile as sf
        sessions = self._play_guitar_session(G1_WAV, 1, dump=True)
        assert len(sessions) == 1, f"one session WAV, got {[s[0] for s in sessions]}"
        label, rate, samples = sessions[0]
        assert label == "Guitar_1tap"
        assert rate == _wav_rate(G1_WAV)
        # Covers the arm → tap → capture span: many chunks, and never more than the whole file.
        assert samples > 8192, f"a continuous run of many chunks, got {samples}"
        assert samples <= sf.info(G1_WAV).frames, f"bounded by the file, got {samples}"

    def test_REG_G2_session_recording_is_labelled_by_the_tap_count(self):
        sessions = self._play_guitar_session(GUITAR_WAV, 8, dump=True)
        assert len(sessions) == 1, f"one session WAV, got {[s[0] for s in sessions]}"
        assert sessions[0][0] == "Guitar_8tap"

    def test_session_recording_dump_off_writes_nothing(self):
        sessions = self._play_guitar_session(G1_WAV, 1, dump=False)
        assert sessions == [], f"no session WAV with the setting off, got {[s[0] for s in sessions]}"

    # ── Stopping a playback ──────────────────────────────────────────────────────────────────────
    # Cancel during a playback stops the file and restarts the sequence on live input; a measurement-type
    # change stops it before arming the new type. Nothing from the rest of the file reaches the new
    # sequence, and the playback's finished callback runs (the input's calibration returns). Twins of
    # Swift's stopping-a-playback cases.

    @staticmethod
    def _stop_playback_after_first_tap(stop):
        """Start "Recording" (8 guitar taps) with the input calibration set, wait for the first tap, run
        ``stop(sut)``; return the analyzer, whether the playback finished, and the input calibration."""
        import threading
        import time
        from PySide6 import QtWidgets
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        input_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(GUITAR_WAV))
        sut.peak_min_threshold = GUITAR_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = GUITAR_TAP_THRESHOLD
        sut.set_temporary_calibration(input_calibration)
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        sut.number_of_taps = 8
        finished = threading.Event()
        sut.play_file(GUITAR_WAV, on_finished=finished.set)
        deadline = time.monotonic() + 20
        while sut.current_tap_count < 1 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert sut.current_tap_count >= 1, "precondition: a tap before the stop"
        stop(sut)
        return sut, finished.is_set(), input_calibration

    @staticmethod
    def _run_on_for(seconds):
        import time
        from PySide6 import QtWidgets
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.005)

    def test_cancel_during_playback_stops_the_file_and_restarts_on_live_input(self):
        from guitar_tap.models.detection_state import DetectionState
        sut, finished, input_calibration = self._stop_playback_after_first_tap(lambda a: a.cancel_tap_sequence())
        assert not sut.mic.is_playing_file, "the file is stopped"
        assert sut.mic.playing_file_name is None, "the chart no longer names the file"
        assert finished, "the playback's finished callback ran"
        assert sut._calibration_profile is input_calibration, "the input's calibration is back"
        assert sut.detection_state == DetectionState.LISTENING, "a fresh sequence is armed"
        assert sut.current_tap_count == 0 and not sut.captured_taps, "the partial result is discarded"
        # The rest of the file must not reach the fresh sequence.
        self._run_on_for(2.0)
        assert sut.current_tap_count == 0 and not sut.captured_taps and not sut.is_measurement_complete, \
            f"no tap from the abandoned file, got {sut.current_tap_count}"

    def test_a_played_file_is_named_while_it_plays_and_after_it_ends_and_a_new_sequence_clears_the_name(self):
        import threading
        import time
        from PySide6 import QtWidgets
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        stem = os.path.splitext(os.path.basename(G1_WAV))[0]
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        finished = threading.Event()
        sut.play_file(G1_WAV, on_finished=finished.set)
        assert sut.mic.playing_file_name == stem, "named while it plays"
        deadline = time.monotonic() + 20
        while not finished.is_set() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert finished.is_set(), "precondition: the file ended"
        assert sut.mic.playing_file_name == stem, "still named when it ends"
        sut.request_start_tap_sequence()
        assert sut.mic.playing_file_name is None, "a new sequence clears it"

    def test_measurement_type_change_during_playback_stops_the_file_before_arming_the_new_type(self):
        from guitar_tap.models.material_tap_phase import MaterialTapPhase
        from guitar_tap.models.tap_display_settings import TapDisplaySettings

        def change_type(sut):
            TapDisplaySettings.set_measurement_type(MeasurementType.PLATE)
            sut.request_start_tap_sequence()   # what the settings Apply does for a changed type

        try:
            sut, finished, _ = self._stop_playback_after_first_tap(change_type)
            assert not sut.mic.is_playing_file, "the file is stopped"
            assert finished, "the playback's finished callback ran"
            assert sut.material_tap_phase == MaterialTapPhase.CAPTURING_LONGITUDINAL, "the plate sequence is armed"
            self._run_on_for(2.0)
            assert sut.longitudinal_spectrum is None and not sut.captured_taps, \
                "no guitar tap from the abandoned file reaches the plate measurement"
        finally:
            TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)

    # ── The end-of-file step runs on the main thread ─────────────────────────────────────────────
    # The flush of an unfinished capture, its finish and the release of the pending audio actions are one
    # step on the main thread, with the playback worker waiting for it — as Swift's worker waits in
    # DispatchQueue.main.sync. (Swift and the web get this by construction; Python's worker is a thread.)
    def test_the_end_of_file_step_runs_on_the_main_thread(self):
        import threading
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        threads = []
        flush = sut.mic._on_pre_mic_restart

        def recording_flush():
            threads.append(threading.current_thread())
            flush()

        sut.mic._on_pre_mic_restart = recording_flush
        play_file_and_wait(sut, path=G1_WAV, measurement_type=MeasurementType.GENERIC, number_of_taps=1)
        assert threads == [threading.main_thread()], f"the end-of-file step ran on {threads}"
        assert sut.is_measurement_complete

    # ── Provenance of a played file ──────────────────────────────────────────────────────────────
    # A result made from a played file is saved with the file's provenance: the calibration it was played
    # with (or none), the file's sample rate, and no microphone — the microphone that recorded a file is
    # unknown. A new sequence listens to the input again, and saves the input's. Twins of Swift's cases.

    def test_save_after_playback_records_the_files_provenance_and_an_unknown_microphone(self, brace_analyzer):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        sut = brace_analyzer
        sut.tap_detection_threshold = BRACE_TAP_THRESHOLD
        play_file_and_wait(sut, path=BRACE_WAV, measurement_type=MeasurementType.BRACE,
                           calibration_path=CALIBRATION_FILE)
        assert sut.is_measurement_complete, "precondition: the brace completed"
        file_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)

        sut.save_measurement()
        saved = sut.saved_measurements[-1]
        assert saved.microphone_name is None and saved.microphone_uid is None, "the microphone is unknown"
        assert saved.calibration_name == file_calibration.name, "the file's calibration"
        assert saved.sample_rate == float(_wav_rate(BRACE_WAV)), "the file's sample rate"
        assert saved.selected_longitudinal_peak_id == sut.effective_longitudinal_peak_id, \
            "fL's role, read by the save"

    def test_a_new_sequence_after_playback_saves_the_inputs_provenance(self, g1_analyzer):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        sut = g1_analyzer
        sut.peak_min_threshold = G1_PEAK_MIN_THRESHOLD
        sut.tap_detection_threshold = G1_TAP_THRESHOLD
        input_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        sut.set_temporary_calibration(input_calibration)
        play_file_and_wait(sut, path=G1_WAV, measurement_type=MeasurementType.GENERIC, number_of_taps=1)
        assert sut.capture_calibration_name is None, "precondition: the file played uncalibrated"

        sut.start_tap_sequence()
        assert sut.capture_calibration_name == input_calibration.name, "the input's calibration again"

    def test_a_loaded_measurement_reports_its_recorded_provenance_and_a_re_save_keeps_it(self, brace_analyzer):
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        # A played-file result saved with an unknown microphone and the file's calibration and rate.
        source = brace_analyzer
        source.tap_detection_threshold = BRACE_TAP_THRESHOLD
        play_file_and_wait(source, path=BRACE_WAV, measurement_type=MeasurementType.BRACE,
                           calibration_path=CALIBRATION_FILE)
        source.save_measurement()
        saved = source.saved_measurements[-1]

        # Loaded by an analyzer whose input has no calibration: the loaded result reports the file's.
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(BRACE_WAV))
        sut.load_measurement(saved)
        assert sut.capture_microphone_name is None and sut.result_provenance is not None, \
            "the microphone is unknown"
        assert sut.capture_calibration_name == saved.calibration_name, "the recorded calibration"
        assert sut.capture_sample_rate == saved.sample_rate, "the recorded sample rate"

        sut.save_measurement()
        re_saved = sut.saved_measurements[-1]
        assert re_saved.microphone_name is None, "a re-save keeps the unknown microphone"
        assert re_saved.calibration_name == saved.calibration_name, "and the recorded calibration"
        assert re_saved.sample_rate == saved.sample_rate, "and the recorded sample rate"

    # ── Playback calibration ─────────────────────────────────────────────────────────────────────
    # A file plays with the calibration given for it, or with none: the microphone it was recorded with
    # is unknown, so the live input's calibration never applies to it. The input's calibration is back
    # once playback ends. Twins of Swift's playback-calibration cases.

    @staticmethod
    def _playback_calibrations(input_calibration, calibration_path):
        """Play G1 with ``calibration_path``; return the active calibration during and after playback."""
        import threading
        import time
        from PySide6 import QtWidgets
        from guitar_tap.models.tap_display_settings import TapDisplaySettings
        from guitar_tap.models.tap_tone_analyzer import TapToneAnalyzer
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        sut = TapToneAnalyzer.for_testing(sample_rate=_wav_rate(G1_WAV))
        sut.set_temporary_calibration(input_calibration)
        TapDisplaySettings.set_measurement_type(MeasurementType.GENERIC)
        ended = threading.Event()
        sut.play_file(G1_WAV, calibration_path=calibration_path, on_finished=ended.set)
        during = sut._calibration_profile
        while not ended.is_set():
            app.processEvents()
            time.sleep(0.005)
        return during, sut._calibration_profile

    def test_playback_without_a_calibration_file_is_uncalibrated_and_the_inputs_calibration_returns(self):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        input_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        during, after = self._playback_calibrations(input_calibration, None)
        assert during is None, "no calibration file → uncalibrated"
        assert after is input_calibration, "the input's calibration is restored after playback"

    def test_playback_with_a_calibration_file_uses_it_and_the_inputs_calibration_returns(self):
        from guitar_tap.models.microphone_calibration import MicrophoneCalibration
        file_calibration = MicrophoneCalibration.from_path(CALIBRATION_FILE)
        during, after = self._playback_calibrations(None, CALIBRATION_FILE)
        assert during is not None and during.correction_points == file_calibration.correction_points, \
            "the file's calibration is applied"
        assert after is None, "the input's (absent) calibration is restored after playback"
