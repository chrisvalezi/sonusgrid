# SonusGridHAL — CoreAudio Plug-In

This is the macOS virtual audio driver. It's compiled into a `.driver`
bundle (technically a CFBundle of type `BNDL` registered as an
AudioServerPlugIn), installed into `/Library/Audio/Plug-Ins/HAL/`, and loaded
by `coreaudiod` at boot. End users see a virtual device named
**SonusGrid-Virtual** in System Settings → Sound; audio routed there flows
to the Dante network via the bundled `libinferno_c.dylib`.

## Status

**Skeleton only — phase C of the macOS port (4-6 weeks of work).** The
Swift sources stake out the architecture; the Obj-C entry point that
implements the `AudioServerPlugInDriver` v-table still needs to be written.

## Build

Requires macOS + Xcode 15+. Cannot be built from Linux.

```bash
xcodebuild -project SonusGridHAL.xcodeproj \
    -scheme SonusGridHAL -configuration Release \
    ARCHS="arm64 x86_64" ONLY_ACTIVE_ARCH=NO \
    CODE_SIGN_IDENTITY="Developer ID Application: <NAME> (<TEAMID>)"
```

Output: `build/Release/SonusGridHAL.bundle/Contents/MacOS/SonusGridHAL`,
plus `Contents/Frameworks/libinferno_c.dylib` copied from
`crates/inferno-c/target/.../release/`.

## Install (development)

```bash
sudo cp -r build/Release/SonusGridHAL.bundle \
    /Library/Audio/Plug-Ins/HAL/SonusGrid.driver
sudo chown -R root:wheel /Library/Audio/Plug-Ins/HAL/SonusGrid.driver
sudo killall coreaudiod
```

`coreaudiod` reloads the plug-in. Open *System Settings → Sound* — should
list **SonusGrid-Virtual** as both an Output and an Input device.

## Files

| File | Role |
|---|---|
| `Sources/Plugin.swift` | Singleton owning plugin state + box ID assignment |
| `Sources/Device.swift` | Virtual device, IO start/stop, realtime processIOBlock |
| `Sources/Streams.swift` | Input/output stream containers + ASBD |
| `Sources/InfernoBridge.swift` | Swift wrapper over libinferno_c FFI |
| `Info.plist` | CFPlugIn registration, code-sign metadata |

## What's missing (phase C TODO)

1. **Objective-C entry shim** (`SonusGridHALEntry.m`) implementing the
   `AudioServerPlugInDriver` v-table. Swift can't synthesise C function
   pointers in a struct. Pattern: copy from BlackHole's structure (AGPL —
   we read for shape, write fresh).
2. **`AudioObjectGetPropertyData` dispatch** — every property selector the
   HAL queries (DeviceUID, ManufacturerName, Streams, Format, Latency,
   Volume) needs a switch case.
3. **IO loop** — `BeginIOOperation` / `DoIOOperation` / `EndIOOperation`
   triplet. Push the buffers from `kAudioServerPlugInIOOperationWriteMix`
   into `processIOBlock`.
4. **Bridging header** that #imports `crates/inferno-c/include/inferno.h`
   so Swift can call `inferno_init`, `inferno_push_tx_block`, etc.
5. **dylib bundling**: link/embed `libinferno_c.dylib` inside
   `SonusGridHAL.bundle/Contents/Frameworks/` with `@rpath` properly set
   so coreaudiod can load it sandboxed.
6. **Notarization** via `xcrun notarytool` — mandatory for end-user installs.
