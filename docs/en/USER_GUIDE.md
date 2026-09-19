# User Guide — SonusGrid

(English mirror; primary docs are in Portuguese under `docs/`.)

> **For DAW use (music production, low-latency)** see the dedicated guide
> [DAW.md](../DAW.md) (bilingual) — covers the embedded JACK client,
> latency per period, real-time kernel, and Reaper / Ardour / Bitwig setup.

## One-line concept

SonusGrid exposes your Linux PC as a Dante device on the network. You route
channels with **Dante Controller** (running on any Windows/Mac), and any
Linux app that plays or records audio (Spotify, Firefox, Audacity, DAW)
talks to the Dante network.

## Audio path (unified, SoundGrid-style)

```
   PulseAudio apps         DAW JACK (Reaper, Ardour, Bitwig)
   (Spotify, Chrome,       │
    pavucontrol)           │ JACK ports SonusGrid:tx_01..tx_NN
        │                  │
        │ PulseAudio       ▼
        ▼               ┌───────────────────────────────────┐
   PipeWire null-sink  │  sonusgrid-bridge (single proc)   │
   "SonusGrid"         │  • sole owner of plug:sonusgrid   │
        │               │  • mixes PA + JACK per channel    │
        │ monitor       │  • exposes JACK rx_01..rx_NN      │
        ▼               └───────────────────────────────────┘
                                  │ ALSA s32le N channels
                                  ▼
                        [SonusGrid Rust ALSA plug-in]
                                  │ RTP multicast/unicast
                                  ▼
                       [Switch + Dante hardware]
                                  ▼
                              🔊 sound
```

The current version uses a **native Rust bridge** (`sonusgrid-bridge`) that
replaced the old ffmpeg stage, eliminating ~20 s of latency and recurring
xruns. There is no longer a runtime ffmpeg dependency.

## Daily operation

### Start

Three equivalent paths:
1. **GUI**: click **SonusGrid** in the application menu. If status reads
   "Stopped", click **Start**.
2. **Terminal**: `sonusgrid start`
3. **Auto-start at login**: `systemctl --user enable sonusgrid-clock.service
   sonusgrid-audio.service` (once).

After 3-5 seconds the status turns green and the device "SonusGrid" appears
in Dante Controller's matrix.

### Route channels

You need **Dante Controller** running on another PC on the same network
(Windows or macOS — Audinate doesn't ship a Linux build). It auto-discovers
your SonusGrid and shows it with **N TX × N RX** where N is whatever you
configured in `device.tx_channels` / `rx_channels` (default 16, supports up
to 256).

Quick test without Dante Controller:

```bash
sonusgrid devices    # list Dante devices visible via mDNS
```

### Send Linux audio to SonusGrid

**Via the GUI**: open SonusGrid → **Dante network** page. It lists the Dante
devices discovered on the LAN, the PipeWire session's JACK buffer, and
launchers for the **per-app mixer (pavucontrol)** — where you pick SonusGrid
as each app's output — and the **visual patchbay (qpwgraph)** for manual
JACK/PipeWire wiring. The **Diagnostics** page shows `doctor` as a checklist
and follows the logs live.

**Via pavucontrol**:

```bash
sonusgrid route      # opens pavucontrol focused on Playback
```

In the **Playback** tab, click each app's output dropdown and pick
**SonusGrid (Dante-compatible)**.

**System-wide default**:
```bash
pactl set-default-sink SonusGrid
```

### Capture Dante audio into Linux

SonusGrid exposes **two capture paths**, depending on the app:

* **PulseAudio apps** (Audacity, OBS, conferencing) — the virtual source
  `SonusGrid_RX` (stereo, channels 1+2) shows up in
  `pavucontrol → Recording` like a microphone.

* **JACK DAWs** (Reaper, Ardour, Bitwig) — the ports
  `SonusGrid:rx_01..rx_NN` carry full multichannel audio. See [DAW.md](../DAW.md).

### Stop

```bash
sonusgrid stop
```

Or click **Stop** in the GUI.

## Configuration

File: `~/.config/sonusgrid/config.toml`. The GUI's **Configuration** tab
covers all common fields. From the terminal:

```bash
sonusgrid config edit
sonusgrid config check
sonusgrid restart
```

See the Portuguese guide for full per-field documentation. Quick highlights:

* **NIC selection is mandatory** — no "auto" mode. Pick the NIC connected
  to the Dante switch in the GUI dropdown (which shows current IPv4) or
  edit `[network] interface = "..."`. The `bind_ip` is **auto-resolved**
  on every `sonusgrid start` — DHCP-renewed addresses are picked up
  without manual intervention.

* **Channels up to 256** — `rx_channels` and `tx_channels` accept any
  value 0-256. Engine limit is 32 Dante flows × 8 channels per flow = 256.

* **JACK on/off** — `[bridge] jack_enabled = true|false`. When off, only
  the PulseAudio sink path is active (no `tx_NN`/`rx_NN` JACK ports).

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
