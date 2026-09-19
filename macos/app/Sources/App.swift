// SPDX-License-Identifier: GPL-3.0-or-later
//
// SonusGrid.app — SwiftUI front-end on macOS.
//
// Mirrors the Linux GTK GUI: hero status card, configuration list, tools
// list. Talks to the same `sonusgrid` CLI via subprocess, so the macOS
// surface and the Linux surface can evolve in lockstep.
//

import SwiftUI

@main
struct SonusGridApp: App {
    @StateObject private var viewModel = StatusViewModel()

    var body: some Scene {
        Window("SonusGrid", id: "main") {
            HomeView()
                .environmentObject(viewModel)
                .frame(minWidth: 640, minHeight: 760)
                .task { await viewModel.startPolling() }
        }
        .windowResizability(.contentSize)

        Settings {
            PreferencesView()
                .environmentObject(viewModel)
                .frame(width: 580)
        }
    }
}

struct HomeView: View {
    @EnvironmentObject var viewModel: StatusViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HeroCardView()
                SectionHeading("Configuração")
                ConfigView()
                SectionHeading("Ferramentas")
                ToolsView()
            }
            .padding(24)
            .frame(maxWidth: 600)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .background(Color(NSColor.windowBackgroundColor))
    }
}

struct SectionHeading: View {
    let title: String
    init(_ title: String) { self.title = title }
    var body: some View {
        Text(title)
            .font(.headline)
            .foregroundStyle(.secondary)
            .padding(.top, 4)
    }
}

#Preview {
    HomeView().environmentObject(StatusViewModel())
}
