// SPDX-License-Identifier: GPL-3.0-or-later
//! Per-user runtime paths (Unix sockets, FIFOs).
//!
//! Everything short-lived that SonusGrid creates at runtime lives under
//! `$XDG_RUNTIME_DIR/sonusgrid/` (normally `/run/user/<uid>/sonusgrid/`).
//! That directory is private to the user, always writable, and wiped by
//! systemd on logout — so stale sockets can never block the next start.
//!
//! Earlier releases used `/tmp/` directly. That broke whenever `/tmp` had
//! unusual permissions or `fs.protected_regular` got in the way, and it made
//! two users on the same box fight over the same socket names.

use anyhow::{Context, Result};
use std::path::PathBuf;

use crate::config::Config;

/// Base runtime directory for this user. Order of preference:
///   1. `$XDG_RUNTIME_DIR/sonusgrid`
///   2. `/run/user/<uid>/sonusgrid`
///   3. `~/.cache/sonusgrid/run` (last resort, e.g. no logind session)
pub fn runtime_dir() -> PathBuf {
    if let Some(p) = std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from) {
        if p.is_dir() {
            return p.join("sonusgrid");
        }
    }
    let uid = unsafe { libc::geteuid() };
    let p = PathBuf::from(format!("/run/user/{uid}"));
    if p.is_dir() {
        return p.join("sonusgrid");
    }
    dirs::cache_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("sonusgrid")
        .join("run")
}

/// Create the runtime directory (mode 0700) if needed and return it.
pub fn ensure_runtime_dir() -> Result<PathBuf> {
    let dir = runtime_dir();
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("creating runtime dir {}", dir.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700));
    }
    Ok(dir)
}

/// Unix socket where Statime publishes the PTP clock overlay and where the
/// SonusGrid engine (ALSA plugin) reads it from.
pub fn clock_socket_path() -> PathBuf {
    runtime_dir().join("ptp-usrvclock")
}

/// FIFO the bridge writes RX audio into; `module-pipe-source` reads it.
pub fn rx_fifo_path(cfg: &Config) -> PathBuf {
    runtime_dir().join(format!("{}_RX.fifo", cfg.bridge.sink_name))
}

/// Legacy socket path used by SonusGrid <= 0.2.0. Cleaned up best-effort so
/// an upgrade never leaves a stale file behind.
pub const LEGACY_CLOCK_SOCKET: &str = "/tmp/ptp-usrvclock";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_dir_ends_with_sonusgrid() {
        let d = runtime_dir();
        assert!(d.ends_with("sonusgrid") || d.ends_with("run"));
    }

    #[test]
    fn socket_lives_in_runtime_dir() {
        assert!(clock_socket_path().starts_with(runtime_dir()));
    }
}
