# SonusGrid — macOS port

This subtree is the macOS-specific code for SonusGrid. It complements the
Linux build in the parent directory with:

- A C-ABI shim (`crates/inferno-c/`) over the `inferno_aoip` Dante engine,
  so Swift can drive it from inside `coreaudiod`.
- A macOS-native PTP daemon (`statime-macos/`).
- A CoreAudio HAL plug-in (`halplugin/`), Swift sources skeleton.
- A SwiftUI front-end (`app/`), skeleton mirroring the GTK GUI.
- launchd integration (`launchd/`).
- A signed/notarized `.pkg` installer (`installer/`).

## Status

**Phase A complete (Rust shims compile cross-target). Phases C-F still
require a Mac with Xcode.**

| Subdir | What's here | What's missing |
|---|---|---|
| `../crates/inferno-c/` | Cargo crate + cbindgen-generated header. Stubs for the C ABI. Compiles on Linux + cross-checks for both Apple targets. 3/3 tests pass. | Real wiring to `inferno_aoip` (currently stubs return `NotImplemented`). |
| `statime-macos/` | Cargo crate, parses TOML, has a launchd-friendly main loop. Compiles on Linux + cross-checks for both Apple targets. 1/1 test passes. | Real wiring to `statime` core + `clock_settime` + usrvclock socket. |
| `halplugin/Sources/` | 4 Swift files (Plugin, Device, Streams, InfernoBridge) — architecture is staked out. Info.plist ready. | Obj-C entry shim implementing the `AudioServerPlugInDriver` v-table. Xcode project. Bridging header for inferno-c. |
| `app/Sources/` | 5 Swift files (App, HeroCardView, ConfigView, CLI, StatusViewModel). Visual parity with Linux GTK GUI. | Xcode project. AppIcon.iconset. Full Preferences window. |
| `launchd/` | `io.sonusgrid.clock.plist` ready. | None — it's a one-file deliverable. |
| `installer/` | `build-pkg.sh`, `distribution.xml`, postinstall/preinstall scripts, license/welcome HTML. | Run on a Mac with Apple Developer cert. |

## Build matrix

```
crates/inferno-c          Rust   linux + macos universal     ✓ skeleton
crates/sonus-cli          Rust   linux + macos universal     ✓ cfg-gated
macos/statime-macos       Rust   macos universal             ✓ skeleton
macos/halplugin           Swift  macos universal             ✗ needs Mac/Xcode
macos/app                 Swift  macos universal             ✗ needs Mac/Xcode
macos/installer           Bash   macos                       ✗ needs Mac
```

## How the existing Linux build is unaffected

- `crates/sonus-cli` is now cfg-gated; the Linux test suite still passes
  (4/4) and the Linux `.deb` still builds.
- The `vendor/inferno/` workspace is untouched — the Linux `.deb` still
  bundles the ALSA plug-in (`libasound_module_pcm_inferno.so`).
- A new crate `crates/inferno-c/` is added without touching upstream
  Inferno; the Linux build doesn't pull it in.

## Continuing on a Mac

```bash
git clone <repo>
cd sonusgrid
git submodule update --init --recursive
rustup target add aarch64-apple-darwin x86_64-apple-darwin

# Verify cross-target compiles still pass:
cargo check --manifest-path crates/sonus-cli/Cargo.toml --target=aarch64-apple-darwin
cargo check --manifest-path crates/inferno-c/Cargo.toml --target=aarch64-apple-darwin
cargo check --manifest-path macos/statime-macos/Cargo.toml --target=aarch64-apple-darwin

# Then on the Mac, open the Xcode projects (need to be created from scratch
# in Xcode the first time — File → New → Project → macOS → App / Bundle).
open macos/halplugin/   # drag Sources/ into a new Xcode project
open macos/app/         # idem

# Once project files exist:
xcodebuild -project macos/halplugin/SonusGridHAL.xcodeproj -scheme SonusGridHAL ARCHS="arm64 x86_64"
xcodebuild -project macos/app/SonusGrid.xcodeproj -scheme SonusGrid ARCHS="arm64 x86_64"

# Final pkg:
bash macos/installer/build-pkg.sh 0.3.0 universal
```

See `docs/ARCHITECTURE_macOS.md` for the full design and `docs/INSTALL_macOS.md`
for end-user instructions.
