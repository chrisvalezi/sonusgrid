# SPDX-License-Identifier: GPL-3.0-or-later
"""SonusGrid GTK launcher."""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from sonus_gtk.window import SonusWindow


class SonusApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="io.sonusgrid.SonusGrid",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.connect("activate", self._on_activate)

    def _on_activate(self, app: Adw.Application) -> None:
        win = self.props.active_window
        if win is None:
            win = SonusWindow(application=app)
        win.present()


def main() -> int:
    app = SonusApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
