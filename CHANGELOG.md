# Changelog

All notable changes to SonusGrid are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
