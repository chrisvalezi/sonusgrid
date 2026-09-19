# SPDX-License-Identifier: GPL-3.0-or-later
"""`sonusgrid doctor --json` runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from sonus_gtk.services import cli


@dataclass
class DoctorReport:
    ok: bool
    passed: list[str] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)  # (pt, en)
    raw: str = ""
    error: str = ""


def run_doctor(callback: Callable[[DoctorReport], None]) -> None:
    def done(r: cli.Result) -> None:
        raw = (r.out + ("\n" + r.err if r.err.strip() else "")).strip()
        if r.rc == 127:
            callback(DoctorReport(ok=False, raw=raw, error="sonusgrid CLI not found"))
            return
        try:
            d = json.loads(r.out)
        except json.JSONDecodeError:
            callback(DoctorReport(ok=False, raw=raw, error=r.last_line or "invalid JSON"))
            return
        callback(
            DoctorReport(
                ok=bool(d.get("ok")),
                passed=[str(x) for x in d.get("passed", [])],
                problems=[(str(p.get("pt", "")), str(p.get("en", ""))) for p in d.get("problems", [])],
                raw=raw,
            )
        )

    cli.run(["sonusgrid", "doctor", "--json"], done, timeout=30)
