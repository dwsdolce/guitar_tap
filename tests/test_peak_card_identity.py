# @parity none
"""
D7 of Development/PEAK-FINDING-DUPLICATE-PEAKS.md (GuitarTapWeb).

Python-only: the Analysis Results card list resolves each card back to its model row
**by frequency**, and ``PeaksModel.freq_index`` returns ``-1`` when a frequency is not
unique (peaks_model.py:296-301). The ``-1`` is never checked, and Python's negative
indexing makes it a *valid* index — ``self._peaks[-1]`` — so the star, mode label and
pitch of every affected card are read from the LAST peak in the list, an unrelated
resonance.

Observed in the field: loading an iPad-saved measurement showed two 235.8 Hz rows
labelled "Air" while the graph annotated the same peak as "Back", and neither row was
starred although one was in ``selectedPeakIDs``. Annotations were correct because they
iterate rows directly (``self._peaks[row].id``); the cards were not.

Swift and the web index by peak identity and have no equivalent defect, so this file is
outside the ``test/peaks`` parity group.

This matters beyond the findPeaks fix: loaded peaks are authoritative and are never
re-derived, so every ``.guitartap`` file already written still contains duplicate peaks
(see section 7b — heal on load). Until both land, this defect is reachable from any
saved measurement.

Authored against the UNFIXED code; expected to fail.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "guitar_tap"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # noqa: E402

from guitar_tap.models.guitar_mode import GuitarMode  # noqa: E402
from guitar_tap.models.resonant_peak import ResonantPeak  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _peaks_like_the_corrupt_file() -> list[ResonantPeak]:
    """Mirrors dws-2024-umik-1-swift-iphone-1784498431.guitartap in miniature.

    Two peaks share a frequency exactly — bit-identical apart from ``id`` — which is
    what findPeaks produced in the Top/Back overlap band. One twin is selected.
    """
    return [
        ResonantPeak(frequency=196.447028, magnitude=-43.472, quality=20.62, bandwidth=9.5),
        ResonantPeak(frequency=231.877, magnitude=-58.035, quality=3.41, bandwidth=68.0),
        ResonantPeak(frequency=239.244433, magnitude=-55.916, quality=23.36, bandwidth=10.2),
        ResonantPeak(frequency=239.244433, magnitude=-55.916, quality=23.36, bandwidth=10.2),
    ]


class TestPeakCardIdentity:
    """Cards must resolve to their own peak, not to whatever shares their frequency."""

    def test_D7_duplicate_frequency_does_not_corrupt_card_state(self, qapp):
        from guitar_tap.views.shared.peak_card_widget import PeakListWidget

        peaks = _peaks_like_the_corrupt_file()
        # Selection mirrors the real file: the claimed Top and one of the 239.2 twins.
        selected = {peaks[0].id, peaks[2].id}

        widget = PeakListWidget()
        widget.model.selected_peak_ids = set(selected)
        widget.model.is_live = False
        widget.update_data_with_modes(
            [
                (peaks[0], GuitarMode.TOP),
                (peaks[1], GuitarMode.BACK),
                (peaks[2], GuitarMode.BACK),
                (peaks[3], GuitarMode.BACK),
            ]
        )

        cards = widget._cards
        assert len(cards) == len(peaks), (
            f"expected one card per peak, got {len(cards)} for {len(peaks)} peaks"
        )

        # The two 239.2 Hz cards must not agree: one twin is selected, the other is not.
        # Under the defect both read _peaks[-1] (the unselected twin) and both show "off".
        twin_states = sorted(c._show for c in cards if abs(c.freq - 239.244433) < 1e-6)
        assert twin_states == ["off", "on"], (
            f"duplicate-frequency cards resolved to the same peak: {twin_states}. "
            "One 239.244433 Hz peak is in selected_peak_ids and the other is not, so exactly "
            "one card must be starred. Cards must resolve by peak id, not by frequency."
        )

        # And the unique-frequency cards must still be right.
        by_freq = {round(c.freq, 3): c for c in cards}
        assert by_freq[196.447]._show == "on", "the selected Top peak lost its star"
        assert by_freq[231.877]._show == "off", "an unselected peak gained a star"

    def test_D7b_duplicate_frequency_does_not_corrupt_mode_labels(self, qapp):
        """Mode labels must come from each card's own peak.

        In the field this surfaced as two cards labelled "Air" for a peak the graph
        annotated as "Back" — the label was read from the last peak in the list.
        """
        from guitar_tap.views.shared.peak_card_widget import PeakListWidget

        peaks = _peaks_like_the_corrupt_file()
        widget = PeakListWidget()
        widget.model.selected_peak_ids = {p.id for p in peaks}
        widget.model.is_live = False
        # Give the LAST peak a distinct mode: if a card reads _peaks[-1] instead of its
        # own row, it will wrongly report this one.
        widget.update_data_with_modes(
            [
                (peaks[0], GuitarMode.TOP),
                (peaks[1], GuitarMode.BACK),
                (peaks[2], GuitarMode.BACK),
                (peaks[3], GuitarMode.AIR),
            ]
        )

        # The two 239.2 Hz cards were given DIFFERENT modes (Back and Air). A card that
        # resolves by frequency lands on _peaks[-1] and both report Air; resolving by id
        # gives one of each. Asserting on a unique-frequency card would pass either way —
        # only the duplicates expose the defect.
        twin_modes = sorted(str(c._mode) for c in widget._cards if abs(c.freq - 239.244433) < 1e-6)
        assert twin_modes == sorted([GuitarMode.AIR.value, GuitarMode.BACK.value]), (
            f"duplicate-frequency cards reported modes {twin_modes}; expected one Back and "
            "one Air. A card must take its label from its own peak, not from whatever shares "
            "its frequency. This is the 'Back on the graph, Air in the table' divergence."
        )