# SPDX-License-Identifier: GPL-3.0-or-later
"""Network helpers (sysfs / `ip -j`). Cheap file reads only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from sonus_gtk.services import cli

_SKIP_PREFIXES = ("docker", "veth", "br-", "cvd-", "tailscale", "nat64", "lxcbr", "virbr", "wg", "tun", "tap")


def list_interfaces_with_ip(callback: Callable[[list[tuple[str, str | None]]], None]) -> None:
    """Async: [(name, ipv4|None)] for physical-looking interfaces, UP first."""

    def done(r: cli.Result) -> None:
        result: list[tuple[str, str | None]] = []
        if r.ok:
            try:
                for e in json.loads(r.out):
                    n = e.get("ifname", "")
                    if n == "lo" or n.startswith(_SKIP_PREFIXES):
                        continue
                    ipv4 = next((a.get("local") for a in e.get("addr_info", []) if a.get("family") == "inet"), None)
                    up = e.get("operstate") == "UP"
                    result.append((n, ipv4, up))
            except Exception:
                result = []
        result.sort(key=lambda t: (not t[2], t[1] is None, t[0]))
        callback([(n, ip) for n, ip, _ in result])

    cli.run(["ip", "-j", "addr", "show"], done, timeout=4)




def read_iface_bytes(iface: str) -> tuple[int, int] | None:
    base = Path("/sys/class/net") / iface / "statistics"
    try:
        rx = int((base / "rx_bytes").read_text())
        tx = int((base / "tx_bytes").read_text())
        return rx, tx
    except Exception:
        return None


def iface_exists(iface: str) -> bool:
    return bool(iface) and (Path("/sys/class/net") / iface).exists()
