import Foundation

/// Edge-level structure derived from a mesh's faces.
///
/// Everything expensive is computed once here and shared, because diagnosis,
/// winding repair and component splitting all need the same edge groups.
public struct EdgeTable {
    /// One entry per undirected edge, in first-seen order.
    public private(set) var edges: [(a: Int32, b: Int32)] = []
    /// Faces incident on each edge, parallel to `edges`.
    public private(set) var incidentFaces: [[Int32]] = []
    /// Index into `edges` for each of the mesh's 3 * faceCount directed edges.
    public private(set) var edgeOfCorner: [Int32] = []

    public init(_ mesh: Mesh) {
        let fc = mesh.faceCount
        edges.reserveCapacity(fc * 3 / 2)
        incidentFaces.reserveCapacity(fc * 3 / 2)
        edgeOfCorner = [Int32](repeating: -1, count: fc * 3)

        var lookup = [UInt64: Int32](minimumCapacity: fc * 2)
        for f in 0..<fc {
            let (a, b, c) = mesh.face(f)
            let corners = [(a, b), (b, c), (c, a)]
            for (k, pair) in corners.enumerated() {
                let lo = min(pair.0, pair.1), hi = max(pair.0, pair.1)
                let key = UInt64(UInt32(bitPattern: lo)) << 32 | UInt64(UInt32(bitPattern: hi))
                let idx: Int32
                if let existing = lookup[key] {
                    idx = existing
                    incidentFaces[Int(existing)].append(Int32(f))
                } else {
                    idx = Int32(edges.count)
                    lookup[key] = idx
                    edges.append((lo, hi))
                    incidentFaces.append([Int32(f)])
                }
                edgeOfCorner[f * 3 + k] = idx
            }
        }
    }

    /// Edges touching exactly one face — the boundary of a hole.
    public var boundaryEdgeCount: Int {
        incidentFaces.reduce(0) { $0 + ($1.count == 1 ? 1 : 0) }
    }

    /// Edges touching three or more faces — non-manifold junctions.
    public var nonManifoldEdgeCount: Int {
        incidentFaces.reduce(0) { $0 + ($1.count > 2 ? 1 : 0) }
    }

    public var uniqueEdgeCount: Int { edges.count }
}

public enum Topology {

    // MARK: - Welding

    /// Merges vertices that land on the same point, rebuilding face indices.
    ///
    /// STL stores a triangle soup, so this is what creates topology in the
    /// first place. Coordinates are quantised before hashing; the default
    /// matches the Python engine's 1e-8 merge tolerance.
    public static func weld(_ mesh: inout Mesh, tolerance: Double = 1e-8) -> Int {
        guard mesh.vertexCount > 0 else { return 0 }
        let scale = tolerance > 0 ? 1.0 / tolerance : 1.0

        struct Key: Hashable { let x: Int64; let y: Int64; let z: Int64 }
        @inline(__always) func quantise(_ v: Double) -> Int64 {
            let scaled = (v * scale).rounded()
            // Clamp rather than trap on absurd coordinates (inf/NaN models exist).
            guard scaled.isFinite else { return scaled.isNaN ? Int64.min : (scaled < 0 ? Int64.min + 1 : Int64.max) }
            return Int64(scaled.clamped(to: -9.0e18...9.0e18))
        }

        var remap = [Int32](repeating: -1, count: mesh.vertexCount)
        var newVertices: [Double] = []
        newVertices.reserveCapacity(mesh.vertices.count / 2)
        var seen = [Key: Int32](minimumCapacity: mesh.vertexCount)

        for v in 0..<mesh.vertexCount {
            let b = v * 3
            let key = Key(x: quantise(mesh.vertices[b]),
                          y: quantise(mesh.vertices[b + 1]),
                          z: quantise(mesh.vertices[b + 2]))
            if let existing = seen[key] {
                remap[v] = existing
            } else {
                let idx = Int32(newVertices.count / 3)
                seen[key] = idx
                remap[v] = idx
                newVertices.append(mesh.vertices[b])
                newVertices.append(mesh.vertices[b + 1])
                newVertices.append(mesh.vertices[b + 2])
            }
        }

        let removed = mesh.vertexCount - newVertices.count / 3
        guard removed > 0 else { return 0 }
        for i in 0..<mesh.faces.count { mesh.faces[i] = remap[Int(mesh.faces[i])] }
        mesh.vertices = newVertices
        return removed
    }

    // MARK: - Face cleanup

    /// Faces with a repeated corner or effectively zero area.
    public static func degenerateFaceMask(_ mesh: Mesh) -> [Bool] {
        (0..<mesh.faceCount).map { f in
            let (a, b, c) = mesh.face(f)
            if a == b || b == c || a == c { return true }
            return mesh.faceArea(f) <= 0
        }
    }

    /// Second and subsequent copies of a face, compared on its sorted corners
    /// so that winding differences still count as duplicates.
    public static func duplicateFaceMask(_ mesh: Mesh) -> [Bool] {
        var seen = Set<SIMD3<Int32>>(minimumCapacity: mesh.faceCount)
        var mask = [Bool](repeating: false, count: mesh.faceCount)
        for f in 0..<mesh.faceCount {
            let (a, b, c) = mesh.face(f)
            var s = [a, b, c]; s.sort()
            let key = SIMD3(s[0], s[1], s[2])
            if !seen.insert(key).inserted { mask[f] = true }
        }
        return mask
    }

    /// Keeps only the faces where `keep` is true.
    public static func filterFaces(_ mesh: inout Mesh, keep: [Bool]) -> Int {
        var out: [Int32] = []
        out.reserveCapacity(mesh.faces.count)
        var dropped = 0
        for f in 0..<mesh.faceCount {
            if keep[f] {
                out.append(contentsOf: [mesh.faces[f * 3], mesh.faces[f * 3 + 1], mesh.faces[f * 3 + 2]])
            } else {
                dropped += 1
            }
        }
        mesh.faces = out
        return dropped
    }

    public static func unreferencedVertexCount(_ mesh: Mesh) -> Int {
        guard mesh.vertexCount > 0 else { return 0 }
        var used = [Bool](repeating: false, count: mesh.vertexCount)
        for i in mesh.faces { used[Int(i)] = true }
        return used.reduce(0) { $0 + ($1 ? 0 : 1) }
    }

    /// Drops vertices no face refers to, compacting the array.
    @discardableResult
    public static func removeUnreferencedVertices(_ mesh: inout Mesh) -> Int {
        guard mesh.vertexCount > 0 else { return 0 }
        var used = [Bool](repeating: false, count: mesh.vertexCount)
        for i in mesh.faces { used[Int(i)] = true }

        var remap = [Int32](repeating: -1, count: mesh.vertexCount)
        var out: [Double] = []
        out.reserveCapacity(mesh.vertices.count)
        for v in 0..<mesh.vertexCount where used[v] {
            remap[v] = Int32(out.count / 3)
            out.append(contentsOf: mesh.vertices[(v * 3)..<(v * 3 + 3)])
        }
        let removed = mesh.vertexCount - out.count / 3
        guard removed > 0 else { return 0 }
        for i in 0..<mesh.faces.count { mesh.faces[i] = remap[Int(mesh.faces[i])] }
        mesh.vertices = out
        return removed
    }

    // MARK: - Orientation

    /// True when every shared edge is traversed in opposite directions by its
    /// two faces, which is what a consistently wound surface looks like.
    public static func isWindingConsistent(_ mesh: Mesh, table: EdgeTable) -> Bool {
        var direction = [Int8](repeating: 0, count: table.edges.count)
        for f in 0..<mesh.faceCount {
            let (a, b, c) = mesh.face(f)
            let corners = [(a, b), (b, c), (c, a)]
            for (k, pair) in corners.enumerated() {
                let e = Int(table.edgeOfCorner[f * 3 + k])
                guard table.incidentFaces[e].count == 2 else { continue }
                let forward: Int8 = pair.0 < pair.1 ? 1 : -1
                if direction[e] == 0 {
                    direction[e] = forward
                } else if direction[e] == forward {
                    return false  // both faces traverse the edge the same way
                }
            }
        }
        return true
    }

    /// Reorients faces by flood fill so neighbours agree, one shell at a time.
    /// Returns the number of faces flipped.
    @discardableResult
    public static func fixWinding(_ mesh: inout Mesh, table: EdgeTable) -> Int {
        let fc = mesh.faceCount
        guard fc > 0 else { return 0 }

        // Neighbours are addressed by vertex id, never by corner slot: flipping
        // a face reorders its corners, so any slot-based index goes stale in the
        // middle of the walk and the fill silently stops correcting.
        var neighbours = [[(face: Int32, a: Int32, b: Int32)]](repeating: [], count: fc)
        for (i, incident) in table.incidentFaces.enumerated() where incident.count == 2 {
            let e = table.edges[i]
            neighbours[Int(incident[0])].append((incident[1], e.a, e.b))
            neighbours[Int(incident[1])].append((incident[0], e.a, e.b))
        }

        var visited = [Bool](repeating: false, count: fc)
        var flipped = 0

        for seed in 0..<fc where !visited[seed] {
            visited[seed] = true
            var stack = [Int32(seed)]
            while let f = stack.popLast() {
                let fi = Int(f)
                for n in neighbours[fi] {
                    let oi = Int(n.face)
                    if visited[oi] { continue }
                    visited[oi] = true
                    // Two faces sharing an edge agree only when they traverse it
                    // in opposite directions.
                    if let mine = traversal(mesh, fi, n.a, n.b),
                       let theirs = traversal(mesh, oi, n.a, n.b),
                       mine == theirs {
                        mesh.faces.swapAt(oi * 3 + 1, oi * 3 + 2)
                        flipped += 1
                    }
                    stack.append(n.face)
                }
            }
        }
        return flipped
    }

    /// Whether face `f` walks the undirected edge {p, q} in the p -> q sense.
    /// Nil when the face does not use that edge at all.
    private static func traversal(_ mesh: Mesh, _ f: Int, _ p: Int32, _ q: Int32) -> Bool? {
        let (a, b, c) = mesh.face(f)
        if (a == p && b == q) || (b == p && c == q) || (c == p && a == q) { return true }
        if (b == p && a == q) || (c == p && b == q) || (a == p && c == q) { return false }
        return nil
    }

    /// Reverses every face. Used when a closed shell encloses negative volume.
    public static func flipAll(_ mesh: inout Mesh) {
        for f in 0..<mesh.faceCount { mesh.faces.swapAt(f * 3 + 1, f * 3 + 2) }
    }

    // MARK: - Components

    /// Groups faces into connected shells via union-find over shared edges.
    public static func connectedComponents(_ mesh: Mesh, table: EdgeTable) -> [[Int32]] {
        let fc = mesh.faceCount
        guard fc > 0 else { return [] }
        var parent = (0..<fc).map { Int32($0) }

        func find(_ x: Int32) -> Int32 {
            var root = x
            while parent[Int(root)] != root { root = parent[Int(root)] }
            var cur = x
            while parent[Int(cur)] != root {  // path compression
                let next = parent[Int(cur)]
                parent[Int(cur)] = root
                cur = next
            }
            return root
        }
        func union(_ a: Int32, _ b: Int32) {
            let ra = find(a), rb = find(b)
            if ra != rb { parent[Int(ra)] = rb }
        }

        // Only manifold edges join faces. A fin welded onto a surface along a
        // single non-manifold edge is its own shell, which is what lets the
        // repair stage drop it as debris instead of treating it as geometry.
        for incident in table.incidentFaces where incident.count == 2 {
            union(incident[0], incident[1])
        }

        var groups = [Int32: [Int32]]()
        for f in 0..<fc { groups[find(Int32(f)), default: []].append(Int32(f)) }
        return groups.values.sorted { $0.count > $1.count }
    }

    /// Builds a standalone mesh from a subset of faces, without touching geometry.
    public static func submesh(_ mesh: Mesh, faces subset: [Int32]) -> Mesh {
        var remap = [Int32: Int32](minimumCapacity: subset.count * 2)
        var vertices: [Double] = []
        var faces: [Int32] = []
        faces.reserveCapacity(subset.count * 3)

        for f in subset {
            for k in 0..<3 {
                let old = mesh.faces[Int(f) * 3 + k]
                if let mapped = remap[old] {
                    faces.append(mapped)
                } else {
                    let idx = Int32(vertices.count / 3)
                    remap[old] = idx
                    let v = mesh.vertex(old)
                    vertices.append(contentsOf: [v.x, v.y, v.z])
                    faces.append(idx)
                }
            }
        }
        return Mesh(vertices: vertices, faces: faces)
    }
}

extension Double {
    func clamped(to range: ClosedRange<Double>) -> Double {
        Swift.min(Swift.max(self, range.lowerBound), range.upperBound)
    }
}
