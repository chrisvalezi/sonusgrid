# SPDX-License-Identifier: GPL-3.0-or-later
"""HeroCard — the big state card at the top of the Status page."""

from __future__ import annotations

from gi.repository import Gtk

from sonus_gtk.i18n import _t


class HeroCard(Gtk.Box):
    def __init__(self, on_toggle) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.add_css_class("card")
        self.add_css_class("sg-hero")

        self.orb = Gtk.Image.new_from_icon_name("media-playback-stop-symbolic")
        self.orb.add_css_class("sg-orb")
        self.orb.set_valign(Gtk.Align.CENTER)
        self.append(self.orb)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("title-2")
        self.title.add_css_class("sg-hero-title")
        self.subtitle = Gtk.Label(xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        text.append(self.title)
        text.append(self.subtitle)
        self.append(text)

        self._stack = Gtk.Stack(valign=Gtk.Align.CENTER, hhomogeneous=False)
        self.button = Gtk.Button(label=_t("Iniciar", "Start"))
        self.button.add_css_class("pill")
        self.button.add_css_class("suggested-action")
        self.button.add_css_class("sg-hero-button")
        self.button.connect("clicked", lambda *_: on_toggle())
        self.spinner = Gtk.Spinner(spinning=True, width_request=40, height_request=40)
        self._stack.add_named(self.button, "button")
        self._stack.add_named(self.spinner, "spinner")
        self.append(self._stack)

    def set_state(self, phase: str, title: str, subtitle: str, busy: bool) -> None:
        self.title.set_label(title)
        self.subtitle.set_label(subtitle)
        for c in ("running", "degraded", "starting", "failed"):
            self.orb.remove_css_class(c)
        for c in ("suggested-action", "destructive-action"):
            self.button.remove_css_class(c)
        icon = "media-playback-stop-symbolic"
        if phase in ("running", "degraded"):
            icon = "io.sonusgrid.SonusGrid-symbolic"
            self.orb.add_css_class(phase)
            self.button.set_label(_t("Parar", "Stop"))
            self.button.add_css_class("destructive-action")
        elif phase == "starting":
            icon = "emblem-synchronizing-symbolic"
            self.orb.add_css_class("starting")
            self.button.set_label(_t("Parar", "Stop"))
            self.button.add_css_class("destructive-action")
        elif phase == "failed":
            icon = "dialog-error-symbolic"
            self.orb.add_css_class("failed")
            self.button.set_label(_t("Tentar de novo", "Try again"))
            self.button.add_css_class("suggested-action")
        else:
            self.button.set_label(_t("Iniciar", "Start"))
            self.button.add_css_class("suggested-action")
        self.orb.set_from_icon_name(icon)
        self._stack.set_visible_child_name("spinner" if busy else "button")
