# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from gi.repository import Gtk

from sonus_gtk.widgets.chip import Dot


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, tag: str, title: str, icon: str) -> None:
        super().__init__()
        self.tag = tag
        self.add_css_class("sg-sidebar-row")
        box = Gtk.Box(spacing=10)
        box.append(Gtk.Image.new_from_icon_name(icon))
        label = Gtk.Label(label=title, xalign=0, hexpand=True)
        box.append(label)
        self.dot = Dot()
        self.dot.set_visible(False)
        box.append(self.dot)
        self.set_child(box)

    def set_dot(self, state: str | None) -> None:
        if state is None:
            self.dot.set_visible(False)
        else:
            self.dot.set_visible(True)
            self.dot.set_state(state)
