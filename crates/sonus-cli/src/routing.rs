// SPDX-License-Identifier: GPL-3.0-or-later
//! `sonus route` and `sonus devices` — discoverability helpers.

use anyhow::Result;
use std::path::Path;
use std::process::Command;

use crate::config;
use crate::text::{dual_println, Lang};

pub fn open_pavucontrol(_cfg_path: &Path, lang: Lang) -> Result<()> {
    let bin = if which("pavucontrol") {
        "pavucontrol"
    } else if which("pwvucontrol") {
        "pwvucontrol"
    } else if which("qpwgraph") {
        "qpwgraph"
    } else {
        dual_println(
            "Nenhum mixer gráfico encontrado. Instale: sudo apt install pavucontrol",
            "No graphical mixer found. Install: sudo apt install pavucontrol",
        );
        let _ = lang;
        return Ok(());
    };
    let _ = Command::new(bin).spawn()?;
    Ok(())
}

pub fn list_devices(cfg_path: &Path, _lang: Lang) -> Result<()> {
    // Minimal: use avahi-browse if present (covers Dante mDNS).
    let _ = config::load(cfg_path)?;
    if !which("avahi-browse") {
        dual_println(
            "avahi-browse não encontrado. Instale: sudo apt install avahi-utils",
            "avahi-browse not found. Install: sudo apt install avahi-utils",
        );
        return Ok(());
    }
    let status = Command::new("avahi-browse")
        .args(["-t", "-r", "_netaudio-cmc._udp"])
        .status()?;
    if !status.success() {
        anyhow::bail!("avahi-browse exited {status}");
    }
    Ok(())
}

fn which(bin: &str) -> bool {
    Command::new("which")
        .arg(bin)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}
