// SPDX-License-Identifier: GPL-3.0-or-later
//! SonusGrid — top-level CLI dispatcher.

use anyhow::Result;
use clap::{Parser, Subcommand};

#[cfg(target_os = "linux")]
mod alsa;
#[cfg(target_os = "linux")]
mod audio;
mod config;
mod doctor;
mod logs;
mod paths;
#[cfg(target_os = "linux")]
mod ptp;
mod routing;
mod runtime;
mod text;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const DISCLAIMER: &str =
    "SonusGrid is compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.";

#[derive(Parser)]
#[command(
    name = "sonusgrid",
    version = VERSION,
    about = "Linux audio app compatible with Dante audio networks",
    long_about = "SonusGrid turns a Linux box into an audio endpoint that interoperates\n\
                  with Dante audio networks. It bundles a PTP clock daemon, an ALSA\n\
                  plugin, and a PipeWire bridge.\n\n\
                  Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd."
)]
struct Cli {
    #[command(subcommand)]
    command: Cmd,

    /// Override config file path.
    #[arg(long, global = true)]
    config: Option<std::path::PathBuf>,

    /// Force message language (pt | en). Defaults to $LANG.
    #[arg(long, global = true, value_parser = ["pt", "en", "auto"])]
    lang: Option<String>,

    /// Verbose output.
    #[arg(short, long, global = true)]
    verbose: bool,
}

#[derive(Subcommand)]
enum Cmd {
    /// Start clock (PTP) and audio bridge.
    Start,
    /// Stop audio bridge and clock.
    Stop,
    /// Stop then start.
    Restart,
    /// Switch the audio path: 'pulse' (casual / OS-wide) or 'jack' (DAW low-latency).
    Mode {
        #[arg(value_parser = ["pulse", "jack"])]
        which: String,
    },
    /// Show clock sync, sink, ALSA device, bridge PID.
    Status {
        /// Emit machine-readable JSON instead of human text.
        #[arg(long)]
        json: bool,
    },
    /// Configuration management.
    #[command(subcommand)]
    Config(ConfigCmd),
    /// Tail journalctl --user for our units.
    Logs {
        /// Which unit to follow.
        #[arg(value_parser = ["clock", "audio", "all"], default_value = "all")]
        unit: String,
        /// Follow (tail -f).
        #[arg(short, long)]
        follow: bool,
    },
    /// Open pavucontrol focused on the SonusGrid sink.
    Route,
    /// List Dante channels currently visible on the network.
    Devices,
    /// Run end-to-end diagnostics (NTP, PTP, ALSA, PipeWire).
    Doctor,
    /// Print version and disclaimer.
    Version,

    // Internal subcommands invoked by systemd units. Hidden from help.
    #[command(name = "_internal-statime-exec", hide = true)]
    InternalStatimeExec,
    #[command(name = "_internal-bridge-exec", hide = true)]
    InternalBridgeExec,
    #[command(name = "_internal-bridge-stop", hide = true)]
    InternalBridgeStop,
    #[command(name = "_internal-wait-network", hide = true)]
    InternalWaitNetwork,
}

#[derive(Subcommand)]
enum ConfigCmd {
    /// Print resolved config.
    Show,
    /// Open $EDITOR on the config file (creates if missing).
    Edit,
    /// Validate config and current system state.
    Check {
        /// Quiet mode — used by ExecStartPre.
        #[arg(long)]
        quiet: bool,
    },
    /// Write the default config file (does not overwrite).
    Init,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let lang = text::resolve_lang(cli.lang.as_deref());
    let cfg_path = cli
        .config
        .unwrap_or_else(|| config::default_path().expect("HOME must be set"));

    match cli.command {
        Cmd::Start => runtime::start(&cfg_path, lang),
        Cmd::Stop => runtime::stop(lang),
        Cmd::Restart => {
            runtime::stop(lang)?;
            runtime::start(&cfg_path, lang)
        }
        Cmd::Mode { which } => runtime::switch_mode(&which, lang),
        Cmd::Status { json } => runtime::status(&cfg_path, lang, json),
        Cmd::Config(c) => match c {
            ConfigCmd::Show => config::cmd_show(&cfg_path, lang),
            ConfigCmd::Edit => config::cmd_edit(&cfg_path, lang),
            ConfigCmd::Check { quiet } => config::cmd_check(&cfg_path, lang, quiet),
            ConfigCmd::Init => config::cmd_init(&cfg_path, lang),
        },
        Cmd::Logs { unit, follow } => logs::follow(&unit, follow),
        Cmd::Route => routing::open_pavucontrol(&cfg_path, lang),
        Cmd::Devices => routing::list_devices(&cfg_path, lang),
        Cmd::Doctor => doctor::run(&cfg_path, lang),
        Cmd::Version => {
            println!("sonusgrid {VERSION}");
            println!("{DISCLAIMER}");
            Ok(())
        }
        #[cfg(target_os = "linux")]
        Cmd::InternalStatimeExec => runtime::internal_statime_exec(&cfg_path),
        #[cfg(target_os = "linux")]
        Cmd::InternalBridgeExec => runtime::internal_bridge_exec(&cfg_path),
        #[cfg(target_os = "linux")]
        Cmd::InternalBridgeStop => runtime::internal_bridge_stop(&cfg_path),
        #[cfg(target_os = "linux")]
        Cmd::InternalWaitNetwork => runtime::internal_wait_network(&cfg_path),
        #[cfg(target_os = "macos")]
        Cmd::InternalStatimeExec | Cmd::InternalBridgeExec | Cmd::InternalBridgeStop | Cmd::InternalWaitNetwork => {
            anyhow::bail!("internal subcommands are Linux-only — macOS uses launchd and the HAL plugin")
        }
    }
}
