# SPDX-License-Identifier: GPL-3.0-or-later
"""Mixer page — master + per-pair faders with peak meters for TX (PC → Dante)
and RX (Dante → PC). Meters are refreshed from the window's frame clock."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from sonus_gtk.i18n import _t
from sonus_gtk.pages import BasePage
from sonus_gtk.services.mixer import MIN_DB, Meters, MixerClient
from sonus_gtk.widgets.meter_bar import MeterBar

FADER_MIN = -80.0
SEND_INTERVAL_MS = 40   # throttle fader → socket


def fmt_db(db: float) -> str:
    return "−∞" if db <= FADER_MIN + 0.5 else f"{db:+.1f} dB"


class Strip(Gtk.Box):
    """One fader strip: label, meter, vertical scale, dB readout, mute, link."""

    def __init__(self, page: "MixerPage", direction: str, channels: list[int], linkable: bool) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.page = page
        self.direction = direction
        self.channels = channels       # 0-based indices (1 or 2)
        self.linked = True
        self.add_css_class("card")
        self.add_css_class("sg-strip")
        title = "-".join(str(c + 1) for c in channels)
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("heading")
        self.append(lbl)

        row = Gtk.Box(spacing=8, vexpand=True, halign=Gtk.Align.CENTER)
        self.meter = MeterBar(bars=len(channels), width=10 * len(channels) + 4, height=170)
        row.append(self.meter)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, FADER_MIN, 0.0, 0.5)
        self.scale.set_inverted(True)
        self.scale.set_draw_value(False)
        self.scale.set_vexpand(True)
        self.scale.add_mark(0.0, Gtk.PositionType.RIGHT, "0")
        self.scale.add_mark(-12.0, Gtk.PositionType.RIGHT, "-12")
        self.scale.add_mark(-24.0, Gtk.PositionType.RIGHT, "-24")
        self.scale.add_mark(-48.0, Gtk.PositionType.RIGHT, "-48")
        self.scale.connect("value-changed", self._on_scale)
        row.append(self.scale)
        self.append(row)

        self.readout = Gtk.Label(label=fmt_db(0.0))
        self.readout.add_css_class("numeric")
        self.readout.add_css_class("caption")
        self.append(self.readout)

        btns = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER)
        self.mute = Gtk.ToggleButton(label="M", tooltip_text=_t("Mudo", "Mute"))
        self.mute.add_css_class("sg-mute")
        self.mute.connect("toggled", self._on_mute)
        btns.append(self.mute)
        if linkable:
            self.link = Gtk.ToggleButton(icon_name="insert-link-symbolic", active=True,
                                         tooltip_text=_t("Par ligado (L/R juntos)", "Linked pair (L/R together)"))
            self.link.connect("toggled", lambda b: setattr(self, "linked", b.get_active()))
            btns.append(self.link)
        self.append(btns)
        self._loading = False
        self._pending: float | None = None
        self._timer = 0

    # ---- from the bridge -------------------------------------------------------------------
    def apply_state(self, gains: list[float], mutes: list[bool]) -> None:
        self._loading = True
        c0 = self.channels[0]
        if c0 < len(gains):
            self.scale.set_value(max(FADER_MIN, gains[c0]))
            self.readout.set_label(fmt_db(gains[c0]))
        if c0 < len(mutes):
            self.mute.set_active(mutes[c0])
        self._loading = False

    def push_meter(self, peaks: list[float]) -> None:
        self.meter.push([peaks[c] if c < len(peaks) else MIN_DB for c in self.channels])

    # ---- to the bridge ---------------------------------------------------------------------
    def _on_scale(self, scale: Gtk.Scale) -> None:
        db = scale.get_value()
        self.readout.set_label(fmt_db(db))
        if self._loading:
            return
        self._pending = db
        if not self._timer:
            self._timer = GLib.timeout_add(SEND_INTERVAL_MS, self._flush)

    def _flush(self) -> bool:
        self._timer = 0
        if self._pending is None:
            return False
        db = self._pending
        self._pending = None
        for c in self.targets():
            self.page.client.set_gain(self.direction, c, db)
        return False

    def _on_mute(self, btn: Gtk.ToggleButton) -> None:
        if self._loading:
            return
        for c in self.targets():
            self.page.client.set_mute(self.direction, c, btn.get_active())

    def targets(self) -> list[int]:
        return self.channels if (self.linked or len(self.channels) == 1) else self.channels[:1]


class MasterStrip(Gtk.Box):
    def __init__(self, page: "MixerPage") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.page = page
        self.add_css_class("card")
        self.add_css_class("sg-strip")
        self.add_css_class("sg-master")
        lbl = Gtk.Label(label="MASTER")
        lbl.add_css_class("heading")
        self.append(lbl)
        row = Gtk.Box(spacing=8, vexpand=True, halign=Gtk.Align.CENTER)
        self.meter = MeterBar(bars=2, width=26, height=170)
        row.append(self.meter)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, FADER_MIN, 0.0, 0.5)
        self.scale.set_inverted(True)
        self.scale.set_draw_value(False)
        self.scale.set_vexpand(True)
        for m in (0, -12, -24, -48):
            self.scale.add_mark(float(m), Gtk.PositionType.RIGHT, str(m) if m else "0")
        self.scale.connect("value-changed", self._on_scale)
        row.append(self.scale)
        self.append(row)
        self.readout = Gtk.Label(label=fmt_db(0.0))
        self.readout.add_css_class("title-4")
        self.readout.add_css_class("numeric")
        self.append(self.readout)
        self.mute = Gtk.ToggleButton(label=_t("MUDO", "MUTE"), halign=Gtk.Align.CENTER)
        self.mute.add_css_class("sg-mute")
        self.mute.add_css_class("sg-mute-master")
        self.mute.connect("toggled", self._on_mute)
        self.append(self.mute)
        self._loading = False
        self._pending: float | None = None
        self._timer = 0

    def apply_state(self, db: float, muted: bool) -> None:
        self._loading = True
        self.scale.set_value(max(FADER_MIN, db))
        self.readout.set_label(fmt_db(db))
        self.mute.set_active(muted)
        self._loading = False

    def _on_scale(self, scale: Gtk.Scale) -> None:
        db = scale.get_value()
        self.readout.set_label(fmt_db(db))
        if self._loading:
            return
        self._pending = db
        if not self._timer:
            self._timer = GLib.timeout_add(SEND_INTERVAL_MS, self._flush)

    def _flush(self) -> bool:
        self._timer = 0
        if self._pending is not None:
            self.page.client.set_master(self._pending)
            self._pending = None
        return False

    def _on_mute(self, btn: Gtk.ToggleButton) -> None:
        if not self._loading:
            self.page.client.set_master_mute(btn.get_active())


class MixerPage(BasePage):
    def __init__(self, app) -> None:
        super().__init__(app, "mixer", _t("Mixer", "Mixer"), scroll=False, clamp=False)
        self.client = MixerClient()
        self.cfg = app.config
        self._strips: dict[str, list[Strip]] = {"tx": [], "rx": []}
        self._master: MasterStrip | None = None
        self._tick_id = 0
        self._last_seq = -1
        self._state_timer = 0
        self._channels = 0

        self.fps_label = Gtk.Label(label="")
        self.fps_label.add_css_class("dim-label")
        self.fps_label.add_css_class("caption")
        self.header.pack_end(self.fps_label)

        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.header.set_title_widget(switcher)
        self.bar = Adw.ViewSwitcherBar(stack=self.stack)
        self.toolbar.add_bottom_bar(self.bar)

        self.status = Adw.StatusPage(icon_name="audio-speakers-symbolic",
                                     title=_t("Mixer indisponível", "Mixer unavailable"),
                                     description=_t("Inicie o SonusGrid para ver os faders e medidores.",
                                                    "Start SonusGrid to see the faders and meters."))
        self.root = Gtk.Stack()
        self.root.add_named(self.status, "off")
        self.root.add_named(self.stack, "on")
        self.toolbar.set_content(self.root)

        self.tx_box = self._page_box()
        self.rx_box = self._page_box()
        self.stack.add_titled_with_icon(self.tx_box[0], "tx", _t("Saída → Dante", "Output → Dante"), "go-up-symbolic")
        self.stack.add_titled_with_icon(self.rx_box[0], "rx", _t("Entrada ← Dante", "Input ← Dante"), "go-down-symbolic")

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.cfg.connect("saved", lambda *_: self._rebuild())

    def _page_box(self) -> tuple[Gtk.Widget, Gtk.Box]:
        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        box = Gtk.Box(spacing=10, margin_top=14, margin_bottom=14, margin_start=14, margin_end=14,
                      halign=Gtk.Align.CENTER)
        sw.set_child(box)
        return sw, box

    # ---- lifecycle -----------------------------------------------------------------------
    def _on_map(self, *_a) -> None:
        self._rebuild()
        if not self._tick_id:
            self._tick_id = self.add_tick_callback(self._tick)
        if not self._state_timer:
            self._state_timer = GLib.timeout_add_seconds(2, self._sync_state)

    def _on_unmap(self, *_a) -> None:
        if self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        if self._state_timer:
            GLib.source_remove(self._state_timer)
            self._state_timer = 0

    def set_collapsed(self, collapsed: bool) -> None:
        self.bar.set_reveal(collapsed)

    # ---- strips --------------------------------------------------------------------------
    def _rebuild(self) -> None:
        m = self.client.read_meters()
        if m is None:
            self.root.set_visible_child_name("off")
            return
        self.root.set_visible_child_name("on")
        if m.channels == self._channels and self._strips["tx"]:
            return
        self._channels = m.channels
        for direction, (_sw, box) in (("tx", self.tx_box), ("rx", self.rx_box)):
            child = box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                box.remove(child)
                child = nxt
            self._strips[direction] = []
            if direction == "tx":
                self._master = MasterStrip(self)
                box.append(self._master)
                box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
            ch = list(range(m.channels))
            pairs = [ch[i:i + 2] for i in range(0, len(ch), 2)]
            for pair in pairs:
                s = Strip(self, direction, pair, linkable=len(pair) == 2)
                self._strips[direction].append(s)
                box.append(s)
        self._sync_state()

    def _sync_state(self) -> bool:
        st = self.client.get_state()
        if not st:
            return True
        if self._master:
            self._master.apply_state(float(st.get("master_db", 0.0)), bool(st.get("master_mute")))
        for direction in ("tx", "rx"):
            d = st.get(direction) or {}
            gains = [float(x) for x in d.get("gain_db", [])]
            mutes = [bool(x) for x in d.get("mute", [])]
            for s in self._strips[direction]:
                if not s.scale.has_css_class("dragging"):
                    s.apply_state(gains, mutes)
        return True

    # ---- meters at the display's frame rate ---------------------------------------------
    def _tick(self, widget, frame_clock) -> bool:
        m = self.client.read_meters()
        if m is None:
            if self.root.get_visible_child_name() != "off":
                self.root.set_visible_child_name("off")
            return GLib.SOURCE_CONTINUE
        if self.root.get_visible_child_name() != "on":
            self._rebuild()
        if m.seq == self._last_seq:
            return GLib.SOURCE_CONTINUE   # bridge hasn't published a new frame
        self._last_seq = m.seq
        for s in self._strips["tx"]:
            s.push_meter(m.tx_peak_db)
        for s in self._strips["rx"]:
            s.push_meter(m.rx_peak_db)
        if self._master:
            self._master.meter.push(list(m.master_peak_db))
        fps = frame_clock.get_fps() if frame_clock else 0.0
        if fps:
            self.fps_label.set_label(f"{fps:.0f} fps")
        return GLib.SOURCE_CONTINUE
