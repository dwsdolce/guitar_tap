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

    def _make_phase_snapshot(
        self,
        magnitudes,
        frequencies,
        min_freq: float,
        max_freq: float,
        min_db: float,
        max_db: float,
        mt_str: str,
    ):
        """Build a per-phase ``SpectrumSnapshot`` from magnitude/frequency arrays.

        Mirrors the local ``makePhaseSnapshot`` helper in Swift's
        ``TapToneAnalysisView+Actions.saveMeasurement()`` — lifted to model scope
        since the model owns the per-phase spectrum data.

        Args:
            magnitudes:  List or array of dB magnitudes for this phase.
            frequencies: List or array of Hz frequencies for this phase.
            min_freq:    Visible axis minimum frequency (Hz), from view.
            max_freq:    Visible axis maximum frequency (Hz), from view.
            min_db:      Visible axis minimum dB, from view.
            max_db:      Visible axis maximum dB, from view.
            mt_str:      Measurement type value string (e.g. ``"plate"``).
        """
        from .spectrum_snapshot import SpectrumSnapshot
        from .tap_display_settings import TapDisplaySettings as TDS
        from .measurement_type import MeasurementType

        try:
            mt = MeasurementType(mt_str)
        except ValueError:
            mt = MeasurementType.CLASSICAL

        _psp_str = TDS.plate_stiffness_preset()
        return SpectrumSnapshot(
            frequencies=frequencies.tolist() if hasattr(frequencies, "tolist") else list(frequencies),
            magnitudes=magnitudes.tolist() if hasattr(magnitudes, "tolist") else list(magnitudes),
            min_freq=min_freq,
            max_freq=max_freq,
            min_db=min_db,
            max_db=max_db,
            is_logarithmic=False,
            show_unknown_modes=TDS.show_unknown_modes(),
            guitar_type=TDS.guitar_type(),
            measurement_type=mt_str,
            max_peaks=getattr(self, "max_peaks", None),
            plate_length=TDS.plate_length() if mt.is_plate else None,
            plate_width=TDS.plate_width() if mt.is_plate else None,
            plate_thickness=TDS.plate_thickness() if mt.is_plate else None,
            plate_mass=TDS.plate_mass() if mt.is_plate else None,
            plate_stiffness_preset=_psp_str if mt.is_plate else None,
            custom_plate_stiffness=(
                TDS.custom_plate_stiffness()
                if mt.is_plate and _psp_str == "Custom" else None
            ),
            guitar_body_length=TDS.guitar_body_length() if mt.is_plate else None,
            guitar_body_width=TDS.guitar_body_width() if mt.is_plate else None,
            measure_flc=TDS.measure_flc() if mt.is_plate else None,
            brace_length=TDS.brace_length() if mt.is_brace else None,
            brace_width=TDS.brace_width() if mt.is_brace else None,
            brace_thickness=TDS.brace_thickness() if mt.is_brace else None,
            brace_mass=TDS.brace_mass() if mt.is_brace else None,
        )

    def save_measurement(
        self,
        tap_location: "str | None" = None,
        notes: "str | None" = None,
        include_spectrum: bool = True,
        spectrum_snapshot=None,
        annotation_offsets: "dict | None" = None,
        selected_longitudinal_peak_id: "str | None" = None,
        selected_cross_peak_id: "str | None" = None,
        selected_flc_peak_id: "str | None" = None,
        microphone_name: "str | None" = None,
        microphone_uid: "str | None" = None,
        calibration_name: "str | None" = None,
        min_freq: "float | None" = None,
        max_freq: "float | None" = None,
        min_db: "float | None" = None,
        max_db: "float | None" = None,
    ) -> None:
        """Assemble a new measurement from live analyzer state, then persist.

        Mirrors Swift ``TapToneAnalyzer+MeasurementManagement.saveMeasurement(...)``:

        - Reads ``currentPeaks``, ``currentDecayTime``, ``selectedPeakIDs``,
          ``peakAnnotationOffsets``, ``annotationVisibilityMode``, and
          ``peakModeOverrides`` directly from model state — not passed by the view.
        - Builds the guitar ``SpectrumSnapshot`` internally from
          ``frozenFrequencies`` / ``frozenMagnitudes`` and ``TapDisplaySettings``.
          The view passes only the four axis-range floats.
        - Builds per-phase snapshots (plate/brace) internally from
          ``self.longitudinal_spectrum``, ``self.cross_spectrum``, ``self.flc_spectrum``
          using ``_make_phase_snapshot``.  These spectra are set on the model by the
          gated-FFT capture pipeline — the view does not pass them.
        - ``spectrum_snapshot`` is an optional override (mirrors Swift's
          ``spectrumSnapshot: SpectrumSnapshot? = nil``) used by the import path.
        - ``annotation_offsets`` falls back to ``self.peak_annotation_offsets``
          when ``None``, matching Swift's ``annotationOffsets ?? peakAnnotationOffsets``.
        """
        from .tap_tone_measurement import TapToneMeasurement
        from .spectrum_snapshot import SpectrumSnapshot
        from .tap_display_settings import TapDisplaySettings as TDS
        from .measurement_type import MeasurementType

        mt_str = TDS.measurement_type().value
        try:
            mt = MeasurementType(mt_str)
        except ValueError:
            mt = MeasurementType.CLASSICAL

        # Resolve axis range — fall back to TapDisplaySettings when not passed by view.
        # Mirrors Swift: minFreq ?? TapDisplaySettings.minFrequency etc.
        _min_freq = min_freq if min_freq is not None else TDS.min_frequency()
        _max_freq = max_freq if max_freq is not None else TDS.max_frequency()
        _min_db   = min_db   if min_db   is not None else TDS.min_magnitude()
        _max_db   = max_db   if max_db   is not None else 0.0

        # ── Build guitar SpectrumSnapshot internally ──────────────────────────
        # Mirrors Swift: snapshot = spectrumSnapshot ?? SpectrumSnapshot(
        #     frequencies: isMeasurementComplete ? frozenFrequencies : fftAnalyzer.frequencies,
        #     magnitudes:  isMeasurementComplete ? frozenMagnitudes  : fftAnalyzer.magnitudes, ...)
        guitar_snapshot = None
        if include_spectrum and mt.is_guitar:
            freqs = self.frozen_frequencies
            mags  = self.frozen_magnitudes
            if freqs is not None and len(freqs) > 0:
                guitar_snapshot = spectrum_snapshot or SpectrumSnapshot(
                    frequencies=freqs.tolist() if hasattr(freqs, "tolist") else list(freqs),
                    magnitudes=mags.tolist()  if hasattr(mags,  "tolist") else list(mags),
                    min_freq=_min_freq,
                    max_freq=_max_freq,
                    min_db=_min_db,
                    max_db=_max_db,
                    is_logarithmic=False,
                    show_unknown_modes=TDS.show_unknown_modes(),
                    guitar_type=TDS.guitar_type(),
                    measurement_type=mt_str,
                    max_peaks=getattr(self, "max_peaks", None),
                )

        # ── Build per-phase snapshots internally ──────────────────────────────
        # Mirrors Swift: longSnap = makePhaseSnapshot(tap.longitudinalSpectrum...)
        # Per-phase spectra are set on self by the gated-FFT capture pipeline.
        longitudinal_snapshot = None
        cross_snapshot = None
        flc_snapshot = None
        if include_spectrum and not mt.is_guitar:
            _kw = dict(min_freq=_min_freq, max_freq=_max_freq,
                       min_db=_min_db, max_db=_max_db, mt_str=mt_str)
            if self.longitudinal_spectrum is not None:
                _mags, _freqs = self.longitudinal_spectrum
                longitudinal_snapshot = self._make_phase_snapshot(_mags, _freqs, **_kw)
            if mt == MeasurementType.PLATE and self.cross_spectrum is not None:
                _mags, _freqs = self.cross_spectrum
                cross_snapshot = self._make_phase_snapshot(_mags, _freqs, **_kw)
            if mt == MeasurementType.PLATE and self.flc_spectrum is not None:
                _mags, _freqs = self.flc_spectrum
                flc_snapshot = self._make_phase_snapshot(_mags, _freqs, **_kw)

        # ── Read model state directly — mirrors Swift currentPeaks etc. ───────
        peaks = list(self.current_peaks)
        decay_time = getattr(self, "current_decay_time", None)

        # annotation_offsets: passed value or self.peak_annotation_offsets
        # Mirrors Swift: annotationOffsets ?? peakAnnotationOffsets
        offsets = annotation_offsets if annotation_offsets is not None \
                  else dict(self.peak_annotation_offsets)

        # selectedPeakIDs / selectedPeakFrequencies
        # Mirrors Swift: selectedPeakIDs.isEmpty ? nil : Array(selectedPeakIDs)
        sel_ids = list(self.selected_peak_ids)
        sel_freqs = (
            [p.frequency for p in peaks if p.id in self.selected_peak_ids]
            if sel_ids else None
        )

        ann_vis = getattr(self, "annotation_visibility_mode", None)
        ann_vis_str = ann_vis.value if ann_vis is not None else None

        overrides = dict(self.peak_mode_overrides) if self.peak_mode_overrides else None

        measurement = TapToneMeasurement.create(
            peaks=peaks,
            decay_time=decay_time,
            tap_location=tap_location,
            notes=notes,
            spectrum_snapshot=guitar_snapshot,
            longitudinal_snapshot=longitudinal_snapshot,
            cross_snapshot=cross_snapshot,
            flc_snapshot=flc_snapshot,
            annotation_offsets=offsets or None,
            selected_peak_ids=sel_ids or None,
            selected_peak_frequencies=sel_freqs,
            annotation_visibility_mode=ann_vis_str,
            tap_detection_threshold=getattr(self, "tap_detection_threshold", None),
            hysteresis_margin=getattr(self, "hysteresis_margin", None),
            number_of_taps=getattr(self, "number_of_taps", None),
            peak_threshold=getattr(self, "peak_threshold", None),
            # Plate/brace peak selections — mirrors Swift conditional nil assignments
            selected_longitudinal_peak_id=selected_longitudinal_peak_id if not mt.is_guitar else None,
            selected_cross_peak_id=selected_cross_peak_id if mt == MeasurementType.PLATE else None,
            selected_flc_peak_id=selected_flc_peak_id if mt == MeasurementType.PLATE else None,
            peak_mode_overrides=overrides,
            microphone_name=microphone_name,
            microphone_uid=microphone_uid,
            calibration_name=calibration_name,
            measurement_type=mt_str,
            guitar_type=TDS.guitar_type(),
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
