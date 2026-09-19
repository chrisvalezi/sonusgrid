// SPDX-License-Identifier: GPL-3.0-or-later
//! Lifecycle: start / stop / status / internal-exec wrappers.
//!
//! The CLI does not run a daemon of its own. Public commands shell out to
//! `systemctl --user`; the systemd units in turn invoke the hidden
//! `_internal-*-exec` subcommands so that all process-level logic stays in
//! Rust (signal handling, error messages, ALSA setup) and the unit files stay
//! one-line ExecStart lines.
//!
//! `start` is deliberately defensive: it validates the config before touching
//! systemd, clears any previous "failed" state (otherwise systemd's start-rate
//! limiter silently refuses to start the unit again), and then *verifies*
//! that both units actually came up, printing the journal tail if not.

use anyhow::{Context, Result};
use serde_json::json;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[cfg(target_os = "linux")]
use crate::audio;
use crate::config;
#[cfg(target_os = "linux")]
use crate::paths;
#[cfg(target_os = "linux")]
use crate::ptp;
use crate::text::{dual_println, Lang};

#[cfg(target_os = "macos")]
use libc;

const CLOCK_UNIT: &str = "sonusgrid-clock.service";
const AUDIO_UNIT: &str = "sonusgrid-audio.service";

/// How long `start` waits for both units to report `active` before giving
/// up and showing the journal. The clock unit's ExecStartPre may itself wait
/// for the NIC to get an IPv4 (see `internal_wait_network`), so this has to
/// be generous.
const START_VERIFY_TIMEOUT: Duration = Duration::from_secs(20);

/// Upper bound for `_internal-wait-network` (ExecStartPre of the clock unit).
const WAIT_NETWORK_TIMEOUT: Duration = Duration::from_secs(45);

/// How long the audio bridge waits for Statime to publish a PTP-locked
/// clock before opening the ALSA device anyway.
const WAIT_CLOCK_TIMEOUT: Duration = Duration::from_secs(60);

/// Legacy mode-switch command. The unified bridge now exposes BOTH the
/// PulseAudio null-sink (system audio) and a JACK client (DAW) at the same
/// time — there is no longer a "mode" to switch between. Kept as a friendly
/// no-op so that any old script or doc snippet referencing
/// `sonusgrid mode pulse|jack` still works.
pub fn switch_mode(_which: &str, _lang: Lang) -> Result<()> {
    dual_println(
        "Modo unificado: SonusGrid expõe sink Pulse (sistema) e cliente JACK (DAW) \
         simultaneamente. Não há mais 'modo' para trocar.",
        "Unified mode: SonusGrid exposes the Pulse sink (system audio) and a JACK \
         client (DAW) at the same time. There's no longer a 'mode' to switch.",
    );
    Ok(())
}

// ---------------------------------------------------------------------------
// start / stop
// ---------------------------------------------------------------------------

#[cfg(target_os = "linux")]
pub fn start(cfg_path: &Path, lang: Lang) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    if !cfg_path.exists() {
        config::save(cfg_path, &cfg)?;
        dual_println(
            &format!("config criado em {}", cfg_path.display()),
            &format!("created config at {}", cfg_path.display()),
        );
    }

    // 1. Fail fast, with a human message, before touching systemd.
    preflight(&cfg)?;

    // 2. Runtime dir for sockets/FIFOs + ALSA config for the engine.
    paths::ensure_runtime_dir()?;
    crate::alsa::install_user_asoundrc(&cfg)?;

    // 3. Make sure systemd sees the current unit files and the PipeWire
    //    drop-in, and forget any previous failure so the start-rate limiter
    //    doesn't refuse us.
    let _ = systemctl_user_quiet(&["daemon-reload"]);
    pipewire_clock_drop_in_reload(lang)?;
    let _ = systemctl_user_quiet(&["reset-failed", CLOCK_UNIT, AUDIO_UNIT]);

    // 4. Enable + start without blocking (the clock unit may wait for the
    //    NIC), then verify ourselves with a proper timeout.
    systemctl_user(&["enable", "--now", "--no-block", CLOCK_UNIT])?;
    systemctl_user(&["enable", "--now", "--no-block", AUDIO_UNIT])?;

    match wait_units_active(START_VERIFY_TIMEOUT) {
        WaitOutcome::Active => {
            dual_println("SonusGrid iniciado.", "SonusGrid started.");
            Ok(())
        }
        WaitOutcome::StillActivating => {
            dual_println(
                "SonusGrid está subindo (aguardando a interface de rede receber IP). \
                 Acompanhe com: sonusgrid status  /  sonusgrid logs -f",
                "SonusGrid is coming up (waiting for the network interface to get an IP). \
                 Follow with: sonusgrid status  /  sonusgrid logs -f",
            );
            Ok(())
        }
        WaitOutcome::Stuck => {
            eprintln!();
            dual_println(
                "O systemd --user aceitou o pedido mas não iniciou o serviço (job preso). \
                 Normalmente é o gerenciador sobrecarregado — veja: systemctl --user list-jobs ; top -p $(pgrep -u $USER -x systemd)",
                "systemd --user accepted the request but never started the service (stuck job). \
                 Usually the user manager is overloaded — see: systemctl --user list-jobs ; top -p $(pgrep -u $USER -x systemd)",
            );
            dual_println(
                "Dica: rode `sonusgrid doctor` — ele detecta GUIs antigas duplicadas e o gerenciador travado.",
                "Hint: run `sonusgrid doctor` — it detects duplicated old GUIs and a stuck manager.",
            );
            anyhow::bail!("systemd --user did not execute the start job")
        }
        WaitOutcome::Failed(unit) => {
            eprintln!();
            dual_println(
                &format!("{unit} falhou ao iniciar. Últimas linhas do log:"),
                &format!("{unit} failed to start. Last log lines:"),
            );
            print_journal_tail(&unit, 25);
            eprintln!();
            dual_println(
                "Dica: rode `sonusgrid doctor` para um diagnóstico completo.",
                "Hint: run `sonusgrid doctor` for a full diagnosis.",
            );
            anyhow::bail!("{unit} failed to start")
        }
    }
}

#[cfg(target_os = "macos")]
pub fn start(cfg_path: &Path, _lang: Lang) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    if !cfg_path.exists() {
        config::save(cfg_path, &cfg)?;
    }
    // On macOS the audio service is the HAL plugin running inside coreaudiod
    // — it's already loaded by the kernel and just waits for an app to open
    // the device. We only need to bring up the PTP clock daemon.
    launchctl_load("clock")?;
    dual_println("SonusGrid iniciado.", "SonusGrid started.");
    Ok(())
}

#[cfg(target_os = "linux")]
pub fn stop(_lang: Lang) -> Result<()> {
    let _ = systemctl_user_quiet(&["stop", AUDIO_UNIT]);
    let _ = systemctl_user_quiet(&["stop", CLOCK_UNIT]);
    // Clear a "failed" marker too, so `status` reads "inactive", not "failed".
    let _ = systemctl_user_quiet(&["reset-failed", CLOCK_UNIT, AUDIO_UNIT]);
    ptp::cleanup_usrvclock_sockets();
    dual_println("SonusGrid parado.", "SonusGrid stopped.");
    Ok(())
}

#[cfg(target_os = "macos")]
pub fn stop(_lang: Lang) -> Result<()> {
    let _ = launchctl_unload("clock");
    dual_println("SonusGrid parado.", "SonusGrid stopped.");
    Ok(())
}

/// Validate what `start` needs *before* asking systemd — a clear message
/// here beats a unit bouncing in the background.
#[cfg(target_os = "linux")]
fn preflight(cfg: &config::Config) -> Result<()> {
    let iface = cfg.network.interface.trim();
    if iface.is_empty() {
        dual_println(
            "Nenhuma interface de rede selecionada. Abra a GUI (Configuração) ou rode: \
             sonusgrid config edit",
            "No network interface selected. Open the GUI (Configuration) or run: \
             sonusgrid config edit",
        );
        anyhow::bail!("network.interface is empty");
    }
    if !Path::new(&format!("/sys/class/net/{iface}")).exists() {
        let available = list_interfaces().join(", ");
        dual_println(
            &format!("Interface '{iface}' não existe. Disponíveis: {available}"),
            &format!("Interface '{iface}' does not exist. Available: {available}"),
        );
        anyhow::bail!("network.interface '{iface}' not found");
    }
    if crate::alsa::interface_ipv4(iface).is_none() {
        dual_println(
            &format!("Aviso: '{iface}' ainda não tem IPv4 — o serviço vai esperar até {}s por um.",
                WAIT_NETWORK_TIMEOUT.as_secs()),
            &format!("Warning: '{iface}' has no IPv4 yet — the service will wait up to {}s for one.",
                WAIT_NETWORK_TIMEOUT.as_secs()),
        );
    }
    Ok(())
}

#[cfg(target_os = "linux")]
pub fn list_interfaces() -> Vec<String> {
    let mut v: Vec<String> = std::fs::read_dir("/sys/class/net")
        .map(|rd| {
            rd.flatten()
                .map(|e| e.file_name().to_string_lossy().to_string())
                .filter(|n| n != "lo")
                .collect()
        })
        .unwrap_or_default();
    v.sort();
    v
}

#[cfg(target_os = "linux")]
enum WaitOutcome {
    Active,
    StillActivating,
    /// The start job is queued but systemd --user hasn't executed it.
    Stuck,
    Failed(String),
}

#[cfg(target_os = "linux")]
fn wait_units_active(timeout: Duration) -> WaitOutcome {
    let t0 = Instant::now();
    loop {
        let (clock, audio) = unit_states();
        if clock == "failed" {
            return WaitOutcome::Failed(CLOCK_UNIT.into());
        }
        if audio == "failed" {
            return WaitOutcome::Failed(AUDIO_UNIT.into());
        }
        if clock == "active" && audio == "active" {
            // The bridge is `Type=exec`, so "active" means the process is
            // up. Give it a moment to open ALSA before we declare victory,
            // so an immediate crash still shows up as a failure here.
            std::thread::sleep(Duration::from_millis(1500));
            if unit_state(AUDIO_UNIT) == "active" && unit_state(CLOCK_UNIT) == "active" {
                return WaitOutcome::Active;
            }
            continue;
        }
        if t0.elapsed() > timeout {
            // "inactive" after all this time means systemd never even ran the
            // job — the user manager is stuck/overloaded, not the network.
            if clock == "inactive" {
                return WaitOutcome::Stuck;
            }
            return WaitOutcome::StillActivating;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

#[cfg(target_os = "linux")]
fn print_journal_tail(unit: &str, lines: usize) {
    let _ = Command::new("journalctl")
        .args(["--user", "-u", unit, "--no-pager", "-n", &lines.to_string(), "-o", "cat"])
        .status();
}

// ---------------------------------------------------------------------------
// status
// ---------------------------------------------------------------------------

pub fn status(cfg_path: &Path, _lang: Lang, json_out: bool) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    let (clock_state, audio_state) = unit_states();
    let clock = clock_state == "active";
    let audio = audio_state == "active";
    #[cfg(target_os = "linux")]
    let sink_loaded = audio::sink_exists(&cfg.bridge.sink_name);
    #[cfg(target_os = "macos")]
    let sink_loaded = std::path::Path::new("/Library/Audio/Plug-Ins/HAL/SonusGrid.driver").exists();
    // The unified bridge embeds the JACK client; if the bridge is up, the
    // JACK client is up. We probe pw-cli for a node named "SonusGrid" with
    // client.api == jack to confirm the JACK client registered successfully.
    #[cfg(target_os = "linux")]
    let jack_active = audio && jack_client_present();
    #[cfg(target_os = "macos")]
    let jack_active = false;
    #[cfg(target_os = "linux")]
    let ptp_obs = if clock { ptp::observe() } else { None };
    #[cfg(target_os = "macos")]
    let ptp_obs: Option<serde_json::Value> = None;

    if json_out {
        let val = json!({
            "version": env!("CARGO_PKG_VERSION"),
            "config": cfg_path.display().to_string(),
            "clock_active": clock,
            "audio_active": audio,
            "clock_state": clock_state,
            "audio_state": audio_state,
            "jack_active": jack_active,
            "sink_present": sink_loaded,
            "mode": "unified",
            "device_name": cfg.device.name,
            "interface": cfg.network.interface,
            "ptp_version": cfg.ptp.version,
            "ptp": ptp_obs,
        });
        println!("{}", serde_json::to_string_pretty(&val)?);
        return Ok(());
    }

    println!("SonusGrid {}\n", env!("CARGO_PKG_VERSION"));
    println!("  config         : {}", cfg_path.display());
    println!("  device name    : {}", cfg.device.name);
    println!("  network iface  : {}", cfg.network.interface);
    println!("  ptp version    : {}", cfg.ptp.version);
    println!("  clock service  : {}", clock_state);
    println!("  audio service  : {}", audio_state);
    println!("  PipeWire sink  : {}", on_off(sink_loaded));
    println!("  JACK client    : {}", on_off(jack_active));
    #[cfg(target_os = "linux")]
    if let Some(p) = &ptp_obs {
        let offset = p
            .offset_ns
            .map(|o| format!(", offset {:+.1} µs", o / 1000.0))
            .unwrap_or_default();
        let gm = p
            .grandmaster
            .as_deref()
            .map(|g| format!(", master {g}"))
            .unwrap_or_default();
        println!(
            "  PTP lock       : {} ({}{offset}{gm})",
            if p.locked { "locked" } else { "acquiring" },
            p.state.to_lowercase()
        );
    }
    if clock_state == "failed" || audio_state == "failed" {
        println!();
        dual_println(
            "Um serviço falhou. Veja: sonusgrid logs   |   sonusgrid doctor",
            "A service failed. See: sonusgrid logs   |   sonusgrid doctor",
        );
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn jack_client_present() -> bool {
    // Probe: pw-cli list nodes for one with `client.api = "jack"` AND
    // `node.name = "SonusGrid"` — that's our embedded JACK client (the
    // null-sink with the same name has no client.api property). The
    // boundaries between PipeWire object blocks aren't perfectly machine-
    // readable from pw-cli's text format, so we just scan the whole output
    // line by line and flip both flags when we see them; an `id` line
    // resets them.
    let out = match Command::new("pw-cli")
        .args(["list-objects", "Node"])
        .output()
    {
        Ok(o) if o.status.success() => o,
        _ => return false,
    };
    let s = String::from_utf8_lossy(&out.stdout);
    let mut has_name = false;
    let mut is_jack = false;
    for line in s.lines() {
        let trimmed = line.trim_start();
        if trimmed.starts_with("id ") && trimmed.contains("PipeWire:Interface:Node") {
            if has_name && is_jack { return true; }
            has_name = false;
            is_jack = false;
        }
        if trimmed.contains("node.name = \"SonusGrid\"") {
            has_name = true;
        }
        if trimmed.contains("client.api = \"jack\"") {
            is_jack = true;
        }
    }
    has_name && is_jack
}

fn on_off(b: bool) -> &'static str {
    if b {
        "active"
    } else {
        "inactive"
    }
}

/// Both unit states with a single `systemctl` round-trip (the GUI polls this
/// every 2 s; keep the load on the user manager minimal).
#[cfg(target_os = "linux")]
pub fn unit_states() -> (String, String) {
    let out = Command::new("systemctl")
        .args(["--user", "is-active", CLOCK_UNIT, AUDIO_UNIT])
        .stderr(Stdio::null())
        .output();
    match out {
        Ok(o) => {
            let s = String::from_utf8_lossy(&o.stdout);
            let mut it = s.lines().map(|l| l.trim().to_string());
            let a = it.next().filter(|x| !x.is_empty()).unwrap_or_else(|| "unknown".into());
            let b = it.next().filter(|x| !x.is_empty()).unwrap_or_else(|| "unknown".into());
            (a, b)
        }
        Err(_) => ("unknown".into(), "unknown".into()),
    }
}

#[cfg(target_os = "macos")]
pub fn unit_states() -> (String, String) {
    (unit_state(CLOCK_UNIT), unit_state(AUDIO_UNIT))
}

/// `active`, `activating`, `inactive`, `failed`, `deactivating` … as
/// reported by `systemctl --user is-active`. Returns "unknown" if systemd
/// can't be reached (no user session bus).
#[cfg(target_os = "linux")]
pub fn unit_state(unit: &str) -> String {
    let out = Command::new("systemctl")
        .args(["--user", "is-active", unit])
        .stderr(Stdio::null())
        .output();
    match out {
        Ok(o) => {
            let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
            if s.is_empty() { "unknown".into() } else { s }
        }
        Err(_) => "unknown".into(),
    }
}

#[cfg(target_os = "macos")]
pub fn unit_state(unit: &str) -> String {
    if unit_active(unit) { "active".into() } else { "inactive".into() }
}

#[cfg(target_os = "macos")]
pub fn unit_active(unit: &str) -> bool {
    // launchctl print returns nonzero if the label isn't loaded.
    // We use `print` instead of `list` because list's exit codes are unreliable
    // across macOS versions.
    let label = unit.trim_end_matches(".service");
    let label = format!("gui/{}/io.sonusgrid.{}", users_uid(), label.replace("sonusgrid-", ""));
    Command::new("launchctl")
        .args(["print", &label])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[cfg(target_os = "macos")]
fn users_uid() -> u32 {
    // The current effective user. macOS user agents live under gui/<uid>/.
    unsafe { libc::geteuid() }
}

#[cfg(target_os = "linux")]
fn systemctl_user(args: &[&str]) -> Result<()> {
    let status = Command::new("systemctl")
        .arg("--user")
        .args(args)
        .status()
        .context("invoking systemctl --user")?;
    if !status.success() {
        anyhow::bail!("systemctl --user {:?} failed: {}", args, status);
    }
    Ok(())
}

/// Same as `systemctl_user` but swallows stdout/stderr — for best-effort
/// housekeeping calls where a non-zero exit is expected sometimes.
#[cfg(target_os = "linux")]
fn systemctl_user_quiet(args: &[&str]) -> Result<()> {
    let status = Command::new("systemctl")
        .arg("--user")
        .args(args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .context("invoking systemctl --user")?;
    if !status.success() {
        anyhow::bail!("systemctl --user {:?} failed: {}", args, status);
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn launchctl_load(label: &str) -> Result<()> {
    let plist = format!("/Library/LaunchDaemons/io.sonusgrid.{label}.plist");
    let _ = Command::new("launchctl")
        .args(["bootstrap", "system", &plist])
        .status();
    let _ = Command::new("launchctl")
        .args(["enable", &format!("system/io.sonusgrid.{label}")])
        .status();
    let _ = Command::new("launchctl")
        .args(["kickstart", "-k", &format!("system/io.sonusgrid.{label}")])
        .status();
    Ok(())
}

#[cfg(target_os = "macos")]
fn launchctl_unload(label: &str) -> Result<()> {
    let plist = format!("/Library/LaunchDaemons/io.sonusgrid.{label}.plist");
    let _ = Command::new("launchctl")
        .args(["bootout", "system", &plist])
        .status();
    Ok(())
}

#[cfg(target_os = "linux")]
fn pipewire_clock_drop_in_reload(_lang: Lang) -> Result<()> {
    // The drop-in is shipped by the package at /usr/lib/systemd/user/
    // pipewire.service.d/sonusgrid-clock.conf. Earlier releases restarted
    // PipeWire on *every* start — which killed every app's audio and, worse,
    // took sonusgrid-audio.service down with it (BindsTo=pipewire.service)
    // right in the middle of starting. Now we only restart PipeWire once,
    // the first time the drop-in isn't yet part of the running unit.
    const DROP_IN: &str = "/usr/lib/systemd/user/pipewire.service.d/sonusgrid-clock.conf";
    if !Path::new(DROP_IN).exists() {
        return Ok(());
    }
    let out = Command::new("systemctl")
        .args(["--user", "show", "pipewire.service", "-p", "DropInPaths", "--value"])
        .output();
    let loaded = match out {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).contains(DROP_IN),
        _ => true, // can't tell — don't restart anything on a guess
    };
    if !loaded {
        dual_println(
            "Aplicando drop-in do PipeWire (só na primeira vez)…",
            "Applying PipeWire drop-in (first time only)…",
        );
        let _ = systemctl_user_quiet(&["daemon-reload"]);
        let _ = systemctl_user_quiet(&["restart", "pipewire.service", "pipewire-pulse.service"]);
        std::thread::sleep(Duration::from_millis(800));
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn pipewire_clock_drop_in_reload(_lang: Lang) -> Result<()> {
    // No equivalent on macOS — the HAL plugin runs in coreaudiod with the
    // capabilities it needs by virtue of being a code-signed system audio
    // plug-in.
    Ok(())
}

// --- internal subcommands invoked by systemd unit ExecStart -----------------

#[cfg(target_os = "macos")]
pub fn internal_statime_exec(_cfg_path: &Path) -> Result<()> {
    // macOS uses launchd directly to invoke /usr/local/libexec/sonusgrid/
    // statime-macos. This subcommand is effectively a no-op there.
    anyhow::bail!("_internal-statime-exec is Linux-only; on macOS launchd runs statime-macos directly")
}

#[cfg(target_os = "macos")]
pub fn internal_bridge_exec(_cfg_path: &Path) -> Result<()> {
    anyhow::bail!("_internal-bridge-exec is Linux-only; on macOS the HAL plugin handles audio")
}

#[cfg(target_os = "macos")]
pub fn internal_bridge_stop(_cfg_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(target_os = "macos")]
pub fn internal_wait_network(_cfg_path: &Path) -> Result<()> {
    Ok(())
}

/// ExecStartPre of the clock unit: block (bounded) until the configured NIC
/// has an IPv4 address. At boot the user session often comes up before DHCP
/// has finished; without this, Statime fails to bind, systemd retries a few
/// times, hits its start-rate limit and gives up — the classic "SonusGrid
/// never starts after reboot". Always exits 0: if the address never shows
/// up, Statime itself will fail with a clear error and be restarted.
#[cfg(target_os = "linux")]
pub fn internal_wait_network(cfg_path: &Path) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    let iface = cfg.network.interface.trim().to_string();
    if iface.is_empty() {
        eprintln!("[sonusgrid] no network interface configured; not waiting");
        return Ok(());
    }
    let t0 = Instant::now();
    let mut warned = false;
    loop {
        if crate::alsa::interface_ipv4(&iface).is_some() {
            if warned {
                eprintln!("[sonusgrid] {iface} has an IPv4 now ({:.0}s)", t0.elapsed().as_secs_f32());
            }
            return Ok(());
        }
        if t0.elapsed() > WAIT_NETWORK_TIMEOUT {
            eprintln!("[sonusgrid] {iface} still has no IPv4 after {}s; continuing anyway",
                WAIT_NETWORK_TIMEOUT.as_secs());
            return Ok(());
        }
        if !warned {
            eprintln!("[sonusgrid] waiting for {iface} to get an IPv4 address…");
            warned = true;
        }
        std::thread::sleep(Duration::from_secs(1));
    }
}

#[cfg(target_os = "linux")]
pub fn internal_statime_exec(cfg_path: &Path) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    paths::ensure_runtime_dir()?;
    ptp::cleanup_usrvclock_sockets();
    let cfg_file = ptp::render_statime_config(&cfg)?;
    let bin = locate_statime();
    let err = Command::new(&bin).args(["-c", cfg_file.to_str().unwrap()]).exec_replace();
    Err(err.context(format!("execv {} failed", bin.display())))
}

#[cfg(target_os = "linux")]
pub fn internal_bridge_exec(cfg_path: &Path) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    paths::ensure_runtime_dir()?;
    // Re-generate ~/.config/alsa/sonusgrid.conf on every service start. This
    // re-reads the live IPv4 of the configured interface (DHCP-renewed
    // addresses) so the engine never tries to bind to a stale IP and panic
    // with "No such device" — which is what was happening at boot when the
    // service auto-started before the user invoked `sonusgrid start`.
    crate::alsa::install_user_asoundrc(&cfg)?;
    audio::ensure_sink(&cfg)?;
    audio::ensure_source(&cfg)?;
    // Don't hand the ALSA device to the bridge until Statime has a PTP
    // lock; otherwise the engine times out waiting for the clock.
    ptp::wait_for_clock(WAIT_CLOCK_TIMEOUT);
    // The bridge owns plug:sonusgrid full-duplex. When it exits, systemd
    // restarts us. The capture leg keeps the engine's RX subscriber alive so
    // Dante Controller shows RX rows.
    audio::run_relay_foreground(&cfg)
}

#[cfg(target_os = "linux")]
pub fn internal_bridge_stop(cfg_path: &Path) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    audio::unload_sink(&cfg);
    Ok(())
}

fn locate_statime() -> std::path::PathBuf {
    // Try installed location first, then fall back to vendored debug build.
    for c in [
        "/usr/libexec/sonusgrid/statime",
        "/usr/local/libexec/sonusgrid/statime",
    ] {
        if std::path::Path::new(c).exists() {
            return c.into();
        }
    }
    // Last resort: search PATH (covers AppImage's $APPDIR/usr/libexec/sonusgrid).
    if let Ok(p) = std::process::Command::new("which")
        .arg("statime")
        .output()
    {
        if p.status.success() {
            let s = String::from_utf8_lossy(&p.stdout).trim().to_string();
            if !s.is_empty() {
                return s.into();
            }
        }
    }
    "/usr/libexec/sonusgrid/statime".into()
}

// Tiny helper: replace current process with another binary (execv-style).
trait CommandExecExt {
    fn exec_replace(&mut self) -> anyhow::Error;
}
impl CommandExecExt for Command {
    fn exec_replace(&mut self) -> anyhow::Error {
        use std::os::unix::process::CommandExt;
        anyhow::Error::from(self.exec())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn on_off_is_stable() {
        assert_eq!(on_off(true), "active");
        assert_eq!(on_off(false), "inactive");
    }
}
