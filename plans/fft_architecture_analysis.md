# FFT Architecture Analysis — Swift ↔ Python Convergence

## Goal

Both implementations must be **structurally identical**: same named functions, same
call hierarchy, same algorithm, same architecture. Names may differ only by language
convention (camelCase Swift vs snake_case Python). No function should exist in one
language that has no direct counterpart in the other. "Wrapper" means not identical.

---

## Agreed Target Architecture (Candidate C)

Two named functions for the **live FFT path**, in both languages:

1. **Pure DSP function** — a free/static function (not an instance method). Takes all
   inputs as explicit parameters. Returns the magnitude spectrum. No side effects, no
   access to instance state, no observer notification.

2. **Dispatch function** — a named method on the class (Swift: `RealtimeFFTAnalyzer`,
   Python: `_FftProcessingThread`). Calls the pure DSP function, applies calibration,
   notifies observers (`@Published` / `fftFrameReady`).

The processing loop (`processAudioBuffer` / `run()`) accumulates samples and calls the
dispatch function — it does not call the pure DSP function directly.

The **gated FFT path** must follow the same two-layer pattern: a pure DSP function and
a named dispatch method. Whether both paths share one pure DSP function or each has its
own is an open question (see Q6 below).

---

## Open Questions

Each question records the current state, the divergence, and its resolution status.
Questions are ordered from most-resolved to most-open.

---

### Q1 — Overall architecture: how many named functions? (RESOLVED)

**Current state:**
- Swift has two named functions in the live path: `computeFFT(on:)` (pure DSP) and
  `performFFT(on:)` (dispatch).
- Python has one free function `dft_anal()` (pure DSP). The dispatch logic is
  **anonymous inline code** in `_FftProcessingThread.run()`.

**Divergence:** Python is missing a named dispatch function.

**Resolution — Candidate C:** Both languages must have the same two-layer structure:
a free/static pure DSP function and a named dispatch method on the class. Swift has
both; Python must add `perform_fft()`. No wrappers that exist only in one language.

---

### Q2 — `fftSetup` parameter: vDSP setup object (ACCEPTED DIVERGENCE)

**Current state:**
- Swift `computeFFT(on:)` reads `self.fftSetup` — a `vDSP_DFT_Setup` object (Apple
  Accelerate framework). This is a pre-computed cache of twiddle factors that vDSP
  requires before calling `vDSP_DFT_Execute`. It is created once at init.
- Python `dft_anal()` has no such parameter. `scipy.fft.fft()` needs no pre-computed
  setup; it creates its own internal plan each call (or uses an internal cache).

**Divergence:** Apple vDSP requires a setup object; NumPy/SciPy does not. This is a
necessary implementation artifact of the underlying FFT library, not a design choice.

**Resolution:** Accepted language-level divergence. No action required or possible.
The Swift signature will include `setup: vDSP_DFT_Setup` where Python has no equivalent
parameter. This is the one documented exception to the "identical signatures" rule.

Note: If Swift `computeFFT` is made `static`, `fftSetup` becomes an explicit parameter
(passed by the caller). See Q10.

---

### Q3 — `fftSize` / `n_freq_samples`: naming only (RESOLVED — NO ACTION)

**Current state:**
- Swift: `fftSize: Int` — the FFT window size N.
- Python: `n_freq_samples: int` — the FFT window size N.

**Divergence:** Name only. Both are the same integer: the number of samples in the FFT
window, which must be a power of two. Python's name (`n_freq_samples`) is arguably
slightly misleading (it is the total FFT size, not the number of frequency bins), but
this is existing code and not a structural issue.

**Resolution:** No code change. Document the equivalence. Python's existing parameter
name is preserved.

---

### Q4 — `window` / `window_function`: structural difference (OPEN)

**Current state:**
- Swift `computeFFT(on:)` reads `self.window` — a `[Float]` array of all-ones
  (rectangular window), set once at init via `vDSP_vfill`. It is not a parameter.
  A separate function `computeGatedFFT` uses a Hann window, applied inline without
  calling `computeFFT`.
- Python `dft_anal()` takes `window_function: Float64_1D` as an explicit parameter.
  The caller passes either a rectangular window (live path) or a Hann window (gated
  path). One function serves both paths.

**Divergence (design level):** Swift hardcodes the window choice per function. Python
passes the window as a parameter, making one function serve both paths. This is a real
architectural difference, not a naming difference.

**Two resolution options:**

Option 4A — Match Python (make Swift's window a parameter):
- `computeFFT` gains `window: [Float]` as an explicit parameter.
- The call site in `performFFT` passes `self.window` (the rectangular window).
- `computeGatedFFT` would also call `computeFFT`, passing its local Hann window.
- Result: one pure DSP function serves both paths in both languages. More general.

Option 4B — Match Swift (give Python two specialized functions):
- Python gets `dft_anal_rect()` for the live path and `dft_anal_hann()` for the gated
  path. Or: `dft_anal` is kept as-is and `compute_gated_fft` builds its own inline DSP.
- Result: each path has its own function in both languages. More explicit.

**Preferred:** Option 4A. Python's design is more general. Swift should adopt it.
This also directly enables Q6 resolution (one pure DSP function for both paths).
**Status: awaiting user confirmation.**

---

### Q5 — Return value: dB only vs. (dB, linear) tuple (OPEN)

**Current state:**
- Swift `computeFFT(on:)` returns `[Float]` — the dB-scale magnitude spectrum only.
- Python `dft_anal()` returns `(magnitude_db, abs_fft)` — both the dB-scale AND the
  linear-scale magnitude spectrum. The linear spectrum is used by the gated FFT path
  for HPS (Harmonic Product Spectrum) peak detection.

**Divergence:** Return type and content differ.

**Three resolution options:**

Option 5A — Match Swift (Python drops linear return):
- `dft_anal` returns only `magnitude_db`. The gated path recomputes linear scale where
  needed, or the linear value is computed separately.
- Simpler signature. Breaks all callers that use `abs_fft` today.

Option 5B — Match Python (Swift returns tuple):
- Swift `computeFFT` returns `(magnitudes: [Float], linearMagnitudes: [Float])`.
- More information available to callers. Swift callers that only need dB ignore the
  second element.
- `performFFT` (dispatch) uses only the dB component for calibration + publish.
- `computeGatedFFT` uses both.

Option 5C — Divergence is acceptable:
- The live display path only needs dB; the gated path needs linear. If the two paths
  have separate pure DSP functions (see Q6, Option 6B), each can return only what it
  needs. Swift `computeFFT` returns `[Float]` dB; Python live-path function also
  returns `[Float]` dB. The gated-path function returns the tuple in both languages.

**Interaction with Q4 and Q6:** The answer to Q5 depends heavily on Q6 (shared vs.
separate pure DSP functions). Recommend resolving Q6 first.
**Status: blocked on Q6.**

---

### Q6 — Gated FFT: shared DSP function or separate? (OPEN — CORE QUESTION)

**Current state:**
- Swift `computeGatedFFT(samples:sampleRate:)` is a fully self-contained instance
  method. It creates its own local `vDSP_DFT_Setup`, applies a local Hann window
  inline, runs the FFT inline, computes magnitudes and dB inline. It does **not** call
  `computeFFT`. DSP code is duplicated between the two paths.
- Python `compute_gated_fft(self, samples, sample_rate)` calls `dft_anal()` with a
  Hann window. It reuses the shared pure DSP function. No DSP code is duplicated.

**Divergence (architecture level):** Swift duplicates DSP between the two paths.
Python shares it. This is the most significant structural difference in the model layer.

**Two resolution options:**

Option 6A — Match Python (Swift calls the shared pure DSP function from gated path):
- `computeGatedFFT` calls `computeFFT` (or the static equivalent) with a Hann window.
- All DSP code lives in one place.
- Requires Q4 Option A (window as parameter) — otherwise `computeFFT` cannot accept
  the Hann window.
- This is the cleanest solution and eliminates code duplication in Swift.

Option 6B — Match Swift (Python gets separate DSP for each path):
- Python gets a dedicated function for the gated path, equivalent to Swift's inline
  DSP inside `computeGatedFFT`. `dft_anal` remains the live-path function.
- More code duplication. Less general. Only advantage: both languages duplicate code
  in the same way.

**Preferred:** Option 6A. Eliminating duplication is better than matching duplication.
Python's design is architecturally superior here. Swift should adopt it.
**Status: awaiting user confirmation.**

---

### Q7 — Gated FFT: which class owns it? (OPEN)

**Current state:**
- Swift `computeGatedFFT(samples:sampleRate:)` is an **instance method on
  `RealtimeFFTAnalyzer`** (the top-level analyzer class).
- Python `compute_gated_fft(self, samples, sample_rate)` is an **instance method on
  `_FftProcessingThread`** (the background processing thread class, nested inside
  the analyzer).

**Divergence:** Different class ownership. In Swift, the top-level class performs gated
FFT analysis. In Python, it is the internal thread.

**Context:** Swift has no equivalent of `_FftProcessingThread` — all FFT work runs
through `processAudioBuffer` on `audioProcessingQueue`. Python splits the accumulation
loop and FFT work onto a dedicated thread object. This means there is no single correct
mapping: Swift's `RealtimeFFTAnalyzer` corresponds structurally to both
`RealtimeFFTAnalyzer` AND `_FftProcessingThread` combined.

**Resolution options:**

Option 7A — Keep current placement (accepted divergence):
- Swift: `computeGatedFFT` on `RealtimeFFTAnalyzer`. Python: `compute_gated_fft` on
  `_FftProcessingThread`. Document as accepted structural divergence due to the
  thread-split architecture.

Option 7B — Move Python `compute_gated_fft` to `RealtimeFFTAnalyzer`:
- Makes class ownership match. `_FftProcessingThread` calls into the parent.
- More disruptive change. May not be worth it given the thread-split architecture.

**Preferred:** Option 7A. The thread-split is an accepted architectural divergence
(equivalent to the `_stop_lock`, `is_stopped`, queue, etc. that exist only in Python).
The gated FFT naturally belongs with the DSP thread in Python.
**Status: awaiting user confirmation.**

---

### Q8 — Calibration in gated FFT (OPEN)

**Current state:**
- Swift `computeGatedFFT` reads `self.activeCalibration` and applies it to the
  magnitude spectrum before returning.
- Python `compute_gated_fft` does NOT apply calibration. It returns raw dB values.
  The caller (`TapToneAnalyzer`) is responsible for any calibration adjustment.

**Divergence:** Swift applies calibration inside the function; Python does not.

**Resolution:** Whichever class owns the gated FFT dispatch (see Q7) should apply
calibration at that layer — not inside the pure DSP function. If Q6 Option A is
adopted, calibration belongs in the gated dispatch method (parallel to how `performFFT`
applies calibration for the live path). Currently Swift applies it inside what is
effectively the dispatch+DSP combined function.

**Status: depends on Q6 and Q7 resolution.**

---

### Q9 — Missing `perform_fft()` dispatch method in Python (OPEN — ACTIONABLE)

**Current state:**
- Swift has a named `performFFT(on: [Float])` method on `RealtimeFFTAnalyzer`. It
  calls `computeFFT`, applies `calibrationCorrections`, and publishes results to
  `@Published` properties on the main thread.
- Python `_FftProcessingThread.run()` performs the equivalent operations inline inside
  the while-loop. There is no named `perform_fft()` method.

**Divergence:** Python is missing the named dispatch layer. This was identified as the
first required change under Candidate C.

**Required change:** Extract the FFT dispatch block from `run()` into:
```python
def perform_fft(self, samples, calibration):
    mag_y_db, mag_y = dft_anal(samples, self._mic.window_fcn, self._mic.fft_size)
    if calibration is not None:
        mag_y_db = mag_y_db + calibration
    fft_peak_amp = int(np.max(mag_y_db) + 100.0)
    ...
    self.fftFrameReady.emit(mag_y_db, mag_y, fft_peak_amp, ...)
```
The `run()` loop calls `self.perform_fft(samples, calibration)`.

**Status: agreed, awaiting implementation approval.**

---

### Q10 — `computeFFT`: instance method vs. static/free function (OPEN — ACTIONABLE)

**Current state:**
- Swift `computeFFT(on:)` is an **instance method** that reads `self.fftSetup` and
  `self.window` from instance state. It cannot be called without a `RealtimeFFTAnalyzer`
  instance. This contradicts Candidate C which requires a free/static pure DSP function.
- Python `dft_anal()` is a **module-level free function**. All inputs are explicit
  parameters. This is correct per Candidate C.

**Required change — Swift:** Make `computeFFT` a `static` function. `self.fftSetup`
and `self.window` become explicit parameters.

**Complication — `vDSP_DFT_Setup`:** This is a C opaque pointer type managed by
Accelerate. Passing it as a parameter is valid (the caller retains ownership and ensures
lifetime). The `static` call site in `performFFT` passes `self.fftSetup!` and
`self.window`. Test code constructs its own setup and window and passes them directly,
removing the need for a live `RealtimeFFTAnalyzer` instance in unit tests.

**Proposed static signature:**
```swift
static func computeFFT(
    on samples: [Float],
    setup: vDSP_DFT_Setup,
    window: [Float],
    fftSize: Int
) -> [Float]
```

If Q4 Option A is adopted (window as explicit parameter), `window` is already in the
signature, which is consistent.

**Status: agreed direction, awaiting implementation approval.**

---

## Summary Table

| Question | Topic | Status |
|----------|-------|--------|
| Q1 | Overall architecture (Candidate C) | RESOLVED |
| Q2 | `fftSetup` — vDSP artifact | ACCEPTED DIVERGENCE |
| Q3 | `fftSize` / `n_freq_samples` naming | RESOLVED — no action |
| Q4 | `window` as parameter vs. instance state | OPEN — prefer Option A |
| Q5 | Return value: dB only vs. (dB, linear) | OPEN — blocked on Q6 |
| Q6 | Gated FFT: shared DSP function or separate | OPEN — prefer Option A |
| Q7 | Gated FFT: class ownership | OPEN — prefer Option A (accepted divergence) |
| Q8 | Calibration inside gated FFT | OPEN — depends on Q6, Q7 |
| Q9 | Missing `perform_fft()` in Python | OPEN — actionable, agreed |
| Q10 | `computeFFT` instance vs. static | OPEN — actionable, agreed |

---

## Sequencing

Recommended order for changes once all questions are resolved:

1. **Q10** — Make Swift `computeFFT` static. Unblocks Q4 naturally (window parameter
   must be explicit if there is no `self`).
2. **Q4** — Add `window` as explicit parameter to `computeFFT` / confirm `dft_anal`
   signature is already correct.
3. **Q6** — Decide whether `computeGatedFFT` calls the shared pure DSP function.
4. **Q5** — Decide return type of pure DSP function (after Q6 is resolved).
5. **Q8** — Move calibration to the correct dispatch layer (after Q6, Q7 resolved).
6. **Q9** — Extract `perform_fft()` from Python `run()`. Independent of above.
7. **Q7** — Confirm gated FFT class ownership. Likely accepted divergence, no change.

Changes Q9 and Q10 are independent of the others and can be implemented in parallel
with the analysis of Q4–Q8.
