# SPDX-License-Identifier: GPL-3.0-or-later
"""NetworkMeter — RX/TX throughput sparklines for the Dante NIC."""

from __future__ import annotations

import math

from gi.repository import Adw, GLib, Gtk

from sonus_gtk.i18n import _t
from sonus_gtk.services import net

HISTORY = 60
MIN_SCALE_BPS = 512_000 / 8   # bytes/s — keeps idle traffic a flat line


def format_rate(bytes_per_s: float) -> str:
    bits = bytes_per_s * 8
    for unit, div in (("Gbit/s", 1e9), ("Mbit/s", 1e6), ("kbit/s", 1e3)):
        if bits >= div:
            return f"{bits / div:.1f} {unit}"
    return f"{bits:.0f} bit/s"


class _Row(Gtk.Box):
    def __init__(self, label: str, css: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("sg-meter-row")
        self.history: list[float] = []
        self.peak = 0.0

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER, width_request=84)
        title = Gtk.Label(label=label, xalign=0)
        title.add_css_class("heading")
        self.peak_label = Gtk.Label(label="", xalign=0)
        self.peak_label.add_css_class("caption")
        self.peak_label.add_css_class("dim-label")
        left.append(title)
        left.append(self.peak_label)
        self.append(left)

        self.area = Gtk.DrawingArea(hexpand=True, content_height=44)
        self.area.add_css_class(css)
        self.area.set_draw_func(self._draw)
        self.append(self.area)

        self.rate = Gtk.Label(label="—", xalign=1, width_request=92)
        self.rate.add_css_class("sg-rate")
        self.rate.add_css_class("numeric")
        self.append(self.rate)

    def push(self, v: float) -> None:
        self.history.append(v)
        del self.history[:-HISTORY]
        self.peak = max(self.peak * 0.995, v)
        self.rate.set_label(format_rate(v))
        self.peak_label.set_label(_t("pico ", "peak ") + format_rate(self.peak))
        self.area.queue_draw()

    def reset(self) -> None:
        self.history.clear()
        self.peak = 0.0
        self.rate.set_label("—")
        self.peak_label.set_label("")
        self.area.queue_draw()

    def _draw(self, area: Gtk.DrawingArea, cr, w: int, h: int) -> None:
        col = area.get_color()
        # baseline
        cr.set_source_rgba(col.red, col.green, col.blue, 0.10)
        cr.set_line_width(1)
        cr.move_to(0, h - 0.5)
        cr.line_to(w, h - 0.5)
        cr.stroke()
        if len(self.history) < 2:
            return
        scale = max(max(self.history), MIN_SCALE_BPS)
        n = len(self.history)
        step = w / (HISTORY - 1)
        x0 = w - (n - 1) * step
        pts = [(x0 + i * step, h - 3 - (v / scale) * (h - 6)) for i, v in enumerate(self.history)]
        cr.move_to(pts[0][0], h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], h)
        cr.close_path()
        cr.set_source_rgba(col.red, col.green, col.blue, 0.16)
        cr.fill()
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(col.red, col.green, col.blue, 0.95)
        cr.set_line_width(1.6)
        cr.set_line_join(1)
        cr.stroke()


class NetworkMeter(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("card")
        self.add_css_class("sg-meter")
        self.rx = _Row(_t("Recebendo", "Receive"), "sg-spark-rx")
        self.tx = _Row(_t("Enviando", "Send"), "sg-spark-tx")
        self.append(self.rx)
        self.append(Gtk.Separator(margin_start=12, margin_end=12))
        self.append(self.tx)
        self._iface = ""
        self._last: tuple[int, int] | None = None
        self._last_t = 0.0
        GLib.timeout_add_seconds(1, self._tick)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: (self.rx.area.queue_draw(), self.tx.area.queue_draw()))

    def set_interface(self, iface: str) -> None:
        if iface == self._iface:
            return
        self._iface = iface
        self._last = None
        self.rx.reset()
        self.tx.reset()
        self.set_visible(bool(iface))

    def _tick(self) -> bool:
        if not self._iface or not self.get_mapped():
            return True
        now = GLib.get_monotonic_time() / 1e6
        cur = net.read_iface_bytes(self._iface)
        if cur is None:
            return True
        if self._last is not None:
            dt = max(now - self._last_t, 1e-3)
            self.rx.push(max(0.0, (cur[0] - self._last[0]) / dt))
            self.tx.push(max(0.0, (cur[1] - self._last[1]) / dt))
        self._last, self._last_t = cur, now
        return True
