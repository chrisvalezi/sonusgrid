// SPDX-License-Identifier: GPL-3.0-or-later
//
// SonusGrid HAL plugin — entry point for AudioServerPlugIn.
//
// The HAL plugin runs in `coreaudiod`, not in our app. It registers a
// virtual audio device that other apps can target as a Sound output (or
// input). When the device is in use, the plugin pushes/pulls audio to/from
// the bundled inferno_c library, which carries it on the Dante network.
//
// Architecture mirrors BlackHole / NullAudio examples. We expose:
//   • One AudioServerPlugInDriver entry (`SonusGridDriverEntry`)
//   • One Box (group of devices)
//   • One Device ("SonusGrid-Virtual"), 16 channels in + 16 channels out
//   • Two Streams (input + output)
//
// IMPORTANT: AudioServerPlugIn requires C-callable function pointers in a
// COM-style v-table. Pure Swift cannot synthesize that. The published API
// must be either (a) C, with Swift backing helpers, or (b) Objective-C++
// which can host both. This skeleton uses the (b) layout: the .bundle has a
// thin Objective-C entry that forwards to Swift classes.
//
// For now we only stake out the Swift surface. The Obj-C entry shim will
// land alongside Phase C real work.

import Foundation
import CoreAudio
import AudioToolbox

/// Singleton holding plugin-global state.
///
/// In a real HAL plugin, this is owned by the C entry function via a
/// `static` AudioServerPlugInDriver struct. We model it as a singleton so
/// the Obj-C shim only needs to call `SonusGridPlugin.shared`.
public final class SonusGridPlugin {
    public static let shared = SonusGridPlugin()

    public let pluginID: AudioObjectID = 1     // assigned by HAL
    public let boxID:    AudioObjectID = 2
    public let deviceID: AudioObjectID = 3

    public private(set) var device: SonusGridDevice
    private let stateLock = NSLock()

    private init() {
        self.device = SonusGridDevice(
            deviceID: deviceID,
            uid: "io.sonusgrid.virtual",
            name: "SonusGrid-Virtual",
            sampleRate: 48000,
            channelsIn: 16,
            channelsOut: 16
        )
    }

    /// Called by the Obj-C shim's CreateDevice / DestroyDevice pair.
    public func reconfigureDevice(name: String, channelsIn: UInt32, channelsOut: UInt32, sampleRate: Float64) {
        stateLock.lock()
        defer { stateLock.unlock() }
        device.name = name
        device.channelsIn = channelsIn
        device.channelsOut = channelsOut
        device.sampleRate = sampleRate
    }
}
