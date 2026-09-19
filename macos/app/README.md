# SonusGrid.app — SwiftUI macOS App

The native macOS front-end. Visual parity with the Linux GTK GUI: hero
status card, configuration list, tools list. Talks to `sonusgrid` CLI via
subprocess.

## Status

**Skeleton only — phase E.** Sources stake out the SwiftUI hierarchy and
the CLI bridge. Xcode project file `SonusGrid.xcodeproj/` still needs to
be created (manually in Xcode or via `swift package init` + manual port).

## Files

| File | Role |
|---|---|
| `Sources/App.swift` | `@main` entry, Window scene, Settings scene |
| `Sources/HeroCardView.swift` | Big status card with gradient glyph + pill toggle (mirrors Linux) |
| `Sources/ConfigView.swift` | Boxed list with name, NIC dropdown (with IPs), latency, channels, PTP — Apply button |
| `Sources/StatusViewModel.swift` | `ObservableObject` polling CLI every 2.5 s, exposing state to views |
| `Sources/CLI.swift` | `Process`-based bridge to `/usr/local/bin/sonusgrid`, `ifconfig`-based NIC enumeration |
| `Resources/Info.plist` | App metadata, minimum macOS 13 |

## Build (on a Mac)

Open `SonusGrid.xcodeproj` in Xcode, or:

```bash
xcodebuild -project app/SonusGrid.xcodeproj \
    -scheme SonusGrid -configuration Release \
    ARCHS="arm64 x86_64" ONLY_ACTIVE_ARCH=NO \
    CODE_SIGN_IDENTITY="Developer ID Application: <NAME> (<TEAMID>)"
```

Output: `build/Release/SonusGrid.app` (universal binary).

## What's missing (phase E TODO)

1. **Xcode project file** — currently absent; the SwiftUI sources need to
   be wired into a target. Easiest: create from Xcode (File → New →
   Project → macOS App → SwiftUI), then copy the source files in.
2. **AppIcon.icns** — design the SonusGrid icon with the same gradient as
   the Linux SVG.
3. **Hardened runtime + entitlements** for sandbox + signing.
4. **Settings (Preferences) window** — currently a stub. Add full-blown
   editor (sample rate, channel counts beyond what the home shows, PTP
   domain/priority, etc.) like the Linux preferences dialog.
5. **`sonusgrid config set`** — the CLI needs to grow this subcommand so
   the SwiftUI app can write fields atomically without serialising TOML
   in Swift.
6. **Lipo dance for the dylib**: `libinferno_c.dylib` lives inside the
   HAL plugin bundle, but the GUI may want to read configuration helpers
   from a separate `libsonusgrid_helpers.dylib` (TBD if needed).
