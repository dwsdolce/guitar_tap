"""
TapToneAnalyzer+ModeOverrideManagement — guitar type and plate analysis control.

Mirrors Swift TapToneAnalyzer+ModeOverrideManagement.swift.
"""

from __future__ import annotations


class TapToneAnalyzerModeOverrideManagementMixin:
    """Guitar type and plate analysis management for TapToneAnalyzer.

    Mirrors Swift TapToneAnalyzer+ModeOverrideManagement.swift.
    """

    def set_guitar_type(self, guitar_type) -> None:
        """Update the guitar type used for mode classification."""
        self._guitar_type = guitar_type

    # ------------------------------------------------------------------ #
    # Plate analysis (mirrors TapToneAnalyzer+SpectrumCapture.swift)
    # ------------------------------------------------------------------ #

    def start_plate_analysis(self) -> None:
        """Arm the plate capture state machine for the next tap(s)."""
        from models.tap_display_settings import TapDisplaySettings as _tds
        self.plate_capture.start(
            is_brace=self._measurement_type.is_brace,
            measure_flc=_tds.measure_flc(),
        )

    def reset_plate_analysis(self) -> None:
        """Abort plate capture and return to idle."""
        self.plate_capture.reset()
