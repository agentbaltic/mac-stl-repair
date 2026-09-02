import SwiftUI
import STLRepairKit
import UniformTypeIdentifiers

/// Every text size in the app, in one place.
///
/// SwiftUI's semantic fonts (.callout, .caption …) are deliberately not used:
/// they are fixed by the system, so there is nowhere to apply an app-wide
/// adjustment. These are explicit point sizes with `bump` added, which makes
/// "make all the text bigger" a one-line change instead of an audit.
private enum AppText {
    static let bump: CGFloat = 6

    static func at(_ base: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: base + bump, weight: weight)
    }

    static var title: Font { at(20, .semibold) }   // app name
    static var byline: Font { at(14) }             // attribution under it
    static var heading: Font { at(15, .medium) }   // drop-zone headline
    static var eyebrow: Font { at(10, .semibold) } // section labels
    static var body: Font { at(12) }               // prose and row detail
    static var rowName: Font { at(13, .semibold) } // filename
    static var small: Font { at(10) }              // timings, byte counts
    static var control: Font { at(13) }            // buttons
}

struct ContentView: View {
    @StateObject private var model = RepairModel()
    @State private var isTargeted = false

    var body: some View {
        VStack(spacing: 0) {
            BrandHeader()

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
                        ForEach(model.jobs) { job in
                            JobRow(job: job) { model.reveal($0) }
                        }
                    }
                    .padding(16)
                }
                .frame(maxHeight: 400)
            }

            Divider()
            AboutSection()
            Divider()
            FooterBar(model: model)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .frame(minWidth: 780, minHeight: 720)
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

// MARK: - Branding

/// Title, logo and channel link, matching the header of the old browser page.
private struct BrandHeader: View {
    var body: some View {
        HStack(spacing: 14) {
            BrandLogo()
                .frame(width: 55, height: 55)
            VStack(alignment: .leading, spacing: 3) {
                Text("Mac STL Repair")
                    .font(AppText.title)
                // Markdown links in Text open in the default browser.
                Text("By [**Agent Baltic**](https://youtube.com/@agentbaltic) · youtube.com/@agentbaltic")
                    .font(AppText.byline)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)

            VStack(alignment: .trailing, spacing: 3) {
                Text("Version \(Self.version)")
                    .font(AppText.small)
                    .foregroundStyle(.secondary)
                Link("Check for Updates", destination: Self.updatesURL)
                    .font(AppText.control)
                Link("Request a Feature", destination: Self.featureRequestURL)
                    .font(AppText.control)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 16)
        .padding(.bottom, 2)
    }

    /// Marketing version from the bundle. Falls back when the executable is
    /// run directly out of .build rather than from the assembled .app.
    private static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
    }

    /// The short link is the canonical download page, so "newer version?"
    /// and "share this" are deliberately the same destination.
    private static let updatesURL = URL(string: "https://rebrand.ly/stlrepair")!

    /// Opens the user's mail client with the recipient and subject filled in.
    /// Built through URLComponents so the subject is percent-encoded properly
    /// rather than hand-escaped:
    ///   mailto:support@talkoverapp.com?subject=STL%20Repair%20Feature%20Request
    private static let featureRequestURL: URL = {
        var components = URLComponents()
        components.scheme = "mailto"
        components.path = "support@talkoverapp.com"
        components.queryItems = [
            URLQueryItem(name: "subject", value: "STL Repair Feature Request")
        ]
        return components.url ?? URL(string: "mailto:support@talkoverapp.com")!
    }()
}

/// The Agent Baltic mark, copied into Contents/Resources by make_app.sh.
/// Falls back to a symbol when run as a bare executable outside a bundle.
private struct BrandLogo: View {
    var body: some View {
        if let url = Bundle.main.url(forResource: "agentbaltic-logo", withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            Image(nsImage: image)
                .resizable()
                .interpolation(.high)
                .clipShape(RoundedRectangle(cornerRadius: 10))
        } else {
            Image(systemName: "cube.transparent")
                .font(.system(size: 30, weight: .light))
                .foregroundStyle(.secondary)
        }
    }
}

/// Why the app exists, the share link, and the pointer to TalkOver — the
/// app is free specifically so it can send people to the other software.
private struct AboutSection: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow("Why this exists")
            Text("Mesh repair has always been the weak spot in a Mac 3D-printing setup. The desktop tools everyone recommends are Windows-only, which leaves Mac users on browser-based repair services — and those cap what you can upload, commonly around 50 MB. **Mac STL Repair runs natively on your own machine.** No upload, no queue, no size ceiling, and nothing ever leaves your Mac.")
                .font(AppText.body)
                .fixedSize(horizontal: false, vertical: true)

            Text("Share this tool → [rebrand.ly/stlrepair](https://rebrand.ly/stlrepair)")
                .font(AppText.body)
                .padding(.top, 2)

            Divider().padding(.vertical, 4)

            Eyebrow("From the same workshop")
            Text("Try our teleprompter app, [TalkOver](https://talkoverapp.com). It follows your voice, floats over your screen, records your presentations, and has no subscription.")
                .font(AppText.body)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }
}

private struct Eyebrow: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.uppercased())
            .font(AppText.eyebrow)
            .kerning(0.6)
            .foregroundStyle(.secondary)
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
                .font(AppText.heading)

            Text("Your files never leave this Mac. Originals are never modified.")
                .font(AppText.body)
                .foregroundStyle(.secondary)

            Button("Choose Files…", action: onBrowse)
                .buttonStyle(.link)
                .font(AppText.control)
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

/// One file's row. Files are repaired one at a time, so every row that has
/// not had its turn yet shows "Waiting"; only one row is ever running.
private struct JobRow: View {
    let job: RepairJob
    let onReveal: (URL) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                icon
                Text(job.name)
                    .font(AppText.rowName)
                    .lineLimit(1)
                    .truncationMode(.middle)

                Spacer(minLength: 8)

                if case .finished(let outcome) = job.state {
                    Text(String(format: "%.1fs", outcome.seconds))
                        .font(AppText.small.monospacedDigit())
                        .foregroundStyle(.secondary)

                    // Per row, so it reveals this file's result rather than
                    // whichever repair happened to finish last.
                    Button("Show in Finder") { onReveal(outcome.output) }
                        .font(AppText.control)
                        .controlSize(.small)
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
            Text("Waiting…").font(AppText.body).foregroundStyle(.secondary)

        case .running(let line):
            // MeshFix gives no progress fraction on long repairs, so show the
            // last thing it actually did rather than a bar that appears stuck.
            Text(line).font(AppText.body).foregroundStyle(.secondary)
                .lineLimit(1).truncationMode(.middle)

        case .finished(let outcome):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(outcome.fixes, id: \.self) { fix in
                    Label(fix, systemImage: "checkmark")
                        .font(AppText.body)
                        .labelStyle(.titleAndIcon)
                }
                if !outcome.isHealthy {
                    Label("Still not fully watertight - inspect before printing.",
                          systemImage: "exclamationmark.triangle")
                        .font(AppText.body).foregroundStyle(.orange)
                }
                if let warning = outcome.warning {
                    Label(warning, systemImage: "info.circle")
                        .font(AppText.body).foregroundStyle(.orange)
                }
                Text("Saved as \(outcome.output.lastPathComponent) · \(formatted(outcome.byteSize))")
                    .font(AppText.small).foregroundStyle(.secondary)
            }

        case .failed(let message):
            Text(message).font(AppText.body).foregroundStyle(.red)
        }
    }
}

private struct FooterBar: View {
    @ObservedObject var model: RepairModel

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Saving to").font(AppText.small).foregroundStyle(.secondary)
                Text(model.displayPath)
                    .font(AppText.body)
                    .lineLimit(1)
                    .truncationMode(.head)
            }
            Button("Change…") { model.chooseOutputDirectory() }
                .font(AppText.control)
                .disabled(model.isWorking)

            Spacer()

            // Revealing a result is per row now; this bar only owns the
            // destination folder and clearing the list.
            if !model.jobs.isEmpty {
                Button("Clear") { model.clear() }
                    .font(AppText.control)
                    .disabled(model.isWorking)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}
