// SPDX-License-Identifier: Apache-2.0 OR MIT
//! Statime PTP daemon for SonusGrid on macOS.
//!
//! Wraps the platform-agnostic `statime` core with macOS-specific clock
//! adjustment via `clock_settime(CLOCK_REALTIME)` and a usrvclock UNIX socket
//! for the HAL plugin to read PTP-disciplined time.
//!
//! Status: skeleton. The TOML parser and the launchd-friendly main loop are
//! in place; the actual statime core is not yet wired in (mirrors the
//! upstream `statime-linux` binary structure, minus systemd integration).

use anyhow::Result;
use clap::Parser;
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "statime-macos",
    about = "PTPv1/v2 daemon for SonusGrid on macOS",
    version
)]
struct Cli {
    /// Configuration file path (TOML).
    #[arg(short, long, default_value = "/etc/sonusgrid/clock.toml")]
    config: PathBuf,

    /// Verbose logging.
    #[arg(short, long)]
    verbose: bool,
}

#[derive(Deserialize, Debug)]
#[serde(default)]
struct Config {
    loglevel: String,
    sdo_id: u8,
    domain: u8,
    priority1: u8,
    virtual_system_clock: bool,
    usrvclock_export: bool,
    usrvclock_socket: PathBuf,
    port: Vec<PortConfig>,
}

#[derive(Deserialize, Debug)]
#[serde(default)]
struct PortConfig {
    interface: String,
    network_mode: String,
    hardware_clock: String,
    protocol_version: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            loglevel: "info".into(),
            sdo_id: 0,
            domain: 0,
            priority1: 251,
            virtual_system_clock: true,
            usrvclock_export: true,
            usrvclock_socket: PathBuf::from("/var/run/sonusgrid/usrvclock"),
            port: Vec::new(),
        }
    }
}

impl Default for PortConfig {
    fn default() -> Self {
        Self {
            interface: String::new(),
            network_mode: "ipv4".into(),
            hardware_clock: "auto".into(),
            protocol_version: "PTPv1".into(),
        }
    }
}

fn main() -> Result<()> {
    let args = Cli::parse();
    let level = if args.verbose { "debug" } else { "info" };
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or(level)).init();

    log::info!(
        "statime-macos starting (config = {})",
        args.config.display()
    );

    let cfg_text = std::fs::read_to_string(&args.config)?;
    let cfg: Config = toml::from_str(&cfg_text)?;

    if cfg.port.is_empty() {
        anyhow::bail!("no [[port]] section in {} — refusing to start", args.config.display());
    }

    log::info!("domain={} priority1={} ports={:?}",
        cfg.domain, cfg.priority1, cfg.port.iter().map(|p| &p.interface).collect::<Vec<_>>());

    // TODO(phase-B): bring in statime + timestamped-socket + clock-steering
    //   - subscribe to PTP multicast on each [[port]].interface
    //   - run BMCA, slave/master state machine
    //   - on offset measurement: clock_settime(CLOCK_REALTIME) +
    //     ntp_adjtime, then write the disciplined timestamp to the
    //     usrvclock UNIX socket so the HAL plugin can sample it
    //   - on SIGTERM (launchd stop): close socket, restore freerun

    log::warn!("statime-macos is a skeleton — exiting after parse-only validation");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_minimal_config() {
        let toml_text = r#"
            loglevel = "info"
            domain = 0
            priority1 = 251
            virtual_system_clock = true
            usrvclock_export = true
            usrvclock_socket = "/var/run/sonusgrid/usrvclock"
            [[port]]
            interface = "en0"
            network_mode = "ipv4"
            hardware_clock = "auto"
            protocol_version = "PTPv1"
        "#;
        let cfg: Config = toml::from_str(toml_text).unwrap();
        assert_eq!(cfg.port.len(), 1);
        assert_eq!(cfg.port[0].interface, "en0");
    }
}
