"""
RealtimeFFTAnalyzer — Engine Control
=====================================

Python counterpart to Swift ``RealtimeFFTAnalyzer+EngineControl.swift``.

Swift uses an extension on ``RealtimeFFTAnalyzer`` in a separate file.
Python achieves the same separation via a mixin class
``RealtimeFFTAnalyzerEngineControlMixin`` that ``RealtimeFFTAnalyzer``
inherits from.  The mixin provides all engine-lifecycle and audio-source
methods.  Nothing outside this file needs to change — callers still access
everything through the ``RealtimeFFTAnalyzer`` instance.

Swift ↔ Python method correspondence:

  start()                           ↔  start()
  stop()                            ↔  stop()
  startFromFile(_:completion:)      ↔  start_from_file(path)
  deinit / close()                  ↔  close()
  AVAudioInputNode tap callback     ↔  new_frame()   [Python-only callback form]
  (no Swift equivalent)             ↔  get_frames()  [Python-only drain helper]

---

## start()

Swift ``start()`` (~108 lines) does:

1. Removes any existing tap from ``inputNode`` (safe to call when no tap exists).
2. Nils ``inputNode``, stops, and replaces ``audioEngine`` with a fresh
   ``AVAudioEngine()`` to recover from irrecoverably broken engine state after
   macOS force-restarts the app following permission revocation.
3. Checks ``AVCaptureDevice.authorizationStatus`` on macOS:
   - ``.authorized``  → proceed
   - ``.notDetermined`` → calls ``AVCaptureDevice.requestAccess``, returns
     immediately; if granted, schedules a main-thread re-call of ``start()``.
   - ``.denied`` / ``.restricted`` → throws ``NSError``
4. On iOS, configures ``AVAudioSession`` with ``.record / .measurement``.
5. On macOS, sets the AUHAL device via
   ``AudioUnitSetProperty(kAudioOutputUnitProperty_CurrentDevice)``
   on ``inputNode.audioUnit`` — the only way to select a device with
   ``AVAudioEngine`` (no public API).
6. Calls ``audioEngine.start()``.
7. Workaround: manually calls ``AudioOutputUnitStart()`` if the AUHAL unit
   did not actually start (a macOS bug where ``AVAudioEngine.start()``
   returns success but the unit stays idle).
8. Reads hardware sample rate from ``inputNode.inputFormat(forBus: 0)``;
   validates it is > 0.
9. Builds ``AVAudioFormat`` (PCM float32, hardware rate, 1 ch for UMIK-style
   measurement mics, otherwise hardware channel count).
10. Installs an input tap at buffer size min(fftSize, 1024) samples; callback
    dispatches ``processAudioBuffer(_:)`` onto ``audioProcessingQueue``.
11. Calls ``updateFrequencyBins()`` and ``updateMetrics()``.
12. Registers a CoreAudio sample-rate listener on the selected device (macOS)
    so Audio MIDI Setup changes restart the engine automatically.
13. On the main thread: sets ``isRunning = true``, records ``engineStartTime``,
    on iOS calls ``loadAvailableInputDevices()``.
14. Schedules a 3-second timeout check: if ``firstBufferReceived`` is still
    false after 3 s, logs a warning; also detects TCC-cached "authorized-but-
    silenced" state by checking ``peakMagnitude.isInfinite`` and calls
    ``stop()`` + sets ``microphonePermissionDenied = true`` if needed.

Python ``start()``:

    if self.stream is None:
        self.stream = _open_input_stream(...)
    self.stream.start()

PortAudio's ``sounddevice.InputStream`` encapsulates steps 1–6 and 9–10
entirely:
- The device chosen at construction (or by a device switch) is the one the
  stream is opened on — equivalent to Swift's AUHAL device property set
  before ``audioEngine.start()``.
- Permission handling is implicit; PortAudio returns an error when the stream
  is opened, which ``start()`` raises as Swift's ``start()`` throws.
- There is no equivalent to Swift's TCC-cache silence check because PortAudio
  does not silently deliver zero samples on permission denial.
- There is no iOS audio session configuration (Python targets macOS/desktop).
- ``updateFrequencyBins()`` / ``updateMetrics()`` are called during
  construction, not at start time (equivalent outcome).

---

## stop()

Swift ``stop()`` (~35 lines) does:

1. Calls ``unregisterSampleRateListener()`` (macOS).
2. If ``audioEngine.isRunning``: removes the input tap, stops the engine.
3. Clears ``inputBuffer`` on the main thread, which owns it.
4. Resets ``firstBufferReceived``, ``fftCount``, ``engineStartTime``.
5. On the main thread: sets ``isRunning = false``, resets ``peakMagnitude``
   to -100 dB, resets ``peakFrequency`` to 0.

Python ``stop()``:

    with self._stop_lock:
        self.is_stopped = True
    self.stream.stop()

- ``is_stopped`` is a boolean guard read by ``_FftProcessingThread.run()`` to
  exit its processing loop — equivalent to Swift's ``isRunning = false``.
- ``self.stream.stop()`` deactivates the PortAudio stream; equivalent to
  ``inputNode.removeTap`` + ``audioEngine.stop()``.
- ``peakMagnitude`` / ``peakFrequency`` reset is handled by the view layer on
  stop rather than by the analyzer.
- No sample-rate listener to unregister (Python hot-plug monitors run in
  background threads and are stopped separately in ``close()``).

---

## startFromFile(_:completion:) / start_from_file()

Swift attaches an ``AVAudioPlayerNode`` to the same ``AVAudioEngine`` and
installs a tap on it so ``processAudioBuffer(_:)`` is called unchanged.
Python injects chunks directly into the queue consumed by
``_FftProcessingThread``, achieving the same effect without a separate player
node (PortAudio has no equivalent concept).

---

## close()

No direct Swift equivalent — corresponds to ``deinit``:

    self._stop_hotplug_monitor()
    self._close_stream_only()

- Stops the platform hot-plug monitor thread
  (``_start_coreaudio_monitor`` / Windows / Linux).
- Closes the PortAudio stream.
- PortAudio requires an explicit ``Pa_Terminate()`` (via ``sd._terminate()``)
  to release resources; Swift's ``AVAudioEngine`` and CoreAudio
  ``AudioObjectRemovePropertyListenerBlock`` handle this automatically in
  ``deinit``.

---

## reinitialize_portaudio()  [realtime_fft_analyzer.py — Python-only, no Swift equivalent]

Python-only — no Swift equivalent.

    sd._terminate()
    sd._initialize()

PortAudio caches the device list at ``Pa_Initialize()`` time.  This method
forces a fresh enumeration so that ``sd.query_devices()`` reflects newly
connected hardware.  Swift's ``AVAudioEngine`` and CoreAudio enumerate devices
on demand via ``AudioObjectGetPropertyData``; no equivalent reinitialisation
is needed.

---

## Structural comparison

| Concern                         | Swift (+EngineControl.swift)          | Python (this mixin)               |
|---------------------------------|---------------------------------------|-----------------------------------|
| Engine abstraction              | AVAudioEngine (AVFoundation)          | sounddevice.InputStream (PortAudio) |
| Device selection at start       | AudioUnitSetProperty (AUHAL, macOS)   | Applied at stream construction    |
| Permission check                | AVCaptureDevice.authorizationStatus   | Implicit (stream open error)      |
| iOS audio session               | AVAudioSession.setCategory            | Not applicable (macOS only)       |
| Input tap / callback            | inputNode.installTap(bufferSize:1024) | InputStream callback (new_frame)  |
| Sample-rate change              | CoreAudio property listener           | _start_coreaudio_monitor() thread |
| Silence / TCC cache check       | 3-second asyncAfter                   | Not needed                        |
| Stop guard                      | audioEngine.isRunning                 | is_stopped boolean + _stop_lock   |
| Resource teardown               | deinit (ARC)                          | close() (explicit)                |
| Device-list refresh             | loadAvailableInputDevices()           | reinitialize_portaudio()          |
| File playback source            | AVAudioPlayerNode on same engine      | background thread → queue         |
"""

from __future__ import annotations

import os
import platform
import queue
import threading
import time
from typing import TYPE_CHECKING, Callable

import numpy as np
import numpy.typing as npt

from guitar_tap.models.audio_backend import ensure_portaudio_started, portaudio_started, sd
from guitar_tap.models.dead_input import (
    BUFFER_DELIVERY_TIMEOUT,
    DEAD_INPUT_DWELL,
    WatchdogDecision,
    chunk_carries_signal,
    should_declare_permission_denied,
    watchdog_decision,
    windows_microphone_access_denied,
)
from guitar_tap.utilities.logging import gt_log


class MicrophonePermissionError(PermissionError):
    """A start the system refused for the microphone permission. Mirrors Swift's own denied (code 1)
    and restricted (code 2) errors."""


def is_permission_error(error: BaseException) -> bool:
    """Whether a start error is a microphone permission refusal. Mirrors Swift
    ``RealtimeFFTAnalyzer.isPermissionError``."""
    return isinstance(error, MicrophonePermissionError)


def _mac_authorization_status() -> str:
    """macOS's microphone authorization: "authorized", "not determined", "denied" or "restricted"."""
    import AVFoundation  # macOS only

    return {
        AVFoundation.AVAuthorizationStatusAuthorized: "authorized",
        AVFoundation.AVAuthorizationStatusNotDetermined: "not determined",
        AVFoundation.AVAuthorizationStatusDenied: "denied",
        AVFoundation.AVAuthorizationStatusRestricted: "restricted",
    }.get(AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeAudio),
          "not determined")


def microphone_authorized() -> bool:
    """Whether macOS reports the microphone authorized; True elsewhere (Windows' consent is checked
    at each start, Linux has none). Mirrors Swift's `microphoneAuthorized`."""
    if platform.system() != "Darwin":
        return True
    return _mac_authorization_status() == "authorized"


def _mac_request_access(answer: "Callable[[bool], None]") -> None:
    """Ask macOS for the microphone; ``answer`` is called with the reply, on a background thread."""
    import AVFoundation  # macOS only

    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVFoundation.AVMediaTypeAudio, lambda granted: answer(bool(granted)))


def _windows_microphone_consent() -> "tuple[str | None, str | None]":
    """The two Windows consent values for the microphone: this device's, and desktop apps'."""
    import winreg  # Windows only

    key = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

    def read(path: str) -> "str | None":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                return str(winreg.QueryValueEx(k, "Value")[0])
        except OSError:
            return None

    return read(key), read(key + r"\NonPackaged")

if TYPE_CHECKING:
    pass


class RealtimeFFTAnalyzerEngineControlMixin:
    """Engine lifecycle and audio-source control for RealtimeFFTAnalyzer.

    Mirrors Swift RealtimeFFTAnalyzer+EngineControl.swift.
    """

    # MARK: - Engine Control (mirrors +EngineControl.swift)

    # pylint: disable=unused-argument
    def new_frame(self, data: np.ndarray, _frame_count, _time_info, _status) -> tuple[None, int]:
        """PortAudio stream callback — enqueues the incoming audio chunk.

        Called by PortAudio on every block of ``chunksize`` frames.
        Enqueues the first channel's samples for _FftProcessingThread (self.proc_thread).

        Python-only — Swift delivers audio via an AVAudioInputNode installTap block
        that feeds ``processAudioBuffer(_:)`` on ``audioProcessingQueue``.
        """
        # A stopping stream's chunks are dropped, not refused with CallbackStop: the thread that stops
        # the stream is the only one that may stop it. CallbackStop makes PortAudio stop the audio unit
        # from this audio thread, and that, at the same moment as the main thread's stop or abort,
        # deadlocks both in CoreAudio.
        with self._stop_lock:
            if self.is_stopped:
                return None
        self._last_buffer_time = self.wall_clock.now()  # watchdog liveness stamp (audio thread)
        chunk = data[:, 0].copy()  # copy before queuing — PortAudio reuses the buffer

        # Dead-input watchdog liveness stamp. float(np.sqrt(chunk.dot(chunk) / n))
        # is an allocation-free RMS — dot() reduces to a scalar, so nothing is
        # materialised inside the realtime callback.
        if chunk.size:
            rms = float(np.sqrt(chunk.dot(chunk) / chunk.size))
            if chunk_carries_signal(rms):
                self._last_signal_time = self.wall_clock.now()

        self.queue.put(chunk)

        # Non-zero status means input overflow or output underflow; samples may have been dropped.
        if _status:
            gt_log(f"WARNING: PortAudio callback status={_status} (input overflow or CPU scheduling jitter)")

        # DIAG: Capture the first 5 s of raw PCM to ~/Desktop/guitar_tap_raw_capture.wav.
        # Used to verify the actual sample rate of audio arriving from the OS.
        # Remove once the Windows sample-rate issue is resolved.
        # Set _DIAG_CAPTURE_ENABLED = True to re-enable.
        _DIAG_CAPTURE_ENABLED = False
        if _DIAG_CAPTURE_ENABLED and not getattr(self, "_diag_capture_done", False):
            if not hasattr(self, "_diag_capture_chunks"):
                self._diag_capture_chunks: list = []
                self._diag_capture_samples: int = 0
                gt_log(f"DIAG: starting raw audio capture at self.rate={self.rate} Hz")
            target = self.rate * 5  # 5 seconds
            if self._diag_capture_samples < target:
                self._diag_capture_chunks.append(chunk)
                self._diag_capture_samples += len(chunk)
            else:
                self._diag_capture_done = True
                chunks_snapshot = list(self._diag_capture_chunks)
                rate = self.rate
                def _write() -> None:
                    try:
                        import numpy as _np
                        import soundfile as _sf
                        out_path = os.path.expanduser("~/Desktop/guitar_tap_raw_capture.wav")
                        pcm = _np.concatenate(chunks_snapshot)
                        _sf.write(out_path, pcm, rate, subtype="FLOAT")
                        gt_log(f"DIAG: wrote {len(pcm)} samples at rate={rate} Hz to {out_path}")
                    except Exception as _e:
                        gt_log(f"DIAG: capture write failed: {_e}")
                import threading as _threading
                _threading.Thread(target=_write, daemon=True).start()

        return None

    def get_frames(self) -> list[npt.NDArray[np.float32]]:
        """Non-blocking drain: returns all audio chunks currently in the queue.

        Python-only — Swift's tap hands each buffer to ``processAudioBuffer(_:)`` on its audio
        processing queue.
        """
        frames: list[npt.NDArray[np.float32]] = []
        try:
            while True:
                frames.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return frames

    # @parity audio/engine-control tests=test/file-playback
    def start(self) -> None:
        """Start the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.start() (+EngineControl.swift).
        Swift starts AVAudioEngine and installs the input tap after checking
        microphone permission; Python checks the permission too (macOS, Windows), then opens the
        PortAudio InputStream when there is none (WASAPI RAW on Windows) and starts it. Raises
        MicrophonePermissionError when the permission is refused, and sd.PortAudioError when no
        input can be opened, as Swift's start() throws; the view reports it. Returns without
        starting when it has asked for the permission — the start resumes through
        ``on_permission_granted`` once granted. A test instance has no stream, and opens none.
        """
        if self.is_for_testing:
            return
        try:
            self._start_engine()
        except Exception as exc:
            # A start that fails for anything but the permission leaves the input unavailable until a
            # start succeeds. Mirrors Swift start().
            if not is_permission_error(exc):
                self._set_input_could_not_start(True)
            raise

    def _start_engine(self) -> None:
        gt_log("🎤 === Starting Audio Engine ===")
        if not self._check_microphone_permission():
            return  # asked for it; the start resumes once granted
        # PortAudio may not have started when the app did (no sound server); it is started here,
        # and a PortAudioError leaves the input unavailable. Started now, its devices are listed
        # first.
        started_now = not portaudio_started()
        ensure_portaudio_started()
        if started_now:
            self.load_available_input_devices()
        if self.stream is None:
            from .realtime_fft_analyzer_device_management import (
                _log_stream_diagnostics,
                _open_input_stream,
            )
            selected = self._selected_input_device
            self.stream = _open_input_stream(
                self.device_index, self.rate, self.chunksize, self.new_frame,
                expected_name=(selected.name if selected is not None
                               and selected.index == self.device_index else None))
            # Verify the negotiated stream rate; warns if WASAPI resampled to a different rate.
            self.rate = _log_stream_diagnostics(self.stream, self.rate)
        self.stream.start()
        self.engine_start_failed = False
        self._set_microphone_permission_denied(False)
        self._set_input_could_not_start(False)
        self._set_running(True)
        gt_log("🎤 Audio engine started")
        gt_log(f"🎤 Hardware sample rate: {self.rate} Hz, hardware channels: 1 (tap will use mono)")
        gt_log("🎤 Audio tap installed")
        # (Re)arm the buffer-delivery watchdog for the live-mic stream. Not armed for
        # file playback (the file path feeds self.queue synthetically, not via new_frame).
        if not self.is_playing_file:
            self.start_buffer_watchdog()
        # Re-check the permission 3 s on: macOS's status can read authorized for a while after it
        # has blocked the input. As Swift's start.
        if platform.system() == "Darwin":
            self.wall_clock.after(3.0, self._post_start_permission_check)

    # MARK: - Microphone permission (mirrors Swift start()'s permission check)

    def _check_microphone_permission(self) -> bool:
        """Whether the start may go on. macOS: authorized → yes; not determined → ask, and no — the
        start resumes through ``on_permission_granted`` once granted; denied or restricted → the flag
        and MicrophonePermissionError. Windows: either consent value "Deny" → the flag and the error.
        Linux has no per-app permission. Mirrors Swift ``start()``."""
        system = platform.system()
        if system == "Darwin":
            status = _mac_authorization_status()
            gt_log(f"🎤 Microphone permission: {status.upper()}")
            if status == "authorized":
                return True
            if status == "not determined":
                # The reply comes on a background thread; the wall clock brings it to the main thread.
                _mac_request_access(lambda granted: self.wall_clock.after(
                    0, lambda: self._on_permission_answer(granted)))
                return False
            self._set_microphone_permission_denied(True)
            raise MicrophonePermissionError(f"Microphone access {status}")
        if system == "Windows":
            device_access, desktop_apps_access = _windows_microphone_consent()
            if windows_microphone_access_denied(device_access, desktop_apps_access):
                gt_log(f"⚠️ Microphone permission: DENIED (device {device_access}, desktop apps "
                       f"{desktop_apps_access})")
                self._set_microphone_permission_denied(True)
                raise MicrophonePermissionError("Microphone access denied")
        return True

    def _on_permission_answer(self, granted: bool) -> None:
        """The reply to the request, on the main thread: granted → resume the start (the owner's
        callback, for the full start); refused → the flag."""
        if granted:
            # The 3-second check must not read the input-acquisition moment as a denial.
            self._permission_just_granted = True
            (self.on_permission_granted or self.start)()
        else:
            self._set_microphone_permission_denied(True)

    def _post_start_permission_check(self) -> None:
        """3 s after a start (macOS): a status that now reads denied is a denial — the engine stops
        and the flag goes up. Silence alone is never one (``should_declare_permission_denied``).
        Right after a grant the check is skipped once. Mirrors Swift's 3-second check."""
        if self.is_stopped:
            return
        status = _mac_authorization_status()
        tcc_denied = status in ("denied", "restricted")
        gt_log(f"🎤 3s TCC check — status: {status}")
        if self._permission_just_granted:
            self._permission_just_granted = False
        elif should_declare_permission_denied(tcc_denied):
            gt_log("⚠️ Microphone permission confirmed DENIED after 3s")
            self.stop()
            self._set_microphone_permission_denied(True)

    def _set_running(self, running: bool) -> None:
        """Set whether the engine is running, and emit the edge on the processing thread's signal."""
        if self.is_running == running:
            return
        self.is_running = running
        thread = getattr(self, "proc_thread", None)
        if thread is not None:
            thread.runningChanged.emit(running)

    def _set_input_could_not_start(self, failed: bool) -> None:
        """Set whether the input could not be started, and emit the edge on the processing thread's
        signal."""
        if self.input_could_not_start == failed:
            return
        self.input_could_not_start = failed
        thread = getattr(self, "proc_thread", None)
        if thread is not None:
            thread.inputCouldNotStartChanged.emit(failed)

    def _set_microphone_permission_denied(self, denied: bool) -> None:
        """Set whether the microphone permission is refused, and emit the edge on the processing
        thread's signal, as ``_set_input_could_not_restart`` does."""
        if self.microphone_permission_denied == denied:
            return
        self.microphone_permission_denied = denied
        thread = getattr(self, "proc_thread", None)
        if thread is not None:
            thread.microphonePermissionDeniedChanged.emit(denied)

    def stop(self) -> None:
        """Stop the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.stop() (+EngineControl.swift).
        Uses abort() instead of stop() — see _close_stream_only() docstring.
        """
        gt_log("🎤 Stop requested")
        # Stop the watchdog so it can't fire a recovery during an intentional stop.
        self.stop_buffer_watchdog()
        with self._stop_lock:
            self.is_stopped = True
        self._set_running(False)
        # Ends an in-flight playback worker at its next chunk (Swift: filePlaybackGeneration += 1).
        self._file_playback_generation += 1
        self.is_playing_file = False
        self.playing_file_name = None  # Mirrors Swift stop(): self?.playingFileName = nil
        self.frame.peak_magnitude = -100.0   # Mirrors Swift stop(): peakMagnitude = -100 (silent state)
        self.frame.peak_frequency = 0.0      # Mirrors Swift stop(): peakFrequency = 0
        if self.stream is not None:
            self.stream.abort()

    # MARK: - WAV File Playback (mirrors Swift startFromFile(_ url:))

    def process_file_data(
        self,
        samples: "npt.NDArray[np.float32]",
        sample_rate: int,
        file_name: str,
    ) -> None:
        """Process pre-read mono audio through the FFT pipeline.

        Data-processing core of ``start_from_file``; runs on its FilePlayback
        worker thread.  The chunk-pacing
        loop, partial flush, and ``_on_pre_mic_restart`` call are included.
        Mic stop/restart and UI state management are NOT.

        Mirrors Swift ``RealtimeFFTAnalyzer.processFileData(samples:sampleRate:fileName:)``.

        Args:
            samples:     Mono float32 PCM array.
            sample_rate: Sample rate in Hz.
            file_name:   Display name for logging.
        """
        # Playback is paced by one-chunk sleeps; keep the OS from throttling them for the whole run.
        # Mirrors Swift's `holdTimingActivity` / `defer releaseTimingActivity`.
        from guitar_tap.utilities.timing_activity import hold_timing_activity, release_timing_activity
        timing_activity = hold_timing_activity("Guitar Tap file playback")
        try:
            from guitar_tap.utilities.logging import TAP_DEBUG as _td

            n_samples = len(samples)
            my_generation = self._file_playback_generation
            self.rate = sample_rate
            self.is_playing_file = True
            self.playing_file_name = file_name
            self.is_stopped = False

            chunksize = self.chunksize
            fft_size = self.fft_size
            chunk_duration = chunksize / sample_rate
            expected_duration_s = n_samples / float(sample_rate)

            _td("file_playback",
                f"START | path={file_name} "
                f"samples={n_samples} rate={int(sample_rate)}Hz "
                f"chunksize={chunksize} chunkDuration={chunk_duration*1000:.1f}ms "
                f"expectedDuration={expected_duration_s:.3f}s "
                f"fftSize={fft_size} expectedFftFrames={n_samples // fft_size}"
            )
            t0 = time.time()
            idx = 0
            chunks_pumped = 0
            while idx < n_samples:
                # Superseded by a newer playback, or stopped: nothing of this file is processed further.
                if self._file_playback_generation != my_generation:
                    _td("file_playback",
                        f"INTERRUPTED | idx={idx}/{n_samples} chunksPumped={chunks_pumped}"
                    )
                    return
                chunk = samples[idx: idx + chunksize]
                if len(chunk) == 0:
                    break
                # Inline processing — no queue, no thread.
                # Mirrors Swift processFileData calling processRawSamples directly.
                self.process_raw_samples(chunk)
                idx += chunksize
                chunks_pumped += 1
                # Pace at real time. Mirrors Swift processFileData, which Thread.sleeps the background
                # thread while the main run loop delivers the asyncAfter callbacks.
                time.sleep(chunk_duration)
            elapsed = time.time() - t0
            _td("file_playback",
                f"END | chunksPumped={chunks_pumped} samplesPumped={idx} "
                f"elapsed={elapsed:.3f}s expected={expected_duration_s:.3f}s "
                f"realtimeRatio={elapsed/max(expected_duration_s,1e-9):.3f}x"
            )

            # Stopped while the last chunk was sleeping? Then nothing of the abandoned file is processed.
            if self._file_playback_generation != my_generation:
                return

            # On the main thread, after the file's last chunk (handed over there ahead of this): the partial
            # FFT frame, zero-padded, then any capture the file stopped filling — before the mic restarts. The
            # flush, the capture's finish and the release of the pending audio actions are one step on the
            # main thread, and this worker waits for it (Swift: DispatchQueue.main.sync). Stopped meanwhile?
            # Then the capture belongs to a playback the user abandoned, and the sequence now running must not
            # receive it.
            def _flush_and_clear() -> None:
                if self._file_playback_generation != my_generation:
                    return
                partial = (np.concatenate(self._input_buffer) if self._input_buffer
                           else np.zeros(0, dtype=np.float32))
                self._input_buffer = []
                self._input_buffer_len = 0
                _td("file_playback", f"PARTIAL_FLUSH | partialSamples={len(partial)} fftSize={fft_size}")
                if len(partial) > 0:
                    if len(partial) < fft_size:
                        partial = np.concatenate(
                            [partial, np.zeros(fft_size - len(partial), dtype=np.float32)]
                        )
                    else:
                        partial = partial[:fft_size]
                    # The final FFT frame, announced as every frame — mirrors Swift performFFT(on:).
                    mag_y_db, _peak_db = self.perform_fft(partial)
                    self.publish_frame(mag_y_db, 0.0)
                pre_restart = self._on_pre_mic_restart
                _td("file_playback", f"PRE_MIC_RESTART | handler={'set' if pre_restart else 'None'}")
                if pre_restart is not None:
                    pre_restart()
                self.is_playing_file = False

            self._on_main_and_wait(_flush_and_clear)
            _td("file_playback", "PRE_MIC_RESTART_DONE")
        finally:
            release_timing_activity(timing_activity)

    # @parity dsp/wav
    def start_from_file(self, path: str) -> None:
        """Feed a WAV (or other audio) file through the same queue as the microphone.

        Stops any active microphone stream, reads the file with soundfile, then
        spawns a background thread that chunks samples into self.queue at real-time
        pace so _FftProcessingThread sees them exactly as it would live microphone
        audio.

        Mirrors Swift RealtimeFFTAnalyzer.startFromFile(_ url:) in
        RealtimeFFTAnalyzer+EngineControl.swift.  The key architectural difference is
        that Swift attaches an AVAudioPlayerNode to the same AVAudioEngine; Python
        injects chunks directly into the existing queue used by _FftProcessingThread.

        Args:
            path: Filesystem path to the audio file (WAV, AIFF, FLAC, OGG, etc.).
                  soundfile is used for reading — see soundfile.available_formats().

        Raises:
            ImportError: if soundfile is not installed.
            RuntimeError: if the file cannot be opened or has no audio channels.
        """
        import soundfile as _sf

        gt_log(f"🎤 === Starting file playback (direct injection): {os.path.basename(path)} ===")

        # Cancel any in-flight previous playback worker BEFORE setting up a new one.
        #
        # Without this, two _playback_worker threads end up writing to self.queue
        # concurrently when the user opens a second file before the first finishes
        # (e.g. tap-count = 1, play, change tap-count = 5, play again).  Worse:
        # when the OLD worker eventually exhausts its sample buffer it executes
        # `self.is_playing_file = False`, which then breaks the NEW worker's loop
        # condition and silently truncates the new playback mid-file.
        #
        # The generation bump ends the old worker at its next chunk (Swift: filePlaybackGeneration += 1);
        # the bounded join makes sure it has exited before we proceed.
        self._file_playback_generation += 1
        prev_worker = getattr(self, "_file_playback_thread", None)
        if prev_worker is not None and prev_worker.is_alive():
            prev_worker.join(timeout=0.5)

        # ── Teardown: stop engine, drain queue, clear buffers ────────────
        # Mirrors Swift startFromFile(_:) preamble:
        #   1. audioEngine.stop()           → stop audio delivery
        #   2. audioProcessingQueue.sync {} → drain in-flight processing
        #   3. inputBuffer.removeAll()      → clear FFT accumulator
        #
        # The drain barrier (step 2) is critical: after stopping the mic,
        # the processing thread may still be mid-way through processing a
        # chunk it already dequeued.  Swift uses a synchronous dispatch on
        # the serial audioProcessingQueue to block until that work finishes.
        # Python mirrors this with a None sentinel + Event handshake.

        # 1. Stop the PortAudio stream (mirrors audioEngine.stop()).
        with self._stop_lock:
            self.is_stopped = True
        try:
            self.stream.stop()
        except Exception:
            pass

        # 2. Drain the queue of any pending chunks.
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break

        # 3. Drain barrier — mirrors Swift audioProcessingQueue.sync {}.
        #    Put a None sentinel so the processing thread finishes any
        #    in-flight chunk, acknowledges via _drain_ack, then blocks
        #    until we clear _drain_event.  This guarantees no stale
        #    processing is in-flight when we clear _input_buffer below.
        proc = self.proc_thread
        if proc is not None:
            proc._drain_ack.clear()
            proc._drain_event.set()
            self.queue.put(None)
            proc._drain_ack.wait(timeout=0.5)

            # 4. Clear the FFT accumulator. A mic chunk still queued for the main thread is dropped when
            #    it arrives (its playback generation is stale). Mirrors Swift: inputBuffer.removeAll().
            self._input_buffer = []
            self._input_buffer_len = 0

            # Release the processing thread so it resumes pulling from the queue.
            proc._drain_event.clear()

        # Notify TapToneAnalyzer that the engine has stopped and the queue is
        # drained.  Used to re-initialize the pre-roll buffer with silence so
        # stale mic audio does not leak into the gated capture's pre-roll seed.
        # Mirrors Swift: postEngineStopHandler?() called after engine stop.
        post_stop = self._on_post_engine_stop
        if post_stop is not None:
            post_stop()

        # Read the file — soundfile returns (data, samplerate).
        # data shape: (frames,) for mono, (frames, channels) for multi-channel.
        data, file_rate = _sf.read(path, dtype="float32", always_2d=True)
        # Downmix to mono by averaging channels — same as Swift's tap using mono format.
        mono = data.mean(axis=1).astype(np.float32)

        gt_log(f"🎤 readAudioFileAsMonoFloat32: {len(mono)} frames, {data.shape[1]} ch, {int(file_rate)} Hz")

        import os as _os
        file_name = _os.path.splitext(_os.path.basename(path))[0]

        # The file defines the analysis rate from now on — set before the worker starts, so the caller
        # sees it on return (Swift prepareForFilePlayback sets actualSampleRate before dispatch).
        self.rate = int(file_rate)
        self.is_playing_file = True
        self.playing_file_name = file_name
        self._set_running(True)  # the engine runs on the file, as Swift's isRunning

        my_generation = self._file_playback_generation

        def _playback_worker() -> None:
            """Call process_file_data, then restart the mic."""
            self.process_file_data(mono, int(file_rate), file_name)

            # Superseded by a newer playback, or stopped: skip the rest. The mic restart and the
            # finished callback run on the main thread (Swift: DispatchQueue.main.async), checked again
            # there. Mirrors Swift guard self.filePlaybackGeneration == myGeneration.
            if self._file_playback_generation != my_generation:
                return

            def _restart_if_current() -> None:
                if self._file_playback_generation == my_generation:
                    self._restart_mic_after_playback()

            self._on_main(_restart_if_current)

        thread = threading.Thread(target=_playback_worker, daemon=True, name="FilePlayback")
        self._file_playback_thread = thread
        thread.start()

    def stop_file_playback(self) -> None:
        """Stop a file playback before the end of the file and switch back to the microphone.

        The rest of the file is not played, and nothing from it is processed: no partial FFT frame is
        flushed and an unfinished capture is not completed — the playback is being abandoned. The
        playback's ``_on_playback_finished`` callback runs, as it does at the end of a file. No-op when
        no file is playing. Mirrors Swift ``RealtimeFFTAnalyzer.stopFilePlayback()``.
        """
        if not self.is_playing_file:
            return
        gt_log("🎤 File playback stopped")
        # The worker checks the generation on every chunk and before any end-of-file work; the bounded
        # join lets a chunk already being processed finish (Swift: audioProcessingQueue.sync {}).
        self._file_playback_generation += 1
        worker = self._file_playback_thread
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=0.5)
        self._input_buffer = []
        self._input_buffer_len = 0
        self.is_playing_file = False
        self.playing_file_name = None
        self._restart_mic_after_playback()

    def _on_main_and_wait(self, fn) -> None:
        """Run *fn* on the main thread and wait for it (Swift ``DispatchQueue.main.sync``). Already on the
        main thread, or with no Qt application, runs it here."""
        from PySide6 import QtCore
        app = QtCore.QCoreApplication.instance()
        if app is None or QtCore.QThread.currentThread() is app.thread():
            fn()
        else:
            self.proc_thread.runOnMainBlocking.emit(fn)

    def _on_main(self, fn) -> None:
        """Run *fn* on the main thread without waiting (Swift ``DispatchQueue.main.async``). With no Qt
        application, runs it here."""
        from PySide6 import QtCore
        if QtCore.QCoreApplication.instance() is None:
            fn()
        else:
            self.proc_thread.runOnMain.emit(fn)

    def _restart_mic_after_playback(self) -> None:
        """Restart the PortAudio stream so the mic is live again, then run the playback's finished
        callback once. A test instance has no stream to restart (Swift: ``if !self.isForTesting {
        try? self.start() }``). Mirrors Swift's main-thread block after a playback and
        ``runFilePlaybackCompletion``."""
        from guitar_tap.utilities.logging import TAP_DEBUG as _td

        _td("file_playback", "MIC_RESTART")
        if not self.is_for_testing:
            try:
                with self._stop_lock:
                    self.is_stopped = False
                self.stream.start()
                self._set_running(True)
            except Exception:
                self._set_running(False)
        _td("file_playback", "MIC_RESTART_DONE")
        cb = self._on_playback_finished
        self._on_playback_finished = None
        if cb is not None:
            cb()

    def close(self) -> None:
        """Stop the audio stream and shut down the hot-plug monitor.

        Mirrors Swift RealtimeFFTAnalyzer.deinit.
        """
        if self.is_for_testing:
            return
        self._stop_hotplug_monitor()
        self._close_stream_only()

    # MARK: - Buffer-delivery Watchdog (mirrors RealtimeFFTAnalyzer+Watchdog.swift)
    #
    # Recovers from a silently-wedged stream: the PortAudio callback (new_frame)
    # stops firing with no error (mic contention, device reconfiguration, sleep/wake).
    # A 1 Hz QTimer detects the silence and re-opens the stream with bounded backoff.

    _WATCHDOG_BACKOFFS = (0.5, 1.0, 2.0, 4.0)


    # @parity audio/buffer-watchdog tests=test/buffer-watchdog
    def start_buffer_watchdog(self, is_watchdog_recovery: bool = False) -> None:
        """(Re)start the buffer-delivery watchdog: stamp its clocks from the wall clock, give a deliberate
        start a clean slate, and start the 1 Hz tick (a main-thread QTimer). Called by a start and by a
        recovery's successful restart. Mirrors Swift startBufferWatchdog(isRecovery:)."""
        from PySide6 import QtCore
        self.stop_buffer_watchdog()
        self._watchdog_engine_start_time = self.wall_clock.now()
        self._last_buffer_time = self.wall_clock.now()
        # Prime the dead-input clock too, so its window is measured from the start -- but ONLY for a
        # start the user asked for.
        #
        # A watchdog RECOVERY must not stamp this: _last_signal_time means "signal was last
        # OBSERVED", and a restart observes nothing.  Stamping it would make the next tick read
        # HEALTHY, clearing the warning and resetting the attempt streak, while the clean slate below
        # cleared the exhausted latch -- so DEAD_INPUT_EXHAUSTED would be unreachable and the stream
        # would restart every 15 s forever, strobing the warning, on any permanently silent input
        # (a BlackHole 2ch virtual input, for one).  Mirrors Swift start(isWatchdogRecovery:).
        if not is_watchdog_recovery:
            self._last_signal_time = self.wall_clock.now()
            # A deliberate (re)start gets a clean slate: full recovery attempts again.
            self._watchdog_recovery_exhausted = False
            self._watchdog_recovery_attempts = 0
            self._set_input_could_not_restart(False)
        if getattr(self, "is_for_testing", False):
            return  # no timer in a test: the test calls the tick itself
        timer = QtCore.QTimer()
        timer.setInterval(1000)
        timer.timeout.connect(self._check_buffer_watchdog)
        timer.start()
        self._watchdog_timer = timer

    def stop_buffer_watchdog(self) -> None:
        """Stop the watchdog (intentional stop / before each recovery restart)."""
        timer = self._watchdog_timer
        if timer is not None:
            timer.stop()
            self._watchdog_timer = None

    def _check_buffer_watchdog(self) -> None:
        """One tick: recover if the live stream has gone silent past the threshold."""
        # A PortAudio re-initialise skipped for a pending stream close is retried from here once
        # the close is no longer pending.
        self._retry_owed_reinit()
        # Running — or given up, which still watches even when failed restarts left the stream closed.
        if (self.is_stopped and not self._watchdog_recovery_exhausted) or self.is_playing_file or self._is_recovering:
            return
        # A permission problem (not a wedge) is the permission check's; don't fight it. Only recover
        # when macOS reports the microphone authorized. As Swift's tick.
        if not self.microphone_authorized():
            return
        started = self._watchdog_engine_start_time
        now = self.wall_clock.now()
        if started is None or (now - started) <= 4.0:
            return  # startup grace — let a freshly-(re)started stream deliver its first buffer

        # The rule itself lives in dead_input.py as a pure function, so the whole truth
        # table is unit-testable without a clock, a timer or audio hardware.  This tick
        # only carries out the decision.
        decision = watchdog_decision(
            now=now,
            last_buffer_time=self._last_buffer_time,
            last_signal_time=self._last_signal_time,
            recovery_exhausted=self._watchdog_recovery_exhausted,
            silence_threshold=self._watchdog_silence_threshold,
            dead_input_threshold=self._watchdog_dead_input_threshold,
        )

        if decision is WatchdogDecision.STARVED:
            gt_log(f"⏱️ Buffer watchdog: no audio for {now - self._last_buffer_time:.1f}s "
                   f"while running — I/O appears wedged")
            self._is_recovering = True
            self._attempt_watchdog_recovery()
            return

        if decision is WatchdogDecision.DEAD_INPUT:
            gt_log(f"🔇 Dead-input watchdog: buffers arriving but no signal for "
                   f"{now - self._last_signal_time:.1f}s — input appears dead")
            if not self.input_appears_dead:
                self.input_appears_dead = True
                self._emit_input_appears_dead(True)
            self._is_recovering = True
            self._attempt_watchdog_recovery()
            return

        if decision is WatchdogDecision.DEAD_INPUT_EXHAUSTED:
            # Out of restart attempts: keep the warning up and keep watching, so the
            # app heals itself the moment audio returns instead of staying deaf.
            if not self.input_appears_dead:
                self.input_appears_dead = True
                self._emit_input_appears_dead(True)
            return

        # Healthy — signal is flowing again.  Clear the warning, the recovery streak
        # and the exhausted latch, so a later failure gets a full set of attempts.
        if self.input_appears_dead:
            self.input_appears_dead = False
            self._emit_input_appears_dead(False)
        self._set_input_could_not_restart(False)
        # Real audio falsifies any earlier "permission denied" determination. Mirrors Swift.
        if self.microphone_permission_denied:
            gt_log("✅ Receiving audio — clearing the earlier permission-denied determination")
            self._set_microphone_permission_denied(False)
        if self._watchdog_recovery_exhausted:
            gt_log("✅ Audio input returned — dead-input warning cleared, recovery re-armed")
            self._watchdog_recovery_exhausted = False
        if self._watchdog_recovery_attempts != 0:
            self._watchdog_recovery_attempts = 0

    def _emit_input_appears_dead(self, dead: bool) -> None:
        """Emit the dead-input edge on the processing thread's signal.

        Guarded in case the mic has no processing thread. The thread is created once, in the mic's
        ``__init__``, and is not torn down or replaced by a recovery restart.
        """
        thread = getattr(self, "proc_thread", None)
        if thread is not None:
            thread.inputAppearsDeadChanged.emit(dead)

    def _set_input_could_not_restart(self, failed: bool) -> None:
        """Set whether the input could not be restarted, and emit the edge on the processing thread's
        signal, as ``_emit_input_appears_dead`` does."""
        if self.input_could_not_restart == failed:
            return
        self.input_could_not_restart = failed
        thread = getattr(self, "proc_thread", None)
        if thread is not None:
            thread.inputCouldNotRestartChanged.emit(failed)

    def _attempt_watchdog_recovery(self) -> None:
        """Schedule one bounded, backed-off recovery restart, on the wall clock."""
        self._watchdog_recovery_attempts += 1
        if self._watchdog_recovery_attempts > self._watchdog_max_attempts:
            # Stop RESTARTING, but keep WATCHING.  Stopping the timer here left the app
            # permanently deaf: nothing remained to notice the input coming back, so a
            # user who fixed the microphone — reconnected it, un-muted it, raised an
            # input level — saw no change until they relaunched.  The tick is cheap; it
            # now keeps evaluating and clears the warning as soon as signal returns.
            gt_log(f"❌ Buffer watchdog: giving up on restarts after "
                   f"{self._watchdog_max_attempts} attempts — still watching; "
                   f"will clear as soon as audio returns")
            self._is_recovering = False
            self._watchdog_recovery_exhausted = True
            # The last restart failed, so the stream is closed: say so, and re-arm the watchdog, so it
            # keeps watching — the dead-input warning follows, and signal returning clears both.
            if self.engine_start_failed:
                self._set_input_could_not_restart(True)
                self.start_buffer_watchdog(is_watchdog_recovery=True)
            return
        idx = min(self._watchdog_recovery_attempts - 1, len(self._WATCHDOG_BACKOFFS) - 1)
        backoff = self._WATCHDOG_BACKOFFS[idx]
        gt_log(f"🔄 Buffer watchdog: recovery attempt "
               f"{self._watchdog_recovery_attempts}/{self._watchdog_max_attempts} in {backoff}s")
        # Close the stream now, as Swift's recovery stops the engine when it schedules its restart:
        # a device refresh while the restart is pending then only updates the selection, and the
        # restart opens whichever device is selected — one stream, opened once.
        self._close_stream_only()
        self.wall_clock.after(backoff, self._do_watchdog_restart)

    def _reopen_input_for_watchdog(self) -> None:
        """The recovery's restart: the permission checked first, then the selected device
        reopened. A refused permission raises the flag and MicrophonePermissionError, so the status
        says the microphone access is required rather than that the input could not be restarted.
        As Swift's recovery, which restarts through start() and its permission check."""
        if not self._check_microphone_permission():
            raise MicrophonePermissionError("Microphone access not determined")
        self.reinitialize_portaudio()

    def _do_watchdog_restart(self) -> None:
        """Re-open the selected device via ``_reopen_input_for_watchdog``, then re-arm.

        A restart that cannot open the device is a failed attempt: it retries at once through
        ``_attempt_watchdog_recovery`` (bounded by max attempts), as Swift's recovery does when
        ``start()`` throws.
        """
        try:
            (self.watchdog_restart or self._reopen_input_for_watchdog)()
        except Exception as e:  # noqa: BLE001 — last-resort recovery, never raise
            # A device that could not be opened is named; any other failure is logged as Swift's.
            device_name = getattr(e, "device_name", None)
            if device_name is not None:
                gt_log(f"⚠️ Buffer watchdog: restart could not open '{device_name}' — retrying")
            else:
                gt_log(f"⚠️ Buffer watchdog: restart failed ({e}) — retrying")
            self.engine_start_failed = True
            self._attempt_watchdog_recovery()
            return
        self.engine_start_failed = False
        self._set_running(True)
        gt_log(f"✅ Buffer watchdog: stream restarted (attempt {self._watchdog_recovery_attempts})")
        self._is_recovering = False
        # re-arm; only REAL signal clears the streak
        self.start_buffer_watchdog(is_watchdog_recovery=True)
