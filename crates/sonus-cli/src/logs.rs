// SPDX-License-Identifier: GPL-3.0-or-later
//! Log tail wrapper. Linux uses `journalctl --user`; macOS uses
//! `log show --predicate 'subsystem == "io.sonusgrid"'`.

use anyhow::Result;
use std::os::unix::process::CommandExt;
use std::process::Command;

#[cfg(target_os = "linux")]
pub fn follow(unit: &str, follow: bool) -> Result<()> {
    let units: &[&str] = match unit {
        "clock" => &["sonusgrid-clock.service"],
        "audio" => &["sonusgrid-audio.service"],
        _ => &["sonusgrid-clock.service", "sonusgrid-audio.service"],
    };
    let mut cmd = Command::new("journalctl");
    cmd.arg("--user");
    for u in units {
        cmd.args(["-u", u]);
    }
    if follow {
        cmd.arg("-f");
    } else {
        cmd.args(["-n", "200"]);
    }
    let err = cmd.exec();
    Err(anyhow::anyhow!("execv journalctl failed: {err}"))
}

#[cfg(target_os = "macos")]
pub fn follow(_unit: &str, follow: bool) -> Result<()> {
    let mut cmd = Command::new("log");
    if follow {
        cmd.args(["stream", "--predicate", "subsystem == \"io.sonusgrid\""]);
    } else {
        cmd.args([
            "show", "--last", "1h",
            "--predicate", "subsystem == \"io.sonusgrid\"",
        ]);
    }
    let err = cmd.exec();
    Err(anyhow::anyhow!("execv log failed: {err}"))
}
