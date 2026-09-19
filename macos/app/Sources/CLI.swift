// SPDX-License-Identifier: GPL-3.0-or-later
//
// CLI — runs `sonusgrid <args>` as a child process and parses output.
//
// Same boundary the Linux GUI uses: the SwiftUI code here never imports
// libinferno_c directly; it goes through the CLI subprocess. Keeps the
// process boundary, error handling, and lifecycle simple.
//

import Foundation

struct NetworkInterface: Hashable, Codable {
    let name: String
    let ipv4: String?
}

struct CLIStatus: Codable {
    let version: String
    let clock_active: Bool
    let audio_active: Bool
    let sink_present: Bool
    let device_name: String
    let interface: String
    let ptp_version: String

    var overall: StatusKind {
        if clock_active && audio_active && sink_present { return .on }
        if clock_active || audio_active { return .starting }
        return .off
    }
}

enum StatusKind {
    case on, starting, off
}

enum CLIError: Error {
    case notFound, exitNonZero(Int32, String)
}

@MainActor
final class CLI {
    static let shared = CLI()

    private let executable = "/usr/local/bin/sonusgrid"

    private func run(args: [String], timeout: TimeInterval = 30) async throws -> (rc: Int32, stdout: String, stderr: String) {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: executable)
        proc.arguments = args
        let outPipe = Pipe(); let errPipe = Pipe()
        proc.standardOutput = outPipe
        proc.standardError = errPipe
        do {
            try proc.run()
        } catch {
            throw CLIError.notFound
        }
        proc.waitUntilExit()
        let out = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let err = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return (proc.terminationStatus, out, err)
    }

    func status() async -> CLIStatus? {
        guard let (rc, out, _) = try? await run(args: ["status", "--json"]) else { return nil }
        guard rc == 0 else { return nil }
        return try? JSONDecoder().decode(CLIStatus.self, from: Data(out.utf8))
    }

    func start() async {
        _ = try? await run(args: ["start"], timeout: 30)
    }

    func stop() async {
        _ = try? await run(args: ["stop"], timeout: 15)
    }

    func restart() async {
        _ = try? await run(args: ["restart"], timeout: 30)
    }

    func doctor() async -> String {
        guard let (_, out, err) = try? await run(args: ["doctor"]) else { return "(CLI not found)" }
        return out + (err.isEmpty ? "" : "\n" + err)
    }

    func interfaces() async -> [NetworkInterface] {
        // `ifconfig -a` parsing — minimal, returns only NICs with active link.
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/sbin/ifconfig")
        proc.arguments = ["-a"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        do { try proc.run() } catch { return [] }
        proc.waitUntilExit()
        let raw = String(
            data: pipe.fileHandleForReading.readDataToEndOfFile(),
            encoding: .utf8) ?? ""
        var result: [NetworkInterface] = []
        var currentName: String?
        var currentIPv4: String?
        for line in raw.split(separator: "\n", omittingEmptySubsequences: false) {
            let s = String(line)
            if !s.hasPrefix("\t") {
                if let n = currentName,
                   !n.hasPrefix("lo"), !n.hasPrefix("utun"),
                   !n.hasPrefix("anpi"), !n.hasPrefix("llw"),
                   !n.hasPrefix("ap"), !n.hasPrefix("awdl"),
                   !n.hasPrefix("bridge"), !n.hasPrefix("gif"),
                   !n.hasPrefix("stf"), !n.hasPrefix("p2p") {
                    result.append(NetworkInterface(name: n, ipv4: currentIPv4))
                }
                currentName = String(s.split(separator: ":").first ?? "")
                currentIPv4 = nil
            } else if s.contains("inet ") {
                let parts = s.split(separator: " ", omittingEmptySubsequences: true)
                if let i = parts.firstIndex(of: "inet"), parts.count > i + 1 {
                    let v = String(parts[i + 1])
                    if !v.contains(":") { currentIPv4 = v }
                }
            }
        }
        if let n = currentName,
           !n.hasPrefix("lo") && !n.hasPrefix("utun") {
            result.append(NetworkInterface(name: n, ipv4: currentIPv4))
        }
        return result
    }
}
