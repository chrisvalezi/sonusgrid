# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnostics page — doctor checklist + live logs."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from sonus_gtk.i18n import _t
from sonus_gtk.pages import BasePage
from sonus_gtk.widgets.doctor_list import DoctorList
from sonus_gtk.widgets.log_view import LogView


class DiagnosticsPage(BasePage):
    def __init__(self, app) -> None:
        super().__init__(app, "diagnostics", _t("Diagnóstico", "Diagnostics"), scroll=False, clamp=False)
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.header.set_title_widget(switcher)
        self.bar = Adw.ViewSwitcherBar(stack=self.stack)
        self.toolbar.add_bottom_bar(self.bar)
        self.toolbar.set_content(self.stack)

        # checks
        self.doctor = DoctorList(self.notify_toast)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=18, margin_bottom=24, margin_start=16, margin_end=16)
        body.append(self.doctor)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_child(Adw.Clamp(maximum_size=760, tightening_threshold=600, child=body))
        self.stack.add_titled_with_icon(sw, "checks", _t("Verificações", "Checks"), "emblem-ok-symbolic")

        # logs
        self.logs = LogView(self.notify_toast)
        self.stack.add_titled_with_icon(self.logs, "logs", _t("Logs", "Logs"), "view-list-symbolic")

        self._ran = False
        self.connect("map", self._on_map)

    def _on_map(self, *_a) -> None:
        if not self._ran:
            self._ran = True
            self.doctor.run()

    def show_tab(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

    def set_collapsed(self, collapsed: bool) -> None:
        self.bar.set_reveal(collapsed)
