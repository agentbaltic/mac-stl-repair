import Foundation

/// A plain-language account of what a repair actually did.
///
/// The engine's diagnosis is a pile of numbers; this turns the before/after
/// pair into sentences someone can act on, plus the integrity warnings that
/// stop a silently-wrong repair from reading as a good one.
public struct RepairSummary: Sendable {
    /// What changed, in the order a person would want to read it.
    public let fixes: [String]
    /// Set when the repair may have altered the model in a way worth checking.
    public let warning: String?
    /// Whether the result is printable.
    public let isHealthy: Bool
    /// Whether it was already printable before we touched it.
    public let wasHealthy: Bool

    public init(before: Diagnosis, after: Diagnosis) {
        var fixes: [String] = []

        let closed = before.boundaryEdges - after.boundaryEdges
        if closed > 0 { fixes.append("Closed \(human(closed)) open edges (holes)") }

        let nonManifold = before.nonmanifoldEdges - after.nonmanifoldEdges
        if nonManifold > 0 { fixes.append("Fixed \(human(nonManifold)) non-manifold edges") }

        if before.components > after.components {
            let n = before.components - after.components
            fixes.append("Removed \(n) stray fragment\(n == 1 ? "" : "s")")
        }
        if !before.windingConsistent && after.windingConsistent {
            fixes.append("Rebuilt inconsistent surface normals")
        }
        if before.inverted && !after.inverted {
            fixes.append("Flipped inside-out normals")
        }
        if before.degenerateFaces > 0 {
            fixes.append("Removed \(human(before.degenerateFaces)) zero-area triangles")
        }
        if before.duplicateFaces > 0 {
            fixes.append("Removed \(human(before.duplicateFaces)) duplicate triangles")
        }

        self.fixes = fixes.isEmpty ? ["Nothing needed fixing"] : fixes
        self.isHealthy = after.isHealthy
        self.wasHealthy = before.isHealthy

        // Closing a hole invents geometry. These two warnings are the only
        // signal the user gets that the result may not match their intent, so
        // they matter more than anything else in this type.
        if before.watertight && after.watertight && before.volumeCm3 > 0 {
            let delta = (after.volumeCm3 - before.volumeCm3) / before.volumeCm3
            if abs(delta) > 0.01 {
                self.warning = String(
                    format: "Repair changed the solid volume by %+.1f%% - check the shape before printing.",
                    delta * 100)
            } else {
                self.warning = nil
            }
        } else if !before.watertight && after.faces > before.faces {
            let added = after.faces - before.faces
            self.warning = "\(human(added)) triangles were added to close holes. "
                + "Patched areas are reconstructed, not recovered - give them a look before printing."
        } else {
            self.warning = nil
        }
    }
}

/// Where repaired files go, and how they are named.
public enum OutputLocation {
    public static let defaultDirectory = FileManager.default
        .homeDirectoryForCurrentUser
        .appendingPathComponent("Downloads")
        .appendingPathComponent("STL Repaired")

    /// `name.stl` -> `name_repaired.stl`, then `_repaired_2`, `_repaired_3` ...
    /// Never overwrites: the original is the user's only copy of their work.
    public static func destination(for originalName: String, in directory: URL) -> URL {
        let stem = (originalName as NSString).deletingPathExtension
        var candidate = directory.appendingPathComponent("\(stem)_repaired.stl")
        var counter = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = directory.appendingPathComponent("\(stem)_repaired_\(counter).stl")
            counter += 1
        }
        return candidate
    }
}
