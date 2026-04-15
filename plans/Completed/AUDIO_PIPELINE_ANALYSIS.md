# Audio Pipeline Analysis: Swift ↔ Python

A side-by-side comparison of the two audio processing paths to identify
real differences in timing, threading, and behaviour.

---

## Pipeline overview

Both implementations use the same three-stage architecture:

| Stage | Swift | Python |
|-------|-------|--------|
| 1. Hardware callback | CoreAudio thread → `audioProcessingQueue.async` | PortAudio thread → `queue.put()` |
| 2. Background processing | `audioProcessingQueue`: accumulates samples, computes FFT, calls `rawSampleHandler` | `_FftProcessingThread` (QThread): drains queue, accumulates ring buffer, calls `raw_sample_handler`, computes FFT |
| 3. Main thread delivery | `DispatchQueue.main.async { magnitudes = db }` → Combine fires `on_fft_frame` | `fftFrameReady.emit()` → Qt `QueuedConnection` → `on_fft_frame` |

Tap detection, frozen spectrum capture, and all gated-FFT phase routing
run on the **main thread** in both implementations.

---

## Buffer accumulation: Swift vs Python

### Swift accumulation model

Swift requests a **1024-sample** hardware tap buffer (hardcoded in
`RealtimeFFTAnalyzer+EngineControl.swift`, line 223):

```swift
let maxSafeBufferSize: AVAudioFrameCount = 1024
let requestedBufferSize = min(AVAudioFrameCount(fftSize), maxSafeBufferSize)
```

The comment explains the intent:
> "Using 1024 samples (~23ms at 44.1kHz) for faster level metering updates.
> FFT accuracy is unaffected since samples are accumulated to fftSize regardless."

`processAudioBuffer` accumulates these 1024-sample callbacks into `inputBuffer`
until it reaches `fftSize` samples, then fires the FFT. So if `fftSize = 16384`,
Swift calls the AVAudioEngine callback **16 times** before running one FFT.

Two things happen on **every 1024-sample callback** regardless of FFT firing:
1. `rawSampleHandler` is called with those 1024 samples
2. `inputLevelDB` and `recentPeakLevelDB` are updated on the main thread

### Python accumulation model

Python uses a PortAudio `blocksize = chunksize = 4096` (set in
`TapToneAnalyzer.__init__`, `tap_tone_analyzer.py` line 431). The
`_FftProcessingThread` accumulates incoming chunks into a ring buffer of size
`m_t = fft_size = 16384`. It fires an FFT only when
`_samples_since_last_fft >= m_t` (lines 277-279).

Since `chunksize (4096) < fft_size (16384)`, the thread accumulates **four
chunks** before firing one FFT. Sub-FFT accumulation is active, just as in
Swift.

Two things happen on **every 4096-sample callback**:
1. `raw_sample_handler` is called with those 4096 samples
2. `rmsLevelChanged` is emitted

### Effective FFT frame rate: IDENTICAL

Both implementations compute one FFT per `fft_size` samples. At 16384 samples
and 44.1 kHz, that is one FFT every ~371 ms (~2.7 fps). **The apps correctly
report identical FFT frame rates.** The earlier analysis claiming a 16× FFT
rate difference was wrong — it missed Swift's buffer accumulation logic.

---

## Gated-FFT pipeline (plate/brace measurements)

### Swift flow

```
audioProcessingQueue (background):
    processAudioBuffer(buffer)           ← called every 1024 samples
        → rawSampleHandler?(samples, sampleRate)
        → accumulateGatedSamples(samples, sampleRate)
            maintains preRollBuffer (always)
            when gatedCaptureActive: appends to gatedAccumBuffer
            when full: gatedCaptureActive = false
                → DispatchQueue.main.async {
                      finishGatedFFTCapture(samples, sampleRate, phase)
                  }
```

Protected by: `mpmLock` (NSLock) on all preRollBuffer/gatedAccumBuffer access.

### Python flow

```
_FftProcessingThread (QThread background):
    run() loop, every chunk:             ← called every 16384 samples
        → mic.raw_sample_handler(chunk_f32, rate)
        → _accumulate_gated_samples(chunk, sample_rate)
            maintains _pre_roll_buf (always)
            when _gated_capture_active: appends to _gated_accum
            when full: _gated_capture_active = False
                → proc_thread.gatedCaptureComplete.emit(captured, rate, phase)
                   [Qt QueuedConnection → main thread]
                → finish_gated_fft_capture(samples, sample_rate, phase)
```

Protected by: `self._gated_lock` (threading.Lock) on all buffer access.

### Assessment

The structures are equivalent. `DispatchQueue.main.async` and Qt's
`QueuedConnection` emit both route the captured buffer to the main thread
for `finishGatedFFTCapture`/`finish_gated_fft_capture`. The NSLock and
`threading.Lock` are functionally equivalent for single-writer protection.

---

## Real differences

### 1. Raw sample handler granularity — RESOLVED

Both implementations now use **1024-sample chunks**.

Swift's `rawSampleHandler` is called every 1024 samples (~23 ms).
Python's `raw_sample_handler` is called every 1024 samples (~23 ms)
(`chunksize=1024` in `tap_tone_analyzer.py:431`).

Pre-roll resolution, gated accumulator fill granularity, and level meter update
rate are now identical.

### 2. Level meter update rate — RESOLVED

Both implementations update at **~43 Hz** (every 1024 samples).

Swift: `inputLevelDB` posted via `DispatchQueue.main.async`.
Python: `rmsLevelChanged` emitted every chunk by `_FftProcessingThread`.

### 3. Safety timeout delivery — RESOLVED

Swift's gated-capture safety timeout uses `DispatchQueue.main.asyncAfter`
(2 seconds), which guarantees main-thread execution.

Python used `threading.Timer(2.0, _safety_timeout)`, which fires on a
background thread. The callback called `finish_gated_fft_capture()` (emits
`spectrumUpdated`, `peaksChanged` Qt signals) and wrote `Published` properties
directly off the main thread. A second `threading.Timer` in
`re_enable_detection_for_next_plate_tap` had the same problem, writing
`is_above_threshold`, `is_detecting`, and `tap_detected` off main.

**Fix applied (`tap_tone_analyzer_spectrum_capture.py`, `tap_tone_analyzer_tap_detection.py`):**
- Safety timeout "has data" branch: emits `proc_thread.gatedCaptureComplete`
  from the background thread; Qt's queued connection delivers
  `finish_gated_fft_capture` on main (same path as normal capture completion).
- Safety timeout "no data" branch: uses `QMetaObject.invokeMethod(self,
  "_on_safety_timeout_no_samples", QueuedConnection)` to post to main.
- `re_enable_detection_for_next_plate_tap`: timer callback now uses
  `QMetaObject.invokeMethod(self, "_do_reenable_detection", QueuedConnection)`
  instead of writing state directly off main.

---

## What is NOT a difference

- **FFT frame rate:** Both fire one FFT per `fft_size` samples. Identical.
  The apps report the same frame rate because they are the same.
- **Continuous FFT window:** Both use a rectangular (boxcar) window for the
  live display path. Swift's `performFFT` comment (line 257) explicitly
  states: "Apply rectangular window (all ones — effectively no windowing).
  This is intentional for the live display path." Python uses `"boxcar"`.
  Identical.
- **Gated FFT window:** Both use a Hann window. Identical.
- **Thread architecture:** Both use background thread for FFT, main thread
  for tap detection and phase routing. Equivalent.
- **Gated FFT algorithm:** HPS + Q filter, pre-roll seeding, power averaging,
  phase routing logic. Equivalent (modulo chunk granularity noted above).
- **Lock discipline:** NSLock (Swift) ↔ threading.Lock (Python) on all
  shared buffer access. Equivalent.
- **Main-thread delivery of gated result:** `DispatchQueue.main.async` ↔
  Qt `QueuedConnection`. Equivalent.

---

## Summary of real differences

| # | Difference | Swift | Python | Status |
|---|---|---|---|---|
| 1 | `rawSampleHandler` / `raw_sample_handler` call granularity | Every 1024 samples (~23 ms) | Every 1024 samples (~23 ms) | **Resolved** |
| 2 | RMS level meter update rate | ~43 Hz (every 1024 samples) | ~43 Hz (every 1024 samples) | **Resolved** |
| 3 | Safety timeout thread context | `DispatchQueue.main.asyncAfter` (definitively main) | `QMetaObject.invokeMethod(QueuedConnection)` | **Resolved** |

---

## Recommended changes, in priority order

| Priority | Change | Status | Effect |
|----------|--------|--------|--------|
| 1 | Reduce `chunksize` from 4096 to 1024 | **Done** (`tap_tone_analyzer.py:431`) | Matches Swift's raw sample handler granularity and level meter update rate exactly; FFT frame rate unchanged |
| 2 | Fix safety timeout and re-enable timer to post to main thread | **Done** (`tap_tone_analyzer_spectrum_capture.py`, `tap_tone_analyzer_tap_detection.py`) | Eliminates off-main-thread Qt signal emission and Published property writes |
