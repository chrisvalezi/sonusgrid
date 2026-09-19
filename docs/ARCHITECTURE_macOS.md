# Architecture — SonusGrid on macOS

> EN-only document for contributors. End-user docs are under
> `docs/INSTALL_macOS.md` and `docs/USER_GUIDE.md`.

## Why a different architecture from Linux?

Linux has ALSA, PipeWire, PulseAudio, systemd, and well-documented
userspace audio plumbing. macOS has CoreAudio, `coreaudiod`, launchd, and
Apple's `AudioServerPlugIn` C-only API. None of the Linux plumbing exists
on macOS, so the architecture is fundamentally different even though the
network plane (Dante protocol via `inferno_aoip`) is the same.

## Process map

```
                  SonusGrid.app (SwiftUI)
                          │ Process.run("sonusgrid …")
                          ▼
                  /usr/local/bin/sonusgrid
                ┌─────────┼──────────┐
                ▼         ▼          ▼
            launchctl  log show  ifconfig
                │       (in-process)
                ▼
   /Library/LaunchDaemons/io.sonusgrid.clock.plist
   ─ runs as root ──────────────────────────────────
   /usr/local/libexec/sonusgrid/statime-macos
     • Reads /etc/sonusgrid/clock.toml
     • Joins PTP multicast on the chosen NIC
     • Writes disciplined timestamps to
       /var/run/sonusgrid/usrvclock (UNIX socket)

   coreaudiod (system process, sandboxed)
   ─────────────────────────────────────
   /Library/Audio/Plug-Ins/HAL/SonusGrid.driver/
     │ loaded via CFPluginFactories at coreaudiod start
     ▼
     SonusGridHAL.bundle
       • AudioServerPlugInDriver C v-table (Obj-C entry shim)
       • Forwards to Swift classes (Plugin/Device/Streams)
       • Real-time IO callback ties into:
         libinferno_c.dylib  (bundled in Contents/Frameworks/)
           ↳ inferno_aoip Tokio runtime (RTP, mDNS, ARC)
           ↳ Reads /var/run/sonusgrid/usrvclock for PTP timestamps
           ↳ UDP sockets → switch Dante físico
```

## Why two processes (statime + HAL plug-in) and not one daemon?

- **PTP daemon needs `cap_sys_time` equivalent**: macOS doesn't have POSIX
  capabilities, but `launchd` running as root has the same effect. The
  HAL plug-in can't be root because it lives inside `coreaudiod` (a
  sandboxed service Apple manages).
- **HAL plug-in lives in `coreaudiod`**: this is non-negotiable on macOS.
  CoreAudio loads HAL plug-ins from `/Library/Audio/Plug-Ins/HAL/` into
  `coreaudiod` at launch. Plug-ins cannot host their own PTP daemon
  because `coreaudiod` is sandboxed and re-launched by Apple at unknown
  cadences.
- **Sharing via `usrvclock` UNIX socket**: same pattern Inferno uses on
  Linux to bridge `statime-linux` and the ALSA plug-in. The macOS port
  reuses this — `statime-macos` writes timestamps; `libinferno_c.dylib`
  reads them.

## Why a C ABI shim (`inferno-c`) instead of calling Rust directly from Swift?

Three reasons:

1. **Stable ABI surface for the HAL plug-in.** Swift's ABI on macOS is
   stable but Apple-specific; Rust's is not stable across compiler versions
   at all. C ABI is the lowest common denominator and lets us upgrade
   either side independently.
2. **Realtime contract.** The HAL plug-in's IO callback runs on a
   real-time-priority thread. It must not allocate, lock, or block. The C
   shim's `inferno_push_tx_block` and `inferno_pull_rx_block` are
   documented as realtime-safe and implemented as memcpy into a lock-free
   ring buffer. The actual network plumbing (Tokio runtime) lives on a
   normal-priority thread spawned during `inferno_init`.
3. **Compile-time safety.** Tokio + `inferno_aoip` use threads, futures,
   channels, allocations — none of which are appropriate in a realtime
   audio callback. Forcing the boundary through a C ABI surfaces this
   invariant: anything in Rust that takes a `&mut self` and might block
   simply cannot be exposed.

## Realtime data flow

Push (TX, app → Dante):
```
   AppKit/SwiftUI app  →  CoreAudio AU Output Stream  →  HAL IO callback
   ─ realtime thread ───────────────────────────────────────────────────
   processIOBlock()  →  bridge.pushTX()  →  inferno_push_tx_block(C)
   ─ memcpy into ring buffer (lock-free, no allocation) ────────────────
   ─ Tokio thread (normal priority) ────────────────────────────────────
   loop { drain ring buffer; pack into RTP; send UDP }
```

Pull (RX, Dante → app):
```
   ─ Tokio thread ──────────────────────────────────────────────────────
   recv UDP RTP  →  unpack  →  push into ring buffer
   ─ realtime thread ───────────────────────────────────────────────────
   inferno_pull_rx_block(C)  →  bridge.pullRX()  →  CoreAudio input stream
```

Underrun on the realtime side fills with silence. Overrun on the Tokio
side drops oldest data.

## File layout (installed)

```
/Applications/SonusGrid.app/                 ← SwiftUI app (signed)
/Library/Audio/Plug-Ins/HAL/SonusGrid.driver/
    Contents/
        Info.plist                           ← AudioServerPlugIn registration
        MacOS/SonusGridHAL                   ← bundle binary (signed)
        Frameworks/libinferno_c.dylib        ← Inferno engine (signed)
/Library/LaunchDaemons/io.sonusgrid.clock.plist
/usr/local/bin/sonusgrid                     ← CLI (universal)
/usr/local/libexec/sonusgrid/statime-macos   ← PTP daemon (universal)
/etc/sonusgrid/clock.toml                    ← Statime config
~/.config/sonusgrid/config.toml              ← Per-user app config
/var/run/sonusgrid/usrvclock                 ← PTP→HAL plug-in socket
/var/log/sonusgrid/clock.log                 ← Statime log
```

## Code-signing & notarization

Mandatory. Without notarization the macOS Gatekeeper refuses to load HAL
plug-ins. The `installer/build-pkg.sh` script does:

1. `cargo build --target=arm64,x86_64` then `lipo` for universal binaries
2. `xcodebuild` for HAL plug-in + app, with
   `OTHER_CODE_SIGN_FLAGS="--options=runtime --timestamp"` (hardened
   runtime, secure timestamp)
3. `pkgbuild` + `productbuild` with `--sign "Developer ID Installer:…"`
4. `xcrun notarytool submit … --wait` (Apple's servers process in 2-15
   minutes)
5. `xcrun stapler staple` (embeds the notarization ticket so even offline
   Macs trust the package)

## What's still pending (phase C-F)

- Obj-C entry shim (`SonusGridHALEntry.m`) implementing the
  `AudioServerPlugInDriver` v-table. Pure Swift can't synthesize a C
  function-pointer struct.
- Real Inferno integration in `inferno-c` (currently stubs).
- Real PTP integration in `statime-macos` (currently parse-only).
- Xcode project files for `halplugin/` and `app/` (Swift sources are
  there; the `.xcodeproj` bundles need to be generated on a Mac).
- App icon (`AppIcon.iconset` and `.icns`).
- Smoke testing on real hardware.

See the plan at `~/.claude/plans/functional-marinating-truffle.md` for
the full phase breakdown.
