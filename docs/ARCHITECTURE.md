# Architecture — SonusGrid

> EN only; the audience is contributors. End-user docs (PT-BR/EN) are the
> companion `USER_GUIDE.md`, `DAW.md`, and `TROUBLESHOOTING.md`.

## Process map

```
                    GUI (Python + libadwaita, GTK4)
                            │  Gio.Subprocess + pw-link/pactl
                            ▼
                    sonusgrid (CLI, Rust)
                  ┌─────────┼──────────┐
                  ▼         ▼          ▼
            systemctl    pactl    Statime / Inferno-fork (sonusgrid-engine)
                            │
   ┌────────────────────────┼────────────────────────────────────┐
   │                        │                                    │
   ▼                        ▼                                    ▼
sonusgrid-clock.service  sonusgrid-audio.service        (system) PipeWire
  (Statime)              (sonusgrid-bridge native        drop-in: @clock
                          Pulse + JACK + ALSA)
```

The bridge process owns the single `plug:sonusgrid` ALSA handle and exposes
two consumer paths: a PipeWire null-sink for casual PA apps (Spotify,
Firefox) and a JACK client `SonusGrid-JACK:tx_NN/rx_NN` for DAWs. Both are mixed
per-channel in the bridge before reaching the SonusGrid ALSA plug-in. There
is **no ffmpeg** anywhere in the runtime path — the native bridge replaced
it in v0.2.0.

The CLI is intentionally a thin orchestrator. There is no SonusGrid daemon. Every
operation is either:
- a one-shot read of `pactl list short sinks` / `systemctl --user is-active`,
- a one-shot write via `systemctl --user enable --now <unit>`, or
- an `exec()` replacement (the `_internal-*-exec` subcommands let systemd
  units stay one-line ExecStart while the actual process plumbing lives in
  Rust).

## Why no daemon

A daemon would let us:
- Hold richer state (PTP offset history, ARC packet decodes, etc.).
- Push notifications to the GUI without polling.

It would cost us:
- Another process to crash, secure, RPC against, and ship privilege boundaries.
- Bus / socket / D-Bus API design for one consumer (the GUI).
- Lifecycle complexity (auto-start, restart, etc.).

Polling `sonusgrid status --json` from the GUI every 3 s is sufficient for the UI
update rate humans can perceive.

## Module boundaries (CLI)

```
crates/sonus-cli/src/
├── main.rs        — clap dispatcher, glues subcommands to module functions
├── config.rs      — TOML schema, load/save, init/edit/check
├── runtime.rs     — start/stop/status, preflight, _internal-*-exec, wait-network
├── paths.rs       — per-user runtime dir ($XDG_RUNTIME_DIR/sonusgrid) for sockets/FIFO
├── audio.rs       — pactl null-sink/pipe-source lifecycle, exec sonusgrid-bridge
├── alsa.rs        — render ~/.config/alsa/sonusgrid.conf, idempotent ~/.asoundrc patch
├── ptp.rs         — render ~/.cache/sonusgrid/statime.toml, wait for PTP lock
├── doctor.rs      — bilingual diagnostics (the support-call killer)
├── logs.rs        — journalctl --user wrapper (exec replace)
├── routing.rs     — pavucontrol launcher, avahi-browse
└── text.rs        — bilingual string helper (Lang enum + t() picker)
```

`anyhow::Result<()>` is the universal return type at module boundaries. Errors
propagate with context strings; the user sees the chain.

## Start-up sequence (0.2.1+)

`sonusgrid start`:
1. Preflight: interface configured and present (fails fast with a bilingual
   message); warns if it has no IPv4 yet.
2. Creates `$XDG_RUNTIME_DIR/sonusgrid/`, renders the ALSA config.
3. `daemon-reload`; restarts PipeWire **only** if our drop-in isn't loaded
   yet; `reset-failed` on both units (otherwise systemd's start-rate limiter
   refuses to start a unit that failed recently).
4. `enable --now --no-block` both units, then polls `is-active` for up to
   20 s and prints the journal tail if either ends up `failed`.

`sonusgrid-clock.service`: `ExecStartPre` waits (≤ 45 s) for the NIC to
have an IPv4, then `exec`s Statime with `usrvclock-path` pointing into the
runtime dir. `StartLimitIntervalSec=0` so it retries forever at boot.

`sonusgrid-audio.service` (`Requires`/`After` the clock unit): loads the
null-sink and pipe-source, then **blocks until Statime publishes its first
clock overlay** (PTP lock, ≤ 60 s) before `exec`ing the bridge. Without
this the engine timed out waiting for the clock and every start looked like
a crash + restart.

## Why not Cargo workspace at the root

Statime and the engine are independent upstream projects with their own
Cargo.toml setups (Statime is a multi-crate workspace itself; the engine
bundles its own Cargo workspace). Putting `sonus-cli` into the same
workspace would mean editing those Cargo.tomls or a virtual workspace that
reaches into them (fragile across version bumps).

Solution: `crates/sonus-cli/` is its own Cargo project (it does take a path
dependency on the engine's `usrvclock-rs` crate to wait for the PTP lock).
The top-level `Makefile` orchestrates the Cargo invocations.

## ALSA plugin lifecycle

The engine's `libasound_module_pcm_sonusgrid.so` is loaded by ALSA when *any*
process opens an ALSA device of `type sonusgrid`. The plugin then:
1. Spawns the inferno_aoip Rust runtime in-process.
2. Binds UDP sockets for ARC/CMC/DBC + RTP.
3. Advertises mDNS via the bundled searchfire mDNS implementation.

When the process closes the device (or dies), the runtime is torn down. The
device disappears from the Dante network within a few seconds.

This is why SonusGrid runs `sonusgrid-bridge` as a long-lived holder. The
bridge opens the device full-duplex (single ALSA handle for both playback
and capture), reads the PipeWire null-sink monitor for casual apps, and
also registers a JACK client for DAW use. As long as the bridge is alive,
Inferno's runtime stays up and Dante Controller subscriptions remain
stable, even when no audio is flowing.

## Why a native Rust bridge, not ffmpeg or pure PipeWire

PipeWire 1.4's `module-alsa-sink` cannot speak ALSA's `pcm.<name>` aliases —
it expects a card-style `hw:N`. The SonusGrid plug-in is a `pcm.`
declaration in asoundrc, not a card. We also tried `pw-cli create-node
adapter` — silently fails on PipeWire 1.4.7.

The earlier prototype used `ffmpeg` as a libasound holder (it talks
libasound directly), but ffmpeg's multi-input demuxer cross-synchronised
the live PulseAudio + ALSA inputs by timestamp, producing **20+ s of
latency** with audible cracking. We replaced it with a purpose-built native
Rust process (`crates/sonusgrid-bridge`) that:

* Opens `plug:sonusgrid` once full-duplex (TX + RX in the same handle, what
  keeps Inferno's RX subscriber alive).
* Runs TX and RX in independent threads with no cross-synchronisation.
* Reads PA monitor via libpulse Simple, writes ALSA s32 directly.
* Registers a JACK client (via PipeWire-jack) with N tx + N rx ports.
* Mixes PA + JACK per channel before the ALSA write.
* Recovers from xruns inline without exiting.

Result: latency dropped from ~20 s to ~25 ms (Pulse path) and ~12 ms (JACK
path), and there is no longer a runtime ffmpeg dependency. The bridge
binary is ~3 MB statically.

## Capability model

Statime needs three capabilities:
- `cap_sys_time` — to call `clock_settime`/`adjtimex` and steer the system
  clock.
- `cap_net_bind_service` — to bind privileged UDP ports if PTPv1 (port 320)
  comes back as-spec.
- `cap_net_admin` — for raw socket multicast operations.

We avoid `sudo` at runtime by running `setcap` once during install (`.deb`
postinst) or first launch (`AppImage` AppRun, prompting `pkexec`). The user
units run as the unprivileged user; the kernel grants the capabilities
because they're file-attached to the binary.

This is the same model JACK has used for a decade for `cap_sys_nice`.

## NTP coexistence

Statime runs with `virtual-system-clock = true` and
`virtual-system-clock-base = "monotonic_raw"`: the PTP clock is an overlay
(offset + frequency scale) on top of `CLOCK_MONOTONIC_RAW`, published to the
engine over the `usrvclock` Unix socket. The system clock is **never**
steered, so NTP daemons are not a conflict and `doctor` no longer asks the
user to stop them. `cap_sys_time` is still granted for the non-virtual
mode Statime supports.

## State

| Path | Owner | Purpose |
|------|-------|---------|
| `~/.config/sonusgrid/config.toml` | user | source of truth, hand-editable |
| `~/.config/alsa/sonusgrid.conf` + block in `~/.asoundrc` | CLI | rendered from config.toml on every start |
| `~/.cache/sonusgrid/statime.toml` | CLI | rendered from config.toml |
| `$XDG_RUNTIME_DIR/sonusgrid/` | CLI / Statime / PipeWire | `ptp-usrvclock` socket, `usrvclock-client.*` reply sockets, `<sink>_RX.fifo` — wiped on logout |
| `~/.local/state/sonusgrid/<DEVICE_ID>/` | engine (in-plugin) | per-device persistent state |

Runtime files used to live in `/tmp`; that broke whenever `/tmp` had unusual
permissions or `fs.protected_regular` interfered, and two users on one box
collided on the same names.

Inferno's state directory survives across runs and stores subscription
acknowledgements, channel-name caches, etc. Wiping it forces a clean
re-discovery.

## Build artefacts

```
crates/sonus-cli/target/release/sonusgrid                ← /usr/bin/sonusgrid
crates/sonusgrid-bridge/target/release/sonusgrid-bridge  ← /usr/libexec/sonusgrid/sonusgrid-bridge
vendor/statime/target/release/statime                    ← /usr/libexec/sonusgrid/statime  (with caps)
crates/sonusgrid-engine/target/release/sonusgrid_pipe    ← /usr/libexec/sonusgrid/sonusgrid_pipe
crates/sonusgrid-engine/target/release/libasound_module_pcm_sonusgrid.so
                                                         ← /usr/lib/<triplet>/alsa-lib/
gui/sonus-gtk/sonus_gtk/                                 ← /usr/share/sonusgrid/gui/sonus_gtk/
systemd/sonusgrid-{clock,audio}.service                  ← /usr/lib/systemd/user/
systemd/sonusgrid-pipewire-clock.conf                    ← /usr/lib/systemd/user/pipewire.service.d/
packaging/udev/60-sonusgrid-ptp.rules                    ← /usr/lib/udev/rules.d/
gui/sonus-gtk/data/io.sonusgrid.SonusGrid.desktop        ← /usr/share/applications/
gui/sonus-gtk/data/icons/.../io.sonusgrid.SonusGrid.svg  ← /usr/share/icons/hicolor/scalable/apps/
```

`make deb` stages all of that through `packaging/debian/` and drops the
result in `dist/`.

## Versioning

Single source of truth: `version.mk` (`SONUS_VERSION`, `DEB_REVISION`). Bump
in lockstep: `crates/sonus-cli/Cargo.toml`, `crates/sonusgrid-bridge/Cargo.toml`,
`gui/sonus-gtk/pyproject.toml`, `gui/.../window.py` (about dialog),
`packaging/debian/changelog`, `CHANGELOG.md`.
