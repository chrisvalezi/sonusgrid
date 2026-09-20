# SPDX-License-Identifier: GPL-3.0-or-later
"""Vertical peak meter (one or two bars) drawn with Cairo. Values in dBFS.
Redrawn from the page's frame-clock tick — i.e. at the display's refresh
rate (60 fps on a 60 Hz monitor, less on slower panels), never faster."""

from __future__ import annotations

from gi.repository import Adw, Gtk

MIN_DB = -72.0   # bottom of the scale
HOLD_FRAMES = 90  # peak-hold marker ≈ 1.5 s at 60 fps


class MeterBar(Gtk.DrawingArea):
    def __init__(self, bars: int = 2, width: int = 22, height: int = 160) -> None:
        super().__init__(content_width=width, content_height=height, vexpand=True)
        self.bars = bars
        self.values = [MIN_DB] * bars
        self._hold = [MIN_DB] * bars
        self._hold_age = [0] * bars
        self.set_draw_func(self._draw)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.queue_draw())

    def push(self, values: list[float]) -> None:
        changed = False
        for i in range(self.bars):
            v = values[i] if i < len(values) else MIN_DB
            if v != self.values[i]:
                changed = True
            self.values[i] = v
            if v >= self._hold[i]:
                self._hold[i] = v
                self._hold_age[i] = 0
            else:
                self._hold_age[i] += 1
                if self._hold_age[i] > HOLD_FRAMES:
                    self._hold[i] = max(v, self._hold[i] - 0.8)  # fall
                    changed = True
        if changed:
            self.queue_draw()

    @staticmethod
    def _frac(db: float) -> float:
        return max(0.0, min(1.0, (db - MIN_DB) / (0.0 - MIN_DB)))

    def _draw(self, area, cr, w: int, h: int) -> None:
        fg = self.get_color()
        gap = 3
        bw = (w - gap * (self.bars - 1)) / self.bars
        # track
        for i in range(self.bars):
            x = i * (bw + gap)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.10)
            cr.rectangle(x, 0, bw, h)
            cr.fill()
        # scale ticks at -3/-12/-24/-48
        for db in (-3, -12, -24, -48, -60):
            y = h - self._frac(db) * h
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.22)
            cr.rectangle(0, y, w, 1)
            cr.fill()
        for i in range(self.bars):
            x = i * (bw + gap)
            v = self.values[i]
            f = self._frac(v)
            top = h - f * h
            # green up to -12, yellow to -3, red above
            y12 = h - self._frac(-12) * h
            y3 = h - self._frac(-3) * h
            segs = [(h, y12, (0.20, 0.72, 0.36)), (y12, y3, (0.95, 0.72, 0.15)), (y3, 0, (0.90, 0.25, 0.25))]
            for y0, y1, (r, g, b) in segs:
                lo, hi = max(top, y1), y0
                if hi > lo:
                    cr.set_source_rgba(r, g, b, 0.95)
                    cr.rectangle(x, lo, bw, hi - lo)
                    cr.fill()
            hv = self._hold[i]
            if hv > MIN_DB + 0.5:
                y = h - self._frac(hv) * h
                r, g, b = (0.90, 0.25, 0.25) if hv > -3 else (0.95, 0.72, 0.15) if hv > -12 else (fg.red, fg.green, fg.blue)
                cr.set_source_rgba(r, g, b, 0.9)
                cr.rectangle(x, max(0, y - 1), bw, 2)
                cr.fill()
