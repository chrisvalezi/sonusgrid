// SPDX-License-Identifier: GPL-3.0-or-later
//
// Stream abstractions used by SonusGridDevice. CoreAudio's HAL has its own
// AudioServerPlugIn-side stream objects; this Swift type is the convenient
// state container that the Obj-C shim queries via property selectors.
//

import Foundation
import CoreAudio

public enum StreamDirection {
    case input   // RX — Dante → macOS apps
    case output  // TX — macOS apps → Dante
}

public final class SonusGridStream {
    public let streamID: AudioObjectID
    public let direction: StreamDirection
    public var channelCount: UInt32
    public var sampleRate: Float64
    public var bitDepth: UInt32 = 32   // matches f32 in inferno-c
    public var isActive: Bool = true

    public init(
        streamID: AudioObjectID, direction: StreamDirection,
        channelCount: UInt32, sampleRate: Float64
    ) {
        self.streamID = streamID
        self.direction = direction
        self.channelCount = channelCount
        self.sampleRate = sampleRate
    }

    public var virtualFormat: AudioStreamBasicDescription {
        AudioStreamBasicDescription(
            mSampleRate: sampleRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsFloat
                | kAudioFormatFlagIsPacked
                | kAudioFormatFlagsNativeEndian,
            mBytesPerPacket: 4 * channelCount,
            mFramesPerPacket: 1,
            mBytesPerFrame: 4 * channelCount,
            mChannelsPerFrame: channelCount,
            mBitsPerChannel: 32,
            mReserved: 0
        )
    }
}
