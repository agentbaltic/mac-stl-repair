import Foundation

/// A shell-level repair engine.
///
/// This is the seam that keeps the licensing question open. Everything else in
/// the kit is permissively licensed original code; the heavy "guarantee a
/// watertight manifold" step lives behind this protocol so a backend can be
/// swapped — or shipped separately — without touching the rest of the app.
public protocol RepairBackend: Sendable {
    /// Short identifier shown in logs and the UI.
    var name: String { get }
    /// Whether the backend is usable in the current build.
    var isAvailable: Bool { get }
    /// The licence the backend obliges the shipped app to honour, if any.
    var licenseNote: String? { get }

    /// Repairs a single connected shell. Must return a mesh or throw; returning
    /// an empty mesh is treated as failure by the caller.
    func repairShell(_ mesh: Mesh, options: RepairOptions, log: RepairLog) throws -> Mesh
}

public struct RepairOptions: Sendable {
    /// Fuse separate shells into one solid instead of repairing each alone.
    public var mergeParts: Bool = false
    /// Shells smaller than this are treated as debris and dropped.
    public var minPartFaces: Int = 8
    /// Vertex merge tolerance.
    public var mergeTolerance: Double = 1e-8
    /// Repair even when the mesh already looks healthy.
    public var force: Bool = false

    public init(mergeParts: Bool = false, minPartFaces: Int = 8,
                mergeTolerance: Double = 1e-8, force: Bool = false) {
        self.mergeParts = mergeParts
        self.minPartFaces = minPartFaces
        self.mergeTolerance = mergeTolerance
        self.force = force
    }
}

/// Collects progress lines. `onLine` runs on the calling thread.
public final class RepairLog: @unchecked Sendable {
    public private(set) var lines: [String] = []
    private let onLine: (@Sendable (String) -> Void)?
    private let lock = NSLock()

    public init(onLine: (@Sendable (String) -> Void)? = nil) { self.onLine = onLine }

    public func callAsFunction(_ message: String) {
        lock.lock(); lines.append(message); lock.unlock()
        onLine?(message)
    }
}

public enum RepairError: Error, CustomStringConvertible {
    case backendUnavailable(String)
    case emptyResult(String)

    public var description: String {
        switch self {
        case .backendUnavailable(let n): return "repair backend '\(n)' is not available in this build"
        case .emptyResult(let n): return "repair backend '\(n)' returned an empty mesh"
        }
    }
}
