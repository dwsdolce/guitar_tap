# @parity test/peak-heal
"""
D8 of Development/PEAK-FINDING-DUPLICATE-PEAKS.md (GuitarTapWeb), section 7b.

Port of PeakDuplicateHealTests.swift.

Fixing find_peaks stops NEW corruption. Every .guitartap file already written still
carries the duplicate peak, and loaded peaks are authoritative — they are never
re-derived — so old files would keep rendering an extra Analysis Results row forever.
The repair therefore happens at DECODE time, in ``TapToneMeasurement.from_dict``, so it
covers both reading a .guitartap file and reading the saved-measurements store, and no
future read path can bypass it.

Rule: collapse peaks closer than peak_proximity_hz, keeping (1) the peak whose id is in
selected_peak_ids, else (2) the higher magnitude, else (3) the first. find_peaks' own
dedup guarantees legitimately saved peaks are >= 2 Hz apart, so any closer pair is by
definition corruption.

Authored against the UNFIXED code. Two kinds of test live here:

  RED NOW — fail until the heal exists:
    test_D8_decoded_measurement_has_no_duplicate_peaks
    test_D8_heal_keeps_the_selected_twin
    test_D8_heal_is_reported_so_the_store_can_force_a_save

  GUARDS — pass now and must keep passing; they constrain what the heal may do rather
  than demanding it exist:
    test_D8_heal_leaves_no_dangling_ids   (must not orphan selection/offset/override ids)
    test_D8_heal_flag_is_not_serialised   (transient flag must never reach the format)

A guard passing today is not evidence of anything; its value is entirely in step 8.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

from guitar_tap.models.tap_tone_measurement import TapToneMeasurement  # noqa: E402

TESTS_DIR = os.path.dirname(__file__)

# The Swift-captured fixture also used by the find_peaks regression: 50 saved peaks,
# one of which is a bit-identical twin at 240.10170 Hz.
FIXTURE = "dws-2024-umik-1-swift-mac-1784225155.guitartap"

PEAK_PROXIMITY_HZ = 2.0


def _decode() -> TapToneMeasurement:
    with open(os.path.join(TESTS_DIR, FIXTURE)) as fh:
        raw = json.load(fh)
    return TapToneMeasurement.from_dict(raw[0])


class TestPeakDuplicateHeal:
    """Mirrors Swift PeakDuplicateHealTests."""

    def test_D8_decoded_measurement_has_no_duplicate_peaks(self):
        m = _decode()

        offenders = []
        for i in range(len(m.peaks)):
            for j in range(i + 1, len(m.peaks)):
                delta = abs(m.peaks[i].frequency - m.peaks[j].frequency)
                if delta < PEAK_PROXIMITY_HZ:
                    offenders.append(
                        f"{m.peaks[i].frequency:.5f} Hz / {m.peaks[j].frequency:.5f} Hz "
                        f"({delta:.5f} apart)"
                    )
        assert not offenders, (
            f"decode must collapse duplicate peaks — found {'; '.join(offenders)}"
        )
        assert len(m.peaks) == 49, (
            f"expected 49 peaks after healing 50, got {len(m.peaks)}"
        )

    def test_D8_heal_keeps_the_selected_twin(self):
        m = _decode()

        # The surviving 240.1 Hz peak must be the one that was claimed as a mode winner,
        # otherwise the selection silently points at a peak that no longer exists.
        survivors = [p for p in m.peaks if abs(p.frequency - 240.10170) < 0.01]
        assert len(survivors) == 1, (
            f"expected exactly one 240.1 Hz peak, got {len(survivors)}"
        )
        assert survivors[0].id in set(m.selected_peak_ids or []), (
            "the heal kept the unselected twin — selection now dangles"
        )

    def test_D8_heal_leaves_no_dangling_ids(self):
        """GUARD — passes today; the heal must not orphan any id-keyed map."""
        m = _decode()
        ids = {p.id for p in m.peaks}

        for pid in (m.selected_peak_ids or []):
            assert pid in ids, f"selected_peak_ids references a removed peak: {pid}"
        for pid in (m.annotation_offsets or {}):
            assert pid in ids, f"annotation_offsets references a removed peak: {pid}"
        for pid in (m.peak_mode_overrides or {}):
            assert pid in ids, f"peak_mode_overrides references a removed peak: {pid}"

    def test_D8_heal_is_reported_so_the_store_can_force_a_save(self):
        """The saved-measurements store repairs itself on load, so decode must report."""
        m = _decode()

        # Probed via getattr on purpose: the attribute does not exist yet. Replace with a
        # direct ``m.was_healed`` reference once the API lands in step 5.
        heal_flag = getattr(m, "was_healed", None)

        assert heal_flag is True, (
            f"decode healed a duplicate but did not report it (was_healed = {heal_flag!r}); "
            "the saved-measurements store cannot know to force a save"
        )

    def test_D8_heal_flag_is_not_serialised(self):
        """GUARD — the heal marker is transient state, not part of the file format."""
        m = _decode()
        encoded = json.dumps([m.to_dict()])

        assert "wasHealed" not in encoded and "was_healed" not in encoded, (
            "the heal marker must not round-trip into the .guitartap format"
        )

        # And the corrected form is what gets written — the twin must not come back.
        round_tripped = TapToneMeasurement.from_dict(json.loads(encoded)[0])
        assert len(round_tripped.peaks) == len(m.peaks), (
            "re-encoding a healed measurement must persist the corrected peak list"
        )