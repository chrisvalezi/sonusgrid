# SPDX-License-Identifier: GPL-3.0-or-later
"""SonusApp — application object: CSS, actions, models, window."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from sonus_gtk import dialogs  # noqa: E402
from sonus_gtk.config import ConfigStore  # noqa: E402
from sonus_gtk.i18n import set_language  # noqa: E402
from sonus_gtk.services import launchers  # noqa: E402
from sonus_gtk.services.status import StatusModel  # noqa: E402

PKG_DIR = Path(__file__).resolve().parent
APP_ID = "io.sonusgrid.SonusGrid"


class SonusApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.config: ConfigStore | None = None
        self.status: StatusModel | None = None
        self._dark_provider: Gtk.CssProvider | None = None

    # ---- lifecycle -------------------------------------------------------------
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._install_css()
        self._install_icons()
        Gtk.Window.set_default_icon_name(APP_ID)
        self.config = ConfigStore()
        set_language(str(self.config.get("ui", "language", "auto")))
        self.status = StatusModel(jack_wanted=lambda: self.config.jack_enabled)
        self._actions()

    def do_activate(self) -> None:
        from sonus_gtk.window import SonusWindow

        win = self.props.active_window or SonusWindow(self)
        win.present()
        self.status.start_polling(2)
        shot = os.environ.get("SONUSGRID_SCREENSHOT")
        if shot:
            size = os.environ.get("SONUSGRID_SCREENSHOT_SIZE")
            if size and "x" in size:
                w, h = (int(x) for x in size.split("x"))
                win.set_default_size(w, h)
            page = os.environ.get("SONUSGRID_SCREENSHOT_PAGE")
            if page:
                tag, _, sub = page.partition(":")
                GLib.timeout_add(600, lambda: (win.navigate(tag, sub or None), False)[1])
            GLib.timeout_add(int(os.environ.get("SONUSGRID_SCREENSHOT_DELAY_MS", "3000")),
                             lambda: (self._screenshot(win, shot), False)[1])

    # ---- styling -----------------------------------------------------------------
    def _install_css(self) -> None:
        display = Gdk.Display.get_default()
        base = Gtk.CssProvider()
        base.load_from_path(str(PKG_DIR / "css" / "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._dark_provider = Gtk.CssProvider()
        self._dark_provider.load_from_path(str(PKG_DIR / "css" / "style-dark.css"))
        sm = Adw.StyleManager.get_default()
        sm.set_color_scheme(Adw.ColorScheme.DEFAULT)
        sm.connect("notify::dark", lambda *_: self._sync_dark())
        self._sync_dark()

    def _sync_dark(self) -> None:
        display = Gdk.Display.get_default()
        if Adw.StyleManager.get_default().get_dark():
            Gtk.StyleContext.add_provider_for_display(display, self._dark_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        else:
            Gtk.StyleContext.remove_provider_for_display(display, self._dark_provider)

    def _install_icons(self) -> None:
        # Running from a source checkout: make data/icons visible.
        src_icons = PKG_DIR.parent / "data" / "icons"
        if src_icons.is_dir():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(src_icons))

    # ---- actions -----------------------------------------------------------------
    def _actions(self) -> None:
        def add(name: str, cb, accels: list[str] | None = None, param=None) -> None:
            act = Gio.SimpleAction.new(name, param)
            act.connect("activate", cb)
            self.add_action(act)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

        add("quit", lambda *_: self.quit(), ["<Primary>q"])
        add("refresh", lambda *_: self.status.refresh(), ["F5"])
        add("about", lambda *_: dialogs.show_about(self.window, self.status.version))
        add("shortcuts", lambda *_: dialogs.show_shortcuts(self.window))
        add("open-config", lambda *_: (self.config.ensure_exists(), launchers.open_uri(str(self.config.path))))
        add("docs", lambda *_: self._open_doc("USER_GUIDE.md"))
        add("daw-guide", lambda *_: self._open_doc("DAW.md"))
        add("page", lambda _a, p: self.window.navigate(p.get_string()), None, GLib.VariantType.new("s"))
        for i, tag in enumerate(("status", "routing", "config", "diagnostics"), start=1):
            self.set_accels_for_action(f"app.page::{tag}", [f"<Primary>{i}"])

    def _open_doc(self, name: str) -> None:
        p = launchers.find_doc(name)
        if p is None:
            self.window.toast(f"{name}: " + ("não encontrado" if os.environ.get("LANG", "").startswith("pt") else "not found"))
            return
        launchers.open_uri(str(p))

    # ---- screenshot hook (docs/tests) ------------------------------------------------
    def _screenshot(self, win: Gtk.Window, path: str) -> None:
        try:
            paintable = Gtk.WidgetPaintable.new(win)
            w, h = win.get_width(), win.get_height()
            snap = Gtk.Snapshot.new()
            paintable.snapshot(snap, w, h)
            node = snap.to_node()
            tex = win.get_native().get_renderer().render_texture(node, None)
            tex.save_to_png(path)
            print(f"screenshot saved: {path}", file=sys.stderr)
        except Exception as e:  # pragma: no cover
            print(f"screenshot failed: {e}", file=sys.stderr)
        if os.environ.get("SONUSGRID_SCREENSHOT_QUIT", "1") == "1":
            self.quit()


def main(argv: list[str] | None = None) -> int:
    return SonusApp().run(argv if argv is not None else sys.argv)
