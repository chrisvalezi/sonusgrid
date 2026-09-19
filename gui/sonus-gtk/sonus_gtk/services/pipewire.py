# SPDX-License-Identifier: GPL-3.0-or-later
"""PipeWire session helpers: JACK buffer (quantum) read/write."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import GLib

from sonus_gtk.services import cli

QUANTA = [64, 128, 256, 512, 1024]
_DROPIN = Path(GLib.get_user_config_dir()) / "pipewire" / "pipewire.conf.d" / "99-sonusgrid-lowlatency.conf"


def _parse_value(text: str, key: str) -> int | None:
    for line in text.splitlines():
        if "value:" in line and key in line:
            v = line.split("value:")[1].strip().strip("'\"").split()[0]
            try:
                return int(v.strip("'\""))
            except ValueError:
                return None
    return None


def read_quantum(callback: Callable[[int], None]) -> None:
    def forced(r: cli.Result) -> None:
        v = _parse_value(r.out, "clock.force-quantum") if r.ok else None
        if v and v > 0:
            callback(v)
            return
        cli.run(["pw-metadata", "-n", "settings", "0", "clock.quantum"], default, timeout=3)

    def default(r: cli.Result) -> None:
        v = _parse_value(r.out, "clock.quantum") if r.ok else None
        callback(v if v and v > 0 else 256)

    cli.run(["pw-metadata", "-n", "settings", "0", "clock.force-quantum"], forced, timeout=3)


def set_quantum(n: int, rate: int, callback: Callable[[bool, str], None]) -> None:
    """Apply live via pw-metadata and persist a conf.d drop-in."""

    def done(r: cli.Result) -> None:
        if not r.ok:
            callback(False, r.last_line or "pw-metadata failed")
            return
        try:
            _DROPIN.parent.mkdir(parents=True, exist_ok=True)
            _DROPIN.write_text(
                "# SonusGrid buffer profile — managed by the GUI; safe to edit.\n"
                "context.properties = {\n"
                f"    default.clock.rate          = {rate}\n"
                f"    default.clock.quantum       = {n}\n"
                f"    default.clock.min-quantum   = {n}\n"
                "    default.clock.max-quantum   = 1024\n"
                "    default.clock.allowed-rates = [ 44100 48000 88200 96000 ]\n"
                "}\n"
            )
        except Exception as e:
            callback(True, f"applied, not persisted: {e}")
            return
        callback(True, "")

    cli.run(["pw-metadata", "-n", "settings", "0", "clock.force-quantum", str(n)], done, timeout=4)


def quantum_ms(n: int, rate: int) -> float:
    return n * 1000.0 / max(rate, 1)
