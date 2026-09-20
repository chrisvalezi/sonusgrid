// SPDX-License-Identifier: GPL-3.0-or-later
//! Mixer: per-channel gain/mute for TX (PC → Dante) and RX (Dante → PC), a
//! master fader, peak meters, and the two IPC surfaces the GUI/CLI use:
//!
//!  * `<runtime>/mixer.sock` — Unix datagram socket, one text command per
//!    datagram (`set tx 3 -6.0`, `mute rx 1 1`, `master -20`, `mmute 1`,
//!    `get`), replies with the current state as one line of JSON.
//!  * `<runtime>/meters` — a small file rewritten ~100×/s by a low-priority
//!    thread with the peak of every channel (post-fader) plus the live gains,
//!    so the GUI can draw meters at the display's frame rate without ever
//!    touching the audio threads. Layout: see `SHM_*` below.
//!
//! State (gains/mutes) is persisted to a TOML-ish key=value file so a
//! restart never comes back louder than the user left it.

use std::fs::File;
use std::os::unix::fs::FileExt;
use std::os::unix::net::UnixDatagram;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

pub const MAX_CH: usize = 256;
pub const SHM_MAGIC: u32 = 0x584d4753; // "SGMX" little-endian
pub const SHM_VERSION: u32 = 1;
/// Header: magic, version, channels, seq, master_gain(f32), master_mute, rate, period = 8 × u32
pub const SHM_HEADER: usize = 32;
/// … then master output peaks L/R (2 × f32) after the mute bytes.
pub const SHM_SIZE: usize = SHM_HEADER + 4 * MAX_CH * 4 + 2 * MAX_CH + 8;
/// Peak envelope decay per period (≈ 300 ms to fall 40 dB at 5 ms periods).
const PEAK_DECAY: f32 = 0.93;
/// Gain ramp: fraction of the remaining distance covered per period (no zipper noise).
const GAIN_SLEW: f32 = 0.35;
pub const MIN_DB: f32 = -80.0;

pub fn db_to_lin(db: f32) -> f32 {
    if db <= MIN_DB { 0.0 } else { 10f32.powf(db / 20.0).min(1.0) }
}
pub fn lin_to_db(lin: f32) -> f32 {
    if lin <= 0.0 { MIN_DB } else { (20.0 * lin.log10()).max(MIN_DB) }
}

struct Chan {
    gain: AtomicU32,   // f32 bits, linear target
    mute: AtomicBool,
    peak: AtomicU32,   // f32 bits, post-fader peak envelope
}
impl Chan {
    fn new() -> Self {
        Self { gain: AtomicU32::new(1f32.to_bits()), mute: AtomicBool::new(false), peak: AtomicU32::new(0) }
    }
    fn gain(&self) -> f32 { f32::from_bits(self.gain.load(Ordering::Relaxed)) }
    fn set_gain(&self, g: f32) { self.gain.store(g.clamp(0.0, 1.0).to_bits(), Ordering::Relaxed) }
    fn effective(&self) -> f32 { if self.mute.load(Ordering::Relaxed) { 0.0 } else { self.gain() } }
    fn peak(&self) -> f32 { f32::from_bits(self.peak.load(Ordering::Relaxed)) }
}

pub struct Mixer {
    pub channels: usize,
    tx: Vec<Chan>,
    rx: Vec<Chan>,
    master_gain: AtomicU32,
    master_mute: AtomicBool,
    master_peak: [AtomicU32; 2],
    dirty: AtomicU64, // monotonic µs of last change, 0 = clean
    state_path: Option<PathBuf>,
    sample_rate: u32,
    period: u32,
}

/// Per-thread smoothing state (one per audio thread; not shared).
pub struct Fader {
    cur: Vec<f32>,
}
impl Fader {
    pub fn new(channels: usize) -> Self { Self { cur: vec![0.0; channels] } }
    /// Gain to apply this period for channel `c`, slewing toward the target.
    #[inline]
    pub fn step(&mut self, c: usize, target: f32) -> f32 {
        let g = self.cur[c] + (target - self.cur[c]) * GAIN_SLEW;
        self.cur[c] = if (g - target).abs() < 1e-5 { target } else { g };
        self.cur[c]
    }
}

impl Mixer {
    pub fn new(channels: usize, sample_rate: u32, period: u32, state_path: Option<PathBuf>) -> Arc<Self> {
        let channels = channels.min(MAX_CH);
        let m = Arc::new(Self {
            channels,
            tx: (0..channels).map(|_| Chan::new()).collect(),
            rx: (0..channels).map(|_| Chan::new()).collect(),
            master_gain: AtomicU32::new(1f32.to_bits()),
            master_mute: AtomicBool::new(false),
            master_peak: [AtomicU32::new(0), AtomicU32::new(0)],
            dirty: AtomicU64::new(0),
            state_path,
            sample_rate,
            period,
        });
        m.load_state();
        m
    }

    // ---- audio-thread side -------------------------------------------------------
    /// Channel fader only (pre-master). Channel meters read this stage.
    #[inline] pub fn tx_target(&self, c: usize) -> f32 { self.tx[c].effective() }
    /// Master fader (post). The master meter reads after this stage.
    #[inline] pub fn master_target(&self) -> f32 {
        if self.master_mute.load(Ordering::Relaxed) { 0.0 } else { f32::from_bits(self.master_gain.load(Ordering::Relaxed)) }
    }
    #[inline] pub fn master_peak_update(&self, side: usize, period_peak: f32) {
        let a = &self.master_peak[side & 1];
        let old = f32::from_bits(a.load(Ordering::Relaxed));
        a.store(period_peak.max(old * PEAK_DECAY).to_bits(), Ordering::Relaxed);
    }
    #[inline] pub fn rx_target(&self, c: usize) -> f32 { self.rx[c].effective() }
    #[inline] pub fn tx_peak_update(&self, c: usize, period_peak: f32) { Self::peak_update(&self.tx[c], period_peak) }
    #[inline] pub fn rx_peak_update(&self, c: usize, period_peak: f32) { Self::peak_update(&self.rx[c], period_peak) }
    #[inline] fn peak_update(ch: &Chan, p: f32) {
        let old = ch.peak();
        let v = p.max(old * PEAK_DECAY);
        ch.peak.store(v.to_bits(), Ordering::Relaxed);
    }

    // ---- control side ----------------------------------------------------------------
    pub fn master_db(&self) -> f32 { lin_to_db(f32::from_bits(self.master_gain.load(Ordering::Relaxed))) }
    pub fn set_master_db(&self, db: f32) { self.master_gain.store(db_to_lin(db).to_bits(), Ordering::Relaxed); self.touch() }
    pub fn set_master_mute(&self, m: bool) { self.master_mute.store(m, Ordering::Relaxed); self.touch() }
    pub fn set_db(&self, dir: &str, c: usize, db: f32) -> bool {
        match self.chan(dir, c) { Some(ch) => { ch.set_gain(db_to_lin(db)); self.touch(); true } None => false }
    }
    pub fn set_mute(&self, dir: &str, c: usize, m: bool) -> bool {
        match self.chan(dir, c) { Some(ch) => { ch.mute.store(m, Ordering::Relaxed); self.touch(); true } None => false }
    }
    fn chan(&self, dir: &str, c: usize) -> Option<&Chan> {
        let v = match dir { "tx" => &self.tx, "rx" => &self.rx, _ => return None };
        v.get(c)
    }
    fn touch(&self) { self.dirty.store(now_us().max(1), Ordering::Relaxed) }

    pub fn state_json(&self) -> String {
        let f = |v: &Vec<Chan>| -> String {
            let g: Vec<String> = v.iter().map(|c| format!("{:.1}", lin_to_db(c.gain()))).collect();
            let m: Vec<&str> = v.iter().map(|c| if c.mute.load(Ordering::Relaxed) { "true" } else { "false" }).collect();
            format!("{{\"gain_db\":[{}],\"mute\":[{}]}}", g.join(","), m.join(","))
        };
        format!(
            "{{\"channels\":{},\"master_db\":{:.1},\"master_mute\":{},\"tx\":{},\"rx\":{}}}",
            self.channels, self.master_db(), self.master_mute.load(Ordering::Relaxed), f(&self.tx), f(&self.rx)
        )
    }

    // ---- persistence (key = value, one per line) ----------------------------------
    fn load_state(&self) {
        let Some(p) = &self.state_path else { return };
        let Ok(text) = std::fs::read_to_string(p) else { return };
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') { continue }
            let Some((k, v)) = line.split_once('=') else { continue };
            let (k, v) = (k.trim(), v.trim());
            let num = || v.parse::<f32>().ok();
            let flag = || matches!(v, "true" | "1");
            if k == "master_db" { if let Some(x) = num() { self.master_gain.store(db_to_lin(x).to_bits(), Ordering::Relaxed) } }
            else if k == "master_mute" { self.master_mute.store(flag(), Ordering::Relaxed) }
            else if let Some(rest) = k.strip_prefix("tx_db_") { if let (Ok(c), Some(x)) = (rest.parse::<usize>(), num()) { if let Some(ch) = self.tx.get(c) { ch.set_gain(db_to_lin(x)) } } }
            else if let Some(rest) = k.strip_prefix("rx_db_") { if let (Ok(c), Some(x)) = (rest.parse::<usize>(), num()) { if let Some(ch) = self.rx.get(c) { ch.set_gain(db_to_lin(x)) } } }
            else if let Some(rest) = k.strip_prefix("tx_mute_") { if let Ok(c) = rest.parse::<usize>() { if let Some(ch) = self.tx.get(c) { ch.mute.store(flag(), Ordering::Relaxed) } } }
            else if let Some(rest) = k.strip_prefix("rx_mute_") { if let Ok(c) = rest.parse::<usize>() { if let Some(ch) = self.rx.get(c) { ch.mute.store(flag(), Ordering::Relaxed) } } }
        }
        log::info!("mixer: state loaded from {} (master {:.1} dB{})", p.display(), self.master_db(),
            if self.master_mute.load(Ordering::Relaxed) { ", muted" } else { "" });
    }

    pub fn save_state(&self) {
        let Some(p) = &self.state_path else { return };
        let mut s = String::from("# SonusGrid mixer state — written by sonusgrid-bridge; safe to edit while stopped.\n");
        s += &format!("master_db = {:.1}\nmaster_mute = {}\n", self.master_db(), self.master_mute.load(Ordering::Relaxed));
        for (i, ch) in self.tx.iter().enumerate() {
            s += &format!("tx_db_{i} = {:.1}\ntx_mute_{i} = {}\n", lin_to_db(ch.gain()), ch.mute.load(Ordering::Relaxed));
        }
        for (i, ch) in self.rx.iter().enumerate() {
            s += &format!("rx_db_{i} = {:.1}\nrx_mute_{i} = {}\n", lin_to_db(ch.gain()), ch.mute.load(Ordering::Relaxed));
        }
        if let Some(dir) = p.parent() { let _ = std::fs::create_dir_all(dir); }
        let tmp = p.with_extension("toml.tmp");
        if std::fs::write(&tmp, s).and_then(|_| std::fs::rename(&tmp, p)).is_err() {
            log::warn!("mixer: could not save state to {}", p.display());
        }
    }

    // ---- publisher: meters file + control socket -------------------------------------
    /// Spawns the (normal-priority) service threads. Returns the meters file path.
    pub fn serve(self: &Arc<Self>, runtime_dir: &Path) -> std::io::Result<()> {
        let meters_path = runtime_dir.join("meters");
        let sock_path = runtime_dir.join("mixer.sock");
        let _ = std::fs::remove_file(&sock_path);
        let sock = UnixDatagram::bind(&sock_path)?;
        let file = File::create(&meters_path)?;
        file.set_len(SHM_SIZE as u64)?;

        // meters publisher
        let m = Arc::clone(self);
        std::thread::Builder::new().name("sg-meters".into()).spawn(move || {
            let mut buf = vec![0u8; SHM_SIZE];
            let mut seq: u32 = 0;
            let mut last_save = Instant::now();
            loop {
                seq = seq.wrapping_add(1);
                let master = if m.master_mute.load(Ordering::Relaxed) { 0.0 } else { f32::from_bits(m.master_gain.load(Ordering::Relaxed)) };
                let hdr: [u32; 8] = [SHM_MAGIC, SHM_VERSION, m.channels as u32, seq,
                    master.to_bits(), m.master_mute.load(Ordering::Relaxed) as u32, m.sample_rate, m.period];
                for (i, w) in hdr.iter().enumerate() { buf[i * 4..i * 4 + 4].copy_from_slice(&w.to_le_bytes()); }
                let mut off = SHM_HEADER;
                for arr in [&m.tx, &m.rx] {               // peaks
                    for c in 0..MAX_CH {
                        let v = arr.get(c).map(|ch| ch.peak()).unwrap_or(0.0);
                        buf[off..off + 4].copy_from_slice(&v.to_le_bytes()); off += 4;
                    }
                }
                for arr in [&m.tx, &m.rx] {               // gains (linear)
                    for c in 0..MAX_CH {
                        let v = arr.get(c).map(|ch| ch.gain()).unwrap_or(1.0);
                        buf[off..off + 4].copy_from_slice(&v.to_le_bytes()); off += 4;
                    }
                }
                for arr in [&m.tx, &m.rx] {               // mutes
                    for c in 0..MAX_CH {
                        buf[off] = arr.get(c).map(|ch| ch.mute.load(Ordering::Relaxed) as u8).unwrap_or(0); off += 1;
                    }
                }
                for side in 0..2 {                          // master output peaks
                    let v = f32::from_bits(m.master_peak[side].load(Ordering::Relaxed));
                    buf[off..off + 4].copy_from_slice(&v.to_le_bytes()); off += 4;
                }
                let _ = file.write_at(&buf, 0);
                // debounced persistence
                let d = m.dirty.load(Ordering::Relaxed);
                if d != 0 && now_us().saturating_sub(d) > 500_000 && last_save.elapsed() > Duration::from_millis(500) {
                    m.dirty.store(0, Ordering::Relaxed);
                    m.save_state();
                    last_save = Instant::now();
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        })?;

        // control socket
        let m = Arc::clone(self);
        std::thread::Builder::new().name("sg-mixer-ctl".into()).spawn(move || {
            let mut buf = [0u8; 512];
            loop {
                let Ok((n, from)) = sock.recv_from(&mut buf) else { continue };
                let cmd = String::from_utf8_lossy(&buf[..n]);
                let reply = m.handle(cmd.trim());
                if let Some(addr) = from.as_pathname() {
                    let _ = sock.send_to(reply.as_bytes(), addr);
                }
            }
        })?;
        log::info!("mixer: control socket {} · meters {}", sock_path.display(), meters_path.display());
        Ok(())
    }

    fn handle(&self, cmd: &str) -> String {
        let parts: Vec<&str> = cmd.split_whitespace().collect();
        let ok = match parts.as_slice() {
            ["get"] => true,
            ["master", db] => db.parse::<f32>().map(|d| self.set_master_db(d)).is_ok(),
            ["mmute", v] => { self.set_master_mute(matches!(*v, "1" | "true" | "on")); true }
            ["set", dir, c, db] => match (c.parse::<usize>(), db.parse::<f32>()) {
                (Ok(c), Ok(d)) => self.set_db(dir, c, d), _ => false },
            ["mute", dir, c, v] => match c.parse::<usize>() {
                Ok(c) => self.set_mute(dir, c, matches!(*v, "1" | "true" | "on")), _ => false },
            ["save"] => { self.save_state(); true }
            _ => false,
        };
        if ok { self.state_json() } else { format!("{{\"error\":\"bad command: {cmd}\"}}") }
    }
}

fn now_us() -> u64 {
    let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
    ts.tv_sec as u64 * 1_000_000 + ts.tv_nsec as u64 / 1000
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn db_roundtrip() {
        assert!((lin_to_db(db_to_lin(-6.0)) + 6.0).abs() < 0.01);
        assert_eq!(db_to_lin(-100.0), 0.0);
        assert_eq!(db_to_lin(3.0), 1.0); // no boost
    }
    #[test] fn commands() {
        let m = Mixer::new(4, 48000, 256, None);
        assert!(m.handle("set tx 1 -6").contains("\"channels\":4"));
        assert!((lin_to_db(m.tx_target(1)) + 6.0).abs() < 0.05);
        m.handle("mmute 1");
        assert_eq!(m.master_target(), 0.0);
        assert!(m.handle("bogus").contains("error"));
    }
}
