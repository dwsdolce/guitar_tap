# @parity util/timing-activity
"""Hold off the operating system's timer throttling while the app does something time-critical.

macOS throttles the timers of an app it considers idle — App Nap. Measured in this edition's test
process (#19): after ~30–35 s a one-chunk (21.3 ms) sleep took 56–98 ms, so paced file playback ran
2–4× slower than real time. Only a LATENCY-CRITICAL activity lifted it; a user-initiated one did not.
File playback is paced by such sleeps, so it holds one of these for its whole run.

Mirrors Swift GuitarTap/Utilities/TimingActivity.swift. Elsewhere than macOS this is a no-op: Windows
and Linux have no App Nap. The web has no equivalent: a browser offers no way to exempt a page from
background-tab timer throttling.
"""

from __future__ import annotations

import sys

# NSActivityUserInitiated | NSActivityLatencyCritical (Foundation, NSProcessInfo.h).
_NS_ACTIVITY_USER_INITIATED = 0x00FFFFFF
_NS_ACTIVITY_LATENCY_CRITICAL = 0xFF00000000


def hold_timing_activity(reason: str) -> object | None:
    """Begin an activity that keeps the OS from throttling this process's timers.

    Returns a token for release_timing_activity, or None where there is nothing to hold.
    """
    if sys.platform != "darwin":
        return None
    from Foundation import NSProcessInfo
    return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
        _NS_ACTIVITY_USER_INITIATED | _NS_ACTIVITY_LATENCY_CRITICAL, reason
    )


def release_timing_activity(token: object | None) -> None:
    """End an activity begun by hold_timing_activity."""
    if token is None:
        return
    from Foundation import NSProcessInfo
    NSProcessInfo.processInfo().endActivity_(token)
