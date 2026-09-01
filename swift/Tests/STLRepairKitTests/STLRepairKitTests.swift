import Testing
import Foundation
@testable import STLRepairKit

/// A closed, correctly wound box as a raw triangle soup, the way an STL
/// actually arrives: no shared vertices at all.
func boxSoup(origin: (Double, Double, Double) = (0, 0, 0), size s: Double = 10) -> Mesh {
    let (ox, oy, oz) = origin
    let p: [(Double, Double, Double)] = [
        (ox, oy, oz), (ox + s, oy, oz), (ox + s, oy + s, oz), (ox, oy + s, oz),
        (ox, oy, oz + s), (ox + s, oy, oz + s), (ox + s, oy + s, oz + s), (ox, oy + s, oz + s)]
    let quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    var vertices: [Double] = []
    var faces: [Int32] = []
    for (a, b, c, d) in quads {
        for tri in [[a, b, c], [a, c, d]] {
            for i in tri {
                vertices.append(contentsOf: [p[i].0, p[i].1, p[i].2])
                faces.append(Int32(faces.count))
            }
        }
    }
    return Mesh(vertices: vertices, faces: faces)
}

/// A closed tetrahedron: only 4 faces, so it reads as debris under any
/// sensible face-count threshold. Scale does not change face count, which is
/// exactly why a "small box" is not debris.
func tetraSoup(origin: (Double, Double, Double) = (0, 0, 0), size s: Double = 1) -> Mesh {
    let (ox, oy, oz) = origin
    let p: [(Double, Double, Double)] = [
        (ox, oy, oz), (ox + s, oy, oz), (ox, oy + s, oz), (ox, oy, oz + s)]
    let tris = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    var vertices: [Double] = []
    var faces: [Int32] = []
    for (a, b, c) in tris {
        for i in [a, b, c] {
            vertices.append(contentsOf: [p[i].0, p[i].1, p[i].2])
            faces.append(Int32(faces.count))
        }
    }
    return Mesh(vertices: vertices, faces: faces)
}

func welded(_ mesh: Mesh) -> Mesh {
    var m = mesh
    _ = Topology.weld(&m)
    return m
}

func isClose(_ a: Double, _ b: Double, _ tolerance: Double = 1e-6) -> Bool {
    abs(a - b) <= tolerance
}

@Suite("Mesh topology and repair")
struct MeshTests {

    @Test("welding turns an STL soup into real topology")
    func weldCreatesTopology() {
        var m = boxSoup()
        #expect(m.vertexCount == 36)  // 3 vertices per triangle, nothing shared
        let removed = Topology.weld(&m)
        #expect(m.vertexCount == 8)   // a box has 8 distinct corners
        #expect(removed == 28)
        #expect(m.faceCount == 12)    // welding must never change the face count
    }

    @Test("a healthy box reports as printable")
    func healthyBoxDiagnosis() {
        let d = Diagnosis.of(welded(boxSoup()))
        #expect(d.isHealthy)
        #expect(d.watertight)
        #expect(d.windingConsistent)
        #expect(d.boundaryEdges == 0)
        #expect(d.nonmanifoldEdges == 0)
        #expect(d.components == 1)
        #expect(d.eulerNumber == 2)  // closed genus-0 surface
        #expect(isClose(d.volumeCm3, 1.0))   // 10mm box = 1000mm^3 = 1cm^3
        #expect(isClose(d.areaCm2, 6.0))
        #expect(d.bboxMm == [10, 10, 10])
    }

    @Test("a hole is detected, then filled back to the original volume")
    func holeIsDetectedAndFilled() throws {
        var soup = boxSoup()
        soup.faces.removeLast(6)  // drop one quad's two triangles
        Topology.removeUnreferencedVertices(&soup)

        let before = Diagnosis.of(welded(soup))
        #expect(!before.watertight)
        #expect(before.boundaryEdges == 4)  // one missing face leaves a 4-edge rim

        let result = try Repair.run(soup, backend: NativeBackend())
        #expect(result.after.isHealthy)
        #expect(result.after.boundaryEdges == 0)
        #expect(isClose(result.after.volumeCm3, 1.0))
    }

    @Test("an inside-out shell is flipped back")
    func invertedShellIsFlipped() throws {
        var soup = boxSoup()
        for f in 0..<soup.faceCount { soup.faces.swapAt(f * 3 + 1, f * 3 + 2) }

        let before = Diagnosis.of(welded(soup))
        #expect(before.inverted)
        #expect(before.windingConsistent)  // consistent, just the wrong way round

        let result = try Repair.run(soup, backend: NativeBackend())
        #expect(!result.after.inverted)
        #expect(result.after.isHealthy)
    }

    /// The regression that motivated rewriting fixWinding: addressing shared
    /// edges by corner slot goes stale the moment a face is flipped, so the
    /// flood fill silently stopped correcting partway through.
    @Test("mixed winding is made consistent across the whole shell")
    func mixedWindingIsFixed() throws {
        var soup = boxSoup()
        for f in [0, 3, 7] { soup.faces.swapAt(f * 3 + 1, f * 3 + 2) }

        #expect(!Diagnosis.of(welded(soup)).windingConsistent)

        let result = try Repair.run(soup, backend: NativeBackend())
        #expect(result.after.windingConsistent)
        #expect(result.after.isHealthy)
        #expect(isClose(result.after.volumeCm3, 1.0))
    }

    @Test("degenerate and duplicate faces are removed")
    func junkFacesRemoved() throws {
        var soup = boxSoup()
        let base = Int32(soup.vertexCount)
        soup.vertices.append(contentsOf: [0, 0, 0, 0, 0, 0, 0, 0, 0])  // zero-area
        soup.faces.append(contentsOf: [base, base + 1, base + 2])
        soup.faces.append(contentsOf: [soup.faces[0], soup.faces[1], soup.faces[2]])

        let before = Diagnosis.of(welded(soup))
        #expect(before.degenerateFaces == 1)
        #expect(before.duplicateFaces == 1)

        let result = try Repair.run(soup, backend: NativeBackend())
        #expect(result.after.degenerateFaces == 0)
        #expect(result.after.duplicateFaces == 0)
        #expect(result.after.faces == 12)
    }

    @Test("a tiny detached speck is discarded as debris")
    func debrisIsDiscarded() throws {
        let combined = Repair.concatenate([boxSoup(), tetraSoup(origin: (50, 0, 0), size: 0.4)])
        #expect(Diagnosis.of(welded(combined)).components == 2)

        // Default threshold is 8 faces: the box (12) survives, the tetra (4) does not.
        let result = try Repair.run(combined, backend: NativeBackend(),
                                    options: RepairOptions(force: true))
        #expect(result.after.components == 1)
        #expect(isClose(result.after.volumeCm3, 1.0))  // only the box is left
    }

    @Test("a small but well-formed shell is kept, because debris is about face count")
    func smallShellIsNotDebris() throws {
        let combined = Repair.concatenate([boxSoup(), boxSoup(origin: (50, 0, 0), size: 0.4)])
        let result = try Repair.run(combined, backend: NativeBackend(),
                                    options: RepairOptions(force: true))
        #expect(result.after.components == 2)
    }

    /// A fin sharing a single edge is non-manifold and must not be counted as
    /// part of the surface it touches, or it can never be dropped as debris.
    @Test("a non-manifold fin counts as its own component")
    func nonManifoldFinIsSeparate() {
        var soup = boxSoup()
        let base = Int32(soup.vertexCount)
        soup.vertices.append(contentsOf: [0, 0, 0, 10, 0, 0, 5, -8, 5])
        soup.faces.append(contentsOf: [base, base + 1, base + 2])

        let d = Diagnosis.of(welded(soup))
        #expect(d.nonmanifoldEdges > 0)
        #expect(d.components == 2)
    }

    @Test("two legitimate shells are both kept")
    func twoShellsBothKept() throws {
        let combined = Repair.concatenate([boxSoup(), boxSoup(origin: (30, 0, 0))])
        let result = try Repair.run(combined, backend: NativeBackend(),
                                    options: RepairOptions(force: true))
        #expect(result.after.components == 2)
        #expect(isClose(result.after.volumeCm3, 2.0))
    }
}

@Suite("STL reading and writing")
struct STLIOTests {

    private func tempURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("stlrepair-test-\(UUID().uuidString).stl")
    }

    @Test("binary write then read preserves the mesh")
    func binaryRoundTrip() throws {
        let original = welded(boxSoup())
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }

        try STL.write(original, to: url)
        let reloaded = welded(try STL.read(contentsOf: url))

        #expect(reloaded.faceCount == original.faceCount)
        #expect(reloaded.vertexCount == original.vertexCount)
        let after = Diagnosis.of(reloaded)
        #expect(after.isHealthy)
        #expect(isClose(after.volumeCm3, Diagnosis.of(original).volumeCm3))
    }

    @Test("ASCII STL parses to the same mesh as binary")
    func asciiMatchesBinary() throws {
        let mesh = welded(boxSoup())
        var text = "solid test\n"
        for f in 0..<mesh.faceCount {
            text += "facet normal 0 0 0\n  outer loop\n"
            let (ia, ib, ic) = mesh.face(f)
            for i in [ia, ib, ic] {
                let v = mesh.vertex(i)
                text += "    vertex \(v.x) \(v.y) \(v.z)\n"
            }
            text += "  endloop\nendfacet\n"
        }
        text += "endsolid test\n"

        let parsed = welded(try STL.read(Data(text.utf8)))
        #expect(parsed.faceCount == 12)
        #expect(Diagnosis.of(parsed).isHealthy)
        #expect(isClose(Diagnosis.of(parsed).volumeCm3, 1.0))
    }

    /// Binary STLs whose 80-byte header happens to start with "solid" are
    /// common in the wild; only the length check tells them from ASCII.
    @Test("a binary STL whose header starts with 'solid' is not misread")
    func binaryStartingWithSolid() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        try STL.write(welded(boxSoup()), to: url)

        var data = try Data(contentsOf: url)
        data.replaceSubrange(0..<5, with: Data("solid".utf8))
        try data.write(to: url)

        #expect(STL.isBinary(data))
        #expect(try STL.read(contentsOf: url).faceCount == 12)
    }

    @Test("a truncated file yields the triangles it actually has")
    func truncatedFile() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        try STL.write(welded(boxSoup()), to: url)

        var data = try Data(contentsOf: url)
        data.removeLast(50 * 4)  // lose four triangles; header still claims 12
        #expect(try STL.read(data).faceCount == 8)
    }
}
