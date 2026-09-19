// SPDX-License-Identifier: GPL-3.0-or-later
//! Bilingual end-to-end diagnostic. Each check returns either Ok or a Problem
//! with PT-BR + EN messages and a suggested remediation command. The CLI
//! prints them side by side so a forum-pasted transcript is readable in either
//! language.

use anyhow::Result;
use std::path::Path;
use std::process::Command;

use crate::config::{self, Config};

pub struct Problem {
    pub pt: String,
    pub en: String,
}

pub fn validate(cfg: &Config) -> Vec<Problem> {
    // Fast pre-flight that doesn't shell out — used by ExecStartPre.
    let mut v = Vec::new();
    if cfg.network.interface.trim().is_empty() {
        v.push(Problem {
            pt: "Nenhuma interface de rede configurada (network.interface). Abra a GUI ou rode: sonusgrid config edit".into(),
            en: "No network interface configured (network.interface). Open the GUI or run: sonusgrid config edit".into(),
        });
    }
    if !matches!(cfg.ptp.version.as_str(), "v1" | "v2") {
        v.push(Problem {
            pt: format!("ptp.version inválido: '{}' (use \"v1\" ou \"v2\")", cfg.ptp.version),
            en: format!("invalid ptp.version: '{}' (use \"v1\" or \"v2\")", cfg.ptp.version),
        });
    }
    if cfg.device.sample_rate != 48_000 && cfg.device.sample_rate != 96_000 {
        v.push(Problem {
            pt: format!("device.sample_rate = {} não é suportado (use 48000 ou 96000)", cfg.device.sample_rate),
            en: format!("device.sample_rate = {} is not supported (use 48000 or 96000)", cfg.device.sample_rate),
        });
    }
    v
}

pub fn run(cfg_path: &Path, _lang: crate::text::Lang) -> Result<()> {
    println!("=== sonusgrid doctor ===\n");

    let cfg = config::load(cfg_path)?;
    let mut problems: Vec<Problem> = Vec::new();
    let mut greens: Vec<String> = Vec::new();

    // 1. Config exists?
    if cfg_path.exists() {
        greens.push(format!("✓ config presente em {}", cfg_path.display()));
    } else {
        problems.push(Problem {
            pt: format!(
                "Config ausente em {}. Rode: sonusgrid config init",
                cfg_path.display()
            ),
            en: format!(
                "Config missing at {}. Run: sonusgrid config init",
                cfg_path.display()
            ),
        });
    }

    // 2. Network interface configured + UP?
    if cfg.network.interface.is_empty() {
        problems.push(Problem {
            pt: "Nenhuma interface de rede selecionada. Abra a GUI e escolha uma na seção Configuração."
                .into(),
            en: "No network interface selected. Open the GUI and pick one in the Configuration section."
                .into(),
        });
    } else {
        let iface = cfg.network.interface.clone();
        match interface_state(&iface) {
            Some(true) => greens.push(format!("✓ interface {iface} UP")),
            Some(false) => problems.push(Problem {
                pt: format!("Interface {iface} está DOWN. Plugue o cabo ou troque a interface na GUI"),
                en: format!("Interface {iface} is DOWN. Plug the cable in or pick a different interface in the GUI"),
            }),
            None => problems.push(Problem {
                pt: format!("Interface {iface} não encontrada"),
                en: format!("Interface {iface} not found"),
            }),
        }
    }

    // 3. Audio plug-in / driver installed?
    #[cfg(target_os = "linux")]
    {
        let plugin_candidates = [
            "/usr/lib/x86_64-linux-gnu/alsa-lib/libasound_module_pcm_sonusgrid.so",
            "/usr/lib/aarch64-linux-gnu/alsa-lib/libasound_module_pcm_sonusgrid.so",
        ];
        let plugin = plugin_candidates.iter().find(|p| std::path::Path::new(p).exists());
        if let Some(p) = plugin {
            greens.push(format!("✓ plugin ALSA presente em {p}"));
        } else {
            problems.push(Problem {
                pt: "Plugin ALSA do SonusGrid não encontrado. Reinstale o pacote sonusgrid.".into(),
                en: "SonusGrid ALSA plugin not found. Reinstall the sonusgrid package.".into(),
            });
        }
    }

    #[cfg(target_os = "macos")]
    {
        let driver = "/Library/Audio/Plug-Ins/HAL/SonusGrid.driver";
        if std::path::Path::new(driver).exists() {
            greens.push(format!("✓ HAL plugin presente em {driver}"));
        } else {
            problems.push(Problem {
                pt: format!("HAL plugin não encontrado em {driver}. Reinstale o pacote SonusGrid."),
                en: format!("HAL plugin not found at {driver}. Reinstall the SonusGrid package."),
            });
        }
    }

    // 4. NTP. Statime runs in virtual-system-clock mode (an overlay on top
    //    of CLOCK_MONOTONIC_RAW) and never steers the system clock, so NTP
    //    daemons are NOT a conflict. We just mention it so nobody wonders.
    #[cfg(target_os = "linux")]
    {
        let ntp: Vec<&str> = ["systemd-timesyncd", "chronyd", "ntp"]
            .into_iter()
            .filter(|s| service_active_system(s))
            .collect();
        if ntp.is_empty() {
            greens.push("✓ nenhum daemon NTP ativo (não faria diferença: o relógio PTP é virtual)".into());
        } else {
            greens.push(format!("✓ {} ativo — sem conflito, o relógio PTP do SonusGrid é virtual", ntp.join(", ")));
        }
    }

    // 5. Statime binary present?
    #[cfg(target_os = "linux")]
    let statime = "/usr/libexec/sonusgrid/statime";
    #[cfg(target_os = "macos")]
    let statime = "/usr/local/libexec/sonusgrid/statime-macos";
    if std::path::Path::new(statime).exists() {
        greens.push(format!("✓ statime presente em {statime}"));
        #[cfg(target_os = "linux")]
        {
            if !has_cap_sys_time(statime) {
                problems.push(Problem {
                    pt: format!(
                        "statime não tem cap_sys_time. Rode: sudo setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep {statime}"
                    ),
                    en: format!(
                        "statime missing cap_sys_time. Run: sudo setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep {statime}"
                    ),
                });
            } else {
                greens.push("✓ statime tem cap_sys_time".into());
            }
        }
        #[cfg(target_os = "macos")]
        {
            // macOS doesn't use POSIX caps. The launchd plist runs the
            // daemon as root, which is the equivalent.
            greens.push("✓ statime gerenciado por launchd (root)".into());
        }
    } else {
        problems.push(Problem {
            pt: format!("statime não encontrado em {statime}. Reinstale o pacote sonusgrid."),
            en: format!("statime missing at {statime}. Reinstall the sonusgrid package."),
        });
    }

    // 6. PipeWire @clock drop-in (Linux) / launchd plist (macOS)
    #[cfg(target_os = "linux")]
    {
        let drop_in = "/usr/lib/systemd/user/pipewire.service.d/sonusgrid-clock.conf";
        if std::path::Path::new(drop_in).exists() {
            greens.push(format!("✓ PipeWire @clock drop-in: {drop_in}"));
        } else {
            problems.push(Problem {
                pt: format!("PipeWire @clock drop-in ausente em {drop_in}. Reinstale o pacote sonusgrid."),
                en: format!("PipeWire @clock drop-in missing at {drop_in}. Reinstall the sonusgrid package."),
            });
        }
    }
    #[cfg(target_os = "macos")]
    {
        let plist = "/Library/LaunchDaemons/io.sonusgrid.clock.plist";
        if std::path::Path::new(plist).exists() {
            greens.push(format!("✓ launchd plist: {plist}"));
        } else {
            problems.push(Problem {
                pt: format!("launchd plist ausente em {plist}. Reinstale o pacote SonusGrid."),
                en: format!("launchd plist missing at {plist}. Reinstall the SonusGrid package."),
            });
        }
    }

    // 7. Audio runtime reachable?
    #[cfg(target_os = "linux")]
    if which("pactl") {
        let s = Command::new("pactl").arg("info").output();
        match s {
            Ok(o) if o.status.success() => greens.push("✓ PipeWire/Pulse acessível via pactl".into()),
            _ => problems.push(Problem {
                pt: "pactl info falhou. PipeWire/Pulse não está rodando para este usuário?".into(),
                en: "pactl info failed. Is PipeWire/Pulse running for this user?".into(),
            }),
        }
    }
    #[cfg(target_os = "macos")]
    {
        let s = Command::new("launchctl")
            .args(["print", "system/com.apple.audio.coreaudiod"])
            .output();
        match s {
            Ok(o) if o.status.success() => greens.push("✓ coreaudiod ativo".into()),
            _ => problems.push(Problem {
                pt: "coreaudiod parece inativo — improvável, mas verifique sudo killall coreaudiod".into(),
                en: "coreaudiod appears inactive — unusual; try sudo killall coreaudiod".into(),
            }),
        }
    }

    // 8. sonusgrid-bridge installed? (replaced ffmpeg in 0.2.0)
    #[cfg(target_os = "linux")]
    {
        let bridge = "/usr/libexec/sonusgrid/sonusgrid-bridge";
        if std::path::Path::new(bridge).exists() {
            greens.push(format!("✓ bridge presente em {bridge}"));
        } else {
            problems.push(Problem {
                pt: format!("Bridge ALSA↔Pulse ausente em {bridge}. Reinstale o pacote."),
                en: format!("ALSA↔Pulse bridge missing at {bridge}. Reinstall the package."),
            });
        }
    }

    // 9. RT priority limits (Linux only — macOS schedules audio threads via
    //    QoS classes, no equivalent file).
    #[cfg(target_os = "linux")]
    if let Ok(s) = std::fs::read_to_string("/etc/security/limits.d/audio.conf") {
        if s.contains("rtprio") {
            greens.push("✓ RT priority configurado em /etc/security/limits.d/audio.conf".into());
        }
    }

    // 9b. PipeWire looking unhealthy? A leaking/spinning pipewire daemon
    //     (seen in the wild: 2.7 GB RSS, 30 % CPU idle, no audio streams
    //     delivered) makes the bridge's Pulse connection time out forever.
    #[cfg(target_os = "linux")]
    if let Some(rss_mb) = process_rss_mb("pipewire") {
        if rss_mb > 1024 {
            problems.push(Problem {
                pt: format!("pipewire está usando {rss_mb} MB de RAM — parece degradado. Rode: systemctl --user restart pipewire pipewire-pulse wireplumber"),
                en: format!("pipewire is using {rss_mb} MB of RAM — looks degraded. Run: systemctl --user restart pipewire pipewire-pulse wireplumber"),
            });
        } else {
            greens.push(format!("✓ pipewire saudável ({rss_mb} MB)"));
        }
    }

    // 10. Per-user runtime dir (sockets / FIFO) writable?
    #[cfg(target_os = "linux")]
    {
        match crate::paths::ensure_runtime_dir() {
            Ok(dir) => {
                let probe = dir.join(".doctor-probe");
                match std::fs::write(&probe, b"ok") {
                    Ok(()) => {
                        let _ = std::fs::remove_file(&probe);
                        greens.push(format!("✓ diretório de runtime gravável: {}", dir.display()));
                    }
                    Err(e) => problems.push(Problem {
                        pt: format!("Não consigo escrever em {} ({e}). Verifique XDG_RUNTIME_DIR / permissões.", dir.display()),
                        en: format!("Cannot write to {} ({e}). Check XDG_RUNTIME_DIR / permissions.", dir.display()),
                    }),
                }
            }
            Err(e) => problems.push(Problem {
                pt: format!("Não consigo criar o diretório de runtime: {e}"),
                en: format!("Cannot create the runtime directory: {e}"),
            }),
        }
    }

    // 11. PTP hardware clock reachable? (udev rule gives group `audio` rw)
    #[cfg(target_os = "linux")]
    {
        let ptp_devs: Vec<_> = std::fs::read_dir("/dev")
            .map(|rd| rd.flatten()
                .map(|e| e.path())
                .filter(|p| p.file_name().map(|n| n.to_string_lossy().starts_with("ptp")).unwrap_or(false))
                .collect())
            .unwrap_or_default();
        if !ptp_devs.is_empty() {
            let in_audio = user_in_group("audio");
            if in_audio {
                greens.push(format!("✓ usuário no grupo audio ({} relógio(s) PTP de hardware)", ptp_devs.len()));
            } else {
                problems.push(Problem {
                    pt: format!("Usuário não está no grupo 'audio' — sem acesso a {}. Rode: sudo usermod -aG audio $USER (depois logout/login)", ptp_devs[0].display()),
                    en: format!("User is not in the 'audio' group — no access to {}. Run: sudo usermod -aG audio $USER (then log out/in)", ptp_devs[0].display()),
                });
            }
        } else {
            greens.push("✓ sem relógio PTP de hardware (usa relógio de software — OK)".into());
        }
    }

    // 12. systemd user units in a failed state? Explain how to see why.
    #[cfg(target_os = "linux")]
    for unit in ["sonusgrid-clock.service", "sonusgrid-audio.service"] {
        let st = crate::runtime::unit_state(unit);
        match st.as_str() {
            "active" => greens.push(format!("✓ {unit} ativo")),
            "failed" => problems.push(Problem {
                pt: format!("{unit} está em estado 'failed'. Veja o motivo com: sonusgrid logs {}  — depois: sonusgrid start",
                    unit.trim_start_matches("sonusgrid-").trim_end_matches(".service")),
                en: format!("{unit} is in 'failed' state. See why with: sonusgrid logs {}  — then: sonusgrid start",
                    unit.trim_start_matches("sonusgrid-").trim_end_matches(".service")),
            }),
            "unknown" => problems.push(Problem {
                pt: format!("Não consegui consultar o systemd --user ({unit}). Está rodando numa sessão de usuário (XDG_RUNTIME_DIR)?"),
                en: format!("Could not query systemd --user ({unit}). Are you in a user session (XDG_RUNTIME_DIR)?"),
            }),
            _ => {} // inactive / activating: nothing to flag
        }
    }

    // 13. libjack resolves to PipeWire's shim? (needed for DAW/JACK path)
    #[cfg(target_os = "linux")]
    {
        let ld_conf = "/etc/ld.so.conf.d/00-sonusgrid-pipewire-jack.conf";
        if std::path::Path::new(ld_conf).exists() {
            greens.push("✓ libjack → PipeWire-JACK (ld.so.conf drop-in presente)".into());
        } else if cfg.bridge.jack_enabled {
            problems.push(Problem {
                pt: format!("{ld_conf} ausente — DAWs (JACK) não vão ver o SonusGrid. Reinstale o pacote ou rode o postinst."),
                en: format!("{ld_conf} missing — DAWs (JACK) won't see SonusGrid. Reinstall the package or re-run postinst."),
            });
        }
    }

    // --- print report ----------------------------------------------------
    for g in &greens {
        println!("  {g}");
    }
    if problems.is_empty() {
        println!("\n[PT] Tudo verde — SonusGrid está pronto.\n[EN] All green — SonusGrid is ready.");
        return Ok(());
    }

    println!("\n--- problemas / problems ---\n");
    for p in &problems {
        println!("[PT] {}\n[EN] {}\n", p.pt, p.en);
    }
    anyhow::bail!("{} problem(s) found", problems.len());
}

#[cfg(target_os = "linux")]
fn interface_state(name: &str) -> Option<bool> {
    let path = format!("/sys/class/net/{name}/operstate");
    let s = std::fs::read_to_string(&path).ok()?;
    Some(s.trim() == "up")
}

#[cfg(target_os = "macos")]
fn interface_state(name: &str) -> Option<bool> {
    // `ifconfig <name>` returns nonzero if the interface doesn't exist.
    // The "status: active" line tells us link state on Wi-Fi/Ethernet.
    let out = Command::new("ifconfig").arg(name).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout);
    if s.contains("status: active") {
        return Some(true);
    }
    if s.contains("status: inactive") {
        return Some(false);
    }
    // No status line (e.g. virtual interfaces) — assume up if it's UP.
    Some(s.contains("flags=") && s.contains("UP"))
}

#[cfg(target_os = "linux")]
fn service_active_system(svc: &str) -> bool {
    Command::new("systemctl")
        .args(["is-active", svc])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

#[cfg(target_os = "macos")]
fn service_active_macos(label: &str) -> bool {
    Command::new("launchctl")
        .args(["print", &format!("system/{label}")])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

#[cfg(target_os = "linux")]
fn has_cap_sys_time(bin: &str) -> bool {
    let out = Command::new("getcap").arg(bin).output();
    match out {
        Ok(o) if o.status.success() => {
            let s = String::from_utf8_lossy(&o.stdout);
            s.contains("cap_sys_time")
        }
        _ => false,
    }
}

/// Resident memory (MB) of the current user's process with the given comm
/// name, or None if it isn't running.
#[cfg(target_os = "linux")]
fn process_rss_mb(comm: &str) -> Option<u64> {
    // NB: ps selection flags are OR-ed together, so `-C comm -U uid` would
    // match *every* process of the user. Select by comm only and filter the
    // uid column ourselves.
    let uid = unsafe { libc::geteuid() }.to_string();
    let out = Command::new("ps")
        .args(["-o", "uid=,rss=", "-C", comm])
        .output()
        .ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    let kb = s
        .lines()
        .filter_map(|l| {
            let mut it = l.split_whitespace();
            let u = it.next()?;
            let rss = it.next()?.parse::<u64>().ok()?;
            (u == uid).then_some(rss)
        })
        .max()?;
    Some(kb / 1024)
}

#[cfg(target_os = "linux")]
fn user_in_group(group: &str) -> bool {
    Command::new("id")
        .args(["-nG"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).split_whitespace().any(|g| g == group))
        .unwrap_or(false)
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
