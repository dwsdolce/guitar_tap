"""
TapToneAnalyzer+MeasurementManagement — freeze/unfreeze spectrum,
comparison overlay loading, and measurement-complete state.

Mirrors Swift TapToneAnalyzer+MeasurementManagement.swift.
"""

from __future__ import annotations

import numpy as np

from .analysis_display_mode import AnalysisDisplayMode


class TapToneAnalyzerMeasurementManagementMixin:
    """Measurement state and comparison overlay management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+MeasurementManagement.swift.
    """

    # ── Persistence helper ────────────────────────────────────────────────────

    def _persist_measurements(self) -> None:
        """Write savedMeasurements to disk and emit savedMeasurementsChanged.

        Python-only helper — Swift achieves the same effect via the
        @Published property observer + explicit save(context:) call.
        """
        from views import tap_analysis_results_view as M
        M.save_all_measurements(self.savedMeasurements)
        self.savedMeasurementsChanged.emit()

    # ── Mutation methods (mirror Swift TapToneAnalyzer+MeasurementManagement) ─

    def import_measurements(self, json_str: str) -> bool:
        """Decode a JSON string of measurements, append, and persist.

        Mirrors Swift ``importMeasurements(json: String) -> Bool``.

        Args:
            json_str: UTF-8 JSON string representing ``[TapToneMeasurement]``.

        Returns:
            ``True`` if decoding succeeded and measurements were appended;
            ``False`` otherwise.
        """
        import json as _json
        from .tap_tone_measurement import TapToneMeasurement

        try:
            raw = _json.loads(json_str)
            measurements = [TapToneMeasurement.from_dict(d) for d in raw]
        except Exception:
            return False

        self.savedMeasurements.extend(measurements)
        self._persist_measurements()
        return True

    def import_measurements_from_data(self, data: bytes) -> list:
        """Decode raw JSON bytes, append, and persist.

        Mirrors Swift ``importMeasurements(from: Data) throws -> [TapToneMeasurement]``.

        Args:
            data: Raw UTF-8 JSON bytes representing ``[TapToneMeasurement]``.

        Returns:
            The list of newly decoded measurements.

        Raises:
            ValueError: If ``data`` cannot be decoded as valid measurement JSON.
        """
        import json as _json
        from .tap_tone_measurement import TapToneMeasurement

        try:
            raw = _json.loads(data.decode("utf-8"))
            measurements = [TapToneMeasurement.from_dict(d) for d in raw]
        except Exception as exc:
            raise ValueError(
                f"import_measurements_from_data: decode failed: {exc}"
            ) from exc

        self.savedMeasurements.extend(measurements)
        self._persist_measurements()
        return measurements

    def _append_measurement(self, measurement) -> None:
        """Append a pre-built measurement, persist to disk, and notify observers.

        Used internally by ``save_measurement`` and by the import path which
        passes already-deserialized ``TapToneMeasurement`` objects.

        Mirrors Swift ``savedMeasurements.append(measurement)`` +
        ``persistMeasurements()`` in ``TapToneAnalyzer+MeasurementManagement``.
        """
        self.savedMeasurements.append(measurement)
        self._persist_measurements()

    def save_measurement(
        self,
        peaks: list,
        decay_time: "float | None" = None,
        tap_location: "str | None" = None,
        notes: "str | None" = None,
        spectrum_snapshot=None,
        longitudinal_snapshot=None,
        cross_snapshot=None,
        flc_snapshot=None,
        annotation_offsets: "dict | None" = None,
        selected_peak_ids: "list | None" = None,
        selected_peak_frequencies: "list | None" = None,
        annotation_visibility_mode: "str | None" = None,
        tap_detection_threshold: "float | None" = None,
        hysteresis_margin: "float | None" = None,
        number_of_taps: "int | None" = None,
        peak_threshold: "float | None" = None,
        selected_longitudinal_peak_id: "str | None" = None,
        selected_cross_peak_id: "str | None" = None,
        selected_flc_peak_id: "str | None" = None,
        peak_mode_overrides: "dict | None" = None,
        microphone_name: "str | None" = None,
        microphone_uid: "str | None" = None,
        calibration_name: "str | None" = None,
        measurement_type: "str | None" = None,
        guitar_type: "str | None" = None,
    ) -> None:
        """Assemble a new measurement from individual parameters, then persist.

        The model is responsible for constructing ``TapToneMeasurement`` —
        the view layer must not call ``TapToneMeasurement.create()`` directly.

        Mirrors Swift
        ``TapToneAnalyzer+MeasurementManagement.saveMeasurement(tapLocation:notes:…)``,
        which accepts individual parameters and constructs the record internally.
        """
        from .tap_tone_measurement import TapToneMeasurement

        measurement = TapToneMeasurement.create(
            peaks=peaks,
            decay_time=decay_time,
            tap_location=tap_location,
            notes=notes,
            spectrum_snapshot=spectrum_snapshot,
            longitudinal_snapshot=longitudinal_snapshot,
            cross_snapshot=cross_snapshot,
            flc_snapshot=flc_snapshot,
            annotation_offsets=annotation_offsets,
            selected_peak_ids=selected_peak_ids,
            selected_peak_frequencies=selected_peak_frequencies,
            annotation_visibility_mode=annotation_visibility_mode,
            tap_detection_threshold=tap_detection_threshold,
            hysteresis_margin=hysteresis_margin,
            number_of_taps=number_of_taps,
            peak_threshold=peak_threshold,
            selected_longitudinal_peak_id=selected_longitudinal_peak_id,
            selected_cross_peak_id=selected_cross_peak_id,
            selected_flc_peak_id=selected_flc_peak_id,
            peak_mode_overrides=peak_mode_overrides,
            microphone_name=microphone_name,
            microphone_uid=microphone_uid,
            calibration_name=calibration_name,
            measurement_type=measurement_type,
            guitar_type=guitar_type,
        )
        self._append_measurement(measurement)

    def update_measurement(
        self,
        at: int,
        tap_location: "str | None",
        notes: "str | None",
    ) -> None:
        """Update the tapLocation and notes of a saved measurement by index.

        Mirrors Swift ``TapToneAnalyzer+MeasurementManagement.updateMeasurement(at:tapLocation:notes:)``.

        The index into ``savedMeasurements`` is used rather than id matching so
        that duplicate imports (which share the same id) are treated independently.

        Args:
            at:           Position in ``savedMeasurements`` to update.
            tap_location: New location label, or ``None`` to clear it.
            notes:        New free-form notes, or ``None`` to clear them.
        """
        if not (0 <= at < len(self.savedMeasurements)):
            return
        self.savedMeasurements[at] = self.savedMeasurements[at].with_(
            tap_location=tap_location,
            notes=notes,
        )
        self._persist_measurements()

    def delete_measurement(self, at: int) -> None:
        """Delete the measurement at the given index, persist, and notify.

        Mirrors Swift ``TapToneAnalyzer+MeasurementManagement.deleteMeasurement(at:)``.
        """
        if not (0 <= at < len(self.savedMeasurements)):
            return
        self.savedMeasurements.pop(at)
        self._persist_measurements()

    def delete_all_measurements(self) -> None:
        """Clear all saved measurements, persist, and notify.

        Mirrors Swift ``TapToneAnalyzer+MeasurementManagement.deleteAllMeasurements()``.
        """
        self.savedMeasurements.clear()
        self._persist_measurements()

    def set_measurement_complete(self, is_complete: bool) -> None:
        """Freeze/unfreeze the spectrum and reset related state."""
        self.is_measurement_complete = is_complete
        if not is_complete:
            self.captured_taps.clear()
            self.loaded_measurement_peaks = None
            self.reset_all_annotation_offsets()
            # Clear the frozen spectrum — mirrors Swift setFrozenSpectrum(frequencies: [], magnitudes: [])
            # in reset() and cancelTapSequence().  Both arrays are reset to empty so they
            # remain matched; frozen_frequencies will be populated again when the next tap
            # fires or a measurement is loaded.
            self.frozen_magnitudes = np.array([])
            self.frozen_frequencies = np.array([])
            # Clear comparison overlay — uses clear_comparison() so comparisonChanged(False)
            # is emitted when needed, allowing the UI to hide the comparison status bar.
            self.clear_comparison()
            # Clear per-phase material spectra — mirrors Swift loadMeasurement clearing
            # longitudinalSpectrum/crossSpectrum/flcSpectrum when returning to live mode.
            self.set_material_spectra([])
        self.measurementComplete.emit(is_complete)

    def load_comparison(self, measurements: list) -> list:
        """Prepare comparison data from measurements.

        Returns list of (label, color, freq_arr, mag_arr) tuples for FftCanvas
        to create PlotDataItem curves.  Mirrors loadComparison(measurements:) in Swift.
        """
        from datetime import datetime
        import numpy as np

        self._comparison_data.clear()
        self.comparison_labels.clear()

        _PALETTE = [
            (0,   122, 255),
            (255, 149,   0),
            (52,  199,  89),
            (175,  82, 222),
            (48,  176, 199),
        ]

        with_snapshots = [m for m in measurements if m.spectrum_snapshot is not None]
        result = []
        for idx, m in enumerate(with_snapshots):
            snap = m.spectrum_snapshot
            color = _PALETTE[idx % len(_PALETTE)]
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes,  dtype=np.float64)
            label = self._comparison_label(m)
            self.comparison_labels.append((label, color))
            self._comparison_data.append({
                "label": label, "color": color,
                "freqs": freq_arr, "mags": mag_arr,
            })
            result.append((label, color, freq_arr, mag_arr))

        if with_snapshots:
            snaps = [m.spectrum_snapshot for m in with_snapshots]
            min_freq = int(min(s.min_freq for s in snaps))
            max_freq = int(max(s.max_freq for s in snaps))
            self.update_axis(min_freq, max_freq)
            self._display_mode = AnalysisDisplayMode.COMPARISON
            self.comparisonChanged.emit(True)
        else:
            # No snapshots → revert to live mode, mirroring Swift loadComparison behaviour
            # when the filtered list is empty (loadComparison([]) or all without snapshots).
            was_comparing = self._display_mode == AnalysisDisplayMode.COMPARISON
            self._display_mode = AnalysisDisplayMode.LIVE
            if was_comparing:
                self.comparisonChanged.emit(False)

        return result

    def clear_comparison(self) -> None:
        """Clear comparison overlay state."""
        was_comparing = self.is_comparing
        self._display_mode = AnalysisDisplayMode.LIVE
        self._comparison_data.clear()
        self.comparison_labels.clear()
        if was_comparing:
            self.comparisonChanged.emit(False)

    @staticmethod
    def _comparison_label(m) -> str:
        """Short label for the comparison legend."""
        from datetime import datetime
        loc = getattr(m, "tap_location", None)
        if loc:
            return loc
        ts = getattr(m, "timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}"
        except Exception:
            return ts[:16]
