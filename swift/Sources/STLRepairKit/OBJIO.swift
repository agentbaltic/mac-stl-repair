import Foundation

/// Wavefront OBJ reading.
///
/// Only geometry is taken: `v` and `f` lines. Normals, texture coordinates,
/// groups, materials and everything else are ignored, because the output is
/// always a bare STL and none of it survives repair anyway.
///
/// Faces may be polygons (fan-triangulated, as trimesh does), may use
/// negative (relative) indices, and may carry `/vt` and `//vn` suffixes.
public enum OBJ {

    public static func read(contentsOf url: URL) throws -> Mesh {
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        return try read(data)
    }

    public static func read(_ data: Data) throws -> Mesh {
        // One copy, then every newline becomes a NUL so each line is a C
        // string. That lets strtod/strtol do the number parsing — far faster
        // than Substring/Double(String) on a 40 MB file — without any risk of
        // them reading past the end of a short or malformed line.
        var bytes = [CChar](repeating: 0, count: data.count + 1)
        data.withUnsafeBytes { raw in
            guard let src = raw.baseAddress else { return }
            memcpy(&bytes, src, data.count)
        }
        for i in 0..<data.count where bytes[i] == 0x0A { bytes[i] = 0 }

        var vertices: [Double] = []
        var faces: [Int32] = []
        var polygon: [Int32] = []
        vertices.reserveCapacity(min(data.count / 8, 1 << 26))
        faces.reserveCapacity(min(data.count / 8, 1 << 26))

        bytes.withUnsafeBufferPointer { buf in
            guard let base = buf.baseAddress else { return }
            let end = data.count
            var i = 0
            while i < end {
                var p = base + i
                while isSpace(p.pointee) { p += 1 }

                if p.pointee == 0x76 /* v */ && isSpace(p[1]) {
                    p += 1
                    var stop: UnsafeMutablePointer<CChar>? = nil
                    let x = strtod(p, &stop); p = UnsafePointer(stop!)
                    let y = strtod(p, &stop); p = UnsafePointer(stop!)
                    let z = strtod(p, &stop)
                    vertices.append(x); vertices.append(y); vertices.append(z)

                } else if p.pointee == 0x66 /* f */ && isSpace(p[1]) {
                    p += 1
                    polygon.removeAll(keepingCapacity: true)
                    let vertexCount = vertices.count / 3
                    while true {
                        while isSpace(p.pointee) { p += 1 }
                        if p.pointee == 0 { break }
                        var stop: UnsafeMutablePointer<CChar>? = nil
                        let raw = strtol(p, &stop, 10)
                        let parsed = UnsafePointer(stop!) != p
                        // Skip the rest of the token, i.e. any /vt/vn suffix.
                        p = UnsafePointer(stop!)
                        while p.pointee != 0 && !isSpace(p.pointee) { p += 1 }
                        guard parsed, raw != 0 else { continue }
                        // OBJ is 1-based; negative counts back from the latest vertex.
                        let index = raw > 0 ? raw - 1 : vertexCount + raw
                        if index >= 0 && index < vertexCount { polygon.append(Int32(index)) }
                    }
                    if polygon.count >= 3 {
                        for k in 1..<(polygon.count - 1) {
                            faces.append(polygon[0]); faces.append(polygon[k]); faces.append(polygon[k + 1])
                        }
                    }
                }

                // Next line: step past this line's NUL.
                while i < end && base[i] != 0 { i += 1 }
                i += 1
            }
        }

        guard !faces.isEmpty else { throw STLError.notATriangleMesh }
        return Mesh(vertices: vertices, faces: faces)
    }

    @inline(__always)
    private static func isSpace(_ c: CChar) -> Bool {
        c == 0x20 || c == 0x09 || c == 0x0D
    }
}

/// Picks a reader by file extension. Output is always STL regardless.
public enum MeshFile {
    public static let supportedExtensions = ["stl", "obj"]

    public static func isSupported(_ url: URL) -> Bool {
        supportedExtensions.contains(url.pathExtension.lowercased())
    }

    public static func read(contentsOf url: URL) throws -> Mesh {
        switch url.pathExtension.lowercased() {
        case "obj": return try OBJ.read(contentsOf: url)
        default: return try STL.read(contentsOf: url)
        }
    }
}
