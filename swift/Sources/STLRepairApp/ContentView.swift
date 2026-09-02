import SwiftUI
import STLRepairKit
import UniformTypeIdentifiers

struct ContentView: View {
    @StateObject private var model = RepairModel()
    @State private var isTargeted = false

    var body: some View {
        VStack(spacing: 0) {
            DropZone(isTargeted: isTargeted, isWorking: model.isWorking) {
                model.add(pickFiles())
            }
            .dropDestination(for: URL.self) { urls, _ in
                model.add(urls)
                return true
            } isTargeted: { isTargeted = $0 }

            if !model.jobs.isEmpty {
                Divider()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(model.jobs) { JobRow(job: $0) }
                    }
                    .padding(16)
                }
                .frame(maxHeight: 340)
            }

            Divider()
            FooterBar(model: model)
        }
        .frame(minWidth: 560, minHeight: 380)
    }

    private func pickFiles() -> [URL] {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.allowedContentTypes = MeshFile.supportedExtensions
            .compactMap { UTType(filenameExtension: $0) }
        return panel.runModal() == .OK ? panel.urls : []
    }
}

private struct DropZone: View {
    let isTargeted: Bool
    let isWorking: Bool
    let onBrowse: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: isWorking ? "gearshape.2" : "square.and.arrow.down")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(isTargeted ? Color.accentColor : .secondary)
                .symbolEffect(.pulse, isActive: isWorking)

            Text(isWorking ? "Repairing…" : "Drop STL or OBJ files here")
                .font(.title3.weight(.medium))

            Text("Your files never leave this Mac. Originals are never modified.")
                .font(.callout)
                .foregroundStyle(.secondary)

            Button("Choose Files…", action: onBrowse)
                .buttonStyle(.link)
                .disabled(isWorking)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40)
        .background {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(style: StrokeStyle(lineWidth: 2, dash: [7, 5]))
                .foregroundStyle(isTargeted ? Color.accentColor : Color.secondary.opacity(0.35))
                .padding(16)
        }
    }
}

private struct JobRow: View {
    let job: RepairJob

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                icon
                Text(job.name).font(.headline)
                Spacer()
                if case .finished(let outcome) = job.state {
                    Text(String(format: "%.1fs", outcome.seconds))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            detail
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
    }

    private func formatted(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }

    @ViewBuilder private var icon: some View {
        switch job.state {
        case .waiting:
            Image(systemName: "clock").foregroundStyle(.secondary)
        case .running:
            ProgressView().controlSize(.small)
        case .finished(let outcome):
            Image(systemName: outcome.isHealthy ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(outcome.isHealthy ? .green : .orange)
        case .failed:
            Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
        }
    }

    @ViewBuilder private var detail: some View {
        switch job.state {
        case .waiting:
            Text("Waiting…").font(.callout).foregroundStyle(.secondary)

        case .running(let line):
            // MeshFix gives no progress fraction on long repairs, so show the
            // last thing it actually did rather than a bar that appears stuck.
            Text(line).font(.callout).foregroundStyle(.secondary)
                .lineLimit(1).truncationMode(.middle)

        case .finished(let outcome):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(outcome.fixes, id: \.self) { fix in
                    Label(fix, systemImage: "checkmark")
                        .font(.callout)
                        .labelStyle(.titleAndIcon)
                }
                if !outcome.isHealthy {
                    Label("Still not fully watertight - inspect before printing.",
                          systemImage: "exclamationmark.triangle")
                        .font(.callout).foregroundStyle(.orange)
                }
                if let warning = outcome.warning {
                    Label(warning, systemImage: "info.circle")
                        .font(.callout).foregroundStyle(.orange)
                }
                Text("Saved as \(outcome.output.lastPathComponent) · \(formatted(outcome.byteSize))")
                    .font(.caption).foregroundStyle(.secondary)
            }

        case .failed(let message):
            Text(message).font(.callout).foregroundStyle(.red)
        }
    }
}

private struct FooterBar: View {
    @ObservedObject var model: RepairModel

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Saving to").font(.caption).foregroundStyle(.secondary)
                Text(model.displayPath).font(.callout).lineLimit(1).truncationMode(.head)
            }
            Button("Change…") { model.chooseOutputDirectory() }
                .disabled(model.isWorking)

            Spacer()

            if !model.jobs.isEmpty {
                Button("Clear") { model.clear() }.disabled(model.isWorking)
            }
            Button("Show in Finder") { model.revealLastOutput() }
                .disabled(!model.hasResults)
                .keyboardShortcut("r")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}
