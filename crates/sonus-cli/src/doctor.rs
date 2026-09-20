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
    if !matches!(cfg.device.sample_rate, 44_100 | 48_000 | 88_200 | 96_000) {
        v.push(Problem {
            pt: format!("device.sample_rate = {} não é suportado (use 44100, 48000, 88200 ou 96000)", cfg.device.sample_rate),
            en: format!("device.sample_rate = {} is not supported (use 44100, 48000, 88200 or 96000)", cfg.device.sample_rate),
        });
    }
    v
}

pub fn run(cfg_path: &Path, _lang: crate::text::Lang, json_out: bool) -> Result<()> {
    if !json_out {
        println!("=== sonusgrid doctor ===\n");
    }

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

    // 9. Real-time scheduling for the audio bridge: needs the session's hard
    //    RLIMIT_RTPRIO > 0 (limits.d + `audio` group + re-login) or rtkit.
    #[cfg(target_os = "linux")]
    {
        let hard_rtprio = std::fs::read_to_string("/proc/self/limits")
            .ok()
            .and_then(|s| s.lines().find(|l| l.starts_with("Max realtime priority")).map(|l| l.to_string()))
            .and_then(|l| l.split_whitespace().nth(4).and_then(|x| x.parse::<u32>().ok()))
            .unwrap_or(0);
        let rtkit = service_active_system("rtkit-daemon");
        if hard_rtprio >= 20 {
            greens.push(format!("✓ prioridade tempo-real disponível (rtprio {hard_rtprio})"));
        } else if rtkit {
            greens.push("✓ rtkit ativo — o bridge pede prioridade tempo-real por ele (limite 20). Para 95: relogue após entrar no grupo audio".into());
        } else {
            problems.push(Problem {
                pt: "Sem prioridade tempo-real (rtprio 0 e rtkit inativo): o áudio vai cortar sob carga de CPU. Entre no grupo 'audio' e faça logout/login (limits.d/sonusgrid.conf).".into(),
                en: "No realtime scheduling (rtprio 0 and rtkit inactive): audio will drop out under CPU load. Join the 'audio' group and log out/in (limits.d/sonusgrid.conf).".into(),
            });
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

    // 9c. Sink volume — purely informational. A very low volume is a
    //     legitimate safety choice (speakers at 100 %), but it also explains
    //     "the video plays and I hear nothing", so say it out loud.
    #[cfg(target_os = "linux")]
    if let Some(pct) = sink_volume_percent(&cfg.bridge.sink_name) {
        if pct == 100 {
            greens.push(format!("✓ sink {} em 100% (o volume real é o Mixer do SonusGrid)", cfg.bridge.sink_name));
        } else {
            problems.push(Problem {
                pt: format!("sink {} está em {pct}% — o volume deve ser controlado no Mixer do SonusGrid; rode `sonusgrid restart` para normalizar (o mixer preserva o nível)", cfg.bridge.sink_name),
                en: format!("sink {} is at {pct}% — volume should be controlled in the SonusGrid Mixer; run `sonusgrid restart` to normalise (the mixer keeps the level)", cfg.bridge.sink_name),
            });
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

    // 11b. systemd --user responsive? Multiple GUI instances hammering it?
    //      (Seen in the wild: 11 stale GUIs × 45 status calls/s pinned the
    //      user manager at 100 % CPU and start jobs never ran.)
    #[cfg(target_os = "linux")]
    {
        let n_gui = count_user_processes("python3 -m sonus_gtk") + count_user_processes("sonusgrid-gtk");
        if n_gui > 1 {
            problems.push(Problem {
                pt: format!("{n_gui} instâncias da GUI rodando ao mesmo tempo (versões antigas sobrecarregam o systemd --user). Feche-as: pkill -f 'python3 -m sonus_gtk'"),
                en: format!("{n_gui} GUI instances running at once (old versions overload systemd --user). Close them: pkill -f 'python3 -m sonus_gtk'"),
            });
        }
        if let Some(cpu) = user_manager_cpu_percent() {
            if cpu >= 50.0 {
                problems.push(Problem {
                    pt: format!("systemd --user está usando {cpu:.0}% de CPU — jobs de start não vão rodar. Feche processos que chamam systemctl em loop (GUIs antigas) e tente de novo."),
                    en: format!("systemd --user is using {cpu:.0}% CPU — start jobs won't run. Close processes calling systemctl in a loop (old GUIs) and retry."),
                });
            } else {
                greens.push(format!("✓ systemd --user responsivo ({cpu:.0}% CPU)"));
            }
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
    if json_out {
        let val = serde_json::json!({
            "ok": problems.is_empty(),
            "passed": greens.iter().map(|g| g.trim_start_matches("✓ ").to_string()).collect::<Vec<_>>(),
            "problems": problems.iter().map(|p| serde_json::json!({"pt": p.pt, "en": p.en})).collect::<Vec<_>>(),
        });
        println!("{}", serde_json::to_string_pretty(&val)?);
        if problems.is_empty() {
            return Ok(());
        }
        std::process::exit(1);
    }
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

/// Number of this user's processes whose command line contains `needle`.
#[cfg(target_os = "linux")]
fn count_user_processes(needle: &str) -> usize {
    let uid = unsafe { libc::geteuid() }.to_string();
    let out = Command::new("ps").args(["-o", "uid=,args=", "-u", &uid]).output();
    match out {
        Ok(o) => String::from_utf8_lossy(&o.stdout)
            .lines()
            .filter(|l| l.contains(needle) && !l.contains("doctor"))
            .count(),
        Err(_) => 0,
    }
}

/// CPU usage of the user's `systemd --user` manager, sampled over 300 ms.
#[cfg(target_os = "linux")]
fn user_manager_cpu_percent() -> Option<f64> {
    let uid = unsafe { libc::geteuid() }.to_string();
    let out = Command::new("pgrep").args(["-u", &uid, "-x", "systemd"]).output().ok()?;
    let pid = String::from_utf8_lossy(&out.stdout).lines().next()?.trim().to_string();
    let read = || -> Option<u64> {
        let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
        let rest = stat.rsplit(')').next()?;
        let f: Vec<&str> = rest.split_whitespace().collect();
        // fields after ')' : state(0) ppid(1) … utime(11) stime(12)
        Some(f.get(11)?.parse::<u64>().ok()? + f.get(12)?.parse::<u64>().ok()?)
    };
    let t0 = read()?;
    std::thread::sleep(std::time::Duration::from_millis(300));
    let t1 = read()?;
    let hz = unsafe { libc::sysconf(libc::_SC_CLK_TCK) } as f64;
    Some((t1 - t0) as f64 / hz / 0.3 * 100.0)
}

/// Current volume (%) of a PipeWire/Pulse sink, via `pactl get-sink-volume`.
#[cfg(target_os = "linux")]
fn sink_volume_percent(sink: &str) -> Option<u32> {
    let out = Command::new("pactl").args(["get-sink-volume", sink]).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout);
    s.split_whitespace()
        .filter_map(|t| t.strip_suffix('%'))
        .filter_map(|t| t.parse::<u32>().ok())
        .max()
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
