# SPDX-License-Identifier: GPL-3.0-or-later
"""Single source of truth for ~/.config/sonusgrid/config.toml in the GUI.

`ConfigStore` mirrors the CLI schema (crates/sonus-cli/src/config.rs). Unknown
keys are preserved on save so the GUI never silently drops fields the CLI
adds later.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from gi.repository import Gio, GLib, GObject

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore

CONFIG_PATH = Path(GLib.get_user_config_dir()) / "sonusgrid" / "config.toml"

SAMPLE_RATES = [44100, 48000, 88200, 96000]
PTP_VERSIONS = ["v1", "v2"]
BRIDGE_MODES = ["null-sink", "none"]
MAX_CHANNELS = 256

DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "device": {
        "name": "SonusGrid-Virtual",
        "device_id": "",
        "sample_rate": 48000,
        "rx_channels": 16,
        "tx_channels": 16,
        "rx_latency_ns": 4_000_000,
        "tx_latency_ns": 4_000_000,
    },
    "network": {"interface": "", "bind_ip": ""},
    "ptp": {"version": "v1", "domain": 0, "priority1": 251, "hardware_clock": "auto"},
    "bridge": {
        "mode": "null-sink",
        "sink_name": "SonusGrid",
        "sink_description": "SonusGrid (Dante-compatible)",
        "relay_channels": 16,
        "jack_enabled": True,
    },
    "ui": {"language": "auto", "show_disclaimer_on_start": True},
}


# ---- TOML writer (preserves unknown keys; no external dependency) ---------

def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value: {v!r}")


def dumps(d: dict[str, Any]) -> str:
    out: list[str] = []
    for k, v in d.items():
        if not isinstance(v, dict):
            out.append(f"{k} = {_fmt(v)}")
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"\n[{k}]")
            for kk, vv in v.items():
                out.append(f"{kk} = {_fmt(vv)}")
    return "\n".join(out) + "\n"


def _deep_merge(base: dict, over: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class ConfigStore(GObject.Object):
    """Loaded config + dirty tracking + external-change monitoring.

    `data` is the merged dict (defaults ← file). Edit via `set_value(section,
    key, value)`; `dirty` flips when the in-memory copy differs from disk.
    """

    __gsignals__ = {
        "reloaded": (GObject.SignalFlags.RUN_FIRST, None, ()),   # disk → memory
        "saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    dirty = GObject.Property(type=bool, default=False)
    exists = GObject.Property(type=bool, default=False)

    def __init__(self) -> None:
        super().__init__()
        self.path = CONFIG_PATH
        self._disk: dict[str, Any] = {}
        self.data: dict[str, Any] = {}
        self._monitor: Gio.FileMonitor | None = None
        self._suppress_monitor_until = 0.0
        self.load()
        self._watch()

    # ---- disk -------------------------------------------------------------
    def load(self) -> None:
        raw: dict[str, Any] = {}
        if self.path.exists():
            try:
                with open(self.path, "rb") as f:
                    raw = tomllib.load(f)
            except Exception:
                raw = {}
            self.exists = True
        else:
            self.exists = False
        self._disk = _deep_merge(DEFAULTS, raw)
        self.data = _deep_merge(self._disk, {})
        self.dirty = False
        self.emit("reloaded")

    def ensure_exists(self) -> None:
        """Create the file through the CLI (keeps one writer for defaults)."""
        if self.path.exists():
            return
        try:
            subprocess.run(["sonusgrid", "config", "init"], capture_output=True, timeout=10)
        except Exception:
            pass
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(dumps(DEFAULTS))
        self.load()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._suppress_monitor_until = GLib.get_monotonic_time() / 1e6 + 1.5
        self.path.write_text(dumps(self.data))
        self._disk = _deep_merge(self.data, {})
        self.exists = True
        self.dirty = False
        self.emit("saved")

    def discard(self) -> None:
        self.data = _deep_merge(self._disk, {})
        self.dirty = False
        self.emit("reloaded")

    def _watch(self) -> None:
        try:
            gfile = Gio.File.new_for_path(str(self.path))
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_changed)
        except Exception:
            self._monitor = None

    def _on_changed(self, _m, _f, _o, event) -> None:
        if event not in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.DELETED,
        ):
            return
        if GLib.get_monotonic_time() / 1e6 < self._suppress_monitor_until:
            return
        if self.dirty:
            return  # don't clobber unsaved edits; the form will show a hint
        self.load()

    # ---- access -----------------------------------------------------------
    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.data.get(section, {}).get(key, default)

    def set_value(self, section: str, key: str, value: Any) -> None:
        self.data.setdefault(section, {})[key] = value
        self._recompute_dirty()

    def _recompute_dirty(self) -> None:
        self.dirty = self.data != self._disk

    # ---- conveniences -------------------------------------------------------
    @property
    def interface(self) -> str:
        return str(self.get("network", "interface", "")).strip()

    @property
    def device_name(self) -> str:
        return str(self.get("device", "name", "SonusGrid-Virtual"))

    @property
    def sample_rate(self) -> int:
        try:
            return int(self.get("device", "sample_rate", 48000))
        except (TypeError, ValueError):
            return 48000

    @property
    def jack_enabled(self) -> bool:
        return bool(self.get("bridge", "jack_enabled", True))
