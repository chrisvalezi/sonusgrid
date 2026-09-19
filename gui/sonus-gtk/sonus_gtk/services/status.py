# SPDX-License-Identifier: GPL-3.0-or-later
"""`StatusModel` — the single poller of `sonusgrid status --json`.

Widgets bind to its GObject properties; nothing else in the GUI asks the CLI
for state. Polling never overlaps (a tick is skipped while one is in flight)
and never blocks the main loop.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Callable

from gi.repository import GLib, GObject

from sonus_gtk.services import cli


class Phase(str, Enum):
    UNKNOWN = "unknown"
    CLI_MISSING = "cli_missing"
    OFF = "off"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"   # running, JACK wanted but not registered
    FAILED = "failed"


class StatusModel(GObject.Object):
    phase = GObject.Property(type=str, default=Phase.UNKNOWN.value)
    busy = GObject.Property(type=bool, default=False)          # start/stop/restart in flight
    version = GObject.Property(type=str, default="")
    device_name = GObject.Property(type=str, default="")
    interface = GObject.Property(type=str, default="")
    ptp_version = GObject.Property(type=str, default="")
    clock_state = GObject.Property(type=str, default="inactive")
    audio_state = GObject.Property(type=str, default="inactive")
    clock_active = GObject.Property(type=bool, default=False)
    audio_active = GObject.Property(type=bool, default=False)
    jack_active = GObject.Property(type=bool, default=False)
    sink_present = GObject.Property(type=bool, default=False)
    # PTP observation (from statime's observation socket)
    ptp_state = GObject.Property(type=str, default="")          # Slave / Master / Listening …
    ptp_locked = GObject.Property(type=bool, default=False)
    ptp_has_offset = GObject.Property(type=bool, default=False)
    ptp_offset_ns = GObject.Property(type=float, default=0.0)
    ptp_delay_ns = GObject.Property(type=float, default=0.0)
    ptp_grandmaster = GObject.Property(type=str, default="")
    last_error = GObject.Property(type=str, default="")

    __gsignals__ = {
        # Emitted after every successful poll, after all properties updated.
        "updated": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Emitted when a start/stop/restart finishes: (verb, ok, message)
        "action-done": (GObject.SignalFlags.RUN_FIRST, None, (str, bool, str)),
    }

    def __init__(self, jack_wanted: Callable[[], bool] = lambda: True) -> None:
        super().__init__()
        self._jack_wanted = jack_wanted
        self._in_flight = False
        self._timer = 0
        self._degraded_since = 0.0   # monotonic seconds; 0 = not degraded

    # ---- polling ------------------------------------------------------------
    def start_polling(self, interval_s: int = 2) -> None:
        if self._timer:
            return
        self.refresh()
        self._timer = GLib.timeout_add_seconds(interval_s, self._tick)

    def stop_polling(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self) -> None:
        if self._in_flight:
            return
        self._in_flight = True
        cli.run(["sonusgrid", "status", "--json"], self._on_status, timeout=6)

    def _on_status(self, r: cli.Result) -> None:
        self._in_flight = False
        if r.rc == 127:
            self.phase = Phase.CLI_MISSING.value
            self.emit("updated")
            return
        if not r.ok:
            # Config parse error etc. Keep the last known state, surface the text.
            self.last_error = r.last_line
            self.emit("updated")
            return
        try:
            d = json.loads(r.out)
        except json.JSONDecodeError:
            self.last_error = "status --json: invalid JSON"
            self.emit("updated")
            return
        self._apply(d)

    def _apply(self, d: dict) -> None:
        self.version = str(d.get("version", ""))
        self.device_name = str(d.get("device_name", ""))
        self.interface = str(d.get("interface", ""))
        self.ptp_version = str(d.get("ptp_version", ""))
        self.clock_state = str(d.get("clock_state", "active" if d.get("clock_active") else "inactive"))
        self.audio_state = str(d.get("audio_state", "active" if d.get("audio_active") else "inactive"))
        self.clock_active = bool(d.get("clock_active"))
        self.audio_active = bool(d.get("audio_active"))
        self.jack_active = bool(d.get("jack_active"))
        self.sink_present = bool(d.get("sink_present"))
        ptp = d.get("ptp") or {}
        self.ptp_state = str(ptp.get("state") or "")
        self.ptp_locked = bool(ptp.get("locked"))
        off = ptp.get("offset_ns")
        self.ptp_has_offset = isinstance(off, (int, float))
        self.ptp_offset_ns = float(off) if self.ptp_has_offset else 0.0
        dly = ptp.get("mean_delay_ns")
        self.ptp_delay_ns = float(dly) if isinstance(dly, (int, float)) else 0.0
        self.ptp_grandmaster = str(ptp.get("grandmaster") or "")

        running = self.clock_active and self.audio_active and self.sink_present
        if any(s == "failed" for s in (self.clock_state, self.audio_state)) and not running:
            phase = Phase.FAILED
        elif running:
            if self._jack_wanted() and not self.jack_active:
                # The bridge registers its JACK client only after the PTP
                # lock, several seconds after the unit turns "active". Give
                # it a grace period before calling the session degraded.
                now = GLib.get_monotonic_time() / 1e6
                if not self._degraded_since:
                    self._degraded_since = now
                phase = Phase.STARTING if now - self._degraded_since < 20 else Phase.DEGRADED
            else:
                self._degraded_since = 0.0
                phase = Phase.RUNNING
        elif self.busy or self.clock_active or self.audio_active or "activating" in (self.clock_state, self.audio_state):
            phase = Phase.STARTING
        else:
            self._degraded_since = 0.0
            phase = Phase.OFF
        if phase == Phase.FAILED:
            self._degraded_since = 0.0
        self.phase = phase.value
        self.last_error = ""
        self.emit("updated")

    # ---- actions ----------------------------------------------------------
    def _action(self, verb: str) -> None:
        if self.busy:
            return
        self.busy = True
        if verb != "stop":
            self.phase = Phase.STARTING.value

        def done(r: cli.Result) -> None:
            self.busy = False
            self.emit("action-done", verb, r.ok, r.last_line if not r.ok else r.out.strip().splitlines()[-1] if r.out.strip() else "")
            self.refresh()

        cli.run(["sonusgrid", verb], done, timeout=120)

    def start(self) -> None:
        self._action("start")

    def stop(self) -> None:
        self._action("stop")

    def restart(self) -> None:
        self._action("restart")

    # ---- helpers ------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self.phase in (Phase.RUNNING.value, Phase.DEGRADED.value)

    @property
    def is_transitioning(self) -> bool:
        return self.busy or self.phase == Phase.STARTING.value
