import Testing
import Foundation
@testable import STLRepairKit

@Suite("OBJ reading")
struct OBJTests {

    /// The same cube written every awkward way a real exporter might: quads,
    /// all three slash forms, negative indices, comments, CRLF line endings,
    /// and lines we must ignore. trimesh reads this as 12 faces / 1000 mm^3.
    static let awkwardCube = [
        "# a cube written the awkward way",
        "mtllib nothing.mtl",
        "o cube",
        "v 0 0 0", "v 10 0 0", "v 10 10 0", "v 0 10 0",
        "v 0 0 10", "v 10 0 10", "v 10 10 10", "v 0 10 10",
        "vt 0 0", "vn 0 0 1",
        "usemtl none",
        "s off",
        "f 1 4 3 2",
        "f 5/1 6/1 7/1 8/1",
        "f 1//1 2//1 6//1 5//1",
        "f 2/1/1 3/1/1 7/1/1 6/1/1",
        "f 3 4 8 7",
        "f -5 -8 -4 -1",
        "",
    ].joined(separator: "\r\n") + "\r\n"

    @Test("quads, slash forms, negative indices and CRLF all parse")
    func awkwardCubeParses() throws {
        var m = try OBJ.read(Data(Self.awkwardCube.utf8))
        #expect(m.vertexCount == 8)
        #expect(m.faceCount == 12)  // six quads, fan-triangulated
        _ = Topology.weld(&m)
        let d = Diagnosis.of(m)
        #expect(d.isHealthy)
        #expect(isClose(d.volumeCm3, 1.0))
    }

    @Test("a degenerate reference is skipped, not fatal")
    func badIndicesSkipped() throws {
        let obj = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\nf 1 2 99\nf 0 1 2\nf 1 2\n"
        let m = try OBJ.read(Data(obj.utf8))
        #expect(m.faceCount == 1)  // only the valid triangle survives
    }

    @Test("a file with no faces is rejected")
    func noFaces() {
        #expect(throws: STLError.self) {
            _ = try OBJ.read(Data("v 0 0 0\nv 1 0 0\nv 0 1 0\n".utf8))
        }
    }

    /// A short last line with no trailing newline must not let strtod read
    /// into the next buffer; every line is NUL-terminated before parsing.
    @Test("a final line without a newline still parses")
    func noTrailingNewline() throws {
        let m = try OBJ.read(Data("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3".utf8))
        #expect(m.faceCount == 1)
    }

    @Test("MeshFile dispatches on extension")
    func dispatch() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("objdispatch-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let obj = dir.appendingPathComponent("cube.OBJ")   // upper-case on purpose
        try Data(Self.awkwardCube.utf8).write(to: obj)
        #expect(MeshFile.isSupported(obj))
        #expect(try MeshFile.read(contentsOf: obj).faceCount == 12)
        #expect(!MeshFile.isSupported(dir.appendingPathComponent("x.ply")))
    }
}
