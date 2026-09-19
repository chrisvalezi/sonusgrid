// SPDX-License-Identifier: GPL-3.0-or-later
//
// HeroCardView — visual parity with the Linux GTK hero card.
//
// Round glyph with purple → red gradient, status label, big rounded toggle
// pill. The glyph and the toggle change colour with the running state.
//

import SwiftUI

struct HeroCardView: View {
    @EnvironmentObject var viewModel: StatusViewModel

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            glyph
                .frame(width: 72, height: 72)

            VStack(alignment: .leading, spacing: 4) {
                Text(viewModel.title)
                    .font(.title2.weight(.bold))
                Text(viewModel.subtitle)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button(action: { Task { await viewModel.toggle() } }) {
                Text(viewModel.toggleLabel)
                    .font(.body.weight(.semibold))
                    .padding(.horizontal, 22)
                    .padding(.vertical, 10)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(viewModel.toggleTint)
            .clipShape(Capsule())
            .disabled(viewModel.toggleBusy)
        }
        .padding(20)
        .background(
            LinearGradient(
                colors: [
                    Color.accentColor.opacity(0.18),
                    Color.accentColor.opacity(0.04)
                ],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.accentColor.opacity(0.22), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private var glyph: some View {
        ZStack {
            Circle()
                .fill(viewModel.glyphGradient)
                .shadow(
                    color: viewModel.glyphShadow,
                    radius: 12, x: 0, y: 4
                )
            Image(systemName: viewModel.glyphSymbol)
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(.white)
        }
    }
}

extension StatusViewModel {
    var glyphGradient: LinearGradient {
        switch state {
        case .on:
            return LinearGradient(
                colors: [Color(red: 0.48, green: 0.12, blue: 0.64),
                         Color(red: 0.72, green: 0.11, blue: 0.30),
                         Color(red: 0.90, green: 0.22, blue: 0.21)],
                startPoint: .topLeading, endPoint: .bottomTrailing)
        case .starting:
            return LinearGradient(
                colors: [.orange, Color(red: 0.94, green: 0.42, blue: 0.0)],
                startPoint: .topLeading, endPoint: .bottomTrailing)
        case .off:
            return LinearGradient(
                colors: [Color(red: 0.36, green: 0.39, blue: 0.42),
                         Color(red: 0.23, green: 0.24, blue: 0.27)],
                startPoint: .topLeading, endPoint: .bottomTrailing)
        }
    }
    var glyphShadow: Color {
        switch state {
        case .on:       return Color(red: 0.48, green: 0.12, blue: 0.64).opacity(0.35)
        case .starting: return Color(red: 0.94, green: 0.42, blue: 0.0).opacity(0.35)
        case .off:      return .clear
        }
    }
    var glyphSymbol: String {
        switch state {
        case .on:       return "antenna.radiowaves.left.and.right"
        case .starting: return "arrow.triangle.2.circlepath"
        case .off:      return "stop.fill"
        }
    }
    var toggleLabel: String {
        switch state {
        case .on:       return "Parar"
        case .starting: return "Aguarde…"
        case .off:      return "Iniciar"
        }
    }
    var toggleTint: Color {
        switch state {
        case .on:       return .red
        case .starting: return .orange
        case .off:      return .accentColor
        }
    }
    var toggleBusy: Bool { state == .starting }
}

#Preview {
    HeroCardView()
        .environmentObject(StatusViewModel())
        .padding()
        .frame(width: 560)
}
