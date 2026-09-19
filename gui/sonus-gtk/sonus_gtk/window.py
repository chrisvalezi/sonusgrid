# SPDX-License-Identifier: GPL-3.0-or-later
"""SonusWindow — NavigationSplitView shell with a sidebar and four pages."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from sonus_gtk import dialogs
from sonus_gtk.i18n import _t
from sonus_gtk.pages.config import ConfigPage
from sonus_gtk.pages.diagnostics import DiagnosticsPage
from sonus_gtk.pages.routing import RoutingPage
from sonus_gtk.pages.status import StatusPage
from sonus_gtk.services.status import Phase
from sonus_gtk.widgets.sidebar import SidebarRow

PAGES = [
    ("status", ("Estado", "Status"), "audio-card-symbolic"),
    ("routing", ("Rede Dante", "Dante network"), "network-workgroup-symbolic"),
    ("config", ("Configuração", "Configuration"), "preferences-system-symbolic"),
    ("diagnostics", ("Diagnóstico", "Diagnostics"), "emblem-system-symbolic"),
]


class SonusWindow(Adw.ApplicationWindow):
    def __init__(self, app) -> None:
        super().__init__(application=app, title="SonusGrid")
        self.app = app
        app.window = self
        self.set_default_size(920, 660)
        self.set_size_request(360, 294)
        self.set_icon_name("io.sonusgrid.SonusGrid")

        self._toasts = Adw.ToastOverlay()
        self.set_content(self._toasts)

        self.split = Adw.NavigationSplitView(min_sidebar_width=200, max_sidebar_width=250, sidebar_width_fraction=0.26)
        self._toasts.set_child(self.split)

        # ---- sidebar
        side_tv = Adw.ToolbarView()
        side_hdr = Adw.HeaderBar()
        side_hdr.set_show_title(False)
        side_hdr.pack_end(self._menu_button())
        side_tv.add_top_bar(side_hdr)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        brand = Gtk.Box(spacing=10)
        brand.add_css_class("sg-sidebar-brand")
        icon = Gtk.Image.new_from_icon_name("io.sonusgrid.SonusGrid")
        icon.add_css_class("sg-brand-icon")
        icon.set_pixel_size(40)
        brand.append(icon)
        bt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        t1 = Gtk.Label(label="SonusGrid", xalign=0)
        t1.add_css_class("title-4")
        self.brand_sub = Gtk.Label(label="", xalign=0)
        self.brand_sub.add_css_class("caption")
        self.brand_sub.add_css_class("dim-label")
        bt.append(t1)
        bt.append(self.brand_sub)
        brand.append(bt)
        side_box.append(brand)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.rows: dict[str, SidebarRow] = {}
        for tag, (pt, en), ic in PAGES:
            row = SidebarRow(tag, _t(pt, en), ic)
            self.rows[tag] = row
            self.list.append(row)
        self.list.connect("row-selected", self._on_row)
        side_box.append(self.list)
        side_tv.set_content(side_box)
        self.split.set_sidebar(Adw.NavigationPage(child=side_tv, title="SonusGrid", tag="sidebar"))

        # ---- pages
        self.pages = {
            "status": StatusPage(app),
            "routing": RoutingPage(app),
            "config": ConfigPage(app),
            "diagnostics": DiagnosticsPage(app),
        }
        self.list.select_row(self.rows["status"])

        # ---- breakpoint (collapse sidebar on narrow windows)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600sp"))
        bp.add_setter(self.split, "collapsed", True)
        bp.connect("apply", lambda *_: self.pages["diagnostics"].set_collapsed(True))
        bp.connect("unapply", lambda *_: self.pages["diagnostics"].set_collapsed(False))
        self.add_breakpoint(bp)

        app.status.connect("updated", lambda *_: self._update_dots())
        self._update_dots()

    # ---- navigation ------------------------------------------------------------
    def _on_row(self, _lb, row: SidebarRow | None) -> None:
        if row is None:
            return
        page = self.pages[row.tag]
        if self.split.get_content() is not page:
            # Drop keyboard focus first: when the old page is unparented GTK
            # would otherwise move focus into the sidebar list, and a
            # single-selection ListBox *selects* the row that gains focus —
            # which silently bounced the selection back to the first row.
            self.set_focus(None)
            self.split.set_content(page)
        if self.split.get_collapsed():
            self.split.set_show_content(True)

    def navigate(self, tag: str, sub: str | None = None) -> None:
        self.list.select_row(self.rows[tag])
        self._on_row(self.list, self.rows[tag])
        if tag == "diagnostics" and sub:
            self.pages["diagnostics"].show_tab(sub)

    def current_tag(self) -> str:
        row = self.list.get_selected_row()
        return row.tag if row else "status"

    # ---- feedback ----------------------------------------------------------------
    def toast(self, text: str) -> None:
        t = Adw.Toast.new(text)
        t.set_timeout(4)
        self._toasts.add_toast(t)

    def toast_with_details(self, text: str, details: str) -> None:
        t = Adw.Toast.new(text)
        t.set_timeout(8)
        if details:
            t.set_button_label(_t("Detalhes", "Details"))
            t.connect("button-clicked", lambda *_: dialogs.show_details(self, text, details))
        self._toasts.add_toast(t)

    def _update_dots(self) -> None:
        m = self.app.status
        ph = m.phase
        dot = {Phase.RUNNING.value: "ok", Phase.DEGRADED.value: "warn", Phase.STARTING.value: "warn",
               Phase.FAILED.value: "err"}.get(ph)
        self.rows["status"].set_dot(dot)
        self.rows["diagnostics"].set_dot("err" if ph == Phase.FAILED.value else None)
        self.rows["config"].set_dot("warn" if not self.app.config.interface else None)
        self.brand_sub.set_label({Phase.RUNNING.value: _t("Rodando", "Running"),
                                  Phase.DEGRADED.value: _t("Rodando (sem JACK)", "Running (no JACK)"),
                                  Phase.STARTING.value: _t("Iniciando…", "Starting…"),
                                  Phase.FAILED.value: _t("Falhou", "Failed"),
                                  Phase.CLI_MISSING.value: _t("CLI ausente", "CLI missing")}.get(ph, _t("Parado", "Stopped")))

    # ---- menu -----------------------------------------------------------------------
    def _menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        s1 = Gio.Menu()
        s1.append(_t("Abrir config.toml", "Open config.toml"), "app.open-config")
        s1.append(_t("Guia do usuário", "User guide"), "app.docs")
        s1.append(_t("Guia DAW / low-latency", "DAW / low-latency guide"), "app.daw-guide")
        menu.append_section(None, s1)
        s2 = Gio.Menu()
        s2.append(_t("Atalhos de teclado", "Keyboard shortcuts"), "app.shortcuts")
        s2.append(_t("Sobre o SonusGrid", "About SonusGrid"), "app.about")
        s2.append(_t("Sair", "Quit"), "app.quit")
        menu.append_section(None, s2)
        btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                             tooltip_text=_t("Menu principal", "Main menu"))
        return btn
