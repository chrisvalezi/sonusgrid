# SPDX-License-Identifier: GPL-3.0-or-later
"""Dante device discovery via `sonusgrid devices --json` (native mDNS)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from sonus_gtk.services import cli


@dataclass
class DanteDevice:
    name: str
    ip: str
    host: str
    is_self: bool


def browse(callback: Callable[[list[DanteDevice] | None, str], None]) -> None:
    """callback(devices, error). devices is None on failure."""

    def done(r: cli.Result) -> None:
        if not r.ok and not r.out.strip():
            callback(None, r.last_line)
            return
        try:
            data = json.loads(r.out)
        except json.JSONDecodeError:
            callback(None, r.last_line or "invalid JSON")
            return
        devs = [
            DanteDevice(
                name=str(d.get("name", "")),
                ip=str(d.get("ip", "")),
                host=str(d.get("host", "")),
                is_self=bool(d.get("is_self")),
            )
            for d in data
        ]
        devs.sort(key=lambda d: (not d.is_self, d.name.lower()))
        callback(devs, "")

    cli.run(["sonusgrid", "devices", "--json"], done, timeout=12)
