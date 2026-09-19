# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders a DoctorReport as summary card + Problems / Passed lists."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from sonus_gtk.i18n import _t, is_pt
from sonus_gtk.services.doctor import DoctorReport, run_doctor


class DoctorList(Gtk.Box):
    def __init__(self, notify) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._notify = notify
        self._report: DoctorReport | None = None
        self._running = False

        # summary card
        self.summary = Gtk.Box(spacing=16)
        self.summary.add_css_class("card")
        self.summary.add_css_class("sg-summary")
        self.orb = Gtk.Image.new_from_icon_name("emblem-system-symbolic")
        self.orb.add_css_class("sg-orb")
        self.orb.set_valign(Gtk.Align.CENTER)
        self.summary.append(self.orb)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("title-3")
        self.subtitle = Gtk.Label(xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        text.append(self.title)
        text.append(self.subtitle)
        self.summary.append(text)
        btns = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_t("Copiar relatório", "Copy report"))
        self.copy_btn.add_css_class("flat")
        self.copy_btn.connect("clicked", self._copy)
        self._stack = Gtk.Stack(hhomogeneous=False)
        self.run_btn = Gtk.Button(label=_t("Rodar de novo", "Run again"))
        self.run_btn.add_css_class("pill")
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.connect("clicked", lambda *_: self.run())
        self._stack.add_named(self.run_btn, "btn")
        self._stack.add_named(Gtk.Spinner(spinning=True, width_request=32, height_request=32), "spin")
        btns.append(self.copy_btn)
        btns.append(self._stack)
        self.summary.append(btns)
        self.append(self.summary)

        self.problems = Adw.PreferencesGroup(title=_t("Problemas", "Problems"))
        self.passed = Adw.PreferencesGroup(title=_t("Aprovados", "Passed"))
        self.append(self.problems)
        self.append(self.passed)
        self._rows: list[tuple[Adw.PreferencesGroup, Gtk.Widget]] = []
        self._set_idle()

    def _set_idle(self) -> None:
        self.title.set_label(_t("Diagnóstico", "Diagnostics"))
        self.subtitle.set_label(_t("Verifica config, rede, PTP, PipeWire e serviços.",
                                   "Checks config, network, PTP, PipeWire and services."))

    def run(self) -> None:
        if self._running:
            return
        self._running = True
        self._stack.set_visible_child_name("spin")
        self.subtitle.set_label(_t("Rodando…", "Running…"))
        run_doctor(self._on_report)

    def _clear(self) -> None:
        for group, row in self._rows:
            group.remove(row)
        self._rows.clear()

    def _on_report(self, rep: DoctorReport) -> None:
        self._running = False
        self._report = rep
        self._stack.set_visible_child_name("btn")
        self._clear()
        for c in ("running", "failed", "starting"):
            self.orb.remove_css_class(c)
        if rep.error and not rep.passed and not rep.problems:
            self.orb.set_from_icon_name("dialog-error-symbolic")
            self.orb.add_css_class("failed")
            self.title.set_label(_t("Não foi possível diagnosticar", "Could not run diagnostics"))
            self.subtitle.set_label(rep.error)
        elif rep.ok:
            self.orb.set_from_icon_name("emblem-ok-symbolic")
            self.orb.add_css_class("running")
            self.title.set_label(_t("Tudo verde", "All checks passed"))
            self.subtitle.set_label(_t(f"{len(rep.passed)} verificações OK. SonusGrid está pronto.",
                                       f"{len(rep.passed)} checks OK. SonusGrid is ready."))
        else:
            n = len(rep.problems)
            self.orb.set_from_icon_name("dialog-warning-symbolic")
            self.orb.add_css_class("failed")
            self.title.set_label(_t(f"{n} problema{'s' if n != 1 else ''} encontrado{'s' if n != 1 else ''}",
                                    f"{n} problem{'s' if n != 1 else ''} found"))
            self.subtitle.set_label(_t("Cada item traz o comando para corrigir.",
                                       "Each item tells you how to fix it."))
        for pt, en in rep.problems:
            row = Adw.ActionRow(title=pt if is_pt() else en, subtitle=en if is_pt() else pt)
            row.set_title_lines(0)
            row.set_subtitle_lines(0)
            row.set_subtitle_selectable(True)
            icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
            icon.add_css_class("error")
            row.add_prefix(icon)
            self.problems.add(row)
            self._rows.append((self.problems, row))
        for text in rep.passed:
            row = Adw.ActionRow(title=text)
            row.set_title_lines(0)
            icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            icon.add_css_class("success")
            row.add_prefix(icon)
            self.passed.add(row)
            self._rows.append((self.passed, row))
        self.problems.set_visible(bool(rep.problems))
        self.passed.set_visible(bool(rep.passed))

    def _copy(self, *_a) -> None:
        if not self._report:
            return
        Gdk.Display.get_default().get_clipboard().set(self._report.raw)
        self._notify(_t("Relatório copiado.", "Report copied."))
