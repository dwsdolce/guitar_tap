"""
RealtimeFFTAnalyzer — Engine Control
=====================================

Python counterpart to Swift ``RealtimeFFTAnalyzer+EngineControl.swift``.

The engine-control responsibilities described here live on
``RealtimeFFTAnalyzer`` in ``realtime_fft_analyzer.py``.

---

## start()  [realtime_fft_analyzer.py:617]

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

Python ``start()`` (realtime_fft_analyzer.py:617):

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

## stop()  [realtime_fft_analyzer.py:626]

Swift ``stop()`` (~35 lines) does:

1. Calls ``unregisterSampleRateListener()`` (macOS).
2. If ``audioEngine.isRunning``: removes the input tap, stops the engine.
3. Clears ``inputBuffer`` on ``bufferAccessQueue``.
4. Resets ``firstBufferReceived``, ``fftCount``, ``engineStartTime``.
5. On the main thread: sets ``isRunning = false``, resets ``peakMagnitude``
   to -100 dB, resets ``peakFrequency`` to 0.

Python ``stop()`` (realtime_fft_analyzer.py:626):

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

## close()  [realtime_fft_analyzer.py:635]

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

## reinitialize_portaudio()  [realtime_fft_analyzer.py:669]

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

| Concern                         | Swift (+EngineControl.swift)          | Python (realtime_fft_analyzer.py) |
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
"""
