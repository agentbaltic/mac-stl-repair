import Foundation

/// Pure-Swift repair: topology cleanup plus fan-filling of boundary loops.
///
/// This covers everything the Python engine does *outside* MeshFix. It is
/// exact on simple holes and, like trimesh's filler, will chord awkwardly
/// across convex-hull-unfriendly ones — which is precisely why a stronger
/// backend exists behind `RepairBackend`. It carries no licence obligations.
public struct NativeBackend: RepairBackend {
    public let name = "native"
    public let isAvailable = true
    public let licenseNote: String? = nil

    public init() {}

    public func repairShell(_ mesh: Mesh, options: RepairOptions, log: RepairLog) throws -> Mesh {
        var m = mesh
        var table = EdgeTable(m)

        let loops = Self.boundaryLoops(m, table: table)
        guard !loops.isEmpty else { return m }

        let before = table.boundaryEdgeCount
        var filled = 0
        for loop in loops where loop.count >= 3 {
            Self.fanFill(&m, loop: loop)
            filled += 1
        }
        table = EdgeTable(m)
        let after = table.boundaryEdgeCount
        if after < before {
            log("filled \(filled) hole\(filled == 1 ? "" : "s") (\(human(before)) -> \(human(after)) open edges)")
        }
        return m
    }

    // MARK: - Boundary loops

    /// Traces closed loops of boundary edges.
    ///
    /// Walks vertex-to-vertex along edges that touch exactly one face. A vertex
    /// where several boundaries meet is ambiguous, so the walk just takes the
    /// first unused edge and stops if it dead-ends — a partial trace is
    /// discarded rather than guessed at.
    static func boundaryLoops(_ mesh: Mesh, table: EdgeTable) -> [[Int32]] {
        var adjacency = [Int32: [Int32]]()
        var boundaryEdges: [(Int32, Int32)] = []
        for (i, incident) in table.incidentFaces.enumerated() where incident.count == 1 {
            let e = table.edges[i]
            boundaryEdges.append((e.a, e.b))
            adjacency[e.a, default: []].append(e.b)
            adjacency[e.b, default: []].append(e.a)
        }
        guard !boundaryEdges.isEmpty else { return [] }

        var used = Set<UInt64>(minimumCapacity: boundaryEdges.count * 2)
        @inline(__always) func key(_ a: Int32, _ b: Int32) -> UInt64 {
            let lo = min(a, b), hi = max(a, b)
            return UInt64(UInt32(bitPattern: lo)) << 32 | UInt64(UInt32(bitPattern: hi))
        }

        var loops: [[Int32]] = []
        for (sa, sb) in boundaryEdges {
            if used.contains(key(sa, sb)) { continue }
            var loop: [Int32] = [sa]
            var previous = sa
            var current = sb
            used.insert(key(sa, sb))

            while current != sa {
                loop.append(current)
                guard let neighbours = adjacency[current] else { break }
                var advanced = false
                for next in neighbours where next != previous && !used.contains(key(current, next)) {
                    used.insert(key(current, next))
                    previous = current
                    current = next
                    advanced = true
                    break
                }
                if !advanced { break }
                if loop.count > boundaryEdges.count + 1 { break }  // safety net
            }
            if current == sa && loop.count >= 3 { loops.append(loop) }
        }
        return loops
    }

    /// Fills a loop with a triangle fan anchored at its centroid.
    ///
    /// A centroid fan beats an ear clip here: hole rims in scanned meshes are
    /// rarely planar, and the extra vertex keeps the added triangles from
    /// collapsing to zero area on a non-planar rim.
    static func fanFill(_ mesh: inout Mesh, loop: [Int32]) {
        var cx = 0.0, cy = 0.0, cz = 0.0
        for v in loop {
            let p = mesh.vertex(v)
            cx += p.x; cy += p.y; cz += p.z
        }
        let n = Double(loop.count)
        let centre = Int32(mesh.vertexCount)
        mesh.vertices.append(contentsOf: [cx / n, cy / n, cz / n])

        for i in 0..<loop.count {
            let a = loop[i]
            let b = loop[(i + 1) % loop.count]
            mesh.faces.append(contentsOf: [centre, b, a])
        }
    }
}
