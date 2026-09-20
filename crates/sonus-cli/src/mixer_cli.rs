// SPDX-License-Identifier: GPL-3.0-or-later
//! `sonusgrid mixer …` — talk to the bridge's mixer over its Unix socket and
//! read the meters file. Same protocol the GUI uses.

use anyhow::{Context, Result};
use std::os::unix::net::UnixDatagram;
use std::time::Duration;

use crate::paths;

pub fn send(cmd: &str) -> Result<String> {
    let server = paths::mixer_socket_path();
    if !server.exists() {
        anyhow::bail!("mixer socket not found ({}) — is sonusgrid-audio.service running?", server.display());
    }
    let client_path = paths::runtime_dir().join(format!("mixer-client.{}", std::process::id()));
    let _ = std::fs::remove_file(&client_path);
    let sock = UnixDatagram::bind(&client_path).context("binding mixer client socket")?;
    let _ = sock.set_read_timeout(Some(Duration::from_secs(2)));
    let res = (|| {
        sock.send_to(cmd.as_bytes(), &server).context("sending to mixer socket")?;
        let mut buf = vec![0u8; 65536];
        let n = sock.recv(&mut buf).context("waiting for mixer reply")?;
        Ok(String::from_utf8_lossy(&buf[..n]).to_string())
    })();
    let _ = std::fs::remove_file(&client_path);
    res
}

/// One snapshot of the meters file: (channels, tx_peaks_db, rx_peaks_db).
pub fn meters() -> Result<(usize, Vec<f32>, Vec<f32>)> {
    let buf = std::fs::read(paths::meters_path()).context("reading meters file (bridge running?)")?;
    if buf.len() < 32 || u32::from_le_bytes(buf[0..4].try_into()?) != 0x584d4753 {
        anyhow::bail!("meters file has an unexpected format");
    }
    let ch = u32::from_le_bytes(buf[8..12].try_into()?) as usize;
    let f = |off: usize| -> f32 { f32::from_le_bytes(buf[off..off + 4].try_into().unwrap()) };
    let to_db = |v: f32| if v <= 0.0 { -80.0 } else { (20.0 * v.log10()).max(-80.0) };
    let tx: Vec<f32> = (0..ch).map(|c| to_db(f(32 + c * 4))).collect();
    let rx: Vec<f32> = (0..ch).map(|c| to_db(f(32 + 256 * 4 + c * 4))).collect();
    let _ = to_db; // (master peaks live after the mute bytes; the GUI reads them)
    Ok((ch, tx, rx))
}

pub fn run(args: &[String], json: bool) -> Result<()> {
    let cmd = match args {
        [] | [_] if args.first().map(|s| s == "show").unwrap_or(true) => "get".to_string(),
        [s, db] if s == "master" => format!("master {db}"),
        [s, v] if s == "mute" => format!("mmute {}", on(v)),
        [s, dir, ch, db] if s == "set" => format!("set {dir} {} {db}", idx(ch)?),
        [s, dir, ch, v] if s == "mute" => format!("mute {dir} {} {}", idx(ch)?, on(v)),
        [s] if s == "meters" => {
            let (ch, tx, rx) = meters()?;
            if json {
                println!("{}", serde_json::json!({"channels": ch, "tx_peak_db": tx, "rx_peak_db": rx}));
            } else {
                for c in 0..ch { println!("ch {:>3}   TX {:>6.1} dB   RX {:>6.1} dB", c + 1, tx[c], rx[c]); }
            }
            return Ok(());
        }
        _ => anyhow::bail!("usage: sonusgrid mixer [show | master <dB> | mute on|off | set tx|rx <ch> <dB> | mute tx|rx <ch> on|off | meters]"),
    };
    let reply = send(&cmd)?;
    if json {
        println!("{reply}");
        return Ok(());
    }
    let v: serde_json::Value = serde_json::from_str(&reply).context("parsing mixer reply")?;
    if let Some(e) = v.get("error") { anyhow::bail!("{}", e); }
    let ch = v["channels"].as_u64().unwrap_or(0) as usize;
    println!("master  {:>6.1} dB{}", v["master_db"].as_f64().unwrap_or(0.0),
        if v["master_mute"].as_bool().unwrap_or(false) { "  [MUTE]" } else { "" });
    for dir in ["tx", "rx"] {
        let g = &v[dir]["gain_db"]; let m = &v[dir]["mute"];
        for c in 0..ch {
            println!("{dir} {:>3}  {:>6.1} dB{}", c + 1, g[c].as_f64().unwrap_or(0.0),
                if m[c].as_bool().unwrap_or(false) { "  [MUTE]" } else { "" });
        }
    }
    Ok(())
}

fn on(v: &str) -> u8 { matches!(v, "on" | "1" | "true" | "yes") as u8 }
/// Channels are 1-based for humans, 0-based on the wire.
fn idx(s: &str) -> Result<usize> {
    let n: usize = s.parse().context("channel must be a number (1-based)")?;
    if n == 0 { anyhow::bail!("channels start at 1"); }
    Ok(n - 1)
}
