# SPDX-License-Identifier: GPL-3.0-or-later
"""Talk to the bridge's mixer: meters file (read on every frame) and the
control socket (set gains/mutes). Same wire format as `sonusgrid mixer`."""

from __future__ import annotations

import json
import os
import socket
import struct
from dataclasses import dataclass, field
from pathlib import Path

from gi.repository import GLib

MAX_CH = 256
MAGIC = 0x584D4753
HEADER = 32
MIN_DB = -80.0


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "sonusgrid"


def lin_to_db(v: float) -> float:
    if v <= 0.0:
        return MIN_DB
    import math
    return max(MIN_DB, 20.0 * math.log10(v))


@dataclass
class Meters:
    channels: int = 0
    seq: int = 0
    master_db: float = 0.0
    master_mute: bool = False
    tx_peak_db: list[float] = field(default_factory=list)
    rx_peak_db: list[float] = field(default_factory=list)
    tx_gain_db: list[float] = field(default_factory=list)
    rx_gain_db: list[float] = field(default_factory=list)
    tx_mute: list[bool] = field(default_factory=list)
    rx_mute: list[bool] = field(default_factory=list)
    master_peak_db: tuple[float, float] = (MIN_DB, MIN_DB)


class MixerClient:
    def __init__(self) -> None:
        self._meters_path = runtime_dir() / "meters"
        self._sock_path = runtime_dir() / "mixer.sock"
        self._sock: socket.socket | None = None
        self._client_path = runtime_dir() / f"mixer-gui.{os.getpid()}"
        self._fmt_f = struct.Struct(f"<{MAX_CH}f")

    # ---- meters ---------------------------------------------------------------
    def read_meters(self) -> Meters | None:
        try:
            with open(self._meters_path, "rb") as f:
                buf = f.read(HEADER + 4 * MAX_CH * 4 + 2 * MAX_CH + 8)
        except OSError:
            return None
        if len(buf) < HEADER:
            return None
        magic, ver, ch, seq, mg, mm, _rate, _period = struct.unpack_from("<8I", buf, 0)
        if magic != MAGIC or ch == 0:
            return None
        ch = min(ch, MAX_CH)
        off = HEADER
        txp = self._fmt_f.unpack_from(buf, off); off += MAX_CH * 4
        rxp = self._fmt_f.unpack_from(buf, off); off += MAX_CH * 4
        txg = self._fmt_f.unpack_from(buf, off); off += MAX_CH * 4
        rxg = self._fmt_f.unpack_from(buf, off); off += MAX_CH * 4
        txm = buf[off:off + MAX_CH]; off += MAX_CH
        rxm = buf[off:off + MAX_CH]; off += MAX_CH
        mp = struct.unpack_from("<2f", buf, off) if len(buf) >= off + 8 else (0.0, 0.0)
        master_lin = struct.unpack("<f", struct.pack("<I", mg))[0]
        return Meters(
            channels=ch, seq=seq,
            master_db=lin_to_db(master_lin) if not mm else MIN_DB, master_mute=bool(mm),
            tx_peak_db=[lin_to_db(v) for v in txp[:ch]],
            rx_peak_db=[lin_to_db(v) for v in rxp[:ch]],
            tx_gain_db=[lin_to_db(v) for v in txg[:ch]],
            rx_gain_db=[lin_to_db(v) for v in rxg[:ch]],
            tx_mute=[bool(b) for b in txm[:ch]],
            rx_mute=[bool(b) for b in rxm[:ch]],
            master_peak_db=(lin_to_db(mp[0]), lin_to_db(mp[1])),
        )

    # ---- control --------------------------------------------------------------
    def _socket(self) -> socket.socket | None:
        if self._sock is not None:
            return self._sock
        try:
            self._client_path.unlink(missing_ok=True)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            s.bind(str(self._client_path))
            s.settimeout(1.0)
            self._sock = s
        except OSError:
            self._sock = None
        return self._sock

    def send(self, cmd: str) -> dict | None:
        s = self._socket()
        if s is None or not self._sock_path.exists():
            return None
        try:
            s.sendto(cmd.encode(), str(self._sock_path))
            data, _ = s.recvfrom(65536)
            return json.loads(data.decode())
        except (OSError, json.JSONDecodeError):
            return None

    def get_state(self) -> dict | None:
        return self.send("get")

    def set_master(self, db: float) -> None:
        self.send(f"master {db:.1f}")

    def set_master_mute(self, on: bool) -> None:
        self.send(f"mmute {int(on)}")

    def set_gain(self, direction: str, ch: int, db: float) -> None:
        self.send(f"set {direction} {ch} {db:.1f}")

    def set_mute(self, direction: str, ch: int, on: bool) -> None:
        self.send(f"mute {direction} {ch} {int(on)}")

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None
        try:
            self._client_path.unlink(missing_ok=True)
        except OSError:
            pass
