# SPDX-License-Identifier: GPL-3.0-or-later
"""Status page — hero, services, network meter, endpoint tiles."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from sonus_gtk.i18n import _t
from sonus_gtk.pages import BasePage
from sonus_gtk.services.status import Phase, StatusModel
from sonus_gtk.widgets.chip import Chip
from sonus_gtk.widgets.hero import HeroCard
from sonus_gtk.widgets.meter import NetworkMeter
from sonus_gtk.widgets.stat_tile import StatTile


def _fmt_offset(m: StatusModel) -> str:
    if not m.ptp_has_offset:
        return ""
    ns = m.ptp_offset_ns
    if abs(ns) < 1000:
        return f"{ns:+.0f} ns"
    us = ns / 1000.0
    return f"{us:+.1f} µs" if abs(us) < 1000 else f"{us / 1000:+.2f} ms"


class StatusPage(BasePage):
    def __init__(self, app) -> None:
        super().__init__(app, "status", _t("Estado", "Status"))
        self.model: StatusModel = app.status
        self.cfg = app.config

        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_t("Atualizar (F5)", "Refresh (F5)"))
        refresh.connect("clicked", lambda *_: self.model.refresh())
        self.header.pack_end(refresh)

        # Banners live above the scrolled body.
        self.banner_iface = Adw.Banner(title=_t("Nenhuma interface de rede selecionada.",
                                                "No network interface selected."))
        self.banner_iface.set_button_label(_t("Configurar", "Configure"))
        self.banner_iface.connect("button-clicked", lambda *_: app.window.navigate("config"))
        self.banner_fail = Adw.Banner(title=_t("Um serviço falhou ao iniciar.", "A service failed to start."))
        self.banner_fail.set_button_label(_t("Ver logs", "View logs"))
        self.banner_fail.connect("button-clicked", lambda *_: app.window.navigate("diagnostics", "logs"))
        self.toolbar.add_top_bar(self.banner_iface)
        self.toolbar.add_top_bar(self.banner_fail)

        # Whole-body stack: normal | CLI missing
        self.hero = HeroCard(on_toggle=self._toggle)
        self.body.append(self.hero)

        # Services group
        svc = Adw.PreferencesGroup(title=_t("Serviços", "Services"))
        self.row_clock = Adw.ActionRow(title=_t("Relógio PTP", "PTP clock"), subtitle="statime")
        self.row_clock.add_prefix(Gtk.Image.new_from_icon_name("alarm-symbolic"))
        self.chip_clock = Chip(_t("parado", "stopped"))
        self.row_clock.add_suffix(self.chip_clock)
        self.row_audio = Adw.ActionRow(title=_t("Ponte de áudio", "Audio bridge"),
                                       subtitle=_t("sink PipeWire + ALSA", "PipeWire sink + ALSA"))
        self.row_audio.add_prefix(Gtk.Image.new_from_icon_name("audio-speakers-symbolic"))
        self.chip_audio = Chip(_t("parado", "stopped"))
        self.row_audio.add_suffix(self.chip_audio)
        self.row_jack = Adw.ActionRow(title=_t("Cliente JACK", "JACK client"),
                                      subtitle=_t("portas SonusGrid-JACK:tx_NN / rx_NN para DAWs", "SonusGrid-JACK:tx_NN / rx_NN ports for DAWs"))
        self.row_jack.add_prefix(Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic"))
        self.chip_jack = Chip(_t("desligado", "off"))
        self.row_jack.add_suffix(self.chip_jack)
        for r in (self.row_clock, self.row_audio, self.row_jack):
            svc.add(r)
        self.body.append(svc)

        # Network group
        self.net_group = Adw.PreferencesGroup(title=_t("Rede", "Network"))
        self.net_label = Gtk.Label(label="")
        self.net_label.add_css_class("dim-label")
        self.net_label.add_css_class("numeric")
        self.net_group.set_header_suffix(self.net_label)
        self.meter = NetworkMeter()
        self.net_group.add(self.meter)
        self.body.append(self.net_group)

        # Endpoint tiles
        ep = Adw.PreferencesGroup(title=_t("Endpoint Dante", "Dante endpoint"))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=2, max_children_per_line=3,
                           row_spacing=10, column_spacing=10)
        self.tiles = {
            "rate": StatTile(_t("Sample rate", "Sample rate"), "media-playlist-repeat-symbolic"),
            "chan": StatTile(_t("Canais", "Channels"), "view-grid-symbolic"),
            "lat": StatTile(_t("Latência", "Latency"), "preferences-system-time-symbolic"),
            "ptp": StatTile("PTP", "network-wired-symbolic"),
            "ip": StatTile("IP", "network-server-symbolic"),
            "ver": StatTile(_t("Versão", "Version"), "help-about-symbolic"),
        }
        for t in self.tiles.values():
            flow.append(t)
        ep.add(flow)
        self.body.append(ep)

        # CLI-missing state
        self.missing = Adw.StatusPage(icon_name="dialog-error-symbolic",
                                      title=_t("CLI sonusgrid não encontrada", "sonusgrid CLI not found"),
                                      description=_t("Instale o pacote sonusgrid ou verifique o PATH.",
                                                     "Install the sonusgrid package or check your PATH."))
        retry = Gtk.Button(label=_t("Tentar de novo", "Retry"), halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.add_css_class("suggested-action")
        retry.connect("clicked", lambda *_: self.model.refresh())
        self.missing.set_child(retry)
        self.missing.set_visible(False)
        # insert missing page into the toolbar content stack
        stack = Gtk.Stack()
        old = self.toolbar.get_content()
        self.toolbar.set_content(stack)
        stack.add_named(old, "main")
        stack.add_named(self.missing, "missing")
        self._stack = stack

        self.model.connect("updated", lambda *_: self._render())
        self.model.connect("notify::busy", lambda *_: self._render())
        self.model.connect("action-done", self._on_action_done)
        self.cfg.connect("reloaded", lambda *_: self._render())
        self.cfg.connect("saved", lambda *_: self._render())
        self._render()

    # ---- actions --------------------------------------------------------------
    def _toggle(self) -> None:
        if self.model.busy:
            return
        if self.model.is_running or self.model.phase == Phase.STARTING.value:
            self.model.stop()
        else:
            if not self.cfg.interface:
                self.notify_toast(_t("Selecione uma interface de rede primeiro.", "Pick a network interface first."))
                self.app.window.navigate("config")
                return
            self.model.start()

    def _on_action_done(self, _m, verb: str, ok: bool, msg: str) -> None:
        if ok:
            self.notify_toast({"start": _t("SonusGrid iniciado.", "SonusGrid started."),
                               "stop": _t("SonusGrid parado.", "SonusGrid stopped."),
                               "restart": _t("SonusGrid reiniciado.", "SonusGrid restarted.")}[verb])
        else:
            self.app.window.toast_with_details(
                _t(f"Falha ao {'iniciar' if verb != 'stop' else 'parar'}.", f"Failed to {verb}."), msg)

    # ---- render ---------------------------------------------------------------
    def _render(self) -> None:
        m = self.model
        self._stack.set_visible_child_name("missing" if m.phase == Phase.CLI_MISSING.value else "main")
        iface = self.cfg.interface
        self.banner_iface.set_revealed(not iface)
        self.banner_fail.set_revealed(m.phase == Phase.FAILED.value)

        name = m.device_name or self.cfg.device_name
        ip = self.cfg.get("network", "bind_ip", "") or ""
        where = f"{iface} · {ip}" if ip else iface
        ptp_txt = ""
        if m.ptp_state:
            lock = _t("lock", "locked") if m.ptp_locked else _t("sincronizando", "syncing")
            ptp_txt = f"PTP {m.ptp_version} {lock}"
            off = _fmt_offset(m)
            if off and m.ptp_locked:
                ptp_txt += f" {off}"
        phase = m.phase
        if phase in (Phase.RUNNING.value, Phase.DEGRADED.value):
            title = f"{name}"
            parts = [_t("Rodando", "Running"), ptp_txt or f"PTP {m.ptp_version}", where]
            if phase == Phase.DEGRADED.value:
                parts.append(_t("JACK indisponível", "JACK unavailable"))
            subtitle = "  ·  ".join(p for p in parts if p)
        elif phase == Phase.STARTING.value:
            title = _t("Iniciando…", "Starting…")
            subtitle = _t("Esperando rede e lock do relógio PTP (até ~1 min).",
                          "Waiting for the network and the PTP clock lock (up to ~1 min).")
        elif phase == Phase.FAILED.value:
            which = _t("relógio", "clock") if m.clock_state == "failed" else _t("áudio", "audio")
            title = _t("Falha ao iniciar", "Failed to start")
            subtitle = _t(f"O serviço de {which} falhou. Veja Diagnóstico → Logs.",
                          f"The {which} service failed. See Diagnostics → Logs.")
        elif phase == Phase.UNKNOWN.value:
            title = _t("Consultando…", "Checking…")
            subtitle = m.last_error or ""
        else:
            title = _t("Parado", "Stopped")
            subtitle = (_t("Selecione a interface e clique Iniciar.", "Pick the interface, then click Start.")
                        if not iface else _t(f"Pronto para iniciar em {where}.", f"Ready to start on {where}."))
        self.hero.set_state(phase, title, subtitle, m.busy)

        # service chips
        def unit_chip(chip: Chip, state: str, extra_ok: bool = True) -> None:
            if state == "active" and extra_ok:
                chip.set_state("ok", _t("ativo", "active"))
            elif state == "active":
                chip.set_state("warn", _t("subindo", "starting"))
            elif state == "activating":
                chip.set_state("warn", _t("iniciando", "activating"))
            elif state == "failed":
                chip.set_state("err", _t("falhou", "failed"))
            else:
                chip.set_state("off", _t("parado", "stopped"))

        unit_chip(self.chip_clock, m.clock_state, m.ptp_locked or not m.ptp_state)
        if m.clock_active and m.ptp_state:
            sub = f"statime · {m.ptp_state.lower()}"
            off = _fmt_offset(m)
            if off:
                sub += f" · offset {off}"
            if m.ptp_grandmaster:
                sub += f" · master {m.ptp_grandmaster}"
            self.row_clock.set_subtitle(sub)
        else:
            self.row_clock.set_subtitle(f"statime · PTP {m.ptp_version or self.cfg.get('ptp', 'version', 'v1')}")
        unit_chip(self.chip_audio, m.audio_state, m.sink_present)
        self.row_audio.set_subtitle(_t("sink PipeWire ", "PipeWire sink ") + (self.cfg.get("bridge", "sink_name", "SonusGrid")) + " + ALSA")
        if not self.cfg.jack_enabled:
            self.chip_jack.set_state("off", _t("desabilitado", "disabled"))
        elif m.jack_active:
            self.chip_jack.set_state("ok", _t("ativo", "active"))
        elif m.audio_active:
            self.chip_jack.set_state("warn", _t("indisponível", "unavailable"))
        else:
            self.chip_jack.set_state("off", _t("parado", "stopped"))

        # network + tiles
        self.meter.set_interface(iface)
        self.net_label.set_label(where)
        rate = self.cfg.sample_rate
        self.tiles["rate"].set(f"{rate / 1000:g} kHz")
        self.tiles["chan"].set(_t(f"{self.cfg.get('device', 'rx_channels', 0)} in · {self.cfg.get('device', 'tx_channels', 0)} out",
                                  f"{self.cfg.get('device', 'rx_channels', 0)} in · {self.cfg.get('device', 'tx_channels', 0)} out"))
        try:
            lat = float(self.cfg.get("device", "rx_latency_ns", 4_000_000)) / 1e6
        except (TypeError, ValueError):
            lat = 4.0
        self.tiles["lat"].set(f"{lat:.1f} ms")
        self.tiles["ptp"].set(f"{self.cfg.get('ptp', 'version', 'v1')} · {_t('domínio', 'domain')} {self.cfg.get('ptp', 'domain', 0)}")
        self.tiles["ip"].set(ip or "—")
        self.tiles["ver"].set(m.version or "—")
