// SPDX-License-Identifier: GPL-3.0-or-later
//! sonusgrid-bridge — unified full-duplex audio bridge.
//!
//! This is the single owner of `plug:sonusgrid` — it handles both the casual
//! system-audio path (PulseAudio null-sink → channels 1+2) and the DAW JACK
//! path (16 input ports + 16 output ports) at the same time, mixing them
//! per-channel before they hit the SonusGrid ALSA plug-in.
//!
//! Architecture (SoundGrid-style virtual interface):
//!
//!   Spotify / Firefox / casual apps
//!       │ PulseAudio
//!       ▼
//!   PipeWire null-sink "SonusGrid" (2-ch s32le)
//!       │ monitor stream
//!       ▼
//!   ┌──────────────────── sonusgrid-bridge (this process) ──────────────┐
//!   │                                                                    │
//!   │  PA reader thread        JACK process_cb (RT)                      │
//!   │       │                       │     ▲                              │
//!   │       │ 2-ch frames           │ 16-ch frames (per port)           │
//!   │       ▼                       ▼                                    │
//!   │   tx_pa_buf[]               tx_jack_rings[16]                      │
//!   │       │                       │                                    │
//!   │       └─────────┬─────────────┘                                    │
//!   │                 ▼                                                  │
//!   │            ALSA writer thread                                      │
//!   │                 │ mix(PA[c], JACK[c]) per channel                  │
//!   │                 ▼                                                  │
//!   │   ALSA `plug:sonusgrid` ───────────► RTP → Dante                   │
//!   │   (single full-duplex open)         ◄── RTP                        │
//!   │                 ▲                                                  │
//!   │            ALSA reader thread                                      │
//!   │                 │                                                  │
//!   │                 ├──► FIFO (channels 1+2 → pipe-source RX)          │
//!   │                 └──► rx_jack_rings[16] → JACK out ports            │
//!   │                                                                    │
//!   └────────────────────────────────────────────────────────────────────┘
//!
//! If JACK initialization fails (PipeWire-jack not installed, JACK server
//! down, etc.) the bridge logs a warning and keeps running in Pulse-only
//! mode — system audio still works. The JACK rings stay empty, so the mix
//! is a no-op.

use std::fs::OpenOptions;
use std::io::Write;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use alsa::pcm::{Access, Format, HwParams, PCM};
use alsa::{Direction, ValueOr};
use anyhow::{Context, Result};
use clap::Parser;
use crossbeam_queue::ArrayQueue;
use libpulse_binding::sample::{Format as PaFormat, Spec};
use libpulse_binding::stream::Direction as PaDir;
use libpulse_simple_binding::Simple;

#[derive(Parser, Debug)]
#[command(name = "sonusgrid-bridge", about = "Unified Pulse + JACK ↔ ALSA bridge for SonusGrid")]
struct Cli {
    /// PulseAudio sink to read the .monitor source from. Example: SonusGrid
    #[arg(long)]
    sink_name: String,
    /// FIFO path the RX leg writes into. A pipe-source reads on the other end.
    #[arg(long)]
    rx_pipe: String,
    /// ALSA device for full-duplex open.
    #[arg(long, default_value = "plug:sonusgrid")]
    alsa: String,
    /// Sample rate (must match Inferno + the PA sink).
    #[arg(long, default_value_t = 48000)]
    rate: u32,
    /// Number of ALSA channels (== Inferno TX/RX channel count).
    #[arg(long, default_value_t = 16)]
    channels: u32,
    /// ALSA period size in frames. 256 ≈ 5.3 ms at 48 kHz; 128 ≈ 2.7 ms.
    #[arg(long, default_value_t = 256)]
    period: u32,
    /// JACK client name for the DAW path. Set to empty string to disable JACK.
    /// Must differ from the PipeWire sink name: tools that pick a target by
    /// node.name (WirePlumber stream restore, pw-play --target) would
    /// otherwise route system audio into the JACK client instead of the sink.
    #[arg(long, default_value = "SonusGrid-JACK")]
    jack_client: String,
}

fn open_alsa(device: &str, dir: Direction, rate: u32, channels: u32, period: u32) -> Result<PCM> {
    let pcm = PCM::new(device, dir, false)
        .with_context(|| format!("opening ALSA {} for {:?}", device, dir))?;
    {
        let hw = HwParams::any(&pcm)?;
        hw.set_access(Access::RWInterleaved)?;
        hw.set_format(Format::s32())?;
        hw.set_rate(rate, ValueOr::Nearest)?;
        hw.set_channels(channels)?;
        hw.set_period_size(period as i64, ValueOr::Nearest)?;
        hw.set_buffer_size(period as i64 * 16)?;
        pcm.hw_params(&hw)?;
    }
    Ok(pcm)
}

#[inline(always)]
fn f32_to_i32(v: f32) -> i32 {
    let v = v.clamp(-1.0, 0.999_999_94);
    (v * 2_147_483_648.0) as i32
}
#[inline(always)]
fn i32_to_f32(v: i32) -> f32 {
    v as f32 / 2_147_483_648.0
}

/// Saturating add for two i32 audio samples — used to mix the PA path and
/// the JACK path on the same channel without wrapping/overflow artefacts at
/// peak levels. For typical content both legs are well below full-scale, so
/// saturation virtually never triggers; when it does it's the lesser of two
/// evils (clipped peak vs wrapped polarity flip).
#[inline(always)]
fn mix_sat(a: i32, b: i32) -> i32 {
    a.saturating_add(b)
}

/// Put the calling thread on SCHED_FIFO. Without this any CPU load on the
/// box (a compiler, a browser, a screenshot) delays the ALSA writer past the
/// engine's 4 ms latency budget and the Dante stream drops out ("tx lag of N
/// samples detected").
///
/// Two paths:
///  1. `pthread_setschedparam` — works when RLIMIT_RTPRIO allows it (the
///     unit sets LimitRTPRIO=95, but a `systemd --user` manager can only
///     hand out what its own hard limit permits — usually 0 unless
///     /etc/security/limits.d grants the `audio` group rtprio).
///  2. rtkit (`org.freedesktop.RealtimeKit1.MakeThreadRealtimeWithPID`) —
///     the desktop-standard fallback PipeWire itself uses. rtkit caps the
///     priority (default 20) and requires RLIMIT_RTTIME to be set.
fn set_realtime(name: &str, prio: i32) {
    let param = libc::sched_param { sched_priority: prio };
    let rc = unsafe { libc::pthread_setschedparam(libc::pthread_self(), libc::SCHED_FIFO, &param) };
    if rc == 0 {
        log::info!("{name}: SCHED_FIFO priority {prio}");
        return;
    }
    // rtkit insists on an RTTIME watchdog (µs). 200 ms is its default max.
    let rl = libc::rlimit { rlim_cur: 200_000, rlim_max: 200_000 };
    unsafe { libc::setrlimit(libc::RLIMIT_RTTIME, &rl) };
    let pid = std::process::id();
    let tid = unsafe { libc::syscall(libc::SYS_gettid) } as u64;
    let rtkit_prio = 20u32;
    let out = std::process::Command::new("busctl")
        .args([
            "--system", "--timeout=3", "call",
            "org.freedesktop.RealtimeKit1", "/org/freedesktop/RealtimeKit1",
            "org.freedesktop.RealtimeKit1", "MakeThreadRealtimeWithPID", "ttu",
            &pid.to_string(), &tid.to_string(), &rtkit_prio.to_string(),
        ])
        .output();
    match out {
        Ok(o) if o.status.success() => {
            log::info!("{name}: SCHED_FIFO priority {rtkit_prio} via rtkit");
        }
        Ok(o) => log::warn!(
            "{name}: no realtime scheduling (rlimit errno {rc}; rtkit: {}). Audio may drop out under CPU load — \
             add the user to the `audio` group and re-login (limits.d/sonusgrid.conf grants rtprio).",
            String::from_utf8_lossy(&o.stderr).trim()
        ),
        Err(e) => log::warn!("{name}: no realtime scheduling (rlimit errno {rc}; busctl: {e})"),
    }
}

fn lock_memory() {
    // Avoid page faults in the audio threads.
    if unsafe { libc::mlockall(libc::MCL_CURRENT | libc::MCL_FUTURE) } != 0 {
        log::warn!("mlockall failed; page faults may cause xruns (check LimitMEMLOCK)");
    }
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();
    let args = Cli::parse();
    lock_memory();

    let channels = args.channels as usize;
    let period = args.period as usize;

    log::info!(
        "ALSA {} period={} ch={} rate={}",
        args.alsa, args.period, args.channels, args.rate
    );
    let alsa_pb = open_alsa(&args.alsa, Direction::Playback, args.rate, args.channels, args.period)?;
    let alsa_cap = open_alsa(&args.alsa, Direction::Capture, args.rate, args.channels, args.period)?;

    // libpulse Simple does the ring-buffer + thread for us. We'll request a
    // small target buffer so the monitor source feeds us in ~5 ms chunks.
    let monitor = format!("{}.monitor", args.sink_name);
    log::info!("PulseAudio: read 2-ch s32le from {}", monitor);
    let pa_spec = Spec {
        format: PaFormat::S32le,
        channels: 2,
        rate: args.rate,
    };
    let pa_attr = libpulse_binding::def::BufferAttr {
        maxlength: u32::MAX,
        fragsize: args.period * 2 * 4,
        tlength: u32::MAX, prebuf: u32::MAX, minreq: u32::MAX,
    };
    let pa_record = Simple::new(
        None, "sonusgrid-bridge",
        PaDir::Record,
        Some(&monitor),
        "tx",
        &pa_spec,
        None,
        Some(&pa_attr),
    ).context("opening pulse Simple for record")?;

    log::info!("RX FIFO open for write: {}", args.rx_pipe);
    let mut rx_fifo = OpenOptions::new()
        .write(true)
        .open(&args.rx_pipe)
        .with_context(|| format!("opening rx fifo {}", args.rx_pipe))?;

    // Per-channel SPSC rings for the JACK path. These are shared with the
    // ALSA writer / reader threads. Capacity = 8 periods of frames per
    // channel — large enough to absorb scheduling jitter between the JACK RT
    // thread and the blocking ALSA threads, small enough that we don't add
    // perceptible latency on top of ALSA's buffer.
    let ring_cap = period * 8;
    let tx_jack_rings: Vec<Arc<ArrayQueue<f32>>> =
        (0..channels).map(|_| Arc::new(ArrayQueue::new(ring_cap))).collect();
    let rx_jack_rings: Vec<Arc<ArrayQueue<f32>>> =
        (0..channels).map(|_| Arc::new(ArrayQueue::new(ring_cap))).collect();

    // Cooperative shutdown.
    let stop = Arc::new(AtomicBool::new(false));
    {
        let stop = stop.clone();
        ctrlc::set_handler(move || stop.store(true, Ordering::Relaxed)).ok();
    }

    // ---------------- TX thread (PA monitor + JACK rings → ALSA playback) ---
    let stop_tx = stop.clone();
    let tx_jack_rings_tx = tx_jack_rings.clone();
    let tx = std::thread::spawn(move || {
        set_realtime("TX thread", 70);
        let mut pa_buf = vec![0u8; period * 2 * 4]; // i32 LE × 2ch × period
        let mut alsa_buf = vec![0i32; period * channels];
        let silence = vec![0i32; period * channels];
        let pcm_io = match alsa_pb.io_i32() {
            Ok(io) => io,
            Err(e) => { log::error!("TX io_i32: {e}"); return; }
        };
        loop {
            if stop_tx.load(Ordering::Relaxed) { return; }
            // 1. Read one period of stereo s32le from PA monitor.
            let pa_ok = pa_record.read(&mut pa_buf).is_ok();
            if !pa_ok {
                log::warn!("PA read transient error; writing silence this period");
                // PA might come back; clear pa_buf so the mix below is a no-op
                // for the casual leg and only the JACK leg is heard.
                for b in pa_buf.iter_mut() { *b = 0; }
            }

            // 2. For each frame, build the 16-ch interleaved ALSA buffer:
            //    channel 0 = PA-left  + JACK[0]
            //    channel 1 = PA-right + JACK[1]
            //    channel c = JACK[c]   for c >= 2
            for f in 0..period {
                let pa_l = i32::from_le_bytes(pa_buf[f * 8..f * 8 + 4].try_into().unwrap());
                let pa_r = i32::from_le_bytes(pa_buf[f * 8 + 4..f * 8 + 8].try_into().unwrap());
                for c in 0..channels {
                    let pa = match c {
                        0 => pa_l,
                        1 => pa_r,
                        _ => 0,
                    };
                    let jack = tx_jack_rings_tx[c].pop()
                        .map(f32_to_i32)
                        .unwrap_or(0);
                    alsa_buf[f * channels + c] = mix_sat(pa, jack);
                }
            }

            // 3. Push to ALSA. On xrun, recover and refill one period of
            //    silence so the device starts streaming again immediately.
            if let Err(e) = pcm_io.writei(&alsa_buf) {
                log::debug!("TX xrun: {e:?}; recover");
                let _ = alsa_pb.try_recover(e, true);
                let _ = pcm_io.writei(&silence);
            }
        }
    });

    // ---------------- RX thread (ALSA capture → FIFO + JACK rings) ----------
    let stop_rx = stop.clone();
    let rx_jack_rings_rx = rx_jack_rings.clone();
    let rx = std::thread::spawn(move || {
        set_realtime("RX thread", 70);
        let pcm_io = match alsa_cap.io_i32() {
            Ok(io) => io,
            Err(e) => { log::error!("RX io_i32: {e}"); return; }
        };
        let mut alsa_buf = vec![0i32; period * channels];
        let mut fifo_buf = vec![0u8; period * 2 * 4];
        let _ = alsa_cap.start();
        loop {
            if stop_rx.load(Ordering::Relaxed) { return; }
            match pcm_io.readi(&mut alsa_buf) {
                Ok(_) => {}
                Err(e) => {
                    log::debug!("RX xrun: {e:?}; recover");
                    let _ = alsa_cap.try_recover(e, true);
                    continue;
                }
            }
            for f in 0..period {
                // 1. Stereo slice (channels 0+1) → pipe-source FIFO.
                let l = alsa_buf[f * channels + 0].to_le_bytes();
                let r = alsa_buf[f * channels + 1].to_le_bytes();
                fifo_buf[f * 8..f * 8 + 4].copy_from_slice(&l);
                fifo_buf[f * 8 + 4..f * 8 + 8].copy_from_slice(&r);
                // 2. All channels → JACK rings (so DAW can record any subset).
                for c in 0..channels {
                    let v = i32_to_f32(alsa_buf[f * channels + c]);
                    if rx_jack_rings_rx[c].push(v).is_err() {
                        // Ring full — DAW JACK isn't pulling fast enough.
                        // Drop oldest and try again so the latest sample wins.
                        let _ = rx_jack_rings_rx[c].pop();
                        let _ = rx_jack_rings_rx[c].push(v);
                    }
                }
            }
            if rx_fifo.write_all(&fifo_buf).is_err() {
                log::warn!("RX FIFO write failed; FIFO leg disabled (JACK leg continues)");
                // Don't return — keep feeding JACK rings even if pipe-source
                // closed its end of the FIFO.
                // Re-open lazily on next iteration would be nice but for now
                // we just fall through; FIFO writes will keep failing silently.
            }
        }
    });

    // ---------------- JACK client (optional) -------------------------------
    // We try to register a JACK client so DAWs see SonusGrid as a 16x16 JACK
    // client at the same time as Spotify sees the null-sink. If JACK isn't
    // available we just keep the rings empty and the bridge runs in
    // Pulse-only mode.
    let jack_active = if args.jack_client.is_empty() {
        log::info!("JACK disabled by --jack-client \"\"");
        None
    } else {
        match try_register_jack(&args.jack_client, args.rate, channels, period,
                                tx_jack_rings.clone(), rx_jack_rings.clone()) {
            Ok(active) => Some(active),
            Err(e) => {
                log::warn!("JACK unavailable ({e}); continuing without JACK client. \
                            DAWs won't see SonusGrid; system audio still works.");
                None
            }
        }
    };

    while !stop.load(Ordering::Relaxed) {
        std::thread::sleep(std::time::Duration::from_secs(1));
        if tx.is_finished() && rx.is_finished() {
            log::error!("both threads finished — exiting so systemd can restart cleanly");
            break;
        }
    }
    if let Some(a) = jack_active {
        let _ = a.deactivate();
    }
    Ok(())
}

/// Wrapper for the JACK active-client handle so we can store it generically.
#[allow(deprecated)]
type JackActive = jack::AsyncClient<(), jack::ClosureProcessHandler<
    Box<dyn FnMut(&jack::Client, &jack::ProcessScope) -> jack::Control + Send>
>>;

fn try_register_jack(
    name: &str,
    rate: u32,
    channels: usize,
    _period: usize,
    tx_rings: Vec<Arc<ArrayQueue<f32>>>,
    rx_rings: Vec<Arc<ArrayQueue<f32>>>,
) -> Result<JackActive> {
    let (client, _status) =
        jack::Client::new(name, jack::ClientOptions::NO_START_SERVER)
            .context("creating JACK client")?;

    if client.sample_rate() as u32 != rate {
        anyhow::bail!(
            "JACK sample rate is {} but SonusGrid is configured for {}",
            client.sample_rate(), rate
        );
    }

    log::info!(
        "JACK '{}' active: sample_rate={} buffer_size={}",
        name, client.sample_rate(), client.buffer_size()
    );

    // Input ports: DAW writes here → mixed into the ALSA TX channels.
    let mut in_ports: Vec<jack::Port<jack::AudioIn>> = Vec::with_capacity(channels);
    for ch in 1..=channels {
        let p = client
            .register_port(&format!("tx_{:02}", ch), jack::AudioIn::default())
            .with_context(|| format!("registering input port tx_{:02}", ch))?;
        in_ports.push(p);
    }
    // Output ports: ALSA RX → DAW reads here.
    let mut out_ports: Vec<jack::Port<jack::AudioOut>> = Vec::with_capacity(channels);
    for ch in 1..=channels {
        let p = client
            .register_port(&format!("rx_{:02}", ch), jack::AudioOut::default())
            .with_context(|| format!("registering output port rx_{:02}", ch))?;
        out_ports.push(p);
    }

    // The closure has to be Send + 'static; we Box it to fit JackActive.
    let process: Box<dyn FnMut(&jack::Client, &jack::ProcessScope) -> jack::Control + Send> =
        Box::new(move |_client: &jack::Client, ps: &jack::ProcessScope| {
            let n = ps.n_frames() as usize;

            // 1. Push DAW input frames into per-channel TX rings.
            //    We snapshot all input slices first to avoid re-borrowing
            //    `ps` per-frame.
            for (ch, port) in in_ports.iter().enumerate() {
                let data = port.as_slice(ps);
                let ring = &tx_rings[ch];
                for f in 0..n {
                    let v = if f < data.len() { data[f] } else { 0.0 };
                    if ring.push(v).is_err() {
                        // Ring full — ALSA writer is behind. Drop one to make
                        // space; the DAW will hear a tiny glitch but the
                        // bridge keeps running.
                        let _ = ring.pop();
                        let _ = ring.push(v);
                    }
                }
            }

            // 2. Pull RX frames from per-channel RX rings into DAW outputs.
            for (ch, port) in out_ports.iter_mut().enumerate() {
                let data = port.as_mut_slice(ps);
                let ring = &rx_rings[ch];
                for f in 0..n {
                    if f < data.len() {
                        data[f] = ring.pop().unwrap_or(0.0);
                    }
                }
            }

            jack::Control::Continue
        });

    #[allow(deprecated)]
    let active = client
        .activate_async((), jack::ClosureProcessHandler::new(process))
        .context("activating JACK client")?;
    Ok(active)
}
