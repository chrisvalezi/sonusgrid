// SPDX-License-Identifier: GPL-3.0-or-later
//! `sonusgrid route` and `sonusgrid devices` — discoverability helpers.

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

#[cfg(target_os = "macos")]
pub fn list_devices(_cfg_path: &Path, _lang: Lang, json_out: bool) -> Result<()> {
    if json_out { println!("[]"); }
    anyhow::bail!("`devices` is not implemented on macOS yet")
}

#[cfg(target_os = "linux")]
pub fn list_devices(cfg_path: &Path, _lang: Lang, json_out: bool) -> Result<()> {
    let cfg = config::load(cfg_path)?;
    let iface = cfg.network.interface.trim();
    if iface.is_empty() {
        if json_out {
            println!("[]");
            return Ok(());
        }
        dual_println(
            "Nenhuma interface configurada — não dá para procurar dispositivos.",
            "No network interface configured — cannot browse for devices.",
        );
        anyhow::bail!("network.interface is empty");
    }
    let ip: std::net::Ipv4Addr = crate::alsa::interface_ipv4(iface)
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| anyhow::anyhow!("interface {iface} has no IPv4 address"))?;
    let devices = match crate::mdns::browse(ip, &cfg.device.name, std::time::Duration::from_millis(2500)) {
        Ok(d) => d,
        Err(e) if json_out => {
            eprintln!("[sonusgrid] mdns browse failed: {e}");
            Vec::new()
        }
        Err(e) => return Err(anyhow::anyhow!("mDNS browse on {iface} ({ip}) failed: {e}")),
    };
    if json_out {
        println!("{}", serde_json::to_string_pretty(&devices)?);
        return Ok(());
    }
    if devices.is_empty() {
        dual_println(
            &format!("Nenhum dispositivo Dante respondeu em {iface} ({ip})."),
            &format!("No Dante device answered on {iface} ({ip})."),
        );
        return Ok(());
    }
    println!("{:<28} {:<16} {:<24}", "NAME", "IP", "HOST");
    for d in &devices {
        println!(
            "{:<28} {:<16} {:<24}{}",
            d.name,
            d.ip,
            d.host,
            if d.is_self { "  (this computer)" } else { "" }
        );
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
