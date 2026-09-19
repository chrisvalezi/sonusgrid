# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogs: about, install hint, error details. libadwaita ≥ 1.5 API only."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from sonus_gtk.i18n import _t

DISCLAIMER = _t(
    "Compatível com redes Dante; não afiliado, endossado ou patrocinado pela Audinate Pty Ltd. "
    "\"Dante\" é marca registrada da Audinate.",
    "Compatible with Dante audio networks; not affiliated with, endorsed by, or sponsored by "
    "Audinate Pty Ltd. \"Dante\" is a trademark of Audinate.",
)


def show_about(parent: Gtk.Widget, version: str) -> None:
    dlg = Adw.AboutDialog(
        application_name="SonusGrid",
        application_icon="io.sonusgrid.SonusGrid",
        developer_name="Chris Valezi (@djchrisnobeat)",
        version=version or "—",
        website="https://github.com/chrisvalezi/sonusgrid",
        issue_url="https://github.com/chrisvalezi/sonusgrid/issues",
        license_type=Gtk.License.GPL_3_0,
        copyright="© 2026 Chris Valezi (@djchrisnobeat) and SonusGrid contributors",
        comments=_t("Transforma um PC Linux em um dispositivo de áudio compatível com redes Dante.",
                    "Turns a Linux box into an audio endpoint compatible with Dante audio networks."),
    )
    dlg.add_legal_section(_t("Compatibilidade Dante", "Dante compatibility"), None, Gtk.License.CUSTOM, DISCLAIMER)
    dlg.set_developers(["Chris Valezi (@djchrisnobeat) https://github.com/chrisvalezi"])
    dlg.add_credit_section(_t("Engine", "Engine"), [
        "Inferno (Teodor Woźniak) https://github.com/teodly/inferno",
        "Statime (Pendulum Project) https://github.com/pendulum-project/statime",
    ])
    dlg.add_credit_section(_t("Áudio e GUI", "Audio & GUI"), ["PipeWire", "ALSA", "libpulse", "GTK 4 / libadwaita"])
    dlg.present(parent)


def show_install_hint(parent: Gtk.Widget, tool: str, cmd: str | None, notify) -> None:
    if cmd:
        body = _t(f"Para instalar, copie e cole no terminal:\n\n{cmd}", f"To install, copy and paste in a terminal:\n\n{cmd}")
    else:
        body = _t("Não detectei seu gerenciador de pacotes — instale manualmente.",
                  "Could not detect your package manager — install it manually.")
    dlg = Adw.AlertDialog(heading=_t(f"{tool} não está instalado", f"{tool} is not installed"), body=body)
    dlg.add_response("close", _t("Fechar", "Close"))
    if cmd:
        dlg.add_response("copy", _t("Copiar comando", "Copy command"))
        dlg.set_response_appearance("copy", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("copy")

    def on_resp(_d, resp: str) -> None:
        if resp == "copy" and cmd:
            Gdk.Display.get_default().get_clipboard().set(cmd)
            notify(_t("Comando copiado.", "Command copied."))

    dlg.connect("response", on_resp)
    dlg.present(parent)


def show_details(parent: Gtk.Widget, heading: str, details: str) -> None:
    dlg = Adw.AlertDialog(heading=heading)
    view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    view.get_buffer().set_text(details.strip() or "—")
    view.add_css_class("sg-log")
    sw = Gtk.ScrolledWindow(min_content_height=160, max_content_height=360, propagate_natural_height=True)
    sw.add_css_class("card")
    sw.set_child(view)
    dlg.set_extra_child(sw)
    dlg.add_response("copy", _t("Copiar", "Copy"))
    dlg.add_response("close", _t("Fechar", "Close"))
    dlg.set_default_response("close")
    dlg.connect("response", lambda _d, r: Gdk.Display.get_default().get_clipboard().set(details) if r == "copy" else None)
    dlg.present(parent)


def show_shortcuts(parent: Gtk.Widget) -> None:
    rows = [
        ("F5", _t("Atualizar estado", "Refresh status")),
        ("Ctrl+1 … Ctrl+4", _t("Trocar de página", "Switch page")),
        ("Ctrl+Q", _t("Sair", "Quit")),
        ("F10", _t("Menu principal", "Primary menu")),
    ]
    body = "\n".join(f"{k}\t{v}" for k, v in rows)
    dlg = Adw.AlertDialog(heading=_t("Atalhos de teclado", "Keyboard shortcuts"), body=body)
    dlg.add_response("close", _t("Fechar", "Close"))
    dlg.present(parent)
