import Foundation
import STLRepairKit
import AppKit

/// One file's journey through the queue.
struct RepairJob: Identifiable, Sendable {
    enum State: Sendable {
        case waiting
        case running(String)          // latest progress line
        case finished(Outcome)
        case failed(String)
    }

    struct Outcome: Sendable {
        let output: URL
        let byteSize: Int
        let seconds: Double
        let fixes: [String]
        let warning: String?
        let isHealthy: Bool
        let wasHealthy: Bool
    }

    let id = UUID()
    let source: URL
    var state: State = .waiting

    var name: String { source.lastPathComponent }
}

@MainActor
final class RepairModel: ObservableObject {
    @Published private(set) var jobs: [RepairJob] = []
    @Published private(set) var isWorking = false
    @Published var outputDirectory: URL {
        didSet { UserDefaults.standard.set(outputDirectory.path, forKey: Self.outputKey) }
    }

    private static let outputKey = "outputDirectory"

    init() {
        if let saved = UserDefaults.standard.string(forKey: Self.outputKey) {
            outputDirectory = URL(fileURLWithPath: saved)
        } else {
            outputDirectory = OutputLocation.defaultDirectory
        }
    }

    /// Path with the home directory collapsed, the way Finder shows it.
    var displayPath: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return outputDirectory.path.replacingOccurrences(of: home, with: "~")
    }

    func clear() {
        guard !isWorking else { return }
        jobs.removeAll()
    }

    func add(_ urls: [URL]) {
        let accepted = urls.filter(MeshFile.isSupported)
        guard !accepted.isEmpty else { return }
        jobs.append(contentsOf: accepted.map { RepairJob(source: $0) })
        Task { await processQueue() }
    }

    func chooseOutputDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Choose"
        panel.message = "Where should repaired files go?"
        panel.directoryURL = outputDirectory
        if panel.runModal() == .OK, let picked = panel.url {
            outputDirectory = picked
        }
    }

    /// Selects one repaired file in Finder. Each row passes its own output,
    /// so the button always lands on that row's result.
    func reveal(_ output: URL) {
        NSWorkspace.shared.activateFileViewerSelecting([output])
    }

    // MARK: - Work

    private func processQueue() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }

        while let index = jobs.firstIndex(where: { if case .waiting = $0.state { return true }; return false }) {
            let source = jobs[index].source
            let id = jobs[index].id
            jobs[index].state = .running("reading \(source.lastPathComponent) ...")

            let destinationDirectory = outputDirectory
            let result = await Self.repair(source: source, into: destinationDirectory) { [weak self] line in
                Task { @MainActor in
                    guard let self, let i = self.jobs.firstIndex(where: { $0.id == id }) else { return }
                    self.jobs[i].state = .running(line)
                }
            }

            if let i = jobs.firstIndex(where: { $0.id == id }) {
                jobs[i].state = result
            }
        }
    }

    /// Runs off the main actor: a 3M-triangle repair takes minutes and must
    /// never block the window.
    private nonisolated static func repair(
        source: URL,
        into directory: URL,
        progress: @escaping @Sendable (String) -> Void
    ) async -> RepairJob.State {
        await Task.detached(priority: .userInitiated) { () -> RepairJob.State in
            let started = Date()
            do {
                try FileManager.default.createDirectory(at: directory,
                                                        withIntermediateDirectories: true)
                let mesh = try MeshFile.read(contentsOf: source)
                let log = RepairLog(onLine: progress)
                let result = try Repair.run(mesh, backend: MeshFixBackend(), log: log)

                guard !result.mesh.isEmpty else {
                    return .failed("Repair produced an empty mesh; nothing was written.")
                }

                let destination = OutputLocation.destination(for: source.lastPathComponent,
                                                             in: directory)
                try STL.write(result.mesh, to: destination)

                let summary = RepairSummary(before: result.before, after: result.after)
                let size = (try? FileManager.default
                    .attributesOfItem(atPath: destination.path)[.size] as? Int) ?? 0

                return .finished(RepairJob.Outcome(
                    output: destination,
                    byteSize: size,
                    seconds: Date().timeIntervalSince(started),
                    fixes: summary.fixes,
                    warning: summary.warning,
                    isHealthy: summary.isHealthy,
                    wasHealthy: summary.wasHealthy))
            } catch {
                return .failed("\(error)")
            }
        }.value
    }
}
