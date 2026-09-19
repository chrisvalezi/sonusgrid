# SPDX-License-Identifier: GPL-3.0-or-later
"""AdwPreferencesWindow with the full Sonus configuration surface.

Reads ~/.config/sonusgrid/config.toml on open, writes it back on save, and prompts
the user to restart Sonus for changes to take effect.
"""

from __future__ import annotations

import json
import locale
import subprocess
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

try:
    import tomllib  # 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

try:
    import tomli_w as _toml_writer
    def _dumps(d: dict) -> str: return _toml_writer.dumps(d)
except ImportError:
    # Fallback: shell out to `sonus config show` after rewriting via the CLI.
    _toml_writer = None
    def _dumps(d: dict) -> str:
        # Hand-rolled, only handles the limited types we use.
        out: list[str] = []
        for section, val in d.items():
            if isinstance(val, dict):
                out.append(f"\n[{section}]")
                for k, v in val.items():
                    out.append(f"{k} = {_format(v)}")
            else:
                out.append(f"{section} = {_format(val)}")
        return "\n".join(out) + "\n"

    def _format(v) -> str:
        if isinstance(v, bool): return "true" if v else "false"
        if isinstance(v, str): return f'"{v}"'
        return str(v)


CONFIG_PATH = Path.home() / ".config" / "sonusgrid" / "config.toml"


def _is_pt() -> bool:
    return (locale.getlocale()[0] or "").startswith("pt")


def _t(pt: str, en: str) -> str:
    return pt if _is_pt() else en


def _list_interfaces() -> list[str]:
    """Return active network interface names (no 'auto' option)."""
    try:
        out = subprocess.run(
            ["ip", "-j", "link", "show"],
            capture_output=True, text=True, timeout=4,
        )
        if out.returncode != 0:
            return []
        names = []
        for entry in json.loads(out.stdout):
            n = entry.get("ifname", "")
            if n in ("lo",) or n.startswith(("docker", "veth", "br-", "cvd-", "tailscale", "nat64", "lxcbr")):
                continue
            names.append(n)
        return names
    except Exception:
        return []


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        subprocess.run(["sonusgrid", "config", "init"], capture_output=True, timeout=10)
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = _dumps(cfg)
    CONFIG_PATH.write_text(text)


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window | None = None) -> None:
        super().__init__()
        if parent:
            self.set_transient_for(parent)
            self.set_modal(True)
        self.set_title(_t("Preferências do SonusGrid", "SonusGrid Preferences"))
        self.set_default_size(640, 600)

        self._cfg = _load_config()
        self._dirty = False

        # --- Page: Device ----------------------------------------------------
        page_dev = Adw.PreferencesPage(
            title=_t("Dispositivo", "Device"),
            icon_name="audio-card-symbolic",
        )
        self.add(page_dev)

        grp_id = Adw.PreferencesGroup(
            title=_t("Identidade na rede", "Network identity"),
            description=_t(
                "Como o Sonus aparece para o Dante Controller e outros equipamentos.",
                "How Sonus appears to Dante Controller and other devices.",
            ),
        )
        page_dev.add(grp_id)

        self._row_name = Adw.EntryRow(title=_t("Nome do dispositivo", "Device name"))
        self._row_name.set_text(self._cfg.get("device", {}).get("name", "SonusGrid-Virtual"))
        self._row_name.connect("notify::text", lambda *_: self._mark_dirty())
        grp_id.add(self._row_name)

        self._row_id = Adw.EntryRow(
            title=_t("Device ID (16 hex, vazio = auto)", "Device ID (16 hex, blank = auto)"),
        )
        self._row_id.set_text(self._cfg.get("device", {}).get("device_id", ""))
        self._row_id.connect("notify::text", lambda *_: self._mark_dirty())
        grp_id.add(self._row_id)

        # --- Audio format ----------------------------------------------------
        grp_aud = Adw.PreferencesGroup(
            title=_t("Formato de áudio", "Audio format"),
            description=_t(
                "Igual à rede Dante (toda a rede precisa estar no mesmo sample rate).",
                "Match the Dante network (all devices must share the sample rate).",
            ),
        )
        page_dev.add(grp_aud)

        self._row_rate = Adw.ComboRow(title=_t("Sample rate", "Sample rate"))
        rates = ["44100", "48000", "88200", "96000", "176400", "192000"]
        rate_model = Gtk.StringList.new(rates)
        self._row_rate.set_model(rate_model)
        cur_rate = str(self._cfg.get("device", {}).get("sample_rate", 48000))
        self._row_rate.set_selected(rates.index(cur_rate) if cur_rate in rates else 1)
        self._row_rate.connect("notify::selected", lambda *_: self._mark_dirty())
        grp_aud.add(self._row_rate)

        self._row_rx = Adw.SpinRow.new_with_range(0, 64, 1)
        self._row_rx.set_title(_t("Canais RX", "RX channels"))
        self._row_rx.set_subtitle(_t("Quantos canais aparecem como entrada", "How many channels appear as inputs"))
        self._row_rx.set_value(self._cfg.get("device", {}).get("rx_channels", 16))
        self._row_rx.connect("changed", lambda *_: self._mark_dirty())
        grp_aud.add(self._row_rx)

        self._row_tx = Adw.SpinRow.new_with_range(0, 64, 1)
        self._row_tx.set_title(_t("Canais TX", "TX channels"))
        self._row_tx.set_subtitle(_t("Quantos canais aparecem como saída", "How many channels appear as outputs"))
        self._row_tx.set_value(self._cfg.get("device", {}).get("tx_channels", 16))
        self._row_tx.connect("changed", lambda *_: self._mark_dirty())
        grp_aud.add(self._row_tx)

        # --- Latency ---------------------------------------------------------
        grp_lat = Adw.PreferencesGroup(
            title=_t("Latência", "Latency"),
            description=_t(
                "Maior latência = mais imune a glitches. Padrão DVS Windows = 4 ms.",
                "Higher latency = fewer glitches. Windows DVS default = 4 ms.",
            ),
        )
        page_dev.add(grp_lat)

        self._row_rx_lat = Adw.SpinRow.new_with_range(0.5, 100.0, 0.5)
        self._row_rx_lat.set_title(_t("Latência RX (ms)", "RX latency (ms)"))
        self._row_rx_lat.set_digits(1)
        self._row_rx_lat.set_value(self._cfg.get("device", {}).get("rx_latency_ns", 4_000_000) / 1_000_000)
        self._row_rx_lat.connect("changed", lambda *_: self._mark_dirty())
        grp_lat.add(self._row_rx_lat)

        self._row_tx_lat = Adw.SpinRow.new_with_range(0.5, 100.0, 0.5)
        self._row_tx_lat.set_title(_t("Latência TX (ms)", "TX latency (ms)"))
        self._row_tx_lat.set_digits(1)
        self._row_tx_lat.set_value(self._cfg.get("device", {}).get("tx_latency_ns", 4_000_000) / 1_000_000)
        self._row_tx_lat.connect("changed", lambda *_: self._mark_dirty())
        grp_lat.add(self._row_tx_lat)

        # --- Page: Network ---------------------------------------------------
        page_net = Adw.PreferencesPage(
            title=_t("Rede", "Network"),
            icon_name="network-wired-symbolic",
        )
        self.add(page_net)

        grp_iface = Adw.PreferencesGroup(
            title=_t("Interface de rede", "Network interface"),
            description=_t(
                "Qual NIC é usada para o tráfego Dante (PTP + RTP + descoberta).",
                "Which NIC carries Dante traffic (PTP + RTP + discovery).",
            ),
        )
        page_net.add(grp_iface)

        ifaces = _list_interfaces()
        self._row_iface = Adw.ComboRow(title=_t("Interface", "Interface"))
        labels = ifaces or [_t("(nenhuma)", "(none)")]
        self._row_iface.set_model(Gtk.StringList.new(labels))
        cur_iface = self._cfg.get("network", {}).get("interface", "")
        if cur_iface in ifaces:
            self._row_iface.set_selected(ifaces.index(cur_iface))
        elif ifaces:
            self._row_iface.set_selected(0)
        self._row_iface.connect("notify::selected", lambda *_: self._mark_dirty())
        grp_iface.add(self._row_iface)
        self._iface_options = ifaces

        self._row_bind = Adw.EntryRow(
            title=_t("Bind IP (vazio = igual interface)", "Bind IP (blank = same as interface)"),
        )
        self._row_bind.set_text(self._cfg.get("network", {}).get("bind_ip", ""))
        self._row_bind.connect("notify::text", lambda *_: self._mark_dirty())
        grp_iface.add(self._row_bind)

        # --- Page: Clock -----------------------------------------------------
        page_clk = Adw.PreferencesPage(
            title=_t("Relógio (PTP)", "Clock (PTP)"),
            icon_name="alarm-symbolic",
        )
        self.add(page_clk)

        grp_clk = Adw.PreferencesGroup(
            title=_t("Sincronização de tempo", "Time sync"),
            description=_t(
                "Dante usa PTPv1; AES67 usa PTPv2. Defina conforme o resto da rede.",
                "Dante uses PTPv1; AES67 uses PTPv2. Match the rest of the network.",
            ),
        )
        page_clk.add(grp_clk)

        self._row_ptp = Adw.ComboRow(title=_t("Versão PTP", "PTP version"))
        ptp_versions = ["v1", "v2"]
        self._row_ptp.set_model(Gtk.StringList.new(ptp_versions))
        cur_ptp = self._cfg.get("ptp", {}).get("version", "v1")
        self._row_ptp.set_selected(ptp_versions.index(cur_ptp) if cur_ptp in ptp_versions else 0)
        self._row_ptp.connect("notify::selected", lambda *_: self._mark_dirty())
        grp_clk.add(self._row_ptp)

        self._row_domain = Adw.SpinRow.new_with_range(0, 127, 1)
        self._row_domain.set_title(_t("Domínio PTP", "PTP domain"))
        self._row_domain.set_value(self._cfg.get("ptp", {}).get("domain", 0))
        self._row_domain.connect("changed", lambda *_: self._mark_dirty())
        grp_clk.add(self._row_domain)

        self._row_priority = Adw.SpinRow.new_with_range(0, 255, 1)
        self._row_priority.set_title(_t("Priority1", "Priority1"))
        self._row_priority.set_subtitle(_t(
            "Menor = vira master mais facilmente. Hardware Dante = 249.",
            "Lower = more likely to become master. Dante hardware = 249.",
        ))
        self._row_priority.set_value(self._cfg.get("ptp", {}).get("priority1", 251))
        self._row_priority.connect("changed", lambda *_: self._mark_dirty())
        grp_clk.add(self._row_priority)

        self._row_hwclock = Adw.EntryRow(
            title=_t("Hardware clock (auto/sw/path)", "Hardware clock (auto/sw/path)"),
        )
        self._row_hwclock.set_text(self._cfg.get("ptp", {}).get("hardware_clock", "auto"))
        self._row_hwclock.connect("notify::text", lambda *_: self._mark_dirty())
        grp_clk.add(self._row_hwclock)

        # --- Page: Bridge ----------------------------------------------------
        page_br = Adw.PreferencesPage(
            title=_t("Ponte de áudio", "Audio bridge"),
            icon_name="audio-volume-high-symbolic",
        )
        self.add(page_br)

        grp_br = Adw.PreferencesGroup(
            title=_t("Como o áudio do sistema chega aos canais TX", "How OS audio reaches TX channels"),
            description=_t(
                "null-sink: PipeWire mostra um sink 'Sonus' para os apps mandarem áudio.\n"
                "none: você abre o device ALSA 'sonus' direto (DAW).",
                "null-sink: PipeWire exposes a 'Sonus' sink for apps to target.\n"
                "none: open the ALSA 'sonus' device directly (DAW use).",
            ),
        )
        page_br.add(grp_br)

        self._row_mode = Adw.ComboRow(title=_t("Modo da ponte", "Bridge mode"))
        modes = ["null-sink", "none"]
        self._row_mode.set_model(Gtk.StringList.new(modes))
        cur_mode = self._cfg.get("bridge", {}).get("mode", "null-sink")
        self._row_mode.set_selected(modes.index(cur_mode) if cur_mode in modes else 0)
        self._row_mode.connect("notify::selected", lambda *_: self._mark_dirty())
        grp_br.add(self._row_mode)

        self._row_sink = Adw.EntryRow(
            title=_t("Nome do sink no PipeWire", "PipeWire sink name"),
        )
        self._row_sink.set_text(self._cfg.get("bridge", {}).get("sink_name", "Sonus"))
        self._row_sink.connect("notify::text", lambda *_: self._mark_dirty())
        grp_br.add(self._row_sink)

        self._row_relay = Adw.SpinRow.new_with_range(2, 64, 2)
        self._row_relay.set_title(_t("Canais relay (TX)", "Relay channels (TX)"))
        self._row_relay.set_subtitle(_t(
            "Quantos canais o ffmpeg upmixa do sink estéreo. Use 2 para clareza.",
            "How many channels ffmpeg upmixes from the stereo sink. Use 2 for clarity.",
        ))
        self._row_relay.set_value(self._cfg.get("bridge", {}).get("relay_channels", 16))
        self._row_relay.connect("changed", lambda *_: self._mark_dirty())
        grp_br.add(self._row_relay)

        # --- Footer: Save / Apply -------------------------------------------
        self._save_btn = Gtk.Button(label=_t("Salvar", "Save"))
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.connect("clicked", lambda *_: self._on_save())

        self._apply_btn = Gtk.Button(
            label=_t("Salvar e reiniciar Sonus", "Save & restart Sonus"),
        )
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.connect("clicked", lambda *_: self._on_save_restart())

        # Add buttons to the header bar via a Gtk.HeaderBar surface.
        # AdwPreferencesWindow uses an internal toolbar; place buttons in title.
        # Simplest robust approach: an action page with the buttons.
        action_page = Adw.PreferencesPage(
            title=_t("Salvar", "Save"), icon_name="document-save-symbolic",
        )
        action_grp = Adw.PreferencesGroup()
        action_page.add(action_grp)
        save_row = Adw.ActionRow(
            title=_t("Salvar alterações", "Save changes"),
            subtitle=_t(
                "Grava em ~/.config/sonusgrid/config.toml.",
                "Writes to ~/.config/sonusgrid/config.toml.",
            ),
        )
        save_row.add_suffix(self._save_btn)
        save_row.add_suffix(self._apply_btn)
        action_grp.add(save_row)
        self.add(action_page)

    # --- helpers ------------------------------------------------------------
    def _mark_dirty(self) -> None:
        self._dirty = True

    def _collect(self) -> dict:
        rates = ["44100", "48000", "88200", "96000", "176400", "192000"]
        ptp_versions = ["v1", "v2"]
        modes = ["null-sink", "none"]
        bind_text = self._row_bind.get_text().strip()
        idx = self._row_iface.get_selected()
        chosen_iface = (
            self._iface_options[idx] if 0 <= idx < len(self._iface_options) else ""
        )
        return {
            "schema_version": 1,
            "device": {
                "name": self._row_name.get_text() or "SonusGrid-Virtual",
                "device_id": self._row_id.get_text(),
                "sample_rate": int(rates[self._row_rate.get_selected()]),
                "rx_channels": int(self._row_rx.get_value()),
                "tx_channels": int(self._row_tx.get_value()),
                "rx_latency_ns": int(round(self._row_rx_lat.get_value() * 1_000_000)),
                "tx_latency_ns": int(round(self._row_tx_lat.get_value() * 1_000_000)),
            },
            "network": {
                "interface": chosen_iface,
                "bind_ip": bind_text,
            },
            "ptp": {
                "version": ptp_versions[self._row_ptp.get_selected()],
                "domain": int(self._row_domain.get_value()),
                "priority1": int(self._row_priority.get_value()),
                "hardware_clock": self._row_hwclock.get_text() or "auto",
            },
            "bridge": {
                "mode": modes[self._row_mode.get_selected()],
                "sink_name": self._row_sink.get_text() or "SonusGrid",
                "sink_description": self._cfg.get("bridge", {}).get(
                    "sink_description", "SonusGrid (Dante-compatible)"
                ),
                "relay_channels": int(self._row_relay.get_value()),
            },
            "ui": self._cfg.get("ui", {"language": "auto", "show_disclaimer_on_start": True}),
        }

    def _on_save(self) -> None:
        new_cfg = self._collect()
        try:
            _save_config(new_cfg)
        except Exception as exc:
            self._toast(_t(f"Erro ao salvar: {exc}", f"Save failed: {exc}"))
            return
        self._dirty = False
        self._toast(_t(
            "Salvo. Reinicie o Sonus para aplicar.",
            "Saved. Restart Sonus to apply.",
        ))

    def _on_save_restart(self) -> None:
        new_cfg = self._collect()
        try:
            _save_config(new_cfg)
        except Exception as exc:
            self._toast(_t(f"Erro ao salvar: {exc}", f"Save failed: {exc}"))
            return
        Gio.Subprocess.new(["sonusgrid", "restart"], Gio.SubprocessFlags.NONE)
        self._toast(_t("Salvo e reiniciando…", "Saved and restarting…"))
        self._dirty = False

    def _toast(self, msg: str) -> None:
        toast = Adw.Toast.new(msg)
        toast.set_timeout(3)
        self.add_toast(toast)
