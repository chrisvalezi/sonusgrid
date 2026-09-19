# SPDX-License-Identifier: GPL-3.0-or-later
"""Dante network page — discovered devices, PipeWire session, tools, DAWs."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from sonus_gtk import dialogs
from sonus_gtk.i18n import _t
from sonus_gtk.pages import BasePage
from sonus_gtk.services import discovery, launchers, pipewire
from sonus_gtk.widgets.chip import Chip

REFRESH_S = 15


class RoutingPage(BasePage):
    def __init__(self, app) -> None:
        super().__init__(app, "routing", _t("Rede Dante", "Dante network"))
        self.cfg = app.config
        self._rows: list[Gtk.Widget] = []
        self._timer = 0
        self._browsing = False

        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_t("Procurar de novo", "Browse again"))
        self.refresh_btn.connect("clicked", lambda *_: self.browse())
        self.header.pack_end(self.refresh_btn)

        # --- devices
        self.devices = Adw.PreferencesGroup(
            title=_t("Dispositivos na rede", "Devices on the network"),
            description=_t("Descobertos via mDNS (_netaudio-arc._udp) na interface configurada.",
                           "Discovered via mDNS (_netaudio-arc._udp) on the configured interface."))
        self.spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=12)
        self.devices.set_header_suffix(self.spinner)
        self.dev_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.dev_list.add_css_class("boxed-list")
        self.devices.add(self.dev_list)
        self.empty = Adw.ActionRow(title=_t("Nenhum dispositivo Dante encontrado", "No Dante devices found"))
        self.empty.add_prefix(Gtk.Image.new_from_icon_name("network-offline-symbolic"))
        self.empty.set_subtitle_lines(0)
        self.empty_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.empty_list.add_css_class("boxed-list")
        self.empty_list.append(self.empty)
        self.empty_list.set_visible(False)
        self.devices.add(self.empty_list)
        self.body.append(self.devices)

        # --- PipeWire session
        pw = Adw.PreferencesGroup(title=_t("Sessão PipeWire", "PipeWire session"))
        self.quantum_row = Adw.ComboRow(title=_t("Buffer JACK", "JACK buffer"))
        self.quantum_row.set_model(Gtk.StringList.new([str(q) for q in pipewire.QUANTA]))
        self.quantum_row.set_subtitle(_t("Lendo…", "Reading…"))
        self._quantum_ready = False
        self.quantum_row.connect("notify::selected", self._on_quantum)
        pw.add(self.quantum_row)
        self.body.append(pw)

        # --- tools
        tools = Adw.PreferencesGroup(title=_t("Ferramentas", "Tools"))
        tools.add(self._tool_row("qpwgraph", _t("Patchbay visual (qpwgraph)", "Visual patchbay (qpwgraph)"),
                                 _t("Conecte portas JACK/PipeWire arrastando.", "Wire JACK/PipeWire ports by dragging."),
                                 "preferences-system-network-symbolic"))
        tools.add(self._tool_row("pavucontrol", _t("Mixer por aplicativo (pavucontrol)", "Per-app mixer (pavucontrol)"),
                                 _t("Escolha o SonusGrid como saída de cada app.", "Send each app's audio to SonusGrid."),
                                 "audio-volume-medium-symbolic"))
        self.body.append(tools)

        # --- DAWs
        daws = Adw.PreferencesGroup(title="DAWs")
        self.daw_row = Adw.ActionRow(title=_t("Criar atalhos JACK para DAWs instalados", "Create JACK launchers for installed DAWs"),
                                     activatable=True)
        self.daw_row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        self.daw_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.daw_row.connect("activated", lambda *_: self._create_daw_launchers())
        daws.add(self.daw_row)
        self.body.append(daws)
        self._update_daw_subtitle()

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    # ---- devices --------------------------------------------------------------
    def _on_map(self, *_a) -> None:
        self.browse()
        pipewire.read_quantum(self._set_quantum)
        if not self._timer:
            self._timer = GLib.timeout_add_seconds(REFRESH_S, lambda: (self.browse(), True)[1])

    def _on_unmap(self, *_a) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def browse(self) -> None:
        if self._browsing:
            return
        if not self.cfg.interface:
            self._show_devices([], _t("Selecione uma interface em Configuração.", "Pick an interface in Configuration."))
            return
        self._browsing = True
        self.spinner.set_visible(True)
        discovery.browse(self._on_devices)

    def _on_devices(self, devs, err: str) -> None:
        self._browsing = False
        self.spinner.set_visible(False)
        if devs is None:
            self._show_devices([], err or _t("Falha na busca.", "Browse failed."))
            return
        self._show_devices(devs, "")

    def _show_devices(self, devs, err: str) -> None:
        for r in self._rows:
            self.dev_list.remove(r)
        self._rows.clear()
        if not devs:
            self.dev_list.set_visible(False)
            self.empty_list.set_visible(True)
            self.empty.set_subtitle(err or _t("Ligue um equipamento Dante no mesmo switch e aguarde alguns segundos.",
                                                 "Connect a Dante device to the same switch and wait a few seconds."))
            return
        self.empty_list.set_visible(False)
        self.dev_list.set_visible(True)
        for d in devs:
            row = Adw.ActionRow(title=d.name, subtitle=(f"{d.ip}" + (f"  ·  {d.host}.local" if d.host else "")))
            row.add_prefix(Gtk.Image.new_from_icon_name("computer-symbolic" if d.is_self else "network-server-symbolic"))
            if d.is_self:
                row.add_suffix(Chip(_t("este computador", "this computer"), "info"))
            self.dev_list.append(row)
            self._rows.append(row)

    # ---- quantum ----------------------------------------------------------------
    def _set_quantum(self, n: int) -> None:
        self._quantum_ready = False
        idx = pipewire.QUANTA.index(n) if n in pipewire.QUANTA else 2
        self.quantum_row.set_selected(idx)
        self._quantum_subtitle(pipewire.QUANTA[idx])
        self._quantum_ready = True

    def _quantum_subtitle(self, n: int) -> None:
        ms = pipewire.quantum_ms(n, self.cfg.sample_rate)
        self.quantum_row.set_subtitle(_t(f"{n} frames ≈ {ms:.1f} ms a {self.cfg.sample_rate / 1000:g} kHz. Menor = menos latência, mais xruns.",
                                         f"{n} frames ≈ {ms:.1f} ms at {self.cfg.sample_rate / 1000:g} kHz. Lower = less latency, more xruns."))

    def _on_quantum(self, *_a) -> None:
        if not self._quantum_ready:
            return
        n = pipewire.QUANTA[self.quantum_row.get_selected()]
        self._quantum_subtitle(n)

        def done(ok: bool, msg: str) -> None:
            if ok:
                self.notify_toast(_t(f"Buffer JACK = {n} frames.", f"JACK buffer = {n} frames.") + (f" ({msg})" if msg else ""))
            else:
                self.notify_toast(_t(f"Falha ao aplicar buffer: {msg}", f"Failed to apply buffer: {msg}"))

        pipewire.set_quantum(n, self.cfg.sample_rate, done)

    # ---- tools ------------------------------------------------------------------
    def _tool_row(self, tool: str, title: str, subtitle: str, icon: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        btn = Gtk.Button(icon_name="external-link-symbolic" if launchers.is_installed(tool) else "folder-download-symbolic",
                         valign=Gtk.Align.CENTER)
        btn.add_css_class("flat")
        btn.connect("clicked", lambda *_: self._open_tool(tool, title))
        row.add_suffix(btn)
        row.connect("activated", lambda *_: self._open_tool(tool, title))
        return row

    def _open_tool(self, tool: str, title: str) -> None:
        if launchers.launch([tool]):
            return
        cmd = launchers.install_command(tool)
        dialogs.show_install_hint(self.app.window, title, cmd, self.notify_toast)

    # ---- DAWs -------------------------------------------------------------------
    def _update_daw_subtitle(self) -> None:
        found = launchers.installed_daws()
        if found:
            self.daw_row.set_subtitle(_t("Encontrados: ", "Found: ") + ", ".join(n for _b, n in found))
        else:
            self.daw_row.set_subtitle(_t("Nenhum DAW conhecido no PATH (REAPER, Ardour, Bitwig, Mixbus, Qtractor…).",
                                         "No known DAW in PATH (REAPER, Ardour, Bitwig, Mixbus, Qtractor…)."))

    def _create_daw_launchers(self) -> None:
        created, err = launchers.create_daw_launchers()
        if err == "pw-jack":
            dialogs.show_install_hint(self.app.window, "pw-jack (PipeWire-JACK)", launchers.install_command("pw-jack"), self.notify_toast)
            return
        if not created:
            self.notify_toast(_t("Nenhum DAW encontrado no PATH.", "No DAW found in PATH."))
            return
        self.notify_toast(_t("Atalhos criados: ", "Launchers created: ") + ", ".join(created)
                          + _t(" — procure '(JACK / SonusGrid)' no menu.", " — look for '(JACK / SonusGrid)' in the menu."))
