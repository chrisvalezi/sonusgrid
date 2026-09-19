# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration page — a PreferencesPage bound to ConfigStore + apply bar."""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from sonus_gtk import config as cfgmod
from sonus_gtk.i18n import _t
from sonus_gtk.pages import BasePage
from sonus_gtk.services import launchers, net


class ConfigPage(BasePage):
    def __init__(self, app) -> None:
        super().__init__(app, "config", _t("Configuração", "Configuration"), scroll=False, clamp=False)
        self.cfg = app.config
        self._loading = False
        self._ifaces: list[tuple[str, str | None]] = []

        page = Adw.PreferencesPage()
        self.toolbar.set_content(page)
        self._page = page
        self.connect("map", lambda *_: GLib.idle_add(self._scroll_top))

        # --- identity
        g = Adw.PreferencesGroup(title=_t("Identidade", "Identity"))
        self.name_row = Adw.EntryRow(title=_t("Nome do dispositivo", "Device name"))
        self.name_row.connect("notify::text", lambda *_: self._set("device", "name", self.name_row.get_text().strip()))
        g.add(self.name_row)
        adv = Adw.ExpanderRow(title=_t("Avançado", "Advanced"))
        self.devid_row = Adw.EntryRow(title=_t("ID do dispositivo (16 hex, vazio = automático)", "Device ID (16 hex, blank = auto)"))
        self.devid_row.connect("notify::text", lambda *_: self._set("device", "device_id", self.devid_row.get_text().strip()))
        adv.add_row(self.devid_row)
        g.add(adv)
        page.add(g)

        # --- network
        g = Adw.PreferencesGroup(title=_t("Rede", "Network"),
                                 description=_t("Obrigatório. Use a placa Ethernet ligada ao switch Dante — nunca Wi-Fi.",
                                                "Required. Use the Ethernet NIC on the Dante switch — never Wi-Fi."))
        self.iface_row = Adw.ComboRow(title=_t("Interface de rede", "Network interface"))
        self.iface_row.connect("notify::selected", self._on_iface)
        g.add(self.iface_row)
        self.ip_row = Adw.ActionRow(title=_t("IP de bind", "Bind IP"), subtitle="—")
        self.ip_row.add_css_class("property")
        g.add(self.ip_row)
        page.add(g)

        # --- audio
        g = Adw.PreferencesGroup(title=_t("Áudio", "Audio"))
        self.rate_row = Adw.ComboRow(title=_t("Sample rate", "Sample rate"),
                                     subtitle=_t("Toda a rede Dante precisa usar o mesmo.", "The whole Dante network must match."))
        self.rate_row.set_model(Gtk.StringList.new([f"{r / 1000:g} kHz" for r in cfgmod.SAMPLE_RATES]))
        self.rate_row.connect("notify::selected", lambda *_: self._set("device", "sample_rate", cfgmod.SAMPLE_RATES[self.rate_row.get_selected()]))
        g.add(self.rate_row)
        self.rx_row = Adw.SpinRow.new_with_range(0, cfgmod.MAX_CHANNELS, 1)
        self.rx_row.set_title(_t("Entradas (da rede Dante)", "Inputs (from Dante)"))
        self.rx_row.connect("notify::value", lambda *_: self._set("device", "rx_channels", int(self.rx_row.get_value())))
        g.add(self.rx_row)
        self.tx_row = Adw.SpinRow.new_with_range(0, cfgmod.MAX_CHANNELS, 1)
        self.tx_row.set_title(_t("Saídas (para a rede Dante)", "Outputs (to Dante)"))
        self.tx_row.connect("notify::value", self._on_tx)
        g.add(self.tx_row)
        self.lat_row = Adw.SpinRow.new_with_range(0.5, 100.0, 0.5)
        self.lat_row.set_digits(1)
        self.lat_row.set_title(_t("Latência (ms)", "Latency (ms)"))
        self.lat_row.set_subtitle(_t("Aplicada a RX e TX. Maior = mais imune a glitches.", "Applied to RX and TX. Higher = more glitch-resistant."))
        self.lat_row.connect("notify::value", self._on_latency)
        g.add(self.lat_row)
        page.add(g)

        # --- clock
        g = Adw.PreferencesGroup(title=_t("Relógio PTP", "PTP clock"))
        self.ptp_row = Adw.ComboRow(title=_t("Versão PTP", "PTP version"))
        self.ptp_row.set_model(Gtk.StringList.new(["v1 — Dante", "v2 — AES67"]))
        self.ptp_row.connect("notify::selected", lambda *_: self._set("ptp", "version", cfgmod.PTP_VERSIONS[self.ptp_row.get_selected()]))
        g.add(self.ptp_row)
        adv = Adw.ExpanderRow(title=_t("Avançado", "Advanced"))
        self.domain_row = Adw.SpinRow.new_with_range(0, 127, 1)
        self.domain_row.set_title(_t("Domínio", "Domain"))
        self.domain_row.connect("notify::value", lambda *_: self._set("ptp", "domain", int(self.domain_row.get_value())))
        adv.add_row(self.domain_row)
        self.prio_row = Adw.SpinRow.new_with_range(0, 255, 1)
        self.prio_row.set_title("Priority 1")
        self.prio_row.set_subtitle(_t("Maior = menos chance de virar master (padrão 251).", "Higher = less likely to become master (default 251)."))
        self.prio_row.connect("notify::value", lambda *_: self._set("ptp", "priority1", int(self.prio_row.get_value())))
        adv.add_row(self.prio_row)
        self.hwclock_row = Adw.EntryRow(title=_t("Relógio de hardware (auto / sw / /dev/ptpN)", "Hardware clock (auto / sw / /dev/ptpN)"))
        self.hwclock_row.connect("notify::text", lambda *_: self._set("ptp", "hardware_clock", self.hwclock_row.get_text().strip() or "auto"))
        adv.add_row(self.hwclock_row)
        g.add(adv)
        page.add(g)

        # --- bridge
        g = Adw.PreferencesGroup(title=_t("Ponte de áudio", "Audio bridge"))
        self.jack_row = Adw.SwitchRow(title=_t("Cliente JACK (DAW)", "JACK client (DAW)"),
                                      subtitle=_t("Expõe portas tx/rx multicanal para Reaper, Ardour, Bitwig…",
                                                  "Exposes multichannel tx/rx ports for Reaper, Ardour, Bitwig…"))
        self.jack_row.connect("notify::active", lambda *_: self._set("bridge", "jack_enabled", self.jack_row.get_active()))
        g.add(self.jack_row)
        adv = Adw.ExpanderRow(title=_t("Avançado", "Advanced"))
        self.mode_row = Adw.ComboRow(title=_t("Modo", "Mode"))
        self.mode_row.set_model(Gtk.StringList.new(cfgmod.BRIDGE_MODES))
        self.mode_row.connect("notify::selected", lambda *_: self._set("bridge", "mode", cfgmod.BRIDGE_MODES[self.mode_row.get_selected()]))
        adv.add_row(self.mode_row)
        self.sink_row = Adw.EntryRow(title=_t("Nome do sink PipeWire", "PipeWire sink name"))
        self.sink_row.connect("notify::text", lambda *_: self._set("bridge", "sink_name", self.sink_row.get_text().strip() or "SonusGrid"))
        adv.add_row(self.sink_row)
        self.relay_row = Adw.SpinRow.new_with_range(2, cfgmod.MAX_CHANNELS, 1)
        self.relay_row.set_title(_t("Canais da ponte", "Bridge channels"))
        self.relay_row.set_subtitle(_t("Normalmente igual às saídas.", "Normally equal to outputs."))
        self.relay_row.connect("notify::value", lambda *_: self._set("bridge", "relay_channels", int(self.relay_row.get_value())))
        adv.add_row(self.relay_row)
        g.add(adv)
        page.add(g)

        # --- file
        g = Adw.PreferencesGroup(title=_t("Arquivo", "File"))
        row = Adw.ActionRow(title=_t("Abrir config.toml no editor", "Open config.toml in an editor"),
                            subtitle=str(self.cfg.path), activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name("text-x-generic-symbolic"))
        row.add_suffix(Gtk.Image.new_from_icon_name("external-link-symbolic"))
        row.connect("activated", lambda *_: (self.cfg.ensure_exists(), launchers.open_uri(str(self.cfg.path))))
        g.add(row)
        page.add(g)

        # --- apply bar
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        bar = Gtk.ActionBar()
        self.dirty_label = Gtk.Label(label=_t("Alterações não aplicadas", "Unapplied changes"))
        self.dirty_label.add_css_class("dim-label")
        bar.set_center_widget(self.dirty_label)
        discard = Gtk.Button(label=_t("Descartar", "Discard"))
        discard.connect("clicked", lambda *_: self.cfg.discard())
        bar.pack_start(discard)
        self.apply_btn = Gtk.Button(label=_t("Aplicar e reiniciar", "Apply and restart"))
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", lambda *_: self._apply())
        bar.pack_end(self.apply_btn)
        self.revealer.set_child(bar)
        self.toolbar.add_bottom_bar(self.revealer)
        self.cfg.bind_property("dirty", self.revealer, "reveal-child", 0)

        self.cfg.connect("reloaded", lambda *_: self._load())
        self.cfg.connect("saved", lambda *_: self._load())
        self._load()
        net.list_interfaces_with_ip(self._set_ifaces)
        self.connect("map", lambda *_: net.list_interfaces_with_ip(self._set_ifaces))

    def _scroll_top(self) -> bool:
        sw = self._page.get_first_child()
        while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
            sw = sw.get_first_child()
        if sw is not None:
            sw.get_vadjustment().set_value(0)
        return False

    # ---- store → form ------------------------------------------------------------
    def _load(self) -> None:
        self._loading = True
        c = self.cfg
        self.name_row.set_text(str(c.get("device", "name", "")))
        self.devid_row.set_text(str(c.get("device", "device_id", "")))
        rate = c.sample_rate
        self.rate_row.set_selected(cfgmod.SAMPLE_RATES.index(rate) if rate in cfgmod.SAMPLE_RATES else 1)
        self.rx_row.set_value(int(c.get("device", "rx_channels", 16)))
        self.tx_row.set_value(int(c.get("device", "tx_channels", 16)))
        self.lat_row.set_value(float(c.get("device", "rx_latency_ns", 4_000_000)) / 1e6)
        v = c.get("ptp", "version", "v1")
        self.ptp_row.set_selected(cfgmod.PTP_VERSIONS.index(v) if v in cfgmod.PTP_VERSIONS else 0)
        self.domain_row.set_value(int(c.get("ptp", "domain", 0)))
        self.prio_row.set_value(int(c.get("ptp", "priority1", 251)))
        self.hwclock_row.set_text(str(c.get("ptp", "hardware_clock", "auto")))
        self.jack_row.set_active(bool(c.get("bridge", "jack_enabled", True)))
        m = c.get("bridge", "mode", "null-sink")
        self.mode_row.set_selected(cfgmod.BRIDGE_MODES.index(m) if m in cfgmod.BRIDGE_MODES else 0)
        self.sink_row.set_text(str(c.get("bridge", "sink_name", "SonusGrid")))
        self.relay_row.set_value(int(c.get("bridge", "relay_channels", 16)))
        self._select_iface(c.interface)
        self._loading = False

    def _set_ifaces(self, ifaces) -> None:
        self._loading = True
        self._ifaces = ifaces
        labels = [f"{n}  ·  {ip}" if ip else f"{n}  ·  " + _t("sem IP", "no IP") for n, ip in ifaces]
        cur = self.cfg.interface
        if cur and cur not in [n for n, _ in ifaces]:
            labels.append(f"{cur}  ·  " + _t("não encontrada", "not found"))
            self._ifaces = ifaces + [(cur, None)]
        if not labels:
            labels = [_t("(nenhuma interface encontrada)", "(no interfaces found)")]
        self.iface_row.set_model(Gtk.StringList.new(labels))
        self._select_iface(cur)
        self._loading = False

    def _select_iface(self, name: str) -> None:
        idx = next((i for i, (n, _) in enumerate(self._ifaces) if n == name), -1)
        if idx >= 0:
            self.iface_row.set_selected(idx)
            ip = self._ifaces[idx][1]
            self.ip_row.set_subtitle(ip or _t("sem IPv4 — o serviço espera o DHCP", "no IPv4 — the service waits for DHCP"))
            self.iface_row.remove_css_class("sg-warn-row")
            if self._ifaces[idx][1] is None and name:
                self.iface_row.add_css_class("sg-warn-row")
        else:
            self.ip_row.set_subtitle("—")
            self.iface_row.add_css_class("sg-warn-row")

    # ---- form → store -------------------------------------------------------------
    def _set(self, section: str, key: str, value) -> None:
        if self._loading:
            return
        self.cfg.set_value(section, key, value)

    def _on_iface(self, *_a) -> None:
        if self._loading or not self._ifaces:
            return
        idx = self.iface_row.get_selected()
        if 0 <= idx < len(self._ifaces):
            name, ip = self._ifaces[idx]
            self.cfg.set_value("network", "interface", name)
            self.cfg.set_value("network", "bind_ip", ip or "")
            self.ip_row.set_subtitle(ip or _t("sem IPv4", "no IPv4"))
            self.iface_row.remove_css_class("sg-warn-row")

    def _on_tx(self, *_a) -> None:
        if self._loading:
            return
        n = int(self.tx_row.get_value())
        self.cfg.set_value("device", "tx_channels", n)
        self.cfg.set_value("bridge", "relay_channels", max(2, n))
        self._loading = True
        self.relay_row.set_value(max(2, n))
        self._loading = False

    def _on_latency(self, *_a) -> None:
        if self._loading:
            return
        ns = int(round(self.lat_row.get_value() * 1e6))
        self.cfg.set_value("device", "rx_latency_ns", ns)
        self.cfg.set_value("device", "tx_latency_ns", ns)

    def _apply(self) -> None:
        if not self.cfg.interface:
            self.notify_toast(_t("Selecione uma interface de rede.", "Pick a network interface."))
            return
        try:
            self.cfg.save()
        except Exception as e:
            self.notify_toast(_t(f"Erro ao salvar: {e}", f"Save failed: {e}"))
            return
        self.notify_toast(_t("Aplicado. Reiniciando…", "Applied. Restarting…"))
        self.app.status.restart()
