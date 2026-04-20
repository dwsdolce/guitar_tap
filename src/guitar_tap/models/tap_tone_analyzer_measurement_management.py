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

        # Warn if any imported measurement's microphone is not currently available.
        # Mirrors Swift importMeasurements(from:) — checks UID first, then name
        # (Python companion app measurements store a "Name:SampleRate" fingerprint
        # as the UID rather than a CoreAudio UID, so name matching is needed).
        mic = getattr(self, "mic", None)
        available_devices = getattr(mic, "available_input_devices", []) or []
        # available_input_devices starts empty; populate if needed.
        if not available_devices and mic is not None and hasattr(mic, "load_available_input_devices"):
            mic.load_available_input_devices()
            available_devices = getattr(mic, "available_input_devices", []) or []
        available_uids  = {d.fingerprint for d in available_devices}
        available_names = {d.name for d in available_devices}
        missing_names: list = []
        for m in measurements:
            uid = getattr(m, "microphone_uid", None)
            if uid:
                found_by_uid  = uid in available_uids
                mic_name = getattr(m, "microphone_name", None) or ""
                found_by_name = (not found_by_uid) and (mic_name in available_names)
                if not found_by_uid and not found_by_name:
                    label = mic_name or uid
                    if label not in missing_names:
                        missing_names.append(label)
        if missing_names:
            joined = ", ".join(missing_names)
            self.microphone_warning = (
                f"Recorded with {joined}, which is not currently connected. "
                f"Attach it and select it in the microphone settings for accurate analysis."
            )

        return measurements

    def _make_phase_snapshot(
        self,
        magnitudes,
        frequencies,
        min_freq: float,
        max_freq: float,
        min_db: float,
        max_db: float,
    ):
        """Build a per-phase ``SpectrumSnapshot`` from magnitude/frequency arrays.

        Mirrors Swift ``TapToneAnalyzer+MeasurementManagement.makePhaseSnapshot(...)``.
        Reads ``TapDisplaySettings.measurementType`` internally — the measurement type
        is not passed as a parameter (mirrors Swift where the helper captures it locally).

        Args:
            magnitudes:  List or array of dB magnitudes for this phase.
            frequencies: List or array of Hz frequencies for this phase.
            min_freq:    Visible axis minimum frequency (Hz), from view.
            max_freq:    Visible axis maximum frequency (Hz), from view.
            min_db:      Visible axis minimum dB, from view.
            max_db:      Visible axis maximum dB, from view.
        """
        from .spectrum_snapshot import SpectrumSnapshot
        from .tap_display_settings import TapDisplaySettings as TDS

        measurement_type = TDS.measurement_type()
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
            measurement_type=measurement_type.value,
            max_peaks=getattr(self, "max_peaks", None),
            plate_length=TDS.plate_length() if measurement_type.is_plate else None,
            plate_width=TDS.plate_width() if measurement_type.is_plate else None,
            plate_thickness=TDS.plate_thickness() if measurement_type.is_plate else None,
            plate_mass=TDS.plate_mass() if measurement_type.is_plate else None,
            guitar_body_length=TDS.guitar_body_length() if measurement_type.is_plate else None,
            guitar_body_width=TDS.guitar_body_width() if measurement_type.is_plate else None,
            plate_stiffness_preset=TDS.plate_stiffness_preset() if measurement_type.is_plate else None,
            custom_plate_stiffness=TDS.custom_plate_stiffness() if measurement_type.is_plate else None,
            measure_flc=TDS.measure_flc() if measurement_type.is_plate else None,
            brace_length=TDS.brace_length() if measurement_type.is_brace else None,
            brace_width=TDS.brace_width() if measurement_type.is_brace else None,
            brace_thickness=TDS.brace_thickness() if measurement_type.is_brace else None,
            brace_mass=TDS.brace_mass() if measurement_type.is_brace else None,
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
            _kw = dict(min_freq=_min_freq, max_freq=_max_freq, min_db=_min_db, max_db=_max_db)
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
        # and currentPeaks.filter { selectedPeakIDs.contains($0.id) }.map { $0.frequency }
        sel_ids = list(self.selected_peak_ids) if self.selected_peak_ids else None
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
            measurement_type=mt_str,
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
        )
        self.savedMeasurements.append(measurement)
        self._persist_measurements()

    def load_measurement(self, measurement) -> None:
        """Restore full analyser state from a saved measurement.

        Mirrors Swift ``TapToneAnalyzer+MeasurementManagement.loadMeasurement(_:)``.

        Sets all model-owned state — peaks, spectra, selections, annotation
        offsets, analysis settings, detection flags — and writes display
        settings to AppSettings (the Python equivalent of Swift's ``loaded*``
        published properties, which the view's ``.onReceive`` handlers propagate
        to ``TapDisplaySettings``).

        The calling view is responsible for all Qt widget updates, canvas
        drawing calls, and the mic auto-select block (which requires access to
        canvas and label widgets).
        """
        import numpy as np
        from .analysis_display_mode import AnalysisDisplayMode
        from .measurement_type import MeasurementType
        from .annotation_visibility_mode import AnnotationVisibilityMode

        # Suppress recalculate_frozen_peaks_if_needed() for the duration of the
        # load — mirrors Swift: isLoadingMeasurement = true / defer { = false }
        self.is_loading_measurement = True
        try:
            self._load_measurement_body(measurement)
        finally:
            self.is_loading_measurement = False

    def _load_measurement_body(self, measurement) -> None:
        """Inner implementation called by load_measurement(); guards isLoadingMeasurement."""
        import numpy as np
        from .analysis_display_mode import AnalysisDisplayMode
        from .measurement_type import MeasurementType
        from .annotation_visibility_mode import AnnotationVisibilityMode

        print("🔄 Loading measurement...")

        # ── Exit comparison mode, enter frozen mode ───────────────────────────
        # Mirrors Swift: comparisonSpectra = []; displayMode = .frozen
        self.clear_comparison()
        self._display_mode = AnalysisDisplayMode.FROZEN

        # ── Restore peaks ─────────────────────────────────────────────────────
        # Mirrors Swift: currentPeaks = measurement.peaks
        self.current_peaks = list(measurement.peaks) if measurement.peaks else []

        # ── Restore decay time ────────────────────────────────────────────────
        self.current_decay_time = measurement.decay_time

        # ── Determine measurement type ────────────────────────────────────────
        mt_str = measurement.measurement_type or ""
        try:
            mt = MeasurementType(mt_str)
        except ValueError:
            mt = MeasurementType.CLASSICAL

        # ── Restore per-phase spectra for plate/brace ─────────────────────────
        # Mirrors Swift: longitudinalSpectrum = (magnitudes:frequencies:) etc.
        has_material_spectra = measurement.longitudinal_snapshot is not None
        if measurement.longitudinal_snapshot is not None:
            ls = measurement.longitudinal_snapshot
            self.longitudinal_spectrum = (
                np.array(ls.magnitudes, dtype=np.float64),
                np.array(ls.frequencies, dtype=np.float64),
            )
        else:
            self.longitudinal_spectrum = None

        if measurement.cross_snapshot is not None:
            cs = measurement.cross_snapshot
            self.cross_spectrum = (
                np.array(cs.magnitudes, dtype=np.float64),
                np.array(cs.frequencies, dtype=np.float64),
            )
        else:
            self.cross_spectrum = None

        if measurement.flc_snapshot is not None:
            fs = measurement.flc_snapshot
            self.flc_spectrum = (
                np.array(fs.magnitudes, dtype=np.float64),
                np.array(fs.frequencies, dtype=np.float64),
            )
        else:
            self.flc_spectrum = None

        # ── Reset per-phase peak arrays ───────────────────────────────────────
        # Mirrors Swift lines 453/456/460/463/467/470:
        #   longitudinalPeaks = []; crossPeaks = []; flcPeaks = []
        self.longitudinal_peaks = []
        self.cross_peaks = []
        self.flc_peaks = []

        # ── Restore frozen spectrum ───────────────────────────────────────────
        # Mirrors Swift: setFrozenSpectrum(frequencies:magnitudes:)
        if has_material_spectra:
            # Plate/brace: frozen spectrum not used; clear it.
            self.set_frozen_spectrum(np.array([]), np.array([]))
            from .material_tap_phase import MaterialTapPhase
            self.material_tap_phase = MaterialTapPhase.COMPLETE
        elif measurement.spectrum_snapshot is not None:
            snap = measurement.spectrum_snapshot
            self.set_frozen_spectrum(
                np.array(snap.frequencies, dtype=np.float64),
                np.array(snap.magnitudes, dtype=np.float64),
            )
        else:
            self.set_frozen_spectrum(np.array([]), np.array([]))

        # ── Restore display settings → AppSettings ────────────────────────────
        # Mirrors Swift's loaded* @Published properties + .onReceive handlers
        # that write to TapDisplaySettings.  In Python TapDisplaySettings is
        # AppSettings, so we write there directly.
        from views.utilities.tap_settings_view import AppSettings as AS
        settings_snapshot = measurement.longitudinal_snapshot or measurement.spectrum_snapshot
        if settings_snapshot is not None:
            snap = settings_snapshot
            from .measurement_type import MeasurementType as _MT
            print(f"  📊 Publishing display ranges: {snap.min_freq}-{snap.max_freq} Hz, {snap.min_db}-{snap.max_db} dB")
            if snap.show_unknown_modes is not None:
                print(f"  👁️ Publishing showUnknownModes: {snap.show_unknown_modes}")
            if snap.guitar_type is not None:
                print(f"  🎸 Publishing guitarType: {snap.guitar_type}")
                try:
                    AS.set_guitar_type(snap.guitar_type)
                except Exception:
                    pass
            if snap.measurement_type is not None:
                print(f"  📐 Publishing measurementType: {snap.measurement_type}")
                try:
                    mt_enum = _MT(snap.measurement_type) if isinstance(snap.measurement_type, str) else snap.measurement_type
                    AS.set_measurement_type(mt_enum)
                except (ValueError, KeyError):
                    pass
            if mt.is_brace:
                if snap.brace_length    is not None: AS.set_brace_length(snap.brace_length)
                if snap.brace_width     is not None: AS.set_brace_width(snap.brace_width)
                if snap.brace_thickness is not None: AS.set_brace_thickness(snap.brace_thickness)
                if snap.brace_mass      is not None: AS.set_brace_mass(snap.brace_mass)
            elif mt.is_plate:
                if snap.plate_length    is not None:
                    print(f"  📏 Publishing plate dimensions: L={snap.plate_length}mm")
                    AS.set_plate_length(snap.plate_length)
                if snap.plate_width     is not None: AS.set_plate_width(snap.plate_width)
                if snap.plate_thickness is not None: AS.set_plate_thickness(snap.plate_thickness)
                if snap.plate_mass      is not None: AS.set_plate_mass(snap.plate_mass)
                if snap.plate_stiffness_preset is not None:
                    print(f"  🪵 Publishing plateStiffnessPreset: {snap.plate_stiffness_preset}")
                    AS.set_plate_stiffness_preset(snap.plate_stiffness_preset)
                if snap.custom_plate_stiffness is not None:
                    AS.set_custom_plate_stiffness(snap.custom_plate_stiffness)
                if snap.guitar_body_length is not None:
                    AS.set_guitar_body_length(snap.guitar_body_length)
                if snap.guitar_body_width is not None:
                    AS.set_guitar_body_width(snap.guitar_body_width)
        else:
            print("  ⚠️ No spectrum snapshot in measurement")

        # ── Store loaded-measurement metadata ─────────────────────────────────
        # Mirrors Swift: loadedMeasurementName = measurement.tapLocation (nil if empty)
        #                sourceMeasurementTimestamp = measurement.timestamp
        _name = measurement.tap_location
        self.loaded_measurement_name = (_name if (_name and _name.strip()) else None)
        self.source_measurement_timestamp = measurement.timestamp
        self.loadedMeasurementNameChanged.emit(self.loaded_measurement_name)

        # ── Restore plate/brace peak selections ───────────────────────────────
        # Mirrors Swift: selectedLongitudinalPeak = measurement.selectedLongitudinalPeakID
        #     .flatMap { id in currentPeaks.first(where: { $0.id == id }) }
        _peak_by_id = {(p.id or "").upper(): p for p in self.current_peaks}
        self.selected_longitudinal_peak = (
            _peak_by_id.get((measurement.selected_longitudinal_peak_id or "").upper())
        )
        self.selected_cross_peak = (
            _peak_by_id.get((measurement.selected_cross_peak_id or "").upper())
        )
        self.selected_flc_peak = (
            _peak_by_id.get((measurement.selected_flc_peak_id or "").upper())
        )
        # Mirrors Swift: userSelectedLongitudinalPeakID = nil (and cross/flc)
        self.user_selected_longitudinal_peak_id = None
        self.user_selected_cross_peak_id = None
        self.user_selected_flc_peak_id = None
        print(f"  🔵 Restored longitudinal peak: {self.selected_longitudinal_peak.frequency if self.selected_longitudinal_peak else -1} Hz")
        print(f"  🟠 Restored cross-grain peak: {self.selected_cross_peak.frequency if self.selected_cross_peak else -1} Hz")
        print(f"  🟣 Restored FLC peak: {self.selected_flc_peak.frequency if self.selected_flc_peak else -1} Hz")

        # ── Stop tap detection ────────────────────────────────────────────────
        # Mirrors Swift: isDetecting = false; isDetectionPaused = false;
        # isMeasurementComplete = true; currentTapCount = 0; tapProgress = 0.0
        # NOTE: is_measurement_complete is set via set_measurement_complete(True) at the
        # END of this method (after all state is restored) so that when measurementComplete
        # fires the view receives it with fully-populated model state — equivalent to
        # SwiftUI's batched objectWillChange which defers re-render until run-loop end.
        self.is_detecting = False
        self.is_detection_paused = False
        self.is_measurement_complete = True  # set early; signal fires at end of method
        self.current_tap_count = 0
        self.tap_progress = 0.0
        print("  🧊 Spectrum frozen, tap detection disabled")

        # ── Retain loaded peaks for recalculate_frozen_peaks_if_needed() ──────
        # Mirrors Swift: loadedMeasurementPeaks = measurement.peaks
        self.loaded_measurement_peaks = list(measurement.peaks) if measurement.peaks else []

        # ── Restore annotation offsets ────────────────────────────────────────
        # Mirrors Swift: peakAnnotationOffsets = measurement.peakAnnotationOffsets
        self.peak_annotation_offsets.clear()
        ann_offsets = measurement.annotation_offsets or {}
        for p in (measurement.peaks or []):
            _off = ann_offsets.get(p.id) or ann_offsets.get((p.id or "").upper())
            if _off:
                self.peak_annotation_offsets[p.id] = (float(_off[0]), float(_off[1]))
        print(f"  🏷️ Restored {len(self.peak_annotation_offsets)} annotation offsets")

        # ── Restore selected peak IDs ─────────────────────────────────────────
        # Mirrors Swift: selectedPeakIDs = saved ?? all; userHasModifiedPeakSelection = true
        if measurement.selected_peak_ids is not None:
            self.selected_peak_ids = set(measurement.selected_peak_ids)
        else:
            self.selected_peak_ids = {p.id for p in self.current_peaks}
        self.user_has_modified_peak_selection = True
        # Seed stable frequency cache — mirrors Swift selectedPeakFrequencies assignment
        self.selected_peak_frequencies = [
            p.frequency for p in self.current_peaks
            if p.id in self.selected_peak_ids
        ]
        print(f"  ⭐ Restored {len(self.selected_peak_ids)} selected peaks")

        # ── Restore annotation visibility mode ────────────────────────────────
        # Mirrors Swift: annotationVisibilityMode = measurement.annotationVisibilityMode ?? .all
        self.annotation_visibility_mode = AnnotationVisibilityMode.from_string(
            measurement.annotation_visibility_mode or "all"
        )
        print(f"  👁️ Restored annotation visibility: {self.annotation_visibility_mode.value}")

        # ── Restore peak mode overrides ───────────────────────────────────────
        # Mirrors Swift: applyModeOverrides(overrides) or peakModeOverrides = [:]
        overrides = measurement.peak_mode_overrides
        if overrides:
            self.apply_mode_overrides(overrides)
            print(f"  🏷️ Restored {len(overrides)} mode overrides")
        else:
            self.peak_mode_overrides = {}

        # ── Reclassify peaks ──────────────────────────────────────────────────
        # Mirrors Swift: reclassifyPeaks()  (after peakModeOverrides is set)
        self.reclassify_peaks()
        print(f"  🔬 Reclassified {len(getattr(self, 'identified_modes', []))} modes after load")

        # ── Restore analysis settings ─────────────────────────────────────────
        # Mirrors Swift: tapDetectionThreshold = ...; loadedTapDetectionThreshold = ...
        # (Python has no separate loaded* properties; write directly to model attrs)
        if measurement.tap_detection_threshold is not None:
            val = float(measurement.tap_detection_threshold)
            db = int(val) if val < 0 else int(val - 100)
            self.tap_detection_threshold = float(max(-80, min(-20, db)))
            print(f"  🎯 Publishing tap threshold: {self.tap_detection_threshold} dB")
        else:
            print("  ⚠️ No tap threshold in measurement")
        if measurement.hysteresis_margin is not None:
            self.hysteresis_margin = float(measurement.hysteresis_margin)
            print(f"  🔄 Publishing hysteresis: {self.hysteresis_margin} dB")
        else:
            print("  ⚠️ No hysteresis in measurement")
        if measurement.number_of_taps is not None:
            self.number_of_taps = int(measurement.number_of_taps)
            print(f"  🔢 Publishing number of taps: {self.number_of_taps}")
        else:
            print("  ⚠️ No number of taps in measurement")
        if measurement.peak_threshold is not None:
            val = float(measurement.peak_threshold)
            db = int(val) if val < 0 else int(val - 100)
            self.peak_threshold = float(max(-100, min(-20, db)))
            print(f"  📊 Publishing peak threshold: {self.peak_threshold} dB")
        else:
            print("  ⚠️ No peak threshold in measurement")

        # ── Auto-select the recorded microphone ───────────────────────────────
        # Mirrors Swift loadMeasurement(_:) device-restore block.
        # UID match is tried first; name match is fallback for Python companion
        # app measurements (which store a "Name:SampleRate" fingerprint as UID).
        mic_uid  = measurement.microphone_uid
        mic_name = measurement.microphone_name
        if mic_uid or mic_name:
            mic = getattr(self, "mic", None)
            available: list = getattr(mic, "available_input_devices", []) or []
            # available_input_devices starts empty until load_available_input_devices()
            # is called. If it is still empty, populate it now so the match below
            # has a real device list to work with.
            if not available and mic is not None and hasattr(mic, "load_available_input_devices"):
                mic.load_available_input_devices()
                available = getattr(mic, "available_input_devices", []) or []
            match = next((d for d in available if d.fingerprint == mic_uid), None)
            if match is None and mic_name:
                match = next((d for d in available if d.name == mic_name), None)
            label = mic_name or mic_uid or ""
            if match is not None:
                # Device is connected — request switch; calibration loads automatically.
                if self._calibration_device_name != match.name:
                    self.requestDeviceSwitch.emit(match)
                    print(f"🎤 Auto-selected microphone '{label}' for loaded measurement")
                self.microphone_warning = None
                self.microphoneWarningChanged.emit(None)
            else:
                warning = (
                    f"This measurement was recorded with '{label}', which is not "
                    f"currently connected. Attach it and select it in the microphone "
                    f"settings for accurate analysis."
                )
                self.microphone_warning = warning
                self.microphoneWarningChanged.emit(warning)

        # ── Arm loaded-settings warning ───────────────────────────────────────
        # Mirrors Swift: showLoadedSettingsWarning = true (last statement in loadMeasurement)
        # Store sentinels so set_tap_threshold/set_tap_num can detect user-initiated changes.
        self.loaded_tap_detection_threshold = self.tap_detection_threshold
        self.loaded_number_of_taps = self.number_of_taps
        self.show_loaded_settings_warning = True
        self.showLoadedSettingsWarningChanged.emit(True)

        # ── Status message ────────────────────────────────────────────────────
        # Mirrors Swift: statusMessage = "Loaded measurement (frozen)..."
        self._set_status_message(
            "Loaded measurement (frozen). Press 'Resume' or 'New Tap' to continue."
        )

        print(f"✅ Loaded measurement with {len(self.current_peaks)} peaks (frozen)")

        # ── Emit measurementComplete — all state now fully restored ───────────
        # Fired last so the view receives it with fully-populated model state.
        # Equivalent to SwiftUI's batched objectWillChange deferring re-render.
        self.measurementComplete.emit(True)

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

        # Build base labels then disambiguate duplicates so the legend is unambiguous.
        # Two measurements with the same tap_location (or both without one) would
        # otherwise produce identical legend entries.  Mirrors the duplicate-label
        # disambiguation added to Swift loadComparison(measurements:).
        base_labels = [self._comparison_label(m) for m in with_snapshots]
        label_counts: dict[str, int] = {}
        label_occurrence: dict[str, int] = {}
        for lbl in base_labels:
            label_counts[lbl] = label_counts.get(lbl, 0) + 1
        unique_labels: list[str] = []
        for lbl in base_labels:
            if label_counts[lbl] > 1:
                label_occurrence[lbl] = label_occurrence.get(lbl, 0) + 1
                unique_labels.append(f"{lbl} ({label_occurrence[lbl]})")
            else:
                unique_labels.append(lbl)

        result = []
        for idx, m in enumerate(with_snapshots):
            snap = m.spectrum_snapshot
            color = _PALETTE[idx % len(_PALETTE)]
            freq_arr = np.array(snap.frequencies, dtype=np.float64)
            mag_arr  = np.array(snap.magnitudes,  dtype=np.float64)
            label = unique_labels[idx]
            self.comparison_labels.append((label, color))
            self._comparison_data.append({
                "label": label, "color": color,
                "freqs": freq_arr, "mags": mag_arr,
                "snapshot": snap,   # stored so loaded_comparison_snapshots() can read display bounds
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

    def loaded_comparison_snapshots(self) -> list:
        """Return the SpectrumSnapshot for each loaded comparison measurement.

        Used by FftCanvas to read the saved display bounds (min_freq, max_freq,
        min_db, max_db) so the axis is set to the union of the snapshots' display
        windows — mirroring Swift setLoadedAxisRange in loadComparison(measurements:).
        """
        return [d["snapshot"] for d in self._comparison_data if d.get("snapshot") is not None]

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
