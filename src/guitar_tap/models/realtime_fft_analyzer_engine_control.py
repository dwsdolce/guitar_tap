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
  rawSampleHandler / inputBuffer    ↔  get_frames()  [Python-only drain helper]

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

    self.stream.start()

PortAudio's ``sounddevice.InputStream`` encapsulates steps 1–6 and 9–10
entirely:
- Device selection was applied at stream construction time (``__init__`` or
  ``set_device()``), not at start time — equivalent to Swift's AUHAL device
  property set before ``audioEngine.start()``.
- Permission handling is implicit; PortAudio returns an error at stream-open
  time (in ``__init__``) rather than at start time.
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
3. Clears ``inputBuffer`` on ``bufferAccessQueue``.
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

import queue
import threading
import time
from typing import TYPE_CHECKING

import sounddevice as sd
import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from typing import Callable


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
        with self._stop_lock:
            if self.is_stopped:
                raise sd.CallbackStop
        self.queue.put(data[:, 0])  # take first channel

        return None

    def get_frames(self) -> list[npt.NDArray[np.float32]]:
        """Non-blocking drain: returns all audio chunks currently in the queue.

        Python-only — Swift exposes audio via ``rawSampleHandler`` and the
        ``inputBuffer`` accumulation inside ``processAudioBuffer(_:)``.
        """
        frames: list[npt.NDArray[np.float32]] = []
        try:
            while True:
                frames.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        return frames

    def start(self) -> None:
        """Start the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.start() (+EngineControl.swift).
        Swift starts AVAudioEngine and installs the input tap after checking
        microphone permission; Python starts the PortAudio InputStream directly.
        """
        self.stream.start()

    def stop(self) -> None:
        """Stop the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.stop() (+EngineControl.swift).
        """
        with self._stop_lock:
            self.is_stopped = True
        self.is_playing_file = False
        self.playing_file_name = None  # Mirrors Swift stop(): self?.playingFileName = nil
        self.stream.stop()

    # MARK: - WAV File Playback (mirrors Swift startFromFile(_ url:))

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

        # Stop the PortAudio stream so new_frame() doesn't race with the file thread.
        with self._stop_lock:
            self.is_stopped = True
        try:
            self.stream.stop()
        except Exception:
            pass

        # Drain the queue so the processing thread starts fresh.
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break

        # Read the file — soundfile returns (data, samplerate).
        # data shape: (frames,) for mono, (frames, channels) for multi-channel.
        data, file_rate = _sf.read(path, dtype="float32", always_2d=True)
        # Downmix to mono by averaging channels — same as Swift's tap using mono format.
        mono = data.mean(axis=1).astype(np.float32)

        # Update sample rate so _FftProcessingThread sees the file's native rate.
        # Mirrors Swift actualSampleRate = fileFormat.sampleRate.
        self.rate = int(file_rate)

        chunksize = self.chunksize
        self.is_playing_file = True
        self.is_stopped = False  # allow queue.put without the stop guard

        # Store the filename (without extension) for chart title use.
        # Mirrors Swift: playingFileName = url.deletingPathExtension().lastPathComponent
        import os as _os
        self.playing_file_name = _os.path.splitext(_os.path.basename(path))[0]

        # Use a mutable sentinel so _playback_worker can verify it is still the
        # active playback thread when the post-playback 0.3 s delay completes.
        # Mirrors Swift's `let scheduledPlayer = player` identity guard.
        sentinel: list[threading.Thread | None] = [None]

        def _playback_worker() -> None:
            """Pace audio chunks into self.queue at real-time speed, then restart the mic."""
            n_samples = len(mono)
            idx = 0
            chunk_duration = chunksize / file_rate  # seconds per chunk
            while idx < n_samples:
                if not self.is_playing_file:
                    break
                chunk = mono[idx: idx + chunksize]
                if len(chunk) == 0:
                    break
                self.queue.put(chunk)
                idx += chunksize
                time.sleep(chunk_duration)
            # Signal end-of-file.
            self.is_playing_file = False

            # Wait 0.3 s to let the last chunks drain through the FFT pipeline before
            # restarting the mic — mirrors Swift asyncAfter(fileDuration + 0.3s).
            time.sleep(0.3)

            # Guard: if a new file was opened while we were sleeping, our thread is
            # no longer the active one — skip the mic restart.
            if self._file_playback_thread is not sentinel[0]:
                return

            # Restart the PortAudio stream so the mic is live again.
            # Mirrors Swift try? self.start() which recreates the AVAudioEngine on the mic.
            # TapToneAnalyzer's is_measurement_complete guard preserves frozen results
            # so New Tap stays enabled — same as Swift's auto-start guard.
            try:
                with self._stop_lock:
                    self.is_stopped = False
                self.stream.start()
            except Exception:
                pass

            # Clear the playing filename and notify the caller (e.g. to update chart title).
            # Mirrors Swift's completion closure called inside asyncAfter after start().
            self.playing_file_name = None
            cb = self._on_playback_finished
            if cb is not None:
                cb()

        thread = threading.Thread(target=_playback_worker, daemon=True, name="FilePlayback")
        sentinel[0] = thread
        self._file_playback_thread = thread
        thread.start()

    def close(self) -> None:
        """Stop the audio stream and shut down the hot-plug monitor.

        Mirrors Swift RealtimeFFTAnalyzer.deinit.
        """
        self._stop_hotplug_monitor()
        self._close_stream_only()
