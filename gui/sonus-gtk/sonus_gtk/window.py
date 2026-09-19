# SPDX-License-Identifier: GPL-3.0-or-later
"""SonusGrid main window — ViewStack layout (Status / Routing / Config / Tools).

Visual hierarchy:
- Header bar with Adw.ViewSwitcherTitle showing 4 pages.
- Page "Status": hero card + at-a-glance metrics.
- Page "Routing": basic native patchbay (active connections + disconnect) with
  fallback button to open qpwgraph for advanced graph editing.
- Page "Configuration": full form (device, network, sample rate, channels,
  latency, PTP, JACK toggle).
- Page "Tools": Mixer, qpwgraph, DAW guide, Doctor, Logs, Edit config, etc.

Inferno's name is internal-only. Everything user-visible is "SonusGrid".
"""

from __future__ import annotations

import json
import locale
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from sonus_gtk import status as st


CONFIG_PATH = Path.home() / ".config" / "sonusgrid" / "config.toml"


# ---------- helpers --------------------------------------------------------

def _is_pt() -> bool:
    return (locale.getlocale()[0] or "").startswith("pt")


def _t(pt: str, en: str) -> str:
    return pt if _is_pt() else en


def _list_interfaces_with_ip() -> list[tuple[str, str | None]]:
    """Return (name, ipv4) tuples for every up, non-virtual NIC."""
    try:
        out = subprocess.run(
            ["ip", "-j", "addr", "show"],
            capture_output=True, text=True, timeout=4,
        )
        if out.returncode != 0:
            return []
        result: list[tuple[str, str | None]] = []
        for entry in json.loads(out.stdout):
            n = entry.get("ifname", "")
            if n in ("lo",) or n.startswith(
                ("docker", "veth", "br-", "cvd-", "tailscale", "nat64", "lxcbr")
            ):
                continue
            ipv4 = None
            for addr in entry.get("addr_info", []):
                if addr.get("family") == "inet":
                    ipv4 = addr.get("local")
                    break
            result.append((n, ipv4))
        return result
    except Exception:
        return []


def _format_iface_label(name: str, ipv4: str | None) -> str:
    if ipv4:
        return f"{name}  ·  {ipv4}"
    return f"{name}  ·  " + _t("sem IP", "no IP")


try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

try:
    import tomli_w
    def _toml_dumps(d: dict) -> str: return tomli_w.dumps(d)
except ImportError:
    def _toml_dumps(d: dict) -> str:
        out: list[str] = []
        for section, val in d.items():
            if isinstance(val, dict):
                out.append(f"\n[{section}]")
                for k, v in val.items():
                    out.append(f"{k} = {_fmt(v)}")
            else:
                out.append(f"{section} = {_fmt(val)}")
        return "\n".join(out) + "\n"
    def _fmt(v) -> str:
        if isinstance(v, bool): return "true" if v else "false"
        if isinstance(v, str): return f'"{v}"'
        return str(v)


def _load_cfg() -> dict:
    if not CONFIG_PATH.exists():
        subprocess.run(["sonusgrid", "config", "init"], capture_output=True, timeout=10)
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _save_cfg(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_toml_dumps(cfg))


# ---------- custom CSS ----------------------------------------------------

# ---------- network meter widget ------------------------------------------

class NetworkMeter(Gtk.Box):
    """Compact RX/TX throughput display with rolling 60-sample sparklines.

    Reads /sys/class/net/<iface>/statistics/{rx_bytes,tx_bytes} at 1 Hz,
    computes per-second deltas, and renders two Cairo line graphs side by
    side with the live numeric value below each.
    """

    HISTORY = 60        # seconds of history kept
    HEIGHT  = 56        # px tall — keeps Status page compact
    PEAK_FLOOR = 65536  # bytes/s — minimum scale ceiling so silence isn't shown as "full"

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_start=14, margin_end=14,
            margin_top=4, margin_bottom=8,
        )
        self.add_css_class("sonusgrid-net-card")
        self._iface = ""
        self._rx_hist = [0.0] * self.HISTORY
        self._tx_hist = [0.0] * self.HISTORY
        self._last_rx = 0
        self._last_tx = 0
        self._first = True

        # RX side.
        self._rx_card = self._make_card(_t("Recebendo", "RX"), kind="rx")
        self.append(self._rx_card["box"])
        # TX side.
        self._tx_card = self._make_card(_t("Enviando", "TX"), kind="tx")
        self.append(self._tx_card["box"])

        GLib.timeout_add_seconds(1, self._tick)

    def set_interface(self, iface: str) -> None:
        if iface != self._iface:
            self._iface = iface
            self._rx_hist = [0.0] * self.HISTORY
            self._tx_hist = [0.0] * self.HISTORY
            self._last_rx = 0
            self._last_tx = 0
            self._first = True

    def _make_card(self, label: str, kind: str) -> dict:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                      hexpand=True)
        box.add_css_class("sonusgrid-net-side")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        arrow = Gtk.Image.new_from_icon_name(
            "go-down-symbolic" if kind == "rx" else "go-up-symbolic",
        )
        arrow.set_pixel_size(14)
        head.append(arrow)
        title = Gtk.Label(label=label, xalign=0.0)
        title.add_css_class("dim-label")
        title.add_css_class("caption")
        head.append(title)
        rate = Gtk.Label(label="—", xalign=1.0, hexpand=True)
        rate.add_css_class("heading")
        head.append(rate)
        box.append(head)

        spark = Gtk.DrawingArea()
        spark.set_content_height(self.HEIGHT)
        spark.set_hexpand(True)
        spark.set_draw_func(self._draw_spark, kind)
        spark.add_css_class("sonusgrid-net-spark")
        box.append(spark)
        return {"box": box, "rate_label": rate, "spark": spark}

    def _read_bytes(self) -> tuple[int, int] | None:
        if not self._iface:
            return None
        base = Path(f"/sys/class/net/{self._iface}/statistics")
        try:
            rx = int((base / "rx_bytes").read_text().strip())
            tx = int((base / "tx_bytes").read_text().strip())
            return (rx, tx)
        except Exception:
            return None

    def _tick(self) -> bool:
        sample = self._read_bytes()
        if sample is None:
            self._rx_card["rate_label"].set_label("—")
            self._tx_card["rate_label"].set_label("—")
            return True
        rx, tx = sample
        if self._first:
            self._last_rx = rx
            self._last_tx = tx
            self._first = False
            return True
        rx_rate = max(0, rx - self._last_rx)
        tx_rate = max(0, tx - self._last_tx)
        self._last_rx = rx
        self._last_tx = tx

        self._rx_hist.pop(0)
        self._rx_hist.append(float(rx_rate))
        self._tx_hist.pop(0)
        self._tx_hist.append(float(tx_rate))

        self._rx_card["rate_label"].set_label(self._format_rate(rx_rate))
        self._tx_card["rate_label"].set_label(self._format_rate(tx_rate))
        self._rx_card["spark"].queue_draw()
        self._tx_card["spark"].queue_draw()
        return True

    @staticmethod
    def _format_rate(bps: float) -> str:
        bps = bps * 8  # bytes → bits
        if bps < 1_000:
            return f"{int(bps)} bps"
        if bps < 1_000_000:
            return f"{bps/1_000:.1f} kbps"
        if bps < 1_000_000_000:
            return f"{bps/1_000_000:.1f} Mbps"
        return f"{bps/1_000_000_000:.2f} Gbps"

    def _draw_spark(self, area, cr, width, height, kind):
        hist = self._rx_hist if kind == "rx" else self._tx_hist
        peak = max(self.PEAK_FLOOR, max(hist) * 1.1)

        # Background.
        cr.set_source_rgba(1, 1, 1, 0.04)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        if peak <= 0 or len(hist) < 2:
            return

        n = len(hist)
        step = width / max(1, n - 1)

        # Filled area under the line for visual weight.
        if kind == "rx":
            r, g, b = 0.13, 0.59, 0.95   # blue
        else:
            r, g, b = 0.26, 0.63, 0.28   # green
        cr.set_source_rgba(r, g, b, 0.18)
        cr.move_to(0, height)
        for i, v in enumerate(hist):
            y = height - (v / peak) * (height - 4) - 2
            cr.line_to(i * step, y)
        cr.line_to(width, height)
        cr.close_path()
        cr.fill()

        # Line on top.
        cr.set_source_rgba(r, g, b, 0.95)
        cr.set_line_width(1.6)
        cr.set_line_join(1)  # ROUND
        for i, v in enumerate(hist):
            y = height - (v / peak) * (height - 4) - 2
            x = i * step
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()


_CSS = b"""
.sonusgrid-hero {
    background: linear-gradient(135deg,
        alpha(@accent_color, 0.18) 0%,
        alpha(@accent_color, 0.04) 100%);
    border-radius: 16px;
    border: 1px solid alpha(@accent_color, 0.22);
}
.sonusgrid-matrix-cell {
    min-width: 24px;
    min-height: 24px;
    padding: 0;
    margin: 1px;
    border-radius: 4px;
}
.sonusgrid-matrix-cell.connected {
    background: linear-gradient(135deg, #43a047, #1b5e20);
    color: white;
}
.sonusgrid-matrix-cell:not(.connected) {
    background: alpha(currentColor, 0.08);
}
.sonusgrid-matrix-header {
    font-size: 8pt;
    font-weight: 600;
    padding: 2px 4px;
}
.sonusgrid-matrix-row-label {
    font-size: 9pt;
    padding: 4px 8px 4px 0;
}
.sonusgrid-hero-title {
    font-weight: 700;
    font-size: 18pt;
}
.sonusgrid-glyph {
    border-radius: 999px;
    padding: 14px;
    background: linear-gradient(135deg, #7b1fa2 0%, #b71c4d 50%, #e53935 100%);
    color: #ffffff;
    box-shadow: 0 4px 12px alpha(#7b1fa2, 0.35);
}
.sonusgrid-glyph.off {
    background: linear-gradient(135deg, #5b6068 0%, #3a3d44 100%);
    box-shadow: none;
}
.sonusgrid-glyph.warn {
    background: linear-gradient(135deg, #ff9800 0%, #ef6c00 100%);
    box-shadow: 0 4px 12px alpha(#ef6c00, 0.35);
}
.sonusgrid-toggle {
    min-height: 36px;
    padding: 0 22px;
    font-weight: 600;
}
.sonusgrid-section-heading {
    font-weight: 600;
    margin-top: 4px;
    margin-bottom: 4px;
    opacity: 0.7;
}
.sonusgrid-stat-pill {
    background: alpha(@accent_color, 0.12);
    border-radius: 999px;
    padding: 4px 12px;
    font-weight: 600;
    font-size: 9pt;
}
.sonusgrid-page {
    padding: 12px;
}
.sonusgrid-net-card {
    background: alpha(@accent_color, 0.06);
    border-radius: 12px;
    border: 1px solid alpha(@accent_color, 0.16);
}
.sonusgrid-net-side {
    padding: 8px 10px;
}
.sonusgrid-net-spark {
    border-radius: 4px;
    background: alpha(currentColor, 0.04);
}
"""


def _install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


_CSS_INSTALLED = False


# ---------- hero card -----------------------------------------------------

class HeroCard(Gtk.Box):
    """Top status card with colored glyph and big toggle."""
    def __init__(self, on_toggle) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=14,
            margin_start=14, margin_end=14, margin_top=14, margin_bottom=14,
        )
        self.add_css_class("sonusgrid-hero")
        self._on_toggle = on_toggle

        self.glyph = Gtk.Image.new_from_icon_name("media-playback-stop-symbolic")
        self.glyph.set_pixel_size(32)
        self.glyph.add_css_class("sonusgrid-glyph")
        self.glyph.add_css_class("off")
        self.append(self.glyph)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.append(text_box)

        self.title = Gtk.Label(xalign=0.0, wrap=True)
        self.title.add_css_class("sonusgrid-hero-title")
        text_box.append(self.title)

        self.subtitle = Gtk.Label(xalign=0.0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        text_box.append(self.subtitle)

        self.toggle = Gtk.Button()
        self.toggle.add_css_class("pill")
        self.toggle.add_css_class("suggested-action")
        self.toggle.add_css_class("sonusgrid-toggle")
        self.toggle.set_valign(Gtk.Align.CENTER)
        self.toggle.connect("clicked", lambda *_: self._on_toggle())
        self.append(self.toggle)

    def set_state(self, state: str, title: str, subtitle: str) -> None:
        self.title.set_label(title)
        self.subtitle.set_label(subtitle)
        for css in ("off", "warn"):
            self.glyph.remove_css_class(css)
        for css in ("suggested-action", "destructive-action"):
            self.toggle.remove_css_class(css)
        if state == "on":
            self.glyph.set_from_icon_name("network-transmit-receive-symbolic")
            self.toggle.set_label(_t("Parar", "Stop"))
            self.toggle.add_css_class("destructive-action")
        elif state == "starting":
            self.glyph.set_from_icon_name("emblem-synchronizing-symbolic")
            self.glyph.add_css_class("warn")
            self.toggle.set_label(_t("Aguarde…", "Working…"))
        else:
            self.glyph.set_from_icon_name("media-playback-stop-symbolic")
            self.glyph.add_css_class("off")
            self.toggle.set_label(_t("Iniciar", "Start"))
            self.toggle.add_css_class("suggested-action")


# ---------- main window ---------------------------------------------------

class SonusWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        global _CSS_INSTALLED
        if not _CSS_INSTALLED:
            _install_css()
            _CSS_INSTALLED = True

        self.set_title("SonusGrid")
        # Sized to fit comfortably on 1366×768 laptops AND tiled half-screen
        # on 1080p with the GNOME shell panel visible. Resizable upward by
        # the user; the Configuration tab scrolls if the user makes the
        # window very small.
        self.set_default_size(740, 700)

        self._cfg = _load_cfg()
        self._dirty = False

        # Outer chrome.
        outer = Adw.ToolbarView()
        self.set_content(outer)

        header = Adw.HeaderBar()
        outer.add_top_bar(header)

        # ViewStack with switcher in the header (Adwaita "tabs").
        self._stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self._stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        header.pack_end(self._build_menu_button())

        self._toast = Adw.ToastOverlay()
        outer.set_content(self._toast)
        self._toast.set_child(self._stack)

        # Pages — 3 tabs (the matrix Routing experiment was retired in favor
        # of dedicated buttons on the Status page that launch qpwgraph +
        # pavucontrol — same patchbay everyone already knows).
        self._stack.add_titled_with_icon(
            self._build_status_page(),
            "status",
            _t("Estado", "Status"),
            "audio-card-symbolic",
        )
        self._stack.add_titled_with_icon(
            self._build_config_page(),
            "config",
            _t("Configuração", "Configuration"),
            "preferences-system-symbolic",
        )
        self._stack.add_titled_with_icon(
            self._build_tools_page(),
            "tools",
            _t("Ferramentas", "Tools"),
            "applications-utilities-symbolic",
        )

        # Status poller.
        GLib.idle_add(self._refresh)
        GLib.timeout_add_seconds(2, self._refresh)

    # ============================================================
    # PAGE: STATUS
    # ============================================================

    def _build_status_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=520)
        scroller.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.add_css_class("sonusgrid-page")
        clamp.set_child(body)

        self._hero = HeroCard(on_toggle=self._on_toggle)
        body.append(self._hero)

        # Big-button row: launch qpwgraph + pavucontrol from the front page.
        # If they aren't installed we show a dialog with the install command
        # for the detected distro instead of failing silently.
        body.append(self._section_label(_t("Roteamento de áudio",
                                           "Audio routing")))
        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                             homogeneous=True)
        button_row.append(self._make_launcher_button(
            tool="qpwgraph",
            label=_t("Roteador (qpwgraph)", "Router (qpwgraph)"),
            sub=_t("Patchbay visual JACK / PipeWire — pra DAWs.",
                   "Visual JACK / PipeWire patchbay — for DAWs."),
            icon="preferences-system-network-symbolic",
            packages={"apt": "qpwgraph", "dnf": "qpwgraph",
                      "pacman": "qpwgraph", "zypper": "qpwgraph"},
        ))
        button_row.append(self._make_launcher_button(
            tool="pavucontrol",
            label=_t("Mixer (pavucontrol)", "Mixer (pavucontrol)"),
            sub=_t("Roteador estilo PulseAudio. Destino por app.",
                   "PulseAudio-style mixer. Per-app destination."),
            icon="audio-volume-medium-symbolic",
            packages={"apt": "pavucontrol", "dnf": "pavucontrol",
                      "pacman": "pavucontrol", "zypper": "pavucontrol"},
        ))
        body.append(button_row)

        # Network throughput card (live sparklines).
        body.append(self._section_label(_t("Tráfego de rede", "Network throughput")))
        self._net_meter = NetworkMeter()
        body.append(self._net_meter)

        # At-a-glance metric pills (filled by _refresh).
        body.append(self._section_label(_t("Resumo", "Summary")))
        pill_box = Gtk.FlowBox(
            row_spacing=8, column_spacing=8,
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=2, max_children_per_line=4,
            homogeneous=True,
        )
        body.append(pill_box)
        self._pills: dict[str, Gtk.Label] = {}
        for key, label in [
            ("device",   _t("Dispositivo", "Device")),
            ("ptp",      _t("PTP",         "PTP")),
            ("nic",      _t("Interface",   "Interface")),
            ("ip",       _t("IP",          "IP")),
            ("inputs",   _t("Entradas",    "Inputs")),
            ("outputs",  _t("Saídas",      "Outputs")),
            ("rate",     _t("Sample rate", "Sample rate")),
            ("jack",     _t("JACK",        "JACK")),
        ]:
            row = self._make_pill(label)
            self._pills[key] = row[1]
            pill_box.append(row[0])

        return scroller

    # ---- Distro-aware launcher buttons -----------------------------------

    def _make_launcher_button(self, tool: str, label: str, sub: str,
                              icon: str, packages: dict[str, str]) -> Gtk.Widget:
        """A big tile that launches `tool` if installed, otherwise shows the
        right install command for the detected distro."""
        btn = Gtk.Button()
        btn.add_css_class("card")
        btn.set_has_frame(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                        margin_start=12, margin_end=12,
                        margin_top=10, margin_bottom=10)
        btn.set_child(inner)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ic = Gtk.Image.new_from_icon_name(icon)
        ic.set_pixel_size(22)
        top.append(ic)
        title = Gtk.Label(label=label, xalign=0.0, hexpand=True)
        title.add_css_class("heading")
        top.append(title)
        inner.append(top)
        s = Gtk.Label(label=sub, xalign=0.0, wrap=True)
        s.add_css_class("dim-label")
        s.add_css_class("caption")
        inner.append(s)
        btn.connect("clicked",
                    lambda *_: self._launch_or_install(tool, label, packages))
        return btn

    def _launch_or_install(self, tool: str, label: str,
                           packages: dict[str, str]) -> None:
        try:
            subprocess.Popen([tool])
            return
        except FileNotFoundError:
            pass

        # Tool missing — present the right install command.
        pm, pkg = self._detect_package_manager(packages)
        if pm is None:
            self._notify(_t(
                f"{tool} não está instalado e não detectei seu gerenciador "
                f"de pacotes. Instale manualmente.",
                f"{tool} is not installed and your package manager wasn't "
                f"detected. Install manually.",
            ))
            return

        cmd = self._install_command_for(pm, pkg)
        dlg = Adw.MessageDialog(
            transient_for=self,
            heading=_t(f"{label} não está instalado",
                       f"{label} is not installed"),
            body=_t(
                f"Para instalar, copie e cole no terminal:\n\n    {cmd}\n",
                f"To install, copy and paste in a terminal:\n\n    {cmd}\n",
            ),
        )
        dlg.add_response("copy", _t("Copiar comando", "Copy command"))
        dlg.add_response("close", _t("Fechar", "Close"))
        dlg.set_default_response("copy")

        def on_response(_dlg, resp):
            if resp == "copy":
                clipboard = Gdk.Display.get_default().get_clipboard()
                clipboard.set(cmd)
                self._notify(_t("Comando copiado.", "Command copied."))
        dlg.connect("response", on_response)
        dlg.present()

    @staticmethod
    def _detect_package_manager(packages: dict[str, str]) -> tuple[str | None, str | None]:
        # Read /etc/os-release ID + ID_LIKE.
        ids: list[str] = []
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if k == "ID":
                        ids.append(v)
                    elif k == "ID_LIKE":
                        ids.extend(v.split())
        except Exception:
            pass

        for ident in ids:
            if ident in ("debian", "ubuntu", "linuxmint", "pop", "elementary",
                         "kali", "raspbian"):
                return ("apt", packages.get("apt"))
            if ident in ("fedora", "rhel", "centos", "rocky", "alma"):
                return ("dnf", packages.get("dnf"))
            if ident in ("arch", "manjaro", "endeavouros", "garuda"):
                return ("pacman", packages.get("pacman"))
            if ident in ("opensuse", "suse", "opensuse-leap", "opensuse-tumbleweed"):
                return ("zypper", packages.get("zypper"))

        # Fallback: probe binaries.
        for pm in ("apt", "dnf", "pacman", "zypper"):
            try:
                if subprocess.run(["command", "-v", pm], capture_output=True,
                                  shell=False, timeout=2).returncode == 0:
                    return (pm, packages.get(pm))
            except Exception:
                pass
            try:
                # `which` works on essentially everything.
                if subprocess.run(["which", pm], capture_output=True,
                                  timeout=2).returncode == 0:
                    return (pm, packages.get(pm))
            except Exception:
                pass

        return (None, None)

    @staticmethod
    def _install_command_for(pm: str, pkg: str | None) -> str:
        if not pkg:
            return f"# pacote desconhecido para {pm}"
        if pm == "apt":
            return f"sudo apt update && sudo apt install -y {pkg}"
        if pm == "dnf":
            return f"sudo dnf install -y {pkg}"
        if pm == "pacman":
            return f"sudo pacman -S --needed {pkg}"
        if pm == "zypper":
            return f"sudo zypper install -y {pkg}"
        return f"sudo {pm} install {pkg}"

    def _make_pill(self, title: str) -> tuple[Gtk.Widget, Gtk.Label]:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                      margin_start=10, margin_end=10, margin_top=8, margin_bottom=8)
        box.add_css_class("sonusgrid-stat-pill")
        t = Gtk.Label(label=title, xalign=0.0)
        t.add_css_class("dim-label")
        t.add_css_class("caption")
        v = Gtk.Label(label="—", xalign=0.0, wrap=True, ellipsize=3)
        v.add_css_class("heading")
        box.append(t)
        box.append(v)
        return (box, v)

    # ============================================================
    # PAGE: CONFIGURATION
    # ============================================================

    def _build_config_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=520)
        scroller.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.add_css_class("sonusgrid-page")
        clamp.set_child(body)

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)

        dev = self._cfg.get("device", {})
        net = self._cfg.get("network", {})
        bridge = self._cfg.get("bridge", {})

        # 1. Device name
        self._name_row = Adw.EntryRow(title=_t("Nome do dispositivo", "Device name"))
        self._name_row.set_text(dev.get("name", "SonusGrid-Virtual"))
        self._name_row.connect("notify::text", lambda *_: self._mark_dirty())
        listbox.append(self._name_row)

        # 2. Interface — IP-aware, MANDATORY.
        self._ifaces = _list_interfaces_with_ip()
        labels = [_format_iface_label(n, ip) for n, ip in self._ifaces]
        if not self._ifaces:
            labels = [_t("(nenhuma interface encontrada)", "(no interfaces found)")]
        self._iface_row = Adw.ComboRow(
            title=_t("Interface de rede", "Network interface"),
            subtitle=_t(
                "Obrigatório — selecione a NIC que conecta ao switch Dante.",
                "Required — pick the NIC connected to the Dante switch.",
            ),
        )
        self._iface_row.set_model(Gtk.StringList.new(labels))
        cur = net.get("interface", "")
        sel = next((i for i, (n, _) in enumerate(self._ifaces) if n == cur), -1)
        if sel >= 0:
            self._iface_row.set_selected(sel)
        else:
            self._iface_row.set_selected(0)
            if cur:
                self._iface_row.set_subtitle(_t(
                    f"Interface anterior '{cur}' não está mais disponível.",
                    f"Previously saved '{cur}' is no longer available.",
                ))
            self._dirty = True
        self._iface_row.connect("notify::selected", lambda *_: self._mark_dirty())
        listbox.append(self._iface_row)

        # 3. Sample rate
        rates = ["44100", "48000", "88200", "96000", "176400", "192000"]
        self._rate_row = Adw.ComboRow(title=_t("Sample rate", "Sample rate"))
        self._rate_row.set_model(Gtk.StringList.new(rates))
        cur_rate = str(dev.get("sample_rate", 48000))
        self._rate_row.set_selected(rates.index(cur_rate) if cur_rate in rates else 1)
        self._rate_row.connect("notify::selected", lambda *_: self._mark_dirty())
        listbox.append(self._rate_row)

        # 4. Latency
        self._lat_row = Adw.SpinRow.new_with_range(0.5, 100.0, 0.5)
        self._lat_row.set_title(_t("Latência (ms)", "Latency (ms)"))
        self._lat_row.set_subtitle(_t(
            "Aplicada em RX e TX. Maior = mais imune a glitches.",
            "Applied to RX and TX. Higher = more glitch-resistant.",
        ))
        self._lat_row.set_digits(1)
        self._lat_row.set_value(dev.get("rx_latency_ns", 4_000_000) / 1_000_000)
        self._lat_row.connect("changed", lambda *_: self._mark_dirty())
        listbox.append(self._lat_row)

        # 5. Inputs (was RX channels).
        self._rx_row = Adw.SpinRow.new_with_range(0, 256, 1)
        self._rx_row.set_title(_t(
            "Entradas (do Dante)",
            "Inputs (from Dante)",
        ))
        self._rx_row.set_subtitle(_t(
            "Canais que apps Linux podem GRAVAR da rede Dante.",
            "Channels Linux apps can RECORD from the Dante network.",
        ))
        self._rx_row.set_value(dev.get("rx_channels", 16))
        self._rx_row.connect("changed", lambda *_: self._mark_dirty())
        listbox.append(self._rx_row)

        # 6. Outputs (was TX channels).
        self._tx_row = Adw.SpinRow.new_with_range(0, 256, 1)
        self._tx_row.set_title(_t(
            "Saídas (para Dante)",
            "Outputs (to Dante)",
        ))
        self._tx_row.set_subtitle(_t(
            "Canais que apps Linux podem TOCAR para a rede Dante.",
            "Channels Linux apps can PLAY to the Dante network.",
        ))
        self._tx_row.set_value(dev.get("tx_channels", 16))
        self._tx_row.connect("changed", lambda *_: self._mark_dirty())
        listbox.append(self._tx_row)

        # 7. PTP version
        ptp_versions = ["v1", "v2"]
        self._ptp_row = Adw.ComboRow(title=_t("Versão PTP", "PTP version"))
        self._ptp_row.set_model(Gtk.StringList.new(ptp_versions))
        cur_ptp = self._cfg.get("ptp", {}).get("version", "v1")
        self._ptp_row.set_selected(ptp_versions.index(cur_ptp) if cur_ptp in ptp_versions else 0)
        self._ptp_row.connect("notify::selected", lambda *_: self._mark_dirty())
        listbox.append(self._ptp_row)

        # 8. JACK toggle.
        self._jack_switch = Adw.SwitchRow(
            title=_t("Cliente JACK (DAW)", "JACK client (DAW)"),
            subtitle=_t(
                "Expõe SonusGrid como cliente JACK com tx_NN/rx_NN para Reaper, "
                "Ardour, Bitwig. Desligue se você não usa DAW.",
                "Exposes SonusGrid as a JACK client with tx_NN/rx_NN for Reaper, "
                "Ardour, Bitwig. Turn off if you don't use a DAW.",
            ),
        )
        self._jack_switch.set_active(bridge.get("jack_enabled", True))
        self._jack_switch.connect("notify::active", lambda *_: self._mark_dirty())
        listbox.append(self._jack_switch)

        # 9. JACK buffer / quantum (live — applies via pw-metadata, no restart).
        buffer_options = ["64", "128", "256", "512", "1024"]
        self._buffer_row = Adw.ComboRow(
            title=_t("Buffer JACK / quantum (frames)",
                     "JACK buffer / quantum (frames)"),
            subtitle=_t(
                "Aplica ao vivo via pw-metadata. Menor = menos latência, "
                "mais sensível a xruns. 256 ≈ 5.3 ms a 48 kHz.",
                "Live-applied via pw-metadata. Lower = lower latency, more "
                "xrun-prone. 256 ≈ 5.3 ms at 48 kHz.",
            ),
        )
        self._buffer_row.set_model(Gtk.StringList.new(buffer_options))
        cur_q = self._read_pw_quantum()
        self._buffer_row.set_selected(
            buffer_options.index(str(cur_q)) if str(cur_q) in buffer_options else 2
        )
        self._buffer_row.connect("notify::selected",
                                 lambda *_: self._on_buffer_changed(buffer_options))
        listbox.append(self._buffer_row)

        body.append(listbox)

        # Apply button.
        apply_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10, halign=Gtk.Align.END,
        )
        self._apply_btn = Gtk.Button(label=_t("Aplicar", "Apply"))
        self._apply_btn.add_css_class("pill")
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.add_css_class("sonusgrid-toggle")
        self._apply_btn.connect("clicked", lambda *_: self._apply_config())
        apply_box.append(self._apply_btn)
        body.append(apply_box)

        return scroller

    # ============================================================
    # PAGE: TOOLS
    # ============================================================

    def _build_tools_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=520)
        scroller.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.add_css_class("sonusgrid-page")
        clamp.set_child(body)

        # Group 1: routing & mixers.
        body.append(self._section_label(_t("Mixers e roteadores", "Mixers and routers")))
        listbox1 = Gtk.ListBox()
        listbox1.add_css_class("boxed-list")
        listbox1.set_selection_mode(Gtk.SelectionMode.NONE)
        for title, sub, icon, cb in [
            (
                _t("Mixer (pavucontrol — legado)",
                   "Mixer (pavucontrol — legacy)"),
                _t("Roteador estilo PulseAudio. Use pra escolher destino por app.",
                   "PulseAudio-style mixer. Pick per-app destination here."),
                "audio-volume-medium-symbolic",
                lambda: subprocess.Popen(["pavucontrol"]),
            ),
            (
                _t("Roteamento avançado (qpwgraph — legado)",
                   "Advanced router (qpwgraph — legacy)"),
                _t("Patchbay visual JACK / PipeWire — pra DAWs.",
                   "Visual JACK / PipeWire patchbay — for DAWs."),
                "preferences-system-network-symbolic",
                self._open_router,
            ),
        ]:
            row = Adw.ActionRow(title=title, subtitle=sub, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda *_a, fn=cb: fn())
            listbox1.append(row)
        body.append(listbox1)

        # Group 2: documentation.
        body.append(self._section_label(_t("Documentação", "Documentation")))
        listbox2 = Gtk.ListBox()
        listbox2.add_css_class("boxed-list")
        listbox2.set_selection_mode(Gtk.SelectionMode.NONE)
        for title, sub, icon, cb in [
            (
                _t("Guia DAW (low-latency)", "DAW guide (low-latency)"),
                _t("Setup Reaper / Ardour / Bitwig + kernel RT.",
                   "Setup Reaper / Ardour / Bitwig + RT kernel."),
                "applications-multimedia-symbolic",
                self._open_daw_guide,
            ),
            (
                _t("Guia do Usuário", "User guide"),
                _t("Operação dia-a-dia, conceitos, troubleshooting.",
                   "Daily operation, concepts, troubleshooting."),
                "help-about-symbolic",
                self._open_docs,
            ),
        ]:
            row = Adw.ActionRow(title=title, subtitle=sub, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda *_a, fn=cb: fn())
            listbox2.append(row)
        body.append(listbox2)

        # Group 3: diagnostics & advanced.
        body.append(self._section_label(_t("Diagnóstico e avançado",
                                           "Diagnostics and advanced")))
        listbox3 = Gtk.ListBox()
        listbox3.add_css_class("boxed-list")
        listbox3.set_selection_mode(Gtk.SelectionMode.NONE)
        for title, sub, icon, cb in [
            (
                _t("Criar atalhos para DAWs (JACK)",
                   "Create DAW launchers (JACK)"),
                _t("Detecta Reaper, Ardour, Bitwig, Mixbus instalados e cria "
                   "um atalho no menu pra cada um, lançando via pw-jack.",
                   "Detects installed Reaper, Ardour, Bitwig, Mixbus and "
                   "creates a menu launcher for each, via pw-jack."),
                "list-add-symbolic",
                self._setup_daw_launchers,
            ),
            (
                _t("Diagnóstico", "Diagnostics"),
                _t("Checagens bilíngues PT/EN com remediação.",
                   "Bilingual checks with remediation."),
                "emblem-system-symbolic",
                self._show_doctor,
            ),
            (
                _t("Ver logs", "View logs"),
                _t("Tail das user services (clock + audio).",
                   "Tail user services (clock + audio)."),
                "view-list-symbolic",
                self._show_logs,
            ),
            (
                _t("Editar config.toml", "Edit config.toml"),
                _t(f"Arquivo cru em {CONFIG_PATH}",
                   f"Raw file at {CONFIG_PATH}"),
                "text-x-generic-symbolic",
                self._edit_conf,
            ),
        ]:
            row = Adw.ActionRow(title=title, subtitle=sub, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda *_a, fn=cb: fn())
            listbox3.append(row)
        body.append(listbox3)

        return scroller

    def _section_label(self, text: str) -> Gtk.Widget:
        lbl = Gtk.Label(label=text, xalign=0.0)
        lbl.add_css_class("sonusgrid-section-heading")
        lbl.add_css_class("heading")
        return lbl

    # ============================================================
    # MENU + actions
    # ============================================================

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu.new()
        menu.append(_t("Roteador de áudio (qpwgraph)", "Audio router (qpwgraph)"), "app.router")
        menu.append(_t("Guia DAW", "DAW guide"), "app.daw-guide")
        menu.append(_t("Documentação", "Documentation"), "app.docs")
        menu.append(_t("Editar config.toml", "Edit config.toml"), "app.edit-conf")
        menu.append(_t("Preferências completas", "Full preferences"), "app.preferences")
        menu.append(_t("Sobre o SonusGrid", "About SonusGrid"), "app.about")

        for name, fn in [
            ("preferences", self._show_preferences),
            ("edit-conf", self._edit_conf),
            ("router", self._open_router),
            ("daw-guide", self._open_daw_guide),
            ("docs", self._open_docs),
            ("about", self._show_about),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, f=fn: f())
            app = self.get_application() or self.props.application
            if app is not None:
                app.add_action(action)

        btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        btn.set_menu_model(menu)
        return btn

    # ============================================================
    # CONFIG handling
    # ============================================================

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _selected_iface(self) -> str:
        if not self._ifaces:
            return ""
        idx = self._iface_row.get_selected()
        if 0 <= idx < len(self._ifaces):
            return self._ifaces[idx][0]
        return ""

    def _selected_iface_ip(self) -> str:
        if not self._ifaces:
            return ""
        idx = self._iface_row.get_selected()
        if 0 <= idx < len(self._ifaces):
            return self._ifaces[idx][1] or ""
        return ""

    def _collect(self) -> dict:
        rates = ["44100", "48000", "88200", "96000", "176400", "192000"]
        ptp_versions = ["v1", "v2"]
        lat_ns = int(round(self._lat_row.get_value() * 1_000_000))
        existing = self._cfg
        chosen_iface = self._selected_iface()
        chosen_ip = self._selected_iface_ip()
        existing_bridge = existing.get("bridge", {})
        cfg = {
            "schema_version": 1,
            "device": {
                "name": self._name_row.get_text() or "SonusGrid-Virtual",
                "device_id": existing.get("device", {}).get("device_id", ""),
                "sample_rate": int(rates[self._rate_row.get_selected()]),
                "rx_channels": int(self._rx_row.get_value()),
                "tx_channels": int(self._tx_row.get_value()),
                "rx_latency_ns": lat_ns,
                "tx_latency_ns": lat_ns,
            },
            "network": {
                "interface": chosen_iface,
                "bind_ip": chosen_ip,
            },
            "ptp": {
                "version": ptp_versions[self._ptp_row.get_selected()],
                "domain": existing.get("ptp", {}).get("domain", 0),
                "priority1": existing.get("ptp", {}).get("priority1", 251),
                "hardware_clock": existing.get("ptp", {}).get("hardware_clock", "auto"),
            },
            "bridge": {
                "mode": existing_bridge.get("mode", "null-sink"),
                "sink_name": existing_bridge.get("sink_name", "SonusGrid"),
                "sink_description": existing_bridge.get(
                    "sink_description", "SonusGrid (Dante-compatible)"),
                "relay_channels": int(self._tx_row.get_value()),
                "jack_enabled": self._jack_switch.get_active(),
            },
            "ui": existing.get("ui", {"language": "auto", "show_disclaimer_on_start": True}),
        }
        return cfg

    def _read_pw_quantum(self) -> int:
        """Read the current PipeWire forced quantum, fallback to 256."""
        try:
            r = subprocess.run(
                ["pw-metadata", "-n", "settings", "0", "clock.force-quantum"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                # Output looks like:
                #   update: id:0 key:'clock.force-quantum' value:'256' type:''
                for line in r.stdout.splitlines():
                    if "value:" in line and "clock.force-quantum" in line:
                        v = line.split("value:")[1].strip()
                        v = v.strip("'\"").split()[0]
                        try:
                            n = int(v)
                            if n > 0:
                                return n
                        except ValueError:
                            pass
        except Exception:
            pass
        # Fallback: read default.clock.quantum
        try:
            r = subprocess.run(
                ["pw-metadata", "-n", "settings", "0", "clock.quantum"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if "value:" in line:
                        v = line.split("value:")[1].strip().strip("'\"").split()[0]
                        try:
                            return int(v)
                        except ValueError:
                            pass
        except Exception:
            pass
        return 256

    def _on_buffer_changed(self, options: list[str]) -> None:
        idx = self._buffer_row.get_selected()
        if not (0 <= idx < len(options)):
            return
        chosen = options[idx]

        # 1. Live: pw-metadata for the running session.
        try:
            r = subprocess.run(
                ["pw-metadata", "-n", "settings", "0",
                 "clock.force-quantum", chosen],
                capture_output=True, text=True, timeout=4,
            )
            if r.returncode != 0:
                self._notify(_t(
                    f"Falha: {r.stderr.strip()}",
                    f"Failed: {r.stderr.strip()}",
                ))
                return
        except Exception as exc:
            self._notify(_t(f"Erro: {exc}", f"Error: {exc}"))
            return

        # 2. Persist: write a drop-in to PipeWire user config so the choice
        #    survives reboots and PipeWire restarts. PipeWire reads
        #    ~/.config/pipewire/pipewire.conf.d/*.conf at startup.
        conf_dir = Path.home() / ".config" / "pipewire" / "pipewire.conf.d"
        try:
            conf_dir.mkdir(parents=True, exist_ok=True)
            (conf_dir / "99-sonusgrid-lowlatency.conf").write_text(
                "# SonusGrid buffer profile — managed by GUI; safe to edit.\n"
                "context.properties = {\n"
                f"    default.clock.rate          = 48000\n"
                f"    default.clock.quantum       = {chosen}\n"
                f"    default.clock.min-quantum   = {chosen}\n"
                f"    default.clock.max-quantum   = 1024\n"
                f"    default.clock.allowed-rates = [ 48000 96000 ]\n"
                "}\n"
            )
        except Exception as exc:
            self._notify(_t(
                f"Aplicado mas não persistido: {exc}",
                f"Applied but not persisted: {exc}",
            ))
            return

        latency_ms = int(chosen) / 48.0
        self._notify(_t(
            f"Buffer JACK = {chosen} frames (~{latency_ms:.1f} ms a 48 kHz). "
            "Sobrevive a reboot.",
            f"JACK buffer = {chosen} frames (~{latency_ms:.1f} ms at 48 kHz). "
            "Survives reboot.",
        ))

    def _apply_config(self) -> None:
        new_cfg = self._collect()
        if not new_cfg["network"]["interface"]:
            self._notify(_t(
                "Selecione uma interface de rede primeiro.",
                "Pick a network interface first.",
            ))
            return
        try:
            _save_cfg(new_cfg)
        except Exception as exc:
            self._notify(_t(f"Erro: {exc}", f"Error: {exc}"))
            return
        self._cfg = new_cfg
        self._dirty = False
        self._notify(_t("Aplicado. Reiniciando…", "Applied. Restarting…"))
        Gio.Subprocess.new(["sonusgrid", "restart"], Gio.SubprocessFlags.NONE)

    def _on_toggle(self) -> None:
        s = st.fetch()
        running = s is not None and s.overall in ("ok", "partial")
        verb = "stop" if running else "start"

        if not running:
            cfg = _load_cfg()
            if not cfg.get("network", {}).get("interface"):
                self._notify(_t(
                    "Selecione uma interface de rede e clique Aplicar antes de iniciar.",
                    "Pick a network interface and click Apply before starting.",
                ))
                return

        self._hero.toggle.set_sensitive(False)
        self._hero.set_state(
            "starting",
            _t("Iniciando…", "Starting…") if verb == "start" else _t("Parando…", "Stopping…"),
            _t("Aguarde.", "Please wait."),
        )

        # `sonusgrid start` can legitimately take a while (it waits for the
        # NIC and verifies both services). Run it off the UI thread and
        # surface the CLI's own message — earlier versions ran it inline,
        # froze the window and silently ignored failures.
        def worker() -> None:
            try:
                p = subprocess.run(
                    ["sonusgrid", verb], capture_output=True, text=True, timeout=60,
                )
                rc, out, err = p.returncode, p.stdout, p.stderr
            except subprocess.TimeoutExpired:
                rc, out, err = 124, "", "timeout"
            except FileNotFoundError:
                rc, out, err = 127, "", "sonusgrid CLI not found"
            GLib.idle_add(finish, rc, out, err)

        def finish(rc: int, out: str, err: str) -> bool:
            self._hero.toggle.set_sensitive(True)
            if rc != 0:
                text = (err or out).strip().splitlines()
                # Keep the last meaningful line for the toast; the full log
                # is one click away in Tools → Logs.
                last = next((l for l in reversed(text) if l.strip()), "")
                self._notify(_t(
                    f"Falha ao {'iniciar' if verb == 'start' else 'parar'}: {last}",
                    f"Failed to {verb}: {last}",
                ))
            self._refresh()
            return False

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # Periodic refresh of status pills + hero
    # ============================================================

    def _refresh(self) -> bool:
        s = st.fetch()
        if s is None:
            self._hero.set_state(
                "off",
                _t("CLI sonusgrid não encontrada", "sonusgrid CLI not found"),
                _t("Verifique a instalação.", "Check the installation."),
            )
            return True

        if s.overall == "ok":
            audio_word = (
                _t("sink + JACK ativos", "sink + JACK active")
                if s.jack_active
                else _t("sink ativo (JACK off)", "sink active (JACK off)")
            )
            sub = (
                _t("PTP ", "PTP ") + s.ptp_version
                + "  ·  "
                + _t("interface ", "interface ") + (s.interface or "—")
                + "  ·  "
                + audio_word
            )
            self._hero.set_state(
                "on",
                (s.device_name or "SonusGrid") + "  ·  " + _t("Conectado", "Running"),
                sub,
            )
        elif s.overall == "partial":
            self._hero.set_state(
                "starting",
                _t("Inicializando…", "Starting…"),
                _t("Aguardando PTP/áudio subir.", "Waiting for PTP/audio to come up."),
            )
        elif s.overall == "failed":
            which = "clock" if s.clock_state == "failed" else "audio"
            self._hero.set_state(
                "off",
                _t("Falha ao iniciar", "Failed to start"),
                _t(
                    f"Serviço {which} falhou. Veja Ferramentas → Logs / Doctor e tente de novo.",
                    f"The {which} service failed. See Tools → Logs / Doctor and try again.",
                ),
            )
        else:
            self._hero.set_state(
                "off",
                _t("Parado", "Stopped"),
                _t(
                    "Selecione a interface, clique Aplicar e Iniciar.",
                    "Pick the interface, then click Apply and Start.",
                ),
            )

        # At-a-glance pills (Status page).
        try:
            cfg = _load_cfg()
        except Exception:
            cfg = {}
        dev = cfg.get("device", {})
        net = cfg.get("network", {})
        bridge = cfg.get("bridge", {})

        # Tell the network meter which interface to read.
        if hasattr(self, "_net_meter"):
            self._net_meter.set_interface(net.get("interface", ""))

        self._pills["device"].set_label(dev.get("name", "SonusGrid-Virtual"))
        self._pills["ptp"].set_label(s.ptp_version or "—")
        self._pills["nic"].set_label(net.get("interface") or "—")
        self._pills["ip"].set_label(net.get("bind_ip") or "—")
        self._pills["inputs"].set_label(str(dev.get("rx_channels", 0)))
        self._pills["outputs"].set_label(str(dev.get("tx_channels", 0)))
        self._pills["rate"].set_label(str(dev.get("sample_rate", 48000)))
        self._pills["jack"].set_label(
            (_t("Ativo", "Active") if s.jack_active else _t("Desligado", "Off"))
            if bridge.get("jack_enabled", True)
            else _t("Desabilitado", "Disabled")
        )
        return True

    def _notify(self, msg: str) -> None:
        toast = Adw.Toast.new(msg)
        toast.set_timeout(4)
        self._toast.add_toast(toast)

    # ============================================================
    # Actions (menu + tools)
    # ============================================================

    def _show_preferences(self) -> None:
        from sonus_gtk.config_dialog import PreferencesWindow
        win = PreferencesWindow(parent=self)
        win.present()

    def _edit_conf(self) -> None:
        for cmd in (
            ["xdg-open", str(CONFIG_PATH)],
            ["gnome-text-editor", str(CONFIG_PATH)],
            ["gedit", str(CONFIG_PATH)],
        ):
            try:
                subprocess.Popen(cmd)
                return
            except FileNotFoundError:
                continue
        text = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else ""
        dlg = Adw.MessageDialog(
            transient_for=self,
            heading=str(CONFIG_PATH),
            body=text or "(empty)",
        )
        dlg.add_response("ok", _t("Fechar", "Close"))
        dlg.present()

    def _show_doctor(self) -> None:
        rc, out, err = st.call("doctor")
        text = (out or "") + (("\n" + err) if err else "")
        dlg = Adw.MessageDialog(
            transient_for=self,
            heading=_t("Diagnóstico", "Diagnostics"),
            body=text or "(empty)",
        )
        dlg.add_response("ok", _t("Fechar", "Close"))
        dlg.set_default_response("ok")
        dlg.present()
        _ = rc

    def _show_logs(self) -> None:
        for cmd in (
            ["gnome-terminal", "--", "bash", "-c",
             "journalctl --user -u sonusgrid-clock.service -u sonusgrid-audio.service -f"],
            ["konsole", "-e", "bash", "-c",
             "journalctl --user -u sonusgrid-clock.service -u sonusgrid-audio.service -f"],
            ["xterm", "-e",
             "journalctl --user -u sonusgrid-clock.service -u sonusgrid-audio.service -f"],
        ):
            try:
                subprocess.Popen(cmd)
                return
            except FileNotFoundError:
                continue
        out = subprocess.run(
            ["journalctl", "--user", "-u", "sonusgrid-clock.service",
             "-u", "sonusgrid-audio.service", "-n", "200", "--no-pager"],
            capture_output=True, text=True, timeout=8,
        ).stdout
        dlg = Adw.MessageDialog(
            transient_for=self,
            heading=_t("Logs (últimas 200 linhas)", "Logs (last 200 lines)"),
            body=out or "(empty)",
        )
        dlg.add_response("ok", _t("Fechar", "Close"))
        dlg.present()

    def _open_docs(self) -> None:
        for path in (
            "/usr/share/doc/sonusgrid/USER_GUIDE.md",
            "/usr/share/doc/sonusgrid/USER_GUIDE.html",
            "/usr/share/doc/sonusgrid/README.md",
        ):
            try:
                subprocess.Popen(["xdg-open", path])
                return
            except FileNotFoundError:
                continue

    def _open_router(self) -> None:
        try:
            subprocess.Popen(["qpwgraph"])
        except FileNotFoundError:
            self._notify(_t(
                "Instale o qpwgraph: sudo apt install qpwgraph",
                "Install qpwgraph: sudo apt install qpwgraph",
            ))

    def _open_daw_guide(self) -> None:
        for path in (
            "/usr/share/doc/sonusgrid/DAW.md",
            str(Path.home() / "dante_dvs" / "sonus" / "docs" / "DAW.md"),
        ):
            if Path(path).exists():
                try:
                    subprocess.Popen(["xdg-open", path])
                    return
                except FileNotFoundError:
                    continue
        self._notify(_t(
            "Guia DAW não encontrado em /usr/share/doc/sonusgrid/DAW.md",
            "DAW guide not found in /usr/share/doc/sonusgrid/DAW.md",
        ))

    def _setup_daw_launchers(self) -> None:
        """Detect common DAWs in PATH and create .desktop launchers that wrap
        each with pw-jack so they connect to PipeWire-JACK on launch."""
        # Each entry: (binary name, display name, icon, mime types).
        candidates = [
            ("reaper",        "REAPER",        "reaper",        "application/x-reaper-project"),
            ("ardour",        "Ardour",        "ardour",        "application/x-ardour"),
            ("ardour8",       "Ardour 8",      "ardour",        "application/x-ardour"),
            ("ardour7",       "Ardour 7",      "ardour",        "application/x-ardour"),
            ("bitwig-studio", "Bitwig Studio", "bitwig-studio", ""),
            ("mixbus",        "Mixbus",        "mixbus",        "application/x-ardour"),
            ("mixbus32c",     "Mixbus 32C",    "mixbus",        "application/x-ardour"),
            ("muse",          "MusE",          "muse",          ""),
            ("qtractor",      "Qtractor",      "qtractor",      ""),
        ]
        if not subprocess.run(["which", "pw-jack"], capture_output=True).returncode == 0:
            self._notify(_t(
                "pw-jack não encontrado. Instale: sudo apt install pipewire-jack",
                "pw-jack not found. Install: sudo apt install pipewire-jack",
            ))
            return

        out_dir = Path.home() / ".local" / "share" / "applications"
        out_dir.mkdir(parents=True, exist_ok=True)
        created = []
        skipped = []
        for binary, name, icon, mime in candidates:
            r = subprocess.run(["which", binary], capture_output=True, text=True)
            if r.returncode != 0:
                continue  # Not installed — silently skip.
            target = out_dir / f"{binary}-jack.desktop"
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={name} (JACK / SonusGrid)\n"
                "GenericName=Digital Audio Workstation\n"
                f"Comment={name} bound to PipeWire-JACK for SonusGrid Dante I/O\n"
                f"Exec=pw-jack {binary} %F\n"
                f"Icon={icon}\n"
                "Terminal=false\n"
                "Categories=AudioVideo;Audio;Music;\n"
            )
            if mime:
                content += f"MimeType={mime};\n"
            content += (
                "StartupNotify=true\n"
                "Keywords=DAW;Audio;Recording;Music;JACK;\n"
            )
            try:
                target.write_text(content)
                created.append(name)
            except Exception:
                skipped.append(name)

        # Refresh the desktop database so the new entries show in the menu.
        try:
            subprocess.run(["update-desktop-database", str(out_dir)],
                           capture_output=True, timeout=5)
        except Exception:
            pass

        if not created:
            self._notify(_t(
                "Nenhum DAW conhecido encontrado no PATH. Instale um e tente "
                "de novo.",
                "No known DAW found in PATH. Install one and try again.",
            ))
            return

        joined = ", ".join(created)
        self._notify(_t(
            f"Atalhos criados: {joined}. Procure no menu por "
            "'<DAW> (JACK / SonusGrid)'.",
            f"Launchers created: {joined}. Look in the menu for "
            "'<DAW> (JACK / SonusGrid)'.",
        ))

    def _show_about(self) -> None:
        DISCLAIMER_PT = (
            "Compatível com redes Dante; não afiliado, endossado ou patrocinado por "
            "Audinate Pty Ltd. \"Dante\" é marca registrada da Audinate."
        )
        DISCLAIMER_EN = (
            "Compatible with Dante audio networks; not affiliated with, endorsed by, or "
            "sponsored by Audinate Pty Ltd. \"Dante\" is a trademark of Audinate."
        )
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="SonusGrid",
            application_icon="io.sonusgrid.SonusGrid",
            developer_name="SonusGrid contributors",
            version="0.2.1",
            comments=_t(
                "Aplicativo de áudio para Linux compatível com redes Dante.",
                "Linux audio app compatible with Dante audio networks.",
            ),
            website="https://github.com/chrisvalezi/sonusgrid",
            issue_url="https://github.com/chrisvalezi/sonusgrid/issues",
            license_type=Gtk.License.GPL_3_0,
            copyright="© 2026 SonusGrid contributors",
        )
        about.add_legal_section(
            title=_t("Compatibilidade Dante", "Dante compatibility"),
            copyright=None,
            license_type=Gtk.License.UNKNOWN,
            license=_t(DISCLAIMER_PT, DISCLAIMER_EN),
        )
        about.add_credit_section(
            _t("Engine subjacente", "Underlying engine"),
            ["Inferno (teodly) — GPLv3-or-later",
             "Statime (Pendulum / Trifecta Tech) — Apache-2.0 OR MIT"],
        )
        about.add_credit_section(
            _t("Áudio e GUI", "Audio & GUI"),
            ["PipeWire", "ALSA (alsa-rs)", "libpulse", "GTK4 / libadwaita"],
        )
        about.present()
