"""
TapToneAnalyzer+PeakAnalysis — findPeaks, parabolic interpolation, Q-factor,
and mode-priority assembly.

Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift.
"""

from __future__ import annotations

import numpy.typing as npt


class TapToneAnalyzerPeakAnalysisMixin:
    """Peak detection and classification for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift.
    """

    def _apply_mode_priority(
        self,
        guaranteed_peaks: "npt.NDArray",
        unknown_peaks: "npt.NDArray",
    ) -> "npt.NDArray":
        """Assemble the final peak list from two pre-separated inputs.

        Mirrors Swift findPeaks Step 3:
          1. All guaranteed-slot peaks (one per known mode, already deduplicated
             by the sequential Pass 1 scan in find_peaks) come first.
          2. Remaining unknown/inter-mode peaks fill remaining slots up to
             self.max_peaks (0 = unlimited), sorted by magnitude descending,
             with 2 Hz deduplication against the guaranteed set.

        Parameters
        ----------
        guaranteed_peaks:
            Rows (freq, mag, Q) — the strongest peak found in each known-mode
            range during Pass 1.  May be empty.
        unknown_peaks:
            Rows (freq, mag, Q) — local maxima found outside all known-mode
            ranges during Pass 2.  May be empty.

        Returns
        -------
        ndarray of shape (N, 3) sorted by magnitude descending, matching the
        Swift output of ``findPeaks``.
        """
        import numpy as np

        if guaranteed_peaks.shape[0] == 0 and unknown_peaks.shape[0] == 0:
            return np.zeros((0, 3))

        # Guaranteed peaks always included; deduplicate within them by 2 Hz.
        final_rows: list = []
        claimed_freqs: list[float] = []

        for row in guaranteed_peaks:
            freq = float(row[0])
            if any(abs(freq - f) < 2.0 for f in claimed_freqs):
                continue
            final_rows.append(row)
            claimed_freqs.append(freq)

        # Fill remaining slots from unknown peaks by magnitude (descending),
        # skipping any that are within 2 Hz of an already-included peak.
        # Mirrors Swift: maxPeaks == 0 means "capture all peaks".
        if unknown_peaks.shape[0] > 0:
            remaining_slots = (self.max_peaks - len(final_rows)) if self.max_peaks > 0 else None
            order = np.argsort(-unknown_peaks[:, 1])
            for idx in order:
                if remaining_slots is not None and remaining_slots <= 0:
                    break
                row = unknown_peaks[idx]
                freq = float(row[0])
                if any(abs(freq - f) < 2.0 for f in claimed_freqs):
                    continue
                final_rows.append(row)
                claimed_freqs.append(freq)
                if remaining_slots is not None:
                    remaining_slots -= 1

        if not final_rows:
            return np.zeros((0, 3))

        result = np.array(final_rows)
        # Sort by magnitude descending, matching Swift's final sort.
        return result[np.argsort(-result[:, 1])]

    def find_peaks(self, mag_y_db) -> "tuple[bool, npt.NDArray]":
        """Detect, interpolate, and deduplicate peaks above threshold.

        Mirrors Swift TapToneAnalyzer+PeakAnalysis.swift ``findPeaks`` using
        the same two-pass strategy:

        Pass 1 — Known-mode ranges (sequential, low→high):
            Scans each mode's band, clamped to [min_frequency, max_frequency],
            with a ``last_claimed_freq`` cursor preventing the same physical peak
            from being claimed by two overlapping mode ranges.

        Pass 2 — Unknown/inter-mode peaks:
            Scans the full [min_frequency, max_frequency] analysis window for
            local maxima that fall outside every known-mode range.

        Assembly (``_apply_mode_priority``):
            Guaranteed peaks occupy fixed slots; remaining slots are filled from
            Pass-2 peaks by magnitude with 2 Hz deduplication, up to max_peaks
            total (0 = unlimited).

        Returns (triggered, peaks_array) where peaks_array columns are
        (freq_hz, mag_db, Q).  Emits peaksChanged with the in-viewport subset.
        """
        import numpy as np
        from models import realtime_fft_analyzer as f_a
        from models import guitar_mode as gm

        if not np.any(mag_y_db):
            return False, self.saved_peaks

        threshold_db = self.threshold - 100
        hz_per_bin = self.fft_data.sample_freq / float(self.fft_data.n_f)
        n_bins = len(mag_y_db)

        # Analysis window — mirrors Swift loFreq/hiFreq = minHz ?? minFrequency,
        # maxHz ?? maxFrequency, clamped to valid bin indices.
        lo_freq = self.min_frequency
        hi_freq = self.max_frequency
        start_bin = max(1, int(lo_freq / hz_per_bin))
        end_bin   = min(n_bins - 2, int(hi_freq / hz_per_bin))

        known_modes = sorted(
            [gm.GuitarMode.AIR, gm.GuitarMode.TOP, gm.GuitarMode.BACK,
             gm.GuitarMode.DIPOLE, gm.GuitarMode.RING_MODE, gm.GuitarMode.UPPER_MODES],
            key=lambda m: m.mode_range(self._guitar_type)[0],
        )

        # --- Pass 1: scan each known-mode range sequentially, low→high -------
        # Each mode's scan begins just above the previous claimed peak frequency
        # (last_claimed_freq cursor), preventing the same physical peak from
        # being claimed by two overlapping mode ranges.
        # Ranges are clamped to the analysis window [start_bin, end_bin].
        strongest_per_mode: dict = {}   # GuitarMode → (ploc_bin, iploc, ipmag)
        last_claimed_freq: float = -1.0

        for mode in known_modes:
            lo, hi = mode.mode_range(self._guitar_type)
            # Clamp mode range to the analysis window, mirrors Swift:
            #   modeStartIdx = max(frequencies.firstIndex(where: $0 >= modeRange.lowerBound), startIdx)
            #   modeEndIdx   = min(frequencies.firstIndex(where: $0 > modeRange.upperBound),  endIdx)
            bin_lo = max(start_bin, int(lo / hz_per_bin))
            bin_hi = min(end_bin,   int(hi / hz_per_bin))
            if bin_lo >= bin_hi:
                continue

            # Advance scan start to just above the last claimed peak.
            cursor_bin = int(last_claimed_freq / hz_per_bin) + 1
            scan_start = max(bin_lo, cursor_bin)
            if scan_start >= bin_hi:
                continue

            # Local-maximum candidates in this mode's effective window.
            window = mag_y_db[scan_start : bin_hi + 1]
            sub_ploc = f_a.peak_detection(window, threshold_db)
            if sub_ploc.size == 0:
                continue
            # Convert sub-array indices back to full-spectrum indices.
            ploc_full = sub_ploc + scan_start

            sub_iploc, sub_ipmag = f_a.peak_interp(mag_y_db, ploc_full)
            best_idx = int(np.argmax(sub_ipmag))
            best_ploc  = ploc_full[best_idx]
            best_iploc = sub_iploc[best_idx]
            best_ipmag = float(sub_ipmag[best_idx])
            best_freq  = float(best_iploc * hz_per_bin)

            # 2 Hz duplicate guard: discard if another mode already claimed
            # a peak at essentially the same frequency (parabolic interpolation
            # can pull a bin back across a mode-boundary cursor).
            already_claimed = any(
                abs(best_freq - float(v[1] * hz_per_bin)) < 2.0
                for v in strongest_per_mode.values()
            )
            if already_claimed:
                continue

            strongest_per_mode[mode] = (best_ploc, best_iploc, best_ipmag)
            last_claimed_freq = best_freq

        # Build guaranteed peaks array (freq, mag, Q) for each mode slot.
        guaranteed_rows: list = []
        if strongest_per_mode:
            g_plocs  = np.array([v[0] for v in strongest_per_mode.values()], dtype=int)
            g_iplocs = np.array([v[1] for v in strongest_per_mode.values()])
            g_imags  = np.array([v[2] for v in strongest_per_mode.values()])
            g_freqs  = g_iplocs * hz_per_bin
            g_q = f_a.peak_q_factor(
                mag_y_db, g_plocs, g_iplocs, g_imags,
                self.fft_data.sample_freq, self.fft_data.n_f,
            )
            for freq, mag, q in zip(g_freqs, g_imags, g_q):
                guaranteed_rows.append([freq, mag, q])
        guaranteed_arr = np.array(guaranteed_rows) if guaranteed_rows else np.zeros((0, 3))

        # --- Pass 2: unknown/inter-mode peaks within the analysis window ------
        # Mirrors Swift: outer scan from startIdx+windowSize to endIdx-windowSize,
        # skipping bins that fall inside a known-mode range.
        window_bins = mag_y_db[start_bin : end_bin + 1]
        all_ploc_sub = f_a.peak_detection(window_bins, threshold_db)
        unknown_rows: list = []
        if all_ploc_sub.size > 0:
            all_ploc = all_ploc_sub + start_bin
            all_iploc, all_ipmag = f_a.peak_interp(mag_y_db, all_ploc)
            all_freqs = all_iploc * hz_per_bin
            in_known = np.zeros(len(all_ploc), dtype=bool)
            for mode in known_modes:
                lo, hi = mode.mode_range(self._guitar_type)
                in_known |= (all_freqs >= lo) & (all_freqs <= hi)

            unknown_mask = ~in_known
            if np.any(unknown_mask):
                u_plocs  = all_ploc[unknown_mask]
                u_iplocs = all_iploc[unknown_mask]
                u_imags  = all_ipmag[unknown_mask]
                u_freqs  = all_freqs[unknown_mask]
                u_q = f_a.peak_q_factor(
                    mag_y_db, u_plocs, u_iplocs, u_imags,
                    self.fft_data.sample_freq, self.fft_data.n_f,
                )
                for freq, mag, q in zip(u_freqs, u_imags, u_q):
                    unknown_rows.append([freq, mag, q])
        unknown_arr = np.array(unknown_rows) if unknown_rows else np.zeros((0, 3))

        # --- Assembly ---------------------------------------------------------
        peaks = self._apply_mode_priority(guaranteed_arr, unknown_arr)

        if peaks.shape[0] > 0:
            max_peaks_mag = float(np.max(peaks[:, 1]))
        else:
            max_peaks_mag = -100.0

        if max_peaks_mag > (self.threshold - 100):
            self.saved_mag_y_db = mag_y_db
            self.saved_peaks = peaks
            triggered = True
            # Emit all peaks — mirrors Swift currentPeaks which holds all detected peaks.
            # Viewport filtering (fmin/fmax) is applied by the results panel at display
            # time, matching Swift's sortedPeaksWithModes filter in TapAnalysisResultsView.
            self.peaksChanged.emit(peaks)
        else:
            self.saved_peaks = np.zeros((0, 3))
            self.peaksChanged.emit(self.saved_peaks)
            triggered = False

        return triggered, peaks
