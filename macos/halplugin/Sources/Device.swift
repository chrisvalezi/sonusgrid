// SPDX-License-Identifier: GPL-3.0-or-later
//
// SonusGridDevice — the virtual Dante audio device hosted in coreaudiod.
//
// Two streams: input (RX channels from the Dante network) and output (TX
// channels to the Dante network). The IO callback runs on the realtime
// audio thread; everything in the IO path must be lock-free.
//

import Foundation
import CoreAudio
import AudioToolbox

public final class SonusGridDevice {
    public let deviceID: AudioObjectID
    public let uid: String
    public var name: String
    public var sampleRate: Float64
    public var channelsIn: UInt32
    public var channelsOut: UInt32

    public let inputStreamID:  AudioObjectID = 4
    public let outputStreamID: AudioObjectID = 5

    /// Inferno bridge — created on first start, torn down on plugin unload.
    private var bridge: InfernoBridge?

    /// Ring buffer state. In the real implementation this is replaced by
    /// the C ring buffer inside libinferno_c (push_tx / pull_rx are O(1)
    /// memcpy into a lock-free structure on the C side).
    private var running = false

    public init(
        deviceID: AudioObjectID, uid: String, name: String,
        sampleRate: Float64, channelsIn: UInt32, channelsOut: UInt32
    ) {
        self.deviceID = deviceID
        self.uid = uid
        self.name = name
        self.sampleRate = sampleRate
        self.channelsIn = channelsIn
        self.channelsOut = channelsOut
    }

    /// Called from the HAL plugin's StartIO entry. Spins up the Inferno
    /// bridge and starts processing.
    public func startIO(networkInterface: String, bindIP: String?, clockSocket: String?) -> Bool {
        guard !running else { return true }
        let cfg = InfernoBridge.Config(
            name: name, bindIP: bindIP, interfaceName: networkInterface,
            sampleRate: UInt32(sampleRate), rxChannels: channelsIn, txChannels: channelsOut,
            rxLatencyNS: 4_000_000, txLatencyNS: 4_000_000,
            clockSocketPath: clockSocket
        )
        guard let b = InfernoBridge(config: cfg) else {
            NSLog("SonusGrid: failed to initialise InfernoBridge")
            return false
        }
        if b.start() != .ok {
            NSLog("SonusGrid: InfernoBridge.start() failed")
            return false
        }
        self.bridge = b
        self.running = true
        return true
    }

    public func stopIO() {
        guard running else { return }
        _ = bridge?.stop()
        bridge = nil
        running = false
    }

    /// Called from the realtime audio thread for every IO cycle.
    /// `outputBuffer` carries samples coming OUT of macOS into the Dante
    /// network (TX). `inputBuffer` is filled with samples coming FROM the
    /// Dante network into macOS (RX).
    @inline(__always)
    public func processIOBlock(
        outputBuffer: UnsafePointer<Float>?, // TX from apps to Dante
        inputBuffer:  UnsafeMutablePointer<Float>?, // RX from Dante to apps
        frames: UInt32
    ) -> OSStatus {
        guard let bridge = bridge else { return -1 }
        if let outputBuffer = outputBuffer {
            _ = bridge.pushTX(samples: outputBuffer, frames: frames, channels: channelsOut)
        }
        if let inputBuffer = inputBuffer {
            _ = bridge.pullRX(samples: inputBuffer, frames: frames, channels: channelsIn)
        }
        return noErr
    }
}
