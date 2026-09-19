# SPDX-License-Identifier: GPL-3.0-or-later
"""Base page: NavigationPage → ToolbarView(HeaderBar) → ScrolledWindow → Clamp → body."""

from __future__ import annotations

from gi.repository import Adw, Gtk


class BasePage(Adw.NavigationPage):
    """Subclasses fill `self.body` (a vertical Gtk.Box) and may add header
    buttons via `self.header.pack_end`."""

    def __init__(self, app, tag: str, title: str, *, scroll: bool = True, clamp: bool = True) -> None:
        super().__init__(title=title, tag=tag)
        self.app = app
        self.toolbar = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        self.toolbar.add_top_bar(self.header)
        self.set_child(self.toolbar)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                            margin_top=18, margin_bottom=24, margin_start=16, margin_end=16)
        content: Gtk.Widget = self.body
        if clamp:
            content = Adw.Clamp(maximum_size=760, tightening_threshold=600, child=self.body)
        if scroll:
            sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_child(content)
            content = sw
        self.toolbar.set_content(content)

    # convenience
    def notify_toast(self, text: str) -> None:
        self.app.window.toast(text)
