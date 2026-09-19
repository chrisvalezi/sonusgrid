# SPDX-License-Identifier: GPL-3.0-or-later
"""Status chip (pill label) and dot indicators."""

from __future__ import annotations

from gi.repository import Gtk

_STATES = ("ok", "warn", "err", "info", "off")


class Chip(Gtk.Label):
    def __init__(self, text: str = "", state: str = "off") -> None:
        super().__init__(label=text, valign=Gtk.Align.CENTER)
        self.add_css_class("sg-chip")
        self.set_state(state)

    def set_state(self, state: str, text: str | None = None) -> None:
        for s in _STATES:
            self.remove_css_class(s)
        if state in _STATES and state != "off":
            self.add_css_class(state)
        if text is not None:
            self.set_label(text)


class Dot(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.add_css_class("sg-dot")

    def set_state(self, state: str) -> None:
        for s in _STATES:
            self.remove_css_class(s)
        if state in _STATES and state != "off":
            self.add_css_class(state)
