import Foundation

/// The health report for a mesh. Field names and semantics mirror the Python
/// engine's `diagnose()` so the two can be diffed against each other.
public struct Diagnosis: Codable, Equatable, Sendable {
    public var vertices: Int
    public var faces: Int
    public var empty: Bool
    public var watertight: Bool
    public var windingConsistent: Bool
    public var boundaryEdges: Int
    public var nonmanifoldEdges: Int
    public var duplicateFaces: Int
    public var degenerateFaces: Int
    public var unreferencedVertices: Int
    public var components: Int
    public var eulerNumber: Int
    public var inverted: Bool
    public var isVolume: Bool
    public var volumeCm3: Double
    public var areaCm2: Double
    public var bboxMm: [Double]

    enum CodingKeys: String, CodingKey {
        case vertices, faces, empty, watertight
        case windingConsistent = "winding_consistent"
        case boundaryEdges = "boundary_edges"
        case nonmanifoldEdges = "nonmanifold_edges"
        case duplicateFaces = "duplicate_faces"
        case degenerateFaces = "degenerate_faces"
        case unreferencedVertices = "unreferenced_vertices"
        case components
        case eulerNumber = "euler_number"
        case inverted
        case isVolume = "is_volume"
        case volumeCm3 = "volume_cm3"
        case areaCm2 = "area_cm2"
        case bboxMm = "bbox_mm"
    }

    static let emptyMesh = Diagnosis(
        vertices: 0, faces: 0, empty: true, watertight: false, windingConsistent: false,
        boundaryEdges: 0, nonmanifoldEdges: 0, duplicateFaces: 0, degenerateFaces: 0,
        unreferencedVertices: 0, components: 0, eulerNumber: 0, inverted: false,
        isVolume: false, volumeCm3: 0, areaCm2: 0, bboxMm: [0, 0, 0])

    /// Printable means: closed, consistently wound, manifold, no junk faces.
    public var isHealthy: Bool {
        !empty && watertight && windingConsistent
            && nonmanifoldEdges == 0 && boundaryEdges == 0
            && degenerateFaces == 0 && duplicateFaces == 0 && !inverted
    }

    /// Human-readable problems, in the order the Python engine reports them.
    public var problems: [String] {
        if empty { return ["mesh contains no faces"] }
        var p: [String] = []
        if !watertight { p.append("not watertight (\(human(boundaryEdges)) open edges / holes)") }
        if nonmanifoldEdges > 0 { p.append("\(human(nonmanifoldEdges)) non-manifold edges") }
        if !windingConsistent { p.append("inconsistent face winding") }
        if inverted { p.append("inside-out normals (negative volume)") }
        if degenerateFaces > 0 { p.append("\(human(degenerateFaces)) degenerate (zero-area) faces") }
        if duplicateFaces > 0 { p.append("\(human(duplicateFaces)) duplicate faces") }
        if unreferencedVertices > 0 { p.append("\(human(unreferencedVertices)) unused vertices") }
        if components > 1 { p.append("\(components) separate shells") }
        return p.isEmpty ? ["none"] : p
    }

    public static func of(_ mesh: Mesh) -> Diagnosis {
        guard !mesh.isEmpty else { return .emptyMesh }
        let table = EdgeTable(mesh)

        let boundary = table.boundaryEdgeCount
        let nonManifold = table.nonManifoldEdgeCount
        let watertight = boundary == 0 && nonManifold == 0
        let winding = Topology.isWindingConsistent(mesh, table: table)
        // Only meaningful on a closed, consistently wound shell. On a mesh
        // with mixed winding the divergence sum is a real number but not a
        // real volume, so report nothing rather than something misleading.
        let volume = (watertight && winding) ? mesh.signedVolume : 0
        let referenced = mesh.vertexCount - Topology.unreferencedVertexCount(mesh)

        return Diagnosis(
            vertices: mesh.vertexCount,
            faces: mesh.faceCount,
            empty: false,
            watertight: watertight,
            windingConsistent: winding,
            boundaryEdges: boundary,
            nonmanifoldEdges: nonManifold,
            duplicateFaces: Topology.duplicateFaceMask(mesh).reduce(0) { $0 + ($1 ? 1 : 0) },
            degenerateFaces: Topology.degenerateFaceMask(mesh).reduce(0) { $0 + ($1 ? 1 : 0) },
            unreferencedVertices: Topology.unreferencedVertexCount(mesh),
            components: Topology.connectedComponents(mesh, table: table).count,
            eulerNumber: referenced - table.uniqueEdgeCount + mesh.faceCount,
            inverted: watertight && volume < 0,
            isVolume: watertight && winding && volume > 0,
            volumeCm3: (abs(volume) / 1000.0).rounded(toPlaces: 3),
            areaCm2: (mesh.area / 100.0).rounded(toPlaces: 2),
            bboxMm: mesh.extents.map { $0.rounded(toPlaces: 2) })
    }
}

/// Thousands separators, matching the Python engine's `human()`.
public func human(_ n: Int) -> String {
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.groupingSeparator = ","
    return f.string(from: NSNumber(value: n)) ?? "\(n)"
}

extension Double {
    func rounded(toPlaces places: Int) -> Double {
        let m = pow(10.0, Double(places))
        return (self * m).rounded() / m
    }
}
