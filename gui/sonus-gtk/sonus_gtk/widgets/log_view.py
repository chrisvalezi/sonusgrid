# SPDX-License-Identifier: GPL-3.0-or-later
"""In-app journal viewer that follows the two SonusGrid user units."""

from __future__ import annotations

import re

from gi.repository import Adw, Gdk, GLib, Gtk

from sonus_gtk.i18n import _t
from sonus_gtk.services import cli

UNITS = {
    "all": ["-u", "sonusgrid-clock.service", "-u", "sonusgrid-audio.service"],
    "clock": ["-u", "sonusgrid-clock.service"],
    "audio": ["-u", "sonusgrid-audio.service"],
}
MAX_LINES = 5000
_ERR = re.compile(r"\b(ERROR|error|panicked|Failed|failed|Error:)\b")
# "Sep 19 01:25:48 host sonusgrid[1234]: " → "01:25:48 "
_PREFIX = re.compile(r"^\w{3} +\d+ (\d\d:\d\d:\d\d) \S+ \S+?\[\d+\]: ")
# engine lines start with their own ISO timestamp: "[2026-09-19T04:25:48.086018Z INFO  target] msg"
_ISO = re.compile(r"^\[\d{4}-\d\d-\d\dT[\d:.]+Z +")
_WARN = re.compile(r"\b(WARN|warning|XRUN)\b")


class LogView(Gtk.Box):
    def __init__(self, notify) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._notify = notify
        self._handle: cli.FollowHandle | None = None
        self._unit = "all"

        bar = Gtk.Box(spacing=6, margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)
        self.unit_dd = Gtk.DropDown.new_from_strings([_t("Tudo", "All"), _t("Relógio PTP", "PTP clock"), _t("Ponte de áudio", "Audio bridge")])
        self.unit_dd.connect("notify::selected", self._on_unit)
        bar.append(self.unit_dd)
        self.follow_btn = Gtk.ToggleButton(icon_name="media-playback-start-symbolic", active=True,
                                           tooltip_text=_t("Seguir (auto-rolar)", "Follow (auto-scroll)"))
        bar.append(self.follow_btn)
        clear = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text=_t("Limpar", "Clear"))
        clear.connect("clicked", lambda *_: self.buffer.set_text(""))
        bar.append(clear)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_t("Copiar tudo", "Copy all"))
        copy.connect("clicked", self._copy)
        bar.append(copy)
        self.search = Gtk.SearchEntry(placeholder_text=_t("Filtrar…", "Filter…"), hexpand=True)
        self.search.connect("search-changed", self._on_search)
        bar.append(self.search)
        self.append(bar)
        self.append(Gtk.Separator())

        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, vexpand=True,
                                 left_margin=6, right_margin=6)
        self.view.add_css_class("sg-log")
        self.buffer = self.view.get_buffer()
        self.tag_err = self.buffer.create_tag("err")
        self.tag_warn = self.buffer.create_tag("warn")
        self.tag_dim = self.buffer.create_tag("dim")
        self.tag_hit = self.buffer.create_tag("hit", weight=700)
        self._retint()
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self._retint())
        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.scroller.set_child(self.view)
        self.append(self.scroller)

        self.connect("map", lambda *_: self.start())
        self.connect("unmap", lambda *_: self.stop())

    def _retint(self) -> None:
        ctx = self.get_style_context()
        ok, err = ctx.lookup_color("error_color")
        ok2, warn = ctx.lookup_color("warning_color")
        self.tag_err.set_property("foreground-rgba", err if ok else Gdk.RGBA(1, 0.3, 0.3, 1))
        self.tag_warn.set_property("foreground-rgba", warn if ok2 else Gdk.RGBA(1, 0.6, 0.1, 1))
        fg = self.get_color()
        self.tag_dim.set_property("foreground-rgba", Gdk.RGBA(fg.red, fg.green, fg.blue, 0.55))

    # ---- process ------------------------------------------------------------
    def start(self) -> None:
        self.stop()
        argv = ["journalctl", "--user", *UNITS[self._unit], "-o", "short", "-n", "300", "-f", "--no-pager"]
        self._handle = cli.follow(argv, self._on_line, self._on_exit)

    def stop(self) -> None:
        if self._handle:
            self._handle.cancel()
            self._handle = None

    def _on_unit(self, *_a) -> None:
        self._unit = ["all", "clock", "audio"][self.unit_dd.get_selected()]
        self.buffer.set_text("")
        if self.get_mapped():
            self.start()

    def _on_exit(self, rc: int) -> None:
        if self.get_mapped() and self._handle and not self._handle.alive:
            self._append(f"[gui] journalctl exited ({rc}); retrying in 3 s", "dim")
            GLib.timeout_add_seconds(3, lambda: (self.get_mapped() and self.start(), False)[1])

    # ---- buffer -------------------------------------------------------------
    def _on_line(self, line: str) -> None:
        line = _strip_ansi(line)
        line = _PREFIX.sub(r"\1 ", line)
        line = _ISO.sub("[", line)
        tag = "err" if _ERR.search(line) else "warn" if _WARN.search(line) else None
        self._append(line, tag)

    def _append(self, line: str, tag: str | None) -> None:
        end = self.buffer.get_end_iter()
        if tag:
            self.buffer.insert_with_tags_by_name(end, line + "\n", tag)
        else:
            self.buffer.insert(end, line + "\n")
        n = self.buffer.get_line_count()
        if n > MAX_LINES:
            s = self.buffer.get_start_iter()
            e = self.buffer.get_iter_at_line(n - MAX_LINES)[1]
            self.buffer.delete(s, e)
        if self.follow_btn.get_active():
            adj = self.scroller.get_vadjustment()
            GLib.idle_add(lambda: (adj.set_value(adj.get_upper() - adj.get_page_size()), False)[1])

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        q = entry.get_text()
        s, e = self.buffer.get_bounds()
        self.buffer.remove_tag(self.tag_hit, s, e)
        if not q:
            return
        it = self.buffer.get_start_iter()
        first = None
        while True:
            res = it.forward_search(q, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if not res:
                break
            ms, me = res
            self.buffer.apply_tag(self.tag_hit, ms, me)
            first = first or ms
            it = me
        if first:
            self.follow_btn.set_active(False)
            self.view.scroll_to_iter(first, 0.1, True, 0, 0.3)

    def _copy(self, *_a) -> None:
        s, e = self.buffer.get_bounds()
        Gdk.Display.get_default().get_clipboard().set(self.buffer.get_text(s, e, False))
        self._notify(_t("Log copiado.", "Log copied."))


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)
