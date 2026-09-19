# SPDX-License-Identifier: GPL-3.0-or-later
"""Async subprocess helpers built on Gio.Subprocess — nothing here blocks the
GTK main loop. Every callback is invoked on the main loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from gi.repository import Gio, GLib


@dataclass
class Result:
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def last_line(self) -> str:
        for text in (self.err, self.out):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                return lines[-1]
        return ""


def run(argv: list[str], callback: Callable[[Result], None], *, timeout: float = 15.0) -> Gio.Cancellable | None:
    """Spawn `argv`, collect stdout/stderr, call `callback(Result)`.
    ENOENT and timeouts are reported through the Result (rc 127 / 124)."""
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        )
    except GLib.Error as e:
        GLib.idle_add(lambda: (callback(Result(127, "", e.message)), False)[1])
        return None
    cancellable = Gio.Cancellable()
    state = {"timer": 0, "timed_out": False}

    def _timeout() -> bool:
        state["timed_out"] = True
        state["timer"] = 0
        proc.force_exit()
        return False

    state["timer"] = GLib.timeout_add(int(timeout * 1000), _timeout)

    def _done(p: Gio.Subprocess, res: Gio.AsyncResult) -> None:
        if state["timer"]:
            GLib.source_remove(state["timer"])
        try:
            _, out, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            callback(Result(1, "", e.message))
            return
        if state["timed_out"]:
            rc = 124
        elif p.get_if_exited():
            rc = p.get_exit_status()
        else:
            rc = 1
        callback(Result(rc, out or "", err or ""))

    proc.communicate_utf8_async(None, cancellable, _done)
    return cancellable


class FollowHandle:
    """Handle for a long-running line-oriented subprocess (journalctl -f)."""

    def __init__(self) -> None:
        self._proc: Gio.Subprocess | None = None
        self._cancel = Gio.Cancellable()
        self.alive = False

    def cancel(self) -> None:
        self.alive = False
        self._cancel.cancel()
        if self._proc is not None:
            try:
                self._proc.force_exit()
            except Exception:
                pass
            self._proc = None


def follow(argv: list[str], on_line: Callable[[str], None], on_exit: Callable[[int], None] | None = None) -> FollowHandle:
    """Spawn `argv` and feed each stdout+stderr line to `on_line`."""
    handle = FollowHandle()
    try:
        proc = Gio.Subprocess.new(
            argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        )
    except GLib.Error as e:
        GLib.idle_add(lambda: (on_line(f"[gui] cannot start {argv[0]}: {e.message}"), False)[1])
        if on_exit:
            GLib.idle_add(lambda: (on_exit(127), False)[1])
        return handle
    handle._proc = proc
    handle.alive = True
    stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

    def _read() -> None:
        stream.read_line_async(GLib.PRIORITY_DEFAULT, handle._cancel, _got)

    def _got(s: Gio.DataInputStream, res: Gio.AsyncResult) -> None:
        try:
            line, _len = s.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None or not handle.alive:
            handle.alive = False
            if on_exit:
                rc = proc.get_exit_status() if proc.get_if_exited() else 1
                on_exit(rc)
            return
        on_line(line)
        _read()

    _read()
    return handle
