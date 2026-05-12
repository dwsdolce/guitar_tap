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

import os
import queue
import threading
import time
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
import sounddevice as sd

from guitar_tap.utilities.logging import gt_log

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
        with self._stop_lock:
            if self.is_stopped:
                raise sd.CallbackStop
        chunk = data[:, 0].copy()  # copy before queuing — PortAudio reuses the buffer
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
        gt_log("🎤 === Starting Audio Engine ===")
        self.stream.start()
        gt_log("🎤 Audio engine started")
        gt_log(f"🎤 Hardware sample rate: {self.rate} Hz, hardware channels: 1 (tap will use mono)")
        gt_log("🎤 Audio tap installed")

    def stop(self) -> None:
        """Stop the audio stream.

        Mirrors Swift RealtimeFFTAnalyzer.stop() (+EngineControl.swift).
        Uses abort() instead of stop() — see _close_stream_only() docstring.
        """
        gt_log("🎤 Stop requested")
        with self._stop_lock:
            self.is_stopped = True
        self.is_playing_file = False
        self.playing_file_name = None  # Mirrors Swift stop(): self?.playingFileName = nil
        self.stream.abort()

    # MARK: - WAV File Playback (mirrors Swift startFromFile(_ url:))

    def process_file_data(
        self,
        samples: "npt.NDArray[np.float32]",
        sample_rate: int,
        file_name: str,
    ) -> None:
        """Process pre-read mono audio through the FFT pipeline.

        Data-processing core of ``start_from_file``, factored out so tests
        can drive the pipeline without audio hardware.  The chunk-pacing
        loop, partial flush, and ``_on_pre_mic_restart`` call are included.
        Mic stop/restart and UI state management are NOT.

        Mirrors Swift ``RealtimeFFTAnalyzer.processFileData(samples:sampleRate:fileName:)``.

        Args:
            samples:     Mono float32 PCM array.
            sample_rate: Sample rate in Hz.
            file_name:   Display name for logging.
        """
        from utilities.logging import TAP_DEBUG as _td
        from .realtime_fft_analyzer_fft_processing import dft_anal as _dft_anal

        n_samples = len(samples)
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
            if not self.is_playing_file:
                _td("file_playback",
                    f"INTERRUPTED | idx={idx}/{n_samples} chunksPumped={chunks_pumped}"
                )
                break
            chunk = samples[idx: idx + chunksize]
            if len(chunk) == 0:
                break
            # Inline processing — no queue, no thread.
            # Mirrors Swift processFileData calling processRawSamples directly.
            self.process_raw_samples(chunk)
            idx += chunksize
            chunks_pumped += 1
            time.sleep(chunk_duration)
        elapsed = time.time() - t0
        _td("file_playback",
            f"END | chunksPumped={chunks_pumped} samplesPumped={idx} "
            f"elapsed={elapsed:.3f}s expected={expected_duration_s:.3f}s "
            f"realtimeRatio={elapsed/max(expected_duration_s,1e-9):.3f}x"
        )

        self.is_playing_file = False

        # Force-flush any partial audio still in the input buffer.
        # Mirrors Swift processFileData partial flush.
        if self._input_buffer:
            partial = np.concatenate(self._input_buffer)
        else:
            partial = np.zeros(0, dtype=np.float32)
        _td("file_playback", f"PARTIAL_FLUSH | partialSamples={len(partial)} fftSize={fft_size}")
        if len(partial) > 0:
            if len(partial) < fft_size:
                partial = np.concatenate(
                    [partial, np.zeros(fft_size - len(partial), dtype=np.float32)]
                )
            else:
                partial = partial[:fft_size]
            # Process the zero-padded partial through process_raw_samples
            # so both direct callbacks and Qt signals fire.
            self.process_raw_samples(partial)
            _td("file_playback", "PARTIAL_FLUSH_DONE")
        # Clear the input buffer so the caller starts from a clean slate.
        self._input_buffer = []
        self._input_buffer_len = 0

        # Flush any active gated capture by zero-padding the remaining
        # window.  Must happen BEFORE the mic restarts.
        # Mirrors Swift processFileData preMicRestartHandler call.
        pre_restart = self._on_pre_mic_restart
        _td("file_playback", f"PRE_MIC_RESTART | handler={'set' if pre_restart else 'None'}")
        if pre_restart is not None:
            pre_restart()
        _td("file_playback", "PRE_MIC_RESTART_DONE")

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
        # We tell the old worker to exit by clearing is_playing_file (its loop
        # guard), then bounded-join so it actually exits before we proceed.
        # Swift's AVAudioEngine handles this via engine.stop()/start() implicitly.
        prev_worker = getattr(self, "_file_playback_thread", None)
        if prev_worker is not None and prev_worker.is_alive():
            self.is_playing_file = False
            prev_worker.join(timeout=0.5)

        # ── Teardown: stop engine, drain queue, clear buffers ────────────
        # Mirrors Swift startFromFile(_:) preamble:
        #   1. audioEngine.stop()           → stop audio delivery
        #   2. audioProcessingQueue.sync {} → drain in-flight processing
        #   3. inputBuffer.removeAll()      → clear FFT accumulator
        #   4. fftFrameCounter = 0          → reset frame counters
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

            # 4. Clear the FFT accumulator and reset frame counters.
            #    Mirrors Swift: bufferAccessQueue.sync { inputBuffer.removeAll() }
            #    and fftFrameCounter = 0; samplesConsumed = 0.
            self._input_buffer = []
            self._input_buffer_len = 0
            self._fft_frame_counter = 0
            self._samples_consumed = 0
            self._diag_total_samples = 0  # DIAG: reset sample counter for file playback

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

        # Use a mutable sentinel so _playback_worker can verify it is still the
        # active playback thread when the post-playback delay completes.
        # Mirrors Swift's filePlaybackGeneration identity guard.
        sentinel: list[threading.Thread | None] = [None]

        def _playback_worker() -> None:
            """Call process_file_data, then restart the mic."""
            from utilities.logging import TAP_DEBUG as _td

            self.process_file_data(mono, int(file_rate), file_name)

            # Guard: if a new file was opened while we were processing, our
            # thread is no longer the active one — skip the rest.
            # Mirrors Swift guard self.filePlaybackGeneration == myGeneration.
            if self._file_playback_thread is not sentinel[0]:
                return

            # Restart the PortAudio stream so the mic is live again.
            # Mirrors Swift try? self.start() in startFromFile's main.async block.
            _td("file_playback", "MIC_RESTART")
            try:
                with self._stop_lock:
                    self.is_stopped = False
                self.stream.start()
            except Exception:
                pass
            _td("file_playback", "MIC_RESTART_DONE")

            # Notify the caller (e.g. to restore freq axis after mic restart).
            # Mirrors Swift's completion?() call.
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
        if self.is_for_testing:
            return
        self._stop_hotplug_monitor()
        self._close_stream_only()
