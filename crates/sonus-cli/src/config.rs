// SPDX-License-Identifier: GPL-3.0-or-later
//! Sonus configuration — TOML schema and helpers.
//!
//! The config file lives at `~/.config/sonus/config.toml`. Every field has a
//! sensible default; missing fields fall back to defaults at parse time so old
//! configs keep working through schema evolutions.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

use crate::text::{dual_println, Lang};

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Config {
    pub schema_version: u32,
    pub device: Device,
    pub network: Network,
    pub ptp: Ptp,
    pub bridge: Bridge,
    pub ui: Ui,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Device {
    pub name: String,
    pub device_id: String,
    pub sample_rate: u32,
    pub rx_channels: u16,
    pub tx_channels: u16,
    pub rx_latency_ns: u64,
    pub tx_latency_ns: u64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Network {
    pub interface: String,
    pub bind_ip: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Ptp {
    pub version: String,
    pub domain: u8,
    pub priority1: u8,
    pub hardware_clock: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Bridge {
    pub mode: String,
    pub sink_name: String,
    pub sink_description: String,
    pub relay_channels: u16,
    /// Whether the bridge should also register a JACK client with N tx/rx
    /// ports for DAW use. When false, only the PulseAudio null-sink path is
    /// active — useful for users who don't run a DAW and want a leaner graph.
    pub jack_enabled: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(default)]
pub struct Ui {
    pub language: String,
    pub show_disclaimer_on_start: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            schema_version: 1,
            device: Device::default(),
            network: Network::default(),
            ptp: Ptp::default(),
            bridge: Bridge::default(),
            ui: Ui::default(),
        }
    }
}

impl Default for Device {
    fn default() -> Self {
        Self {
            name: "SonusGrid-Virtual".into(),
            device_id: String::new(),
            sample_rate: 48_000,
            rx_channels: 16,
            tx_channels: 16,
            // 4 ms is conservative on a non-RT kernel; 1 ms is too aggressive
            // and produces audible crackling under load.
            rx_latency_ns: 4_000_000,
            tx_latency_ns: 4_000_000,
        }
    }
}

impl Default for Network {
    fn default() -> Self {
        // No "auto": user must pick a NIC explicitly via the GUI or by editing
        // config.toml. doctor flags an empty interface as a hard error.
        Self {
            interface: String::new(),
            bind_ip: String::new(),
        }
    }
}

impl Default for Ptp {
    fn default() -> Self {
        Self {
            version: "v1".into(),
            domain: 0,
            priority1: 251,
            hardware_clock: "auto".into(),
        }
    }
}

impl Default for Bridge {
    fn default() -> Self {
        Self {
            mode: "null-sink".into(),
            sink_name: "SonusGrid".into(),
            sink_description: "SonusGrid (Dante-compatible)".into(),
            relay_channels: 16,
            jack_enabled: true,
        }
    }
}

impl Default for Ui {
    fn default() -> Self {
        Self {
            language: "auto".into(),
            show_disclaimer_on_start: true,
        }
    }
}

/// Default config file path. Returns `$XDG_CONFIG_HOME/sonusgrid/config.toml`
/// (or `~/.config/sonusgrid/config.toml` if XDG isn't set).
pub fn default_path() -> Option<PathBuf> {
    dirs::config_dir().map(|d| d.join("sonusgrid").join("config.toml"))
}

pub fn load(path: &Path) -> Result<Config> {
    if !path.exists() {
        return Ok(Config::default());
    }
    let text = std::fs::read_to_string(path)
        .with_context(|| format!("reading config {}", path.display()))?;
    let cfg: Config = toml::from_str(&text)
        .with_context(|| format!("parsing config {}", path.display()))?;
    Ok(cfg)
}

pub fn save(path: &Path, cfg: &Config) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text = toml::to_string_pretty(cfg)?;
    std::fs::write(path, text).with_context(|| format!("writing config {}", path.display()))?;
    Ok(())
}

pub fn cmd_show(path: &Path, _lang: Lang) -> Result<()> {
    let cfg = load(path)?;
    print!("{}", toml::to_string_pretty(&cfg)?);
    Ok(())
}

pub fn cmd_init(path: &Path, lang: Lang) -> Result<()> {
    if path.exists() {
        dual_println(
            &format!("config já existe em {}", path.display()),
            &format!("config already exists at {}", path.display()),
        );
        let _ = lang;
        return Ok(());
    }
    save(path, &Config::default())?;
    dual_println(
        &format!("config criado em {}", path.display()),
        &format!("config created at {}", path.display()),
    );
    Ok(())
}

pub fn cmd_edit(path: &Path, _lang: Lang) -> Result<()> {
    if !path.exists() {
        save(path, &Config::default())?;
    }
    let editor = std::env::var("EDITOR").unwrap_or_else(|_| "nano".into());
    let status = std::process::Command::new(editor).arg(path).status()?;
    if !status.success() {
        anyhow::bail!("editor exited with status {status}");
    }
    // Re-parse to surface syntax errors immediately.
    load(path)?;
    Ok(())
}

pub fn cmd_check(path: &Path, lang: Lang, quiet: bool) -> Result<()> {
    let cfg = load(path)?;
    let problems = crate::doctor::validate(&cfg);
    if problems.is_empty() {
        if !quiet {
            dual_println("config OK", "config OK");
        }
        return Ok(());
    }
    for p in &problems {
        dual_println(&p.pt, &p.en);
    }
    let _ = lang;
    // EX_CONFIG. The systemd units list this in RestartPreventExitStatus so a
    // broken/empty config doesn't turn into an endless 3-second restart loop
    // (seen: 130 000 restarts from a stray config in another user session).
    eprintln!("config check failed ({} problem(s))", problems.len());
    std::process::exit(78);
}
