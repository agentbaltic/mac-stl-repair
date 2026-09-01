import Foundation

public struct RepairResult: Sendable {
    public let mesh: Mesh
    public let before: Diagnosis
    public let after: Diagnosis
    public let log: [String]
}

public enum Repair {

    /// Cheap, near-lossless topology cleanup. Mirrors the Python `basic_clean`.
    @discardableResult
    public static func basicClean(_ mesh: inout Mesh, options: RepairOptions, log: RepairLog) -> Bool {
        var changed = false

        let welded = Topology.weld(&mesh, tolerance: options.mergeTolerance)
        if welded > 0 { log("welded \(human(welded)) duplicate vertices"); changed = true }

        let degenerate = Topology.degenerateFaceMask(mesh)
        if degenerate.contains(true) {
            let n = Topology.filterFaces(&mesh, keep: degenerate.map { !$0 })
            log("removed \(human(n)) degenerate faces"); changed = true
        }

        let duplicate = Topology.duplicateFaceMask(mesh)
        if duplicate.contains(true) {
            let n = Topology.filterFaces(&mesh, keep: duplicate.map { !$0 })
            log("removed \(human(n)) duplicate faces"); changed = true
        }

        let unreferenced = Topology.removeUnreferencedVertices(&mesh)
        if unreferenced > 0 { log("removed \(human(unreferenced)) unreferenced vertices"); changed = true }

        return changed
    }

    /// Makes winding consistent, then flips the whole shell if it came out
    /// inside-out. Order matters: volume is only meaningful once winding agrees.
    public static func fixOrientation(_ mesh: inout Mesh, log: RepairLog) {
        guard !mesh.isEmpty else { return }
        var table = EdgeTable(mesh)
        if !Topology.isWindingConsistent(mesh, table: table) {
            let flipped = Topology.fixWinding(&mesh, table: table)
            if flipped > 0 { log("rebuilt face winding (\(human(flipped)) faces)") }
            table = EdgeTable(mesh)
        }
        let watertight = table.boundaryEdgeCount == 0 && table.nonManifoldEdgeCount == 0
        if watertight && mesh.signedVolume < 0 {
            Topology.flipAll(&mesh)
            log("flipped inside-out normals")
        }
    }

    /// The full pipeline: clean, diagnose, repair each shell, clean again.
    public static func run(_ input: Mesh,
                           backend: RepairBackend,
                           options: RepairOptions = RepairOptions(),
                           log: RepairLog = RepairLog()) throws -> RepairResult {
        var mesh = input

        log("cleaning topology")
        basicClean(&mesh, options: options, log: log)
        fixOrientation(&mesh, log: log)
        let before = Diagnosis.of(mesh)

        log("diagnosis")
        for problem in before.problems { log("- \(problem)") }

        if before.isHealthy && !options.force {
            log("mesh is already printable - nothing to repair")
            return RepairResult(mesh: mesh, before: before, after: before, log: log.lines)
        }

        log("repairing")
        var shells: [Mesh] = [mesh]
        if !options.mergeParts {
            let table = EdgeTable(mesh)
            let components = Topology.connectedComponents(mesh, table: table)
            if components.count > 1 {
                let kept = components.filter { $0.count >= options.minPartFaces }
                let dropped = components.count - kept.count
                if dropped > 0 {
                    log("discarded \(dropped) shell(s) below \(options.minPartFaces) faces (likely stray debris)")
                }
                if !kept.isEmpty {
                    shells = kept.map { Topology.submesh(mesh, faces: $0) }
                    if shells.count > 1 {
                        log("repairing \(shells.count) shells independently (use --parts merge to fuse them instead)")
                    }
                }
            }
        }

        var repaired: [Mesh] = []
        repaired.reserveCapacity(shells.count)
        for (i, shell) in shells.enumerated() {
            let label = shells.count > 1 ? "shell \(i + 1)/\(shells.count)" : "mesh"
            if Diagnosis.of(shell).isHealthy && !options.force {
                log("\(label): already sound, left untouched")
                repaired.append(shell)
                continue
            }
            do {
                let fixed = try backend.repairShell(shell, options: options, log: log)
                guard !fixed.isEmpty else { throw RepairError.emptyResult(backend.name) }
                repaired.append(fixed)
            } catch {
                // A backend failure must not lose the shell: keep the original
                // rather than dropping geometry the user handed us.
                log("\(backend.name) failed on \(label) (\(error)); keeping shell as-is")
                repaired.append(shell)
            }
        }

        mesh = repaired.count == 1 ? repaired[0] : concatenate(repaired)
        basicClean(&mesh, options: options, log: log)
        fixOrientation(&mesh, log: log)
        let after = Diagnosis.of(mesh)
        return RepairResult(mesh: mesh, before: before, after: after, log: log.lines)
    }

    /// Combines meshes without merging their vertices.
    public static func concatenate(_ meshes: [Mesh]) -> Mesh {
        var vertices: [Double] = []
        var faces: [Int32] = []
        vertices.reserveCapacity(meshes.reduce(0) { $0 + $1.vertices.count })
        faces.reserveCapacity(meshes.reduce(0) { $0 + $1.faces.count })
        var offset: Int32 = 0
        for m in meshes {
            vertices.append(contentsOf: m.vertices)
            faces.append(contentsOf: m.faces.map { $0 + offset })
            offset += Int32(m.vertexCount)
        }
        return Mesh(vertices: vertices, faces: faces)
    }
}
