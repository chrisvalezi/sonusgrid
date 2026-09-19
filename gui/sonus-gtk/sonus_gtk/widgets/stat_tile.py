# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from gi.repository import Gtk, Pango


class StatTile(Gtk.Box):
    def __init__(self, caption: str, icon: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("card")
        self.add_css_class("sg-tile")
        head = Gtk.Box(spacing=6)
        if icon:
            img = Gtk.Image.new_from_icon_name(icon)
            img.add_css_class("dim-label")
            head.append(img)
        cap = Gtk.Label(label=caption.upper(), xalign=0)
        cap.add_css_class("sg-tile-caption")
        head.append(cap)
        self.append(head)
        self.value = Gtk.Label(label="—", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.value.add_css_class("sg-tile-value")
        self.value.add_css_class("numeric")
        self.append(self.value)

    def set(self, text: str) -> None:
        self.value.set_label(text or "—")
