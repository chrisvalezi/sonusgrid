// SPDX-License-Identifier: GPL-3.0-or-later
//
// StatusViewModel — observable state shared by the views. Polls the CLI
// every 2.5 s and exposes Apply/Toggle helpers that the views call.
//

import SwiftUI

@MainActor
final class StatusViewModel: ObservableObject {
    @Published var state: StatusKind = .off
    @Published var deviceName: String = "SonusGrid"
    @Published var interfaceLabel: String = "—"
    @Published var ptpVersion: String = "v1"
    @Published var sinkActive: Bool = false
    @Published var interfaces: [NetworkInterface] = []
    @Published var lastError: String?

    private var pollingTask: Task<Void, Never>?

    var title: String {
        switch state {
        case .on:       return "\(deviceName)  ·  Conectado"
        case .starting: return "Inicializando…"
        case .off:      return "Parado"
        }
    }
    var subtitle: String {
        switch state {
        case .on:
            return "PTP \(ptpVersion)  ·  interface \(interfaceLabel)"
                + (sinkActive ? "  ·  sink ativo" : "")
        case .starting:
            return "Aguardando PTP/áudio subir."
        case .off:
            return "Selecione a interface, clique Aplicar e Iniciar."
        }
    }

    func startPolling() async {
        // Initial interface enumeration
        interfaces = await CLI.shared.interfaces()
        await refresh()
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                await self?.refresh()
            }
        }
    }

    func refresh() async {
        guard let s = await CLI.shared.status() else {
            state = .off
            return
        }
        state = s.overall
        deviceName = s.device_name.isEmpty ? "SonusGrid" : s.device_name
        interfaceLabel = s.interface.isEmpty ? "—" : s.interface
        ptpVersion = s.ptp_version
        sinkActive = s.sink_present
    }

    func toggle() async {
        switch state {
        case .on:        await CLI.shared.stop()
        case .starting:  break
        case .off:       await CLI.shared.start()
        }
        await refresh()
    }

    func openDoctor() async {
        let body = await CLI.shared.doctor()
        let alert = NSAlert()
        alert.messageText = "Diagnóstico"
        alert.informativeText = body
        alert.runModal()
    }

    func openLogs() async {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        proc.arguments = ["-a", "Console"]
        try? proc.run()
    }

    func openConfigFile() async {
        let path = NSString("~/.config/sonusgrid/config.toml")
            .expandingTildeInPath
        let url = URL(fileURLWithPath: path)
        if !FileManager.default.fileExists(atPath: path) {
            try? "".write(to: url, atomically: true, encoding: .utf8)
        }
        NSWorkspace.shared.open(url)
    }

    func applyConfiguration(
        deviceName: String,
        interface: NetworkInterface?,
        sampleRate: Int,
        latencyMs: Double,
        rxChannels: Int,
        txChannels: Int,
        ptpVersion: String
    ) async {
        // The CLI doesn't yet expose `config set` — for the skeleton we
        // simply restart with the existing on-disk config. In phase E we
        // wire `sonusgrid config set <key> <value>` (or write the TOML
        // directly here).
        guard let iface = interface else {
            lastError = "Selecione uma interface."
            return
        }
        _ = (deviceName, iface, sampleRate, latencyMs, rxChannels, txChannels, ptpVersion)
        await CLI.shared.restart()
        await refresh()
    }
}
