# @parity view/threshold-slider
"""
ThresholdSlider — QSlider subclass that displays a level meter in the groove.

The slider's groove is overlaid with a horizontal level-meter rectangle that
fills from the slider's minimum to the current input level (set via
``set_level_db``).  A bright peak-hold dot tracks the recent maximum and
decays slowly back to the current level.  The rightmost ~10 % of the groove
turns red when the input is clipping (set via ``set_clipping``).  The slider
handle remains draggable and represents the threshold value.

Mirrors Swift ``ThresholdSlider`` SwiftUI view.  Used for the tap-detection
threshold control across all measurement types (guitar, plate, brace), since
all measurement types now base detection on the magnitude of the audio
waveform (RMS) rather than the FFT-peak magnitude — making a level meter
the natural way to show the user what the threshold is being compared
against.
"""

from __future__ import annotations

import time

from PySide6 import QtCore, QtGui, QtWidgets


_STYLE_SHEET = """
    QSlider::groove:horizontal {
        border: 1px solid palette(mid);
        background: palette(base);
        height: 14px;
        margin: 2px 0;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: red;
        border: 1px solid #800;
        width: 4px;
        margin: -3px 0;
        border-radius: 1px;
    }
    QSlider::handle:horizontal:hover {
        background: #f44;
    }
"""


class _ProxyStyle(QtWidgets.QProxyStyle):
    """Proxy style: clicking in the groove jumps the handle to that position
    immediately (rather than stepping by pageStep).
    """

    def styleHint(self, hint, opt=None, widget=None, returnData=None):
        res = super().styleHint(hint, opt, widget, returnData)
        if hint == QtWidgets.QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
            # PySide6 6.x / Py 3.14: Qt.MouseButton is a flag enum without
            # __int__; use .value (the underlying integer) explicitly.
            res = QtCore.Qt.MouseButton.LeftButton.value
        return res


class ThresholdSlider(QtWidgets.QSlider):
    """Horizontal slider with an integrated level-meter feedback fill.

    State:
      - The slider value (inherited) is the threshold setting in dB.
      - ``_level_db`` is the most recent input RMS level (dB).
      - ``_peak_hold_db`` is a rolling peak-hold marker that immediately
        snaps to a new high, holds for ``PEAK_HOLD_SECONDS``, then decays
        at ``PEAK_DECAY_DB_PER_SEC``.
      - ``_is_clipping`` colours the rightmost ``CLIP_ZONE_FRACTION`` of
        the groove red.

    Wire up:
      - ``set_level_db(db)`` from ``RealtimeFFTAnalyzer.rmsLevelChanged``
        (per-chunk RMS, ~43 Hz).
      - ``set_clipping(bool)`` from ``RealtimeFFTAnalyzer.clippingChanged``
        (edge-triggered).
    """

    # Peak-hold behaviour.
    PEAK_HOLD_SECONDS: float = 0.5
    PEAK_DECAY_DB_PER_SEC: float = 20.0

    # Fraction of the groove width that turns red when clipping.
    CLIP_ZONE_FRACTION: float = 0.10

    def __init__(self, parent: "QtWidgets.QWidget | None" = None) -> None:
        super().__init__(QtCore.Qt.Orientation.Horizontal, parent)
        self.setStyleSheet(_STYLE_SHEET)
        # Hold a Python reference to the proxy style — QWidget.setStyle() does
        # NOT take Python ownership, so without this the proxy is garbage
        # collected and the next paintEvent dereferences a freed pointer.
        # Crash signature: access violation in QStyle.subControlRect().
        self._proxy_style = _ProxyStyle()
        self.setStyle(self._proxy_style)
        # Default to a representative dB range — typically overridden by
        # setRange() after construction (-80 to -20 for tap threshold).
        self._level_db: float = float(self.minimum())
        self._peak_hold_db: float = float(self.minimum())
        self._is_clipping: bool = False
        self._peak_set_time: float = 0.0
        self._last_update_time: float = time.monotonic()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_level_db(self, db: float) -> None:
        """Update the displayed input RMS level (dB).

        Decays the peak-hold marker if the hold time has elapsed; bumps it
        up to a new high if the incoming level exceeds it.  Triggers a
        repaint.
        """
        now = time.monotonic()

        # Decay the peak hold if the hold duration has elapsed since the
        # peak was last set.  Decay is incremental over real wall-clock
        # time, so the rate is independent of update frequency.
        if now - self._peak_set_time > self.PEAK_HOLD_SECONDS:
            dt = max(0.0, now - self._last_update_time)
            self._peak_hold_db -= self.PEAK_DECAY_DB_PER_SEC * dt

        # New maximum: snap up immediately, restart the hold timer.
        if db > self._peak_hold_db:
            self._peak_hold_db = db
            self._peak_set_time = now
        # Floor the peak at the current level (never below).
        if self._peak_hold_db < db:
            self._peak_hold_db = db

        self._level_db = db
        self._last_update_time = now
        self.update()

    def set_clipping(self, clipping: bool) -> None:
        """Toggle the clipping indicator (red zone at the right edge)."""
        if clipping != self._is_clipping:
            self._is_clipping = clipping
            self.update()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _db_to_x(self, db: float, groove_rect: QtCore.QRect) -> int:
        """Map a dB value to a pixel x-coordinate within *groove_rect*."""
        rng = float(self.maximum() - self.minimum())
        if rng <= 0:
            return groove_rect.left()
        frac = (db - float(self.minimum())) / rng
        frac = max(0.0, min(1.0, frac))
        return groove_rect.left() + int(frac * groove_rect.width())

    # ------------------------------------------------------------------ #
    # Custom paint
    # ------------------------------------------------------------------ #

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt API)
        qp = QtWidgets.QStylePainter(self)
        opt = QtWidgets.QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()

        # Groove rectangle reported by the active style.
        groove_rect = style.subControlRect(
            QtWidgets.QStyle.ComplexControl.CC_Slider, opt,
            QtWidgets.QStyle.SubControl.SC_SliderGroove, self,
        )

        qp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        # ── Background groove ─────────────────────────────────────────
        qp.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.Mid), 1))
        qp.setBrush(self.palette().color(QtGui.QPalette.ColorRole.Base))
        qp.drawRoundedRect(groove_rect.adjusted(0, 0, -1, -1), 2, 2)

        # ── Level fill (cyan→blue gradient from min to current level) ─
        fill_x = self._db_to_x(self._level_db, groove_rect)
        if fill_x > groove_rect.left():
            level_rect = QtCore.QRect(
                groove_rect.left(), groove_rect.top() + 1,
                fill_x - groove_rect.left(), groove_rect.height() - 2,
            )
            grad = QtGui.QLinearGradient(0, level_rect.top(), 0, level_rect.bottom())
            grad.setColorAt(0.0, QtGui.QColor(102, 204, 255))
            grad.setColorAt(0.7, QtGui.QColor(0, 102, 204))
            grad.setColorAt(1.0, QtGui.QColor(0, 30, 80))
            qp.setPen(QtCore.Qt.PenStyle.NoPen)
            qp.setBrush(QtGui.QBrush(grad))
            qp.drawRect(level_rect)

        # ── Clipping zone (rightmost N% turns red when clipping) ──────
        if self._is_clipping:
            clip_w = max(2, int(groove_rect.width() * self.CLIP_ZONE_FRACTION))
            clip_rect = QtCore.QRect(
                groove_rect.right() - clip_w + 1, groove_rect.top() + 1,
                clip_w, groove_rect.height() - 2,
            )
            qp.setPen(QtCore.Qt.PenStyle.NoPen)
            qp.setBrush(QtGui.QColor(220, 40, 40, 220))
            qp.drawRect(clip_rect)

        # ── Tick marks every 10 dB ────────────────────────────────────
        tick_step_db = 10
        rng = self.maximum() - self.minimum()
        if rng > 0:
            qp.setPen(QtGui.QPen(QtGui.QColor(60, 140, 60, 180), 1))
            db = self.minimum() + tick_step_db
            while db < self.maximum():
                x = self._db_to_x(db, groove_rect)
                qp.drawLine(x, groove_rect.top() + 2, x, groove_rect.bottom() - 2)
                db += tick_step_db

        # ── Peak-hold dot (bright amber, decays back toward level) ────
        if self._peak_hold_db > self.minimum():
            peak_x = self._db_to_x(self._peak_hold_db, groove_rect)
            mid_y = (groove_rect.top() + groove_rect.bottom()) // 2
            qp.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 220), 1))
            qp.setBrush(QtGui.QColor(255, 200, 0, 240))
            qp.drawEllipse(QtCore.QPoint(peak_x, mid_y), 3, 3)

        # ── Standard slider handle (red vertical line via stylesheet) ──
        opt.subControls = QtWidgets.QStyle.SubControl.SC_SliderHandle
        if self.isSliderDown():
            opt.state |= QtWidgets.QStyle.StateFlag.State_Sunken
        qp.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_Slider, opt)
