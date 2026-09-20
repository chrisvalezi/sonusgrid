# Changelog

All notable changes to SonusGrid are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Planned
- Dante Primary/Secondary redundancy and interface failover — see
  `docs/ROADMAP.md` (blocked on a two-port device for protocol captures).

## [0.3.0] — 2026-09-20

### Added
- **New icon** — a mesh of connected nodes whose horizontal link is an audio
  wave; flat GNOME style, with a symbolic variant and AppStream metainfo.
- **Redesigned GUI** (GTK4 / libadwaita ≥ 1.5): sidebar navigation that
  collapses on narrow windows, light/dark from the system, a status page with
  a live **PTP lock indicator** (port state, offset to master, grandmaster),
  service chips, redesigned throughput meter, a **Dante network** page that
  lists devices discovered on the LAN, a configuration page with an
  apply/discard bar and external-change reload, and a **diagnostics** page
  with `doctor` rendered as a checklist plus an in-app log viewer. All CLI
  calls are asynchronous; no deprecated libadwaita API.
- `sonusgrid status --json` now reports `ptp` (state, locked, offset,
  delay, grandmaster) read from Statime's observation socket.
- `sonusgrid devices [--json]` — native mDNS discovery of Dante devices on
  the configured NIC (no Avahi needed). `sonusgrid doctor --json`.
- **End-user installer** `SonusGrid-<ver>-<arch>.run` (makeself) and the
  one-liner `curl -fsSL …/releases/latest/download/install.sh | bash`.
- GitHub Actions: CI (build + install test on Debian 12 / Ubuntu 24.04) and
  Release (deb + run for amd64 and arm64, checksums, notes from this file).
- `make bump VERSION=…`, `make check-version`, `make release`.

### Fixed
- **Dropouts under CPU load** ("tx lag of N samples detected"): the bridge's
  TX/RX threads and the engine's flow threads now run SCHED_FIFO, via
  RLIMIT_RTPRIO when the session allows it or through **rtkit** otherwise;
  the package installs `/etc/security/limits.d/sonusgrid.conf` (rtprio /
  memlock for the `audio` group). Zero dropouts in a 15 s 8-core stress test
  that previously produced hundreds.
- **Player hangs buffering when routed to SonusGrid** (YouTube "spinner"):
  a stale `SonusGrid_RX` pipe-source that survived many bridge restarts left
  WirePlumber unable to link streams to the sink *by name* (the way browsers
  and stream-restore target it). The bridge now tears down and recreates
  its sink and source on every start, in a fixed order; sink descriptions
  with spaces are no longer truncated. `doctor` reports the sink volume.
- **Clock jumps under host load**: Statime now runs its PTP loop on a single
  SCHED_FIFO thread (rtkit fallback) instead of a normal-priority pool, so
  a busy machine no longer produces millisecond steps that made the engine
  restart its transmitter ("clock jumped"). PTPv1 `DelayReq` chatter is no
  longer logged as a warning.
- **Bridge killed by the rtkit watchdog**: the TX thread no longer spins at
  RT priority when the PulseAudio connection dies (it paces itself and
  exits cleanly after ~10 s so systemd restarts it).
- **Desktop output lost after a bridge restart**: `ensure_sink` no longer
  reverts the default sink WirePlumber restores; if SonusGrid is your
  chosen output it stays the output.
- **Endless restarts on a broken config**: `config check` exits 78
  (EX_CONFIG) and the units carry `RestartPreventExitStatus=78`. (A stray
  config in another user session had produced 130 000 restarts.)
- **"Start does nothing"**: `sonusgrid start` now tells you when systemd
  --user accepted but never ran the job, and `doctor` flags a spinning user
  manager and duplicated GUI instances (11 stale 0.2.x GUIs polling 45×/s
  had pinned `systemd --user` at 100 % CPU). `status` makes one systemctl
  call instead of two.

### Changed
- The embedded JACK client is now named **`SonusGrid-JACK`** (ports
  `SonusGrid-JACK:tx_NN/rx_NN`). It used to share the name of the PipeWire
  sink, so tools that pick a target by name (WirePlumber stream restore,
  `pw-play --target`) could route system audio into the JACK client — a
  node that never advances the clock — and the player would hang buffering.
- `config check` accepts 44.1 / 48 / 88.2 / 96 kHz.
- Engine log level defaults to `info` in the audio unit (was `debug`).
- Debian package: `Architecture: any`, native arm64 builds, depends on
  `pipewire-jack` and a session manager, recommends `qpwgraph`; minimum
  libadwaita 1.5 / GTK 4.12 / Python 3.11.

### Removed
- `config_dialog.py` (duplicate configuration UI) and the `avahi-utils`
  recommendation.

## [0.2.1] — 2026-09-19

### Fixed
- **Start-up reliability.** Runtime sockets and the RX FIFO moved from `/tmp`
  to `$XDG_RUNTIME_DIR/sonusgrid/`; `sonusgrid start` validates the config,
  clears systemd's *failed* state, starts without blocking and verifies both
  services (printing the journal tail when one fails); units no longer hit
  the start-rate limiter and the clock unit waits for the NIC to get an IPv4
  at boot; PipeWire is only restarted the first time the drop-in is applied.
- `ExecStop` unloads only SonusGrid's own PipeWire modules.
- GUI: start/stop no longer freezes the window and reports errors; status
  no longer shows *partial* when JACK is merely unavailable.

### Added
- `sonusgrid doctor`: runtime-dir, `audio` group / `/dev/ptp*`, failed-unit
  and PipeWire-JACK checks. `sonusgrid config check` validates the
  interface, PTP version and sample rate.
- `install.sh` / `uninstall.sh` one-shot installers.
- Statime source vendored in-tree; repository is self-contained.

## [0.2.0] — 2026-05-08

### Changed
- Project renamed from **Sonus** to **SonusGrid**.
- Native Rust full-duplex bridge (`sonusgrid-bridge`) replaces the ffmpeg
  pipeline (removes ~20 s of latency); embedded JACK client for DAWs.
- Network interface picker is mandatory; GUI lists interfaces with IPv4.
- udev rule grants the `audio` group access to `/dev/ptp*`.
- `libjack` resolves to PipeWire-JACK via an `ld.so.conf.d` drop-in.

## [0.1.0] — 2026-04-30

### Added
- First public release.
- `sonus` CLI: `start`, `stop`, `restart`, `status`, `config`, `logs`, `route`, `devices`, `doctor`.
- systemd user units `sonus-clock.service` and `sonus-audio.service`.
- PipeWire null-sink + ffmpeg bridge (`sonus_audio.service` ExecStart).
- ALSA PCM device `sonus` rendered from `~/.config/sonus/config.toml`.
- GTK4/libadwaita GUI (Python 3 + PyGObject).
- Bundled vendored builds of Statime (PTPv1/v2) and Inferno (ALSA plugin).
- Bilingual diagnostics in `sonus doctor` (Portuguese-Brazil + English).
- `.deb` package for Debian 12+, Ubuntu 22.04+, Linux Mint 21+.
- AppImage build for Fedora / Arch / openSUSE.
- Documentation set: README, INSTALL, USER_GUIDE, TROUBLESHOOTING, FAQ.
