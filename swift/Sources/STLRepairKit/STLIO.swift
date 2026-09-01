import Foundation

public enum STLError: Error, CustomStringConvertible {
    case unreadable(String)
    case truncated(expected: Int, got: Int)
    case notATriangleMesh

    public var description: String {
        switch self {
        case .unreadable(let why): return why
        case .truncated(let expected, let got):
            return "file is truncated: expected \(expected) bytes of triangle data, found \(got)"
        case .notATriangleMesh: return "file does not contain a triangle mesh"
        }
    }
}

/// Binary and ASCII STL reading and writing.
///
/// STL is a triangle soup — every triangle carries its own three vertices with
/// no sharing — so a freshly read mesh always has `3 * faceCount` vertices and
/// no topology at all. `Topology.weld` is what turns it into a real mesh.
public enum STL {

    // MARK: - Reading

    public static func read(contentsOf url: URL) throws -> Mesh {
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        return try read(data)
    }

    public static func read(_ data: Data) throws -> Mesh {
        guard data.count >= 15 else { throw STLError.unreadable("file is too small to be an STL") }
        return isBinary(data) ? try readBinary(data) : try readASCII(data)
    }

    /// An STL is binary unless the header says `solid` *and* the declared
    /// triangle count doesn't match the file length. Some binary writers start
    /// their 80-byte header with "solid", so the length check is what decides.
    static func isBinary(_ data: Data) -> Bool {
        guard data.count >= 84 else { return false }
        let count = data.withUnsafeBytes { raw in
            UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: 80, as: UInt32.self))
        }
        if 84 + Int(count) * 50 == data.count { return true }

        let head = data.prefix(6).map { UInt8($0) }
        let startsWithSolid = head.count >= 5
            && (head[0] | 0x20) == UInt8(ascii: "s")
            && (head[1] | 0x20) == UInt8(ascii: "o")
            && (head[2] | 0x20) == UInt8(ascii: "l")
            && (head[3] | 0x20) == UInt8(ascii: "i")
            && (head[4] | 0x20) == UInt8(ascii: "d")
        return !startsWithSolid
    }

    static func readBinary(_ data: Data) throws -> Mesh {
        let declared = data.withUnsafeBytes { raw in
            Int(UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: 80, as: UInt32.self)))
        }
        let available = (data.count - 84) / 50
        // Trust the file's actual length over the header when they disagree;
        // truncated exports are common and the readable prefix is still useful.
        let count = min(declared, max(0, available))
        guard count > 0 else { throw STLError.notATriangleMesh }

        var vertices = [Double](repeating: 0, count: count * 9)
        var faces = [Int32](repeating: 0, count: count * 3)

        data.withUnsafeBytes { raw in
            for t in 0..<count {
                // 50-byte record: normal (12) + 3 vertices (36) + attribute (2).
                // The stored normal is ignored; winding is the authority.
                var off = 84 + t * 50 + 12
                let base = t * 9
                for k in 0..<9 {
                    vertices[base + k] = Double(Float(bitPattern: UInt32(littleEndian:
                        raw.loadUnaligned(fromByteOffset: off, as: UInt32.self))))
                    off += 4
                }
                faces[t * 3] = Int32(t * 3)
                faces[t * 3 + 1] = Int32(t * 3 + 1)
                faces[t * 3 + 2] = Int32(t * 3 + 2)
            }
        }
        return Mesh(vertices: vertices, faces: faces)
    }

    static func readASCII(_ data: Data) throws -> Mesh {
        guard let text = String(data: data, encoding: .utf8)
            ?? String(data: data, encoding: .isoLatin1) else {
            throw STLError.unreadable("file is not valid text and not a valid binary STL")
        }
        var vertices: [Double] = []
        var faces: [Int32] = []

        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard line.hasPrefix("vertex") || line.hasPrefix("VERTEX") else { continue }
            let parts = line.split(separator: " ", omittingEmptySubsequences: true)
            guard parts.count >= 4,
                  let x = Double(parts[1]), let y = Double(parts[2]), let z = Double(parts[3])
            else { continue }
            vertices.append(contentsOf: [x, y, z])
        }
        guard vertices.count >= 9 else { throw STLError.notATriangleMesh }
        // Drop any trailing partial triangle rather than failing the whole read.
        let triangles = vertices.count / 9
        vertices.removeLast(vertices.count - triangles * 9)
        faces.reserveCapacity(triangles * 3)
        for i in 0..<(triangles * 3) { faces.append(Int32(i)) }
        return Mesh(vertices: vertices, faces: faces)
    }

    // MARK: - Writing

    /// Writes binary STL. Normals are recomputed from winding, not preserved,
    /// because a repaired mesh's stored normals are meaningless.
    public static func write(_ mesh: Mesh, to url: URL) throws {
        var data = Data(capacity: 84 + mesh.faceCount * 50)
        data.append(Data(repeating: 0, count: 80))
        var count = UInt32(mesh.faceCount).littleEndian
        withUnsafeBytes(of: &count) { data.append(contentsOf: $0) }

        var record = [UInt8](repeating: 0, count: 50)
        for f in 0..<mesh.faceCount {
            let n = mesh.crossProduct(f)
            let len = (n.x * n.x + n.y * n.y + n.z * n.z).squareRoot()
            let unit = len > 0 ? (n.x / len, n.y / len, n.z / len) : (0.0, 0.0, 0.0)

            var floats = [Float](repeating: 0, count: 12)
            floats[0] = Float(unit.0); floats[1] = Float(unit.1); floats[2] = Float(unit.2)
            let (ia, ib, ic) = mesh.face(f)
            for (slot, idx) in [ia, ib, ic].enumerated() {
                let v = mesh.vertex(idx)
                floats[3 + slot * 3] = Float(v.x)
                floats[4 + slot * 3] = Float(v.y)
                floats[5 + slot * 3] = Float(v.z)
            }
            floats.withUnsafeBytes { src in
                record.withUnsafeMutableBytes { dst in
                    dst.copyBytes(from: UnsafeRawBufferPointer(rebasing: src[0..<48]))
                }
            }
            record[48] = 0; record[49] = 0
            data.append(contentsOf: record)
        }
        try data.write(to: url, options: .atomic)
    }
}
