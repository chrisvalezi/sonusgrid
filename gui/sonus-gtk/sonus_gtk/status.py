# SPDX-License-Identifier: GPL-3.0-or-later
"""`sonusgrid status --json` poller. Subprocess-based; never imports CLI internals."""

import json
import subprocess
from dataclasses import dataclass


@dataclass
class Status:
    clock_active: bool
    audio_active: bool
    jack_active: bool
    sink_present: bool
    mode: str  # "unified" (0.2+); "pulse"/"jack" were pre-0.2 modes
    device_name: str
    interface: str
    ptp_version: str
    clock_state: str = "inactive"  # active | activating | inactive | failed
    audio_state: str = "inactive"

    @property
    def failed(self) -> bool:
        return self.clock_state == "failed" or self.audio_state == "failed"

    @property
    def overall(self) -> str:
        """One of 'ok', 'partial', 'failed', 'off'.

        The unified bridge always provides the PipeWire null-sink; the JACK
        client is a bonus for DAWs and must NOT gate the "ok" state — a
        machine without PipeWire-JACK still has working system audio.
        """
        audio_path_up = self.audio_active and self.sink_present
        if self.clock_active and audio_path_up:
            return "ok"
        if self.failed:
            return "failed"
        if self.clock_active or self.audio_active or self.jack_active \
                or self.clock_state == "activating" or self.audio_state == "activating":
            return "partial"
        return "off"


def fetch() -> Status | None:
    try:
        out = subprocess.run(
            ["sonusgrid", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    return Status(
        clock_active=data.get("clock_active", False),
        audio_active=data.get("audio_active", False),
        jack_active=data.get("jack_active", False),
        sink_present=data.get("sink_present", False),
        mode=data.get("mode", "unified"),
        device_name=data.get("device_name", ""),
        interface=data.get("interface", ""),
        ptp_version=data.get("ptp_version", ""),
        clock_state=data.get("clock_state", "active" if data.get("clock_active") else "inactive"),
        audio_state=data.get("audio_state", "active" if data.get("audio_active") else "inactive"),
    )


def call(*args: str) -> tuple[int, str, str]:
    """Run `sonusgrid <args>` and return (rc, stdout, stderr)."""
    p = subprocess.run(
        ["sonusgrid", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return p.returncode, p.stdout, p.stderr
