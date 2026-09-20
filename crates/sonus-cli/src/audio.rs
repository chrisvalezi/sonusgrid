// SPDX-License-Identifier: GPL-3.0-or-later
//! PipeWire null-sink + virtual-source + native Rust full-duplex bridge.
//!
//! Lifecycle (run by `sonusgrid-audio.service`):
//! 1. `ensure_sink` — load `module-null-sink` named `<sink_name>` (TX side:
//!    apps target this sink to send audio to the Dante network).
//! 2. `ensure_source` — load `module-pipe-source` named `<sink_name>_RX`
//!    (RX side: a virtual source that recording apps can capture from).
//! 3. `run_relay_foreground` — exec the `sonusgrid-bridge` binary (native
//!    Rust) which opens `plug:sonusgrid` for BOTH playback AND capture in
//!    one process. The single full-duplex open is what makes the SonusGrid
//!    Engine initialise its RX subscriber so Dante Controller shows the
//!    receivable rows. Replaced the previous ffmpeg pipeline whose
//!    multi-input demuxer cross-synchronised TX and RX timestamps and
//!    produced 20+ s of latency.
//! 4. `unload_sink` (ExecStop) — best-effort `pactl unload-module` for both.

use anyhow::{Context, Result};
use std::os::unix::process::CommandExt;
use std::process::Command;

use crate::config::Config;
use crate::paths;

/// Returns true if a sink with the given name is currently loaded.
pub fn sink_exists(name: &str) -> bool {
    let out = Command::new("pactl")
        .args(["list", "short", "sinks"])
        .output();
    let Ok(out) = out else { return false };
    if !out.status.success() {
        return false;
    }
    let s = String::from_utf8_lossy(&out.stdout);
    s.lines().any(|l| {
        let mut cols = l.split('\t');
        let _id = cols.next();
        cols.next().map(|n| n == name).unwrap_or(false)
    })
}

fn rx_source_name(cfg: &Config) -> String {
    format!("{}_RX", cfg.bridge.sink_name)
}

/// (Re)create the null-sink (TX side).
///
/// A stale sink/source pair that survived many bridge restarts was seen to
/// leave WirePlumber unable to link streams to the sink *by name* (players
/// hung buffering while `pw-play --target <id>` still worked). So we never
/// reuse a leftover module: tear it down and create a fresh one, always in
/// the same order (sink, then source).
///
/// SonusGrid is *opt-in*: `priority.session=0` keeps WirePlumber from
/// auto-promoting it to default output. If the user *chose* it as default
/// (configured default in WirePlumber state), WirePlumber restores that
/// choice as soon as the sink reappears — and we must not undo it. An
/// earlier version snapshotted the previous default and reverted to it,
/// which silently moved the desktop's audio away from Dante after every
/// bridge restart.
pub fn ensure_sink(cfg: &Config) -> Result<()> {
    if let Some(idx) = module_index_for("module-null-sink", "sink_name", &cfg.bridge.sink_name) {
        let _ = Command::new("pactl").args(["unload-module", &idx]).status();
        std::thread::sleep(std::time::Duration::from_millis(200));
    }

    // pipewire-pulse splits module args on whitespace and does not honour
    // "\ " escapes, so a description with spaces was silently truncated.
    // Replace spaces with non-breaking spaces to keep the text intact.
    let props = format!(
        "device.description={desc} priority.session=0 node.dont-reconnect=true",
        desc = cfg.bridge.sink_description.replace(' ', "\u{a0}")
    );
    let status = Command::new("pactl")
        .args([
            "load-module",
            "module-null-sink",
            &format!("sink_name={}", cfg.bridge.sink_name),
            &format!("sink_properties={props}"),
            &format!("rate={}", cfg.device.sample_rate),
            "channels=2",
            // Match the bridge's read format so PulseAudio doesn't run a
            // hidden s16→s32 resample-and-buffer step that introduced jitter
            // and ~20 ms underruns at the ALSA side.
            "format=s32le",
            // Don't pin the sink to 4 ms — under load that produces PA-side
            // jitter that swamps even a 16-period ALSA buffer. Letting PA
            // pick (~25 ms typical) gives the bridge more headroom; the
            // user-visible latency is still well under what ffmpeg gave us.
            //"latency_msec=4",
        ])
        .status()
        .context("loading PipeWire null-sink (pactl)")?;
    if !status.success() {
        anyhow::bail!("pactl load-module returned {}", status);
    }

    std::thread::sleep(std::time::Duration::from_millis(400));
    Ok(())
}

/// Load the virtual source (RX side) if not already present. Idempotent.
///
/// We use `module-pipe-source` with a FIFO under the per-user runtime dir
/// that the bridge writes into. PipeWire then exposes a regular Source that any recording app
/// (Audacity, OBS, ffmpeg-as-input) can capture from.
pub fn ensure_source(cfg: &Config) -> Result<()> {
    let src_name = rx_source_name(cfg);
    if let Some(idx) = module_index_for("module-pipe-source", "source_name", &src_name) {
        let _ = Command::new("pactl").args(["unload-module", &idx]).status();
        std::thread::sleep(std::time::Duration::from_millis(200));
    }

    let pipe_path = paths::rx_fifo_path(cfg).display().to_string();
    // Make sure stale FIFO is gone — pipe-source recreates if missing.
    let _ = std::fs::remove_file(&pipe_path);

    let props = format!(
        "device.description={desc}\u{a0}RX",
        desc = cfg.bridge.sink_description.replace(' ', "\u{a0}")
    );
    let status = Command::new("pactl")
        .args([
            "load-module",
            "module-pipe-source",
            &format!("source_name={}", src_name),
            &format!("source_properties={props}"),
            &format!("file={}", pipe_path),
            "format=s32le",
            &format!("rate={}", cfg.device.sample_rate),
            "channels=2",
        ])
        .status()
        .context("loading PipeWire pipe-source (pactl)")?;
    if !status.success() {
        anyhow::bail!("pactl load-module pipe-source returned {}", status);
    }
    Ok(())
}


/// Find the PipeWire/Pulse module index that owns `<key>=<value>` in its
/// argument string (e.g. `sink_name=SonusGrid`). Returns None if not loaded.
fn module_index_for(module: &str, key: &str, value: &str) -> Option<String> {
    let out = Command::new("pactl")
        .args(["list", "short", "modules"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let needle = format!("{key}={value}");
    let s = String::from_utf8_lossy(&out.stdout);
    for line in s.lines() {
        let mut cols = line.split('\t');
        let idx = cols.next()?;
        let name = cols.next().unwrap_or("");
        let args = cols.next().unwrap_or("");
        if name == module && args.split_whitespace().any(|a| a == needle) {
            return Some(idx.to_string());
        }
    }
    None
}

/// Unload *our* sink and source only. Earlier releases ran
/// `pactl unload-module module-null-sink`, which tears down every null-sink
/// the user has — including ones that have nothing to do with SonusGrid.
pub fn unload_sink(cfg: &Config) {
    if let Some(idx) = module_index_for("module-null-sink", "sink_name", &cfg.bridge.sink_name) {
        let _ = Command::new("pactl").args(["unload-module", &idx]).status();
    }
    if let Some(idx) = module_index_for("module-pipe-source", "source_name", &rx_source_name(cfg)) {
        let _ = Command::new("pactl").args(["unload-module", &idx]).status();
    }
    let _ = std::fs::remove_file(paths::rx_fifo_path(cfg));
}

/// Replace this process with `sonusgrid-bridge` running a *full-duplex*
/// bridge in two independent threads (TX and RX). This replaces the
/// previous ffmpeg-based bridge whose multi-input demuxer cross-synchronised
/// the live PulseAudio + ALSA inputs by timestamp, producing 20+ s of
/// latency and audible cracking.
///
/// The single-process full-duplex open is what keeps Inferno's RX
/// subscriber alive, which is what makes Dante Controller show RX channels.
pub fn run_relay_foreground(cfg: &Config) -> Result<()> {
    let rx_pipe = paths::rx_fifo_path(cfg).display().to_string();
    let chans = cfg.bridge.relay_channels.to_string();
    let rate = cfg.device.sample_rate.to_string();

    let bridge = locate_bridge();
    let mut cmd = Command::new(&bridge);
    // The engine's usrvclock client creates its own reply sockets in
    // `$TMPDIR`; keep them next to the server socket, inside the per-user
    // runtime dir, instead of `/tmp`. `INFERNO_CLOCK_PATH` is a belt-and-
    // braces fallback in case the rendered ALSA config is stale.
    let rt = paths::runtime_dir();
    cmd.env("TMPDIR", &rt);
    cmd.env("INFERNO_CLOCK_PATH", paths::clock_socket_path());
    cmd.args([
        "--sink-name", cfg.bridge.sink_name.as_str(),
        "--rx-pipe",   rx_pipe.as_str(),
        "--alsa",      "plug:sonusgrid",
        "--rate",      rate.as_str(),
        "--channels",  chans.as_str(),
        "--period",    "256",
    ]);
    // When jack_enabled = false, pass an empty client name to skip JACK
    // registration entirely. The bridge keeps the Pulse + ALSA path running.
    if !cfg.bridge.jack_enabled {
        cmd.args(["--jack-client", ""]);
    }
    let err = cmd.exec();
    Err(anyhow::anyhow!("execv {} failed: {err}", bridge.display()))
}

fn locate_bridge() -> std::path::PathBuf {
    for c in [
        "/usr/libexec/sonusgrid/sonusgrid-bridge",
        "/usr/local/libexec/sonusgrid/sonusgrid-bridge",
    ] {
        if std::path::Path::new(c).exists() {
            return c.into();
        }
    }
    "/usr/libexec/sonusgrid/sonusgrid-bridge".into()
}
