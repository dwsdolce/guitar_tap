# @parity view/chart-help tests=test/chart-help
"""
The chart's help (its ⓘ): its lines, and which of them the device in use can do. The view shows these; the same
lines are in every edition and in the shared chart-help.json. Mirrors Swift ``ChartHelp`` (Views/ChartHelp.swift).
"""

from __future__ import annotations

import sys
from typing import NamedTuple

TITLE = "Zoom & Pan Controls"


class ChartHelpLine(NamedTuple):
    """One line of the chart's help: a gesture (with Apple's key symbols), its words on a system that is not
    Apple's where they differ, what it does, and what the device needs for it to work ("pointer", "keyboard",
    "pinch"). Mirrors Swift ``ChartHelpLine``."""

    gesture: str
    other_keys: str | None
    effect: str
    needs: frozenset[str]


def _line(gesture: str, effect: str, needs: tuple[str, ...] = (), other_keys: str | None = None) -> ChartHelpLine:
    return ChartHelpLine(gesture, other_keys, effect, frozenset(needs))


# The help's lines, in the groups a separator divides.
GROUPS: list[list[ChartHelpLine]] = [
    [
        _line("Scroll over plot", "Zoom both axes around cursor", ("pointer",)),
        _line("Scroll over freq axis", "Zoom frequency only", ("pointer",)),
        _line("Scroll over mag axis", "Zoom magnitude only", ("pointer",)),
        _line("⇧ + Scroll", "Pan frequency axis", ("pointer", "keyboard"), "Shift + Scroll"),
        _line("⌥ + Scroll", "Pan magnitude axis", ("pointer", "keyboard"), "Alt + Scroll"),
        _line("⌘/⌃ + Scroll", "Zoom both axes", ("pointer", "keyboard"), "Ctrl + Scroll"),
    ],
    [
        _line("Pinch over plot", "Zoom both axes", ("pinch",)),
        _line("Pinch over freq axis", "Zoom frequency only", ("pinch",)),
        _line("Pinch over mag axis", "Zoom magnitude only", ("pinch",)),
    ],
    [
        _line("Drag over plot", "Pan both axes"),
        _line("Drag over freq axis", "Pan frequency only"),
        _line("Drag over mag axis", "Pan magnitude only"),
        _line("Right-click", "Chart menu", ("pointer",)),
    ],
]


class Device(NamedTuple):
    """What a device has, for its help. Mirrors Swift ``ChartHelp.Device``."""

    pointer: bool
    keyboard: bool
    pinch: bool
    apple_keys: bool


def shown(device: Device) -> list[list[tuple[str, str]]]:
    """The lines a device's help shows — (gesture, effect) — by group, empty groups left out. Mirrors Swift
    ``ChartHelp.shown(on:)``."""
    has = {"pointer": device.pointer, "keyboard": device.keyboard, "pinch": device.pinch}
    out = []
    for group in GROUPS:
        lines = [((line.gesture if device.apple_keys or line.other_keys is None else line.other_keys), line.effect)
                 for line in group if all(has[n] for n in line.needs)]
        if lines:
            out.append(lines)
    return out


def current() -> Device:
    """The device in use: a pointer and a keyboard everywhere; on a Mac a trackpad's pinch, and Apple's key symbols.
    On Windows and Linux a trackpad's pinch arrives as Ctrl + Scroll, which the help already lists."""
    mac = sys.platform == "darwin"
    return Device(pointer=True, keyboard=True, pinch=mac, apple_keys=mac)
