# @parity test/mode-colors
"""Lock GuitarMode's display colour against silent drift (parity group model/mode-colors).

Until the #17 sweep Python rendered its own palette — invented here, never matching Swift, on the
same white background. Ring was #823CC8 against Swift's #CB30E0, and UPPER_MODES and UNKNOWN were
the SAME grey, so those two categories were indistinguishable on this chart while Swift and the web
separated them. Swift is canonical and these are its values, now absolute in both.

Mirrors Swift ModeColorsTests and web mode-colors.test.ts. See SLUG-SWEEP.md F9.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from guitar_tap.models.guitar_mode import GuitarMode


def test_per_mode_hex():
    """The canonical table. Swift's GuitarMode.hex carries these exactly."""
    assert GuitarMode.AIR.hex         == "#00C0E8"
    assert GuitarMode.TOP.hex         == "#34C759"
    assert GuitarMode.BACK.hex        == "#FF8D28"
    assert GuitarMode.DIPOLE.hex      == "#FF383C"
    assert GuitarMode.RING_MODE.hex   == "#CB30E0"
    assert GuitarMode.UPPER_MODES.hex == "#8E8E93"
    assert GuitarMode.UNKNOWN.hex     == "#808080"


def test_every_mode_has_its_own_colour():
    """Seven modes must be seven tellable-apart colours — the only thing the hue has to do.

    Upper Modes and Unknown are the close pair, and they were IDENTICAL here until #17.
    """
    hexes = [m.hex for m in GuitarMode.current_cases]
    assert len(set(hexes)) == len(hexes), f"each mode needs its own colour, got {hexes}"
    assert GuitarMode.UPPER_MODES.hex != GuitarMode.UNKNOWN.hex, \
        "Upper Modes and Unknown must stay distinguishable"


def test_legacy_cases_share_their_canonical_colour():
    """Legacy cases collapse to their canonical equivalent's colour, via normalized."""
    assert GuitarMode.HELMHOLTZ.hex   == GuitarMode.AIR.hex
    assert GuitarMode.CROSS_GRAIN.hex == GuitarMode.AIR.hex
    assert GuitarMode.LONG_GRAIN.hex  == GuitarMode.TOP.hex
    assert GuitarMode.MONOPOLE.hex    == GuitarMode.BACK.hex


def test_rgb_tuple_is_derived_from_the_hex():
    """color is the (r, g, b) form of hex, so the Qt drawing calls cannot diverge from it."""
    for m in GuitarMode.current_cases:
        h = m.hex.lstrip("#")
        assert m.color == (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
