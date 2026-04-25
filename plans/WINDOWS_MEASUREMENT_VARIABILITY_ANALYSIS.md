# Windows Measurement Variability Analysis

## Problem Statement

On Windows (Python/sounddevice), tap-tone measurements are inconsistent — waveforms and
identified peaks vary from tap to tap. On macOS and iPad (Swift/AVAudioEngine/CoreAudio),
the same user performing the same taps produces consistent, reproducible results. The FFT
pipeline has been independently verified to produce identical output given identical input,
so the variability must originate before the FFT — in audio acquisition, chunk delivery,
or gated capture.

---

## Root Causes (ordered by likelihood)

### 1. WASAPI Shared-Mode Sample Rate Coercion (most likely)

**Mechanism:** When sounddevice opens a WASAPI stream in shared mode (the default), Windows
silently resamples audio to the device's system-configured rate (Sound Control Panel /
Audio MIDI Setup equivalent). The configured rate is commonly 48000 Hz even when the device
natively supports 44100 Hz. The code requests `samplerate=self.rate` (from
`device.sample_rate`) and PortAudio reports success, but the stream actually delivers
48000 Hz samples. The code never validates the actual opened rate against the requested
rate.

**Impact:** The gated capture window is calculated in `_accumulate_gated_samples()` as:

```python
# tap_tone_analyzer_spectrum_capture.py:192-193
rate = float(self._gated_sample_rate)          # reads self.mic.rate — the REQUESTED rate
target_samples = int(rate * self.GATED_CAPTURE_DURATION)   # 0.4 s × requested rate
```

If `self.mic.rate = 44100` but the stream delivers 48000 Hz, the window is calculated as
17640 samples but fills in ~367 ms of real time instead of 400 ms. More critically, the
pre-roll buffer capacity is also wrong:

```python
# tap_tone_analyzer_spectrum_capture.py:82-83
return int(self.mic.rate * self._pre_roll_seconds)   # 44100 × 0.2 = 8820 samples
```

At 48000 Hz, 8820 samples = 183.75 ms instead of 200 ms. Each tap captures a slightly
different acoustic slice, and the mismatch shifts every time the stream is reopened (e.g.,
after a device change or app restart). On macOS, Swift reads the actual engine sample rate
via `inputNode.inputFormat(forBus:0).sampleRate` after starting, so `self.mic.rate` always
reflects what the hardware is actually doing.

**Verification:** After `stream.start()` in `set_device()`, query:
```python
actual = sd.query_devices(self.device_index)['default_samplerate']
```
Compare to `self.rate`. A mismatch confirms this cause.

---

### 2. Variable WASAPI Chunk Sizes Break Pre-Roll Alignment

**Mechanism:** The code requests `blocksize=self.chunksize` (1024 samples). CoreAudio on
macOS guarantees exactly the requested buffer size. PortAudio on Windows WASAPI shared mode
negotiates the buffer size with the audio driver and may deliver 128, 256, 480, 512, or
other sizes regardless of the request — especially with USB audio interfaces which have
their own hardware buffer constraints.

**Impact:** Tap detection fires in `detect_tap()` once per chunk, after the chunk has
already been accumulated. The tap is known to have occurred *sometime during that chunk*,
but the exact sub-chunk position is unknown. When gated capture starts, the pre-roll buffer
is seeded with the last `_pre_roll_samples` worth of samples. The acoustic offset of the
tap impact relative to the start of the gated capture window therefore varies by up to one
full chunk duration:

- 1024-sample chunks (requested): max offset jitter = ~23 ms at 44100 Hz
- 480-sample chunks (WASAPI typical): max offset jitter = ~11 ms — *smaller* but
  inconsistent across taps if chunk sizes vary during a session
- Mixed chunk sizes: offset varies tap-to-tap, producing different waveform alignments

On macOS, `installTap(bufferSize:1024)` guarantees exactly 1024 samples per callback, so
the tap-position jitter is bounded and consistent.

**Verification:** Log `data.shape[0]` inside `new_frame()` on Windows and check whether
chunk sizes vary during a session.

---

### 3. Windows Audio Driver Enhancements (AGC, Noise Suppression)

**Mechanism:** Windows enables "audio enhancements" by default on many microphone devices:
Automatic Gain Control (AGC), Noise Suppression, Loudness Equalization, and Bass Boost.
These are applied in the driver before PortAudio receives the samples. The result is that
even identical taps produce different amplitude and spectral shapes — AGC adjusts the gain
between taps based on the ambient noise level, and noise suppression modifies the decay
tail of the tap transient.

**Impact:** Since each tap is recorded at a different effective gain level, the relative
magnitudes of resonant peaks change from tap to tap. Peaks near the noise floor are
suppressed differently each time. This is the most user-facing explanation — the user taps
consistently but the recordings look different because Windows is modifying the signal.

On macOS, CoreAudio bypasses all audio enhancement layers and delivers raw hardware samples.

**Verification:** Control Panel → Sound → Recording → device Properties → Additional
device settings → Enhancements → Disable all enhancements. Repeat measurements and check
for improved consistency.

---

### 4. CPU Scheduling Jitter on the PortAudio Callback Thread

**Mechanism:** Windows is not a real-time OS. The PortAudio callback thread can be
preempted by other processes. If the callback is delayed, PortAudio may deliver a
catch-up chunk (double-sized or larger) or accumulate latency silently. The `new_frame`
callback enqueues chunks into `self.queue` without bounds, so no samples are dropped, but
the pre-roll buffer may contain samples from further back in time than intended when the
tap fires.

**Impact:** Intermittent rather than systematic. Would manifest as occasional outlier
measurements rather than uniform inconsistency across all taps.

**Mitigation:** The `_status` parameter in `new_frame` (currently unused/ignored) carries
PortAudio overflow/underflow flags. Logging these would reveal whether callback timing
problems are occurring.

---

## What Is NOT the Cause

- **The FFT pipeline itself** — independently verified to produce identical output for
  identical input.
- **The gated capture accumulation logic** — correctly handles variable chunk sizes; the
  ring buffer accumulates until `>= target_samples` regardless of chunk size.
- **The tap detection threshold formula** — `slider_value - 100 = dBFS` is linear and
  platform-independent.
- **The pre-roll seeding logic** — correctly seeds the accumulator with the ring buffer
  contents at capture-open time.

---

## Recommended Diagnostic Steps

1. **Verify sample rate:** After `stream.start()` in `set_device()`, log both
   `self.rate` and `sd.query_devices(self.device_index)['default_samplerate']`.
   A mismatch = cause #1 confirmed.

2. **Verify chunk sizes:** Log `data.shape[0]` in the `new_frame` callback for 10 seconds.
   Any value other than 1024 = cause #2 present.

3. **Disable Windows audio enhancements:** Go to Sound → Recording device properties →
   Enhancements → Disable All. Repeat measurements and compare variance.

4. **Log PortAudio status flags:** In `new_frame`, log `_status` when non-zero to detect
   overflow or underflow events.

---

## Potential Fixes (if diagnostics confirm a cause)

### Fix for cause #1 (sample rate mismatch)
After opening the stream, query the actual sample rate and update `self.rate` and all
dependent calculations (`self.freq`, pre-roll capacity, gated window) to use the actual
hardware rate rather than the requested rate.

### Fix for cause #2 (variable chunk sizes)
The gated capture is already robust to variable chunk sizes at the accumulation level.
The tap-position jitter within the first chunk is unavoidable without sub-chunk timing
information. The multi-tap averaging mode (`number_of_taps > 1`) naturally averages out
this jitter and should be preferred on Windows for reproducibility.

### Fix for cause #3 (audio enhancements)
Document in the user guide that Windows audio enhancements must be disabled. Consider
adding a startup warning on Windows if enhancements cannot be programmatically detected.
There is no reliable API to disable them from within the app.

---

## Related Code Locations

| File | Relevant Lines | Topic |
|------|---------------|-------|
| `models/realtime_fft_analyzer_device_management.py` | 260–274 | `set_device()` — stream open, no rate validation |
| `models/realtime_fft_analyzer.py` | 546–552 | `sd.InputStream` creation with `blocksize` |
| `models/realtime_fft_analyzer.py` | ~193 | `new_frame` callback — `_status` discarded |
| `models/tap_tone_analyzer_spectrum_capture.py` | 69 | `GATED_CAPTURE_DURATION = 0.4` |
| `models/tap_tone_analyzer_spectrum_capture.py` | 80–83 | `_pre_roll_samples` — uses `self.mic.rate` |
| `models/tap_tone_analyzer_spectrum_capture.py` | 86–89 | `_gated_sample_rate` — uses `self.mic.rate` |
| `models/tap_tone_analyzer_spectrum_capture.py` | 192–202 | `start_gated_capture()` — window calculation |
| `models/tap_tone_analyzer.py` | 440 | `chunksize=1024` — requested, not guaranteed |
