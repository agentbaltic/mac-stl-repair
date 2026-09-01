import Foundation

/// A triangle mesh held as flat arrays.
///
/// Coordinates are `Double` to match the Python engine's float64 pipeline, and
/// both arrays are flat rather than arrays-of-structs: a 1.96M-triangle model
/// is the working case, and `SIMD3<Double>` would pad each vertex to 32 bytes.
public struct Mesh: Sendable {
    /// Vertex coordinates, 3 per vertex: x0, y0, z0, x1, ...
    public var vertices: [Double]
    /// Triangle corner indices, 3 per face.
    public var faces: [Int32]

    public init(vertices: [Double] = [], faces: [Int32] = []) {
        precondition(vertices.count % 3 == 0, "vertices must be a multiple of 3")
        precondition(faces.count % 3 == 0, "faces must be a multiple of 3")
        self.vertices = vertices
        self.faces = faces
    }

    public var vertexCount: Int { vertices.count / 3 }
    public var faceCount: Int { faces.count / 3 }
    public var isEmpty: Bool { faces.isEmpty }

    @inlinable
    public func vertex(_ i: Int32) -> (x: Double, y: Double, z: Double) {
        let b = Int(i) * 3
        return (vertices[b], vertices[b + 1], vertices[b + 2])
    }

    @inlinable
    public func face(_ f: Int) -> (a: Int32, b: Int32, c: Int32) {
        let b = f * 3
        return (faces[b], faces[b + 1], faces[b + 2])
    }

    /// Twice the area vector of a face (the raw cross product).
    @inlinable
    func crossProduct(_ f: Int) -> (x: Double, y: Double, z: Double) {
        let (ia, ib, ic) = face(f)
        let a = vertex(ia), b = vertex(ib), c = vertex(ic)
        let ux = b.x - a.x, uy = b.y - a.y, uz = b.z - a.z
        let vx = c.x - a.x, vy = c.y - a.y, vz = c.z - a.z
        return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    }

    public func faceArea(_ f: Int) -> Double {
        let n = crossProduct(f)
        return (n.x * n.x + n.y * n.y + n.z * n.z).squareRoot() * 0.5
    }

    /// Total surface area, in the mesh's own units squared.
    public var area: Double {
        var total = 0.0
        for f in 0..<faceCount { total += faceArea(f) }
        return total
    }

    /// Signed volume by the divergence theorem. Negative means inside-out.
    public var signedVolume: Double {
        var total = 0.0
        for f in 0..<faceCount {
            let (ia, ib, ic) = face(f)
            let a = vertex(ia), b = vertex(ib), c = vertex(ic)
            let cx = b.y * c.z - b.z * c.y
            let cy = b.z * c.x - b.x * c.z
            let cz = b.x * c.y - b.y * c.x
            total += a.x * cx + a.y * cy + a.z * cz
        }
        return total / 6.0
    }

    /// Bounding-box side lengths. Zero-length array stays `[0, 0, 0]`.
    public var extents: [Double] {
        guard vertexCount > 0 else { return [0, 0, 0] }
        var lo = [Double.greatestFiniteMagnitude, .greatestFiniteMagnitude, .greatestFiniteMagnitude]
        var hi = [-Double.greatestFiniteMagnitude, -.greatestFiniteMagnitude, -.greatestFiniteMagnitude]
        for i in stride(from: 0, to: vertices.count, by: 3) {
            for k in 0..<3 {
                let v = vertices[i + k]
                if v < lo[k] { lo[k] = v }
                if v > hi[k] { hi[k] = v }
            }
        }
        return (0..<3).map { hi[$0] - lo[$0] }
    }
}
