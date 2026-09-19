// SPDX-License-Identifier: GPL-3.0-or-later
//
// ConfigView — the primary "Configuração" boxed-list section.
//
// Lists device name, network interface (mandatory, with IPv4),
// sample rate, latency, channel counts, and PTP version. Apply persists to
// ~/.config/sonusgrid/config.toml and tells the daemon to restart.
//

import SwiftUI

struct ConfigView: View {
    @EnvironmentObject var viewModel: StatusViewModel
    @State private var deviceName: String = "SonusGrid-Virtual"
    @State private var selectedInterface: NetworkInterface?
    @State private var sampleRateIdx: Int = 1
    @State private var latencyMs: Double = 4.0
    @State private var rxChannels: Int = 16
    @State private var txChannels: Int = 16
    @State private var ptpVersionIdx: Int = 0

    private let sampleRates = [44100, 48000, 88200, 96000, 176400, 192000]
    private let ptpVersions = ["v1", "v2"]

    var body: some View {
        VStack(spacing: 12) {
            GroupBox {
                LabeledContent("Nome do dispositivo") {
                    TextField("", text: $deviceName)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 220)
                }

                Divider().padding(.vertical, 4)

                LabeledContent("Interface de rede") {
                    Picker("", selection: $selectedInterface) {
                        ForEach(viewModel.interfaces, id: \.self) { iface in
                            Text("\(iface.name)  ·  \(iface.ipv4 ?? "sem IP")")
                                .tag(Optional(iface))
                        }
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .frame(width: 220)
                }

                Divider().padding(.vertical, 4)

                LabeledContent("Sample rate") {
                    Picker("", selection: $sampleRateIdx) {
                        ForEach(0..<sampleRates.count, id: \.self) { i in
                            Text("\(sampleRates[i]) Hz").tag(i)
                        }
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .frame(width: 220)
                }

                Divider().padding(.vertical, 4)

                LabeledContent("Latência (ms)") {
                    Stepper(value: $latencyMs, in: 0.5...100, step: 0.5) {
                        Text(String(format: "%.1f", latencyMs))
                    }
                    .frame(width: 220)
                }

                Divider().padding(.vertical, 4)

                LabeledContent("Canais RX") {
                    Stepper(value: $rxChannels, in: 0...64) {
                        Text("\(rxChannels)")
                    }.frame(width: 220)
                }

                Divider().padding(.vertical, 4)

                LabeledContent("Canais TX") {
                    Stepper(value: $txChannels, in: 0...64) {
                        Text("\(txChannels)")
                    }.frame(width: 220)
                }

                Divider().padding(.vertical, 4)

                LabeledContent("Versão PTP") {
                    Picker("", selection: $ptpVersionIdx) {
                        ForEach(0..<ptpVersions.count, id: \.self) { i in
                            Text(ptpVersions[i]).tag(i)
                        }
                    }
                    .pickerStyle(.menu)
                    .labelsHidden()
                    .frame(width: 220)
                }
            }

            HStack {
                Spacer()
                Button("Aplicar") {
                    Task {
                        await viewModel.applyConfiguration(
                            deviceName: deviceName,
                            interface: selectedInterface,
                            sampleRate: sampleRates[sampleRateIdx],
                            latencyMs: latencyMs,
                            rxChannels: rxChannels,
                            txChannels: txChannels,
                            ptpVersion: ptpVersions[ptpVersionIdx])
                    }
                }
                .keyboardShortcut(.return, modifiers: .command)
                .controlSize(.large)
                .buttonStyle(.borderedProminent)
                .disabled(selectedInterface == nil)
            }
        }
        .onAppear {
            selectedInterface = viewModel.interfaces.first
        }
    }
}

struct ToolsView: View {
    @EnvironmentObject var viewModel: StatusViewModel
    var body: some View {
        GroupBox {
            ToolRow(icon: "speaker.wave.3", title: "Mixer (Sound preferences)",
                    subtitle: "Roteia áudio dos apps para o sink SonusGrid.") {
                NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.sound")!)
            }
            Divider()
            ToolRow(icon: "stethoscope", title: "Diagnóstico",
                    subtitle: "Checagens bilíngues PT/EN com remediação.") {
                Task { await viewModel.openDoctor() }
            }
            Divider()
            ToolRow(icon: "list.bullet.rectangle", title: "Ver logs",
                    subtitle: "log show das duas user services.") {
                Task { await viewModel.openLogs() }
            }
            Divider()
            ToolRow(icon: "doc.text", title: "Avançado: editar config.toml",
                    subtitle: "Arquivo cru em ~/.config/sonusgrid/config.toml") {
                Task { await viewModel.openConfigFile() }
            }
        }
    }
}

struct ToolRow: View {
    let icon: String
    let title: String
    let subtitle: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(.tint)
                    .frame(width: 24)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.body.weight(.medium))
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
            .padding(.vertical, 6)
        }
        .buttonStyle(.plain)
    }
}

struct PreferencesView: View {
    @EnvironmentObject var viewModel: StatusViewModel
    var body: some View {
        Form {
            Section("Identidade") {
                Text("Configurações detalhadas seguem aqui na fase E.")
                    .foregroundStyle(.secondary)
            }
        }
        .padding(20)
    }
}

#Preview {
    ConfigView().environmentObject(StatusViewModel()).padding()
}
