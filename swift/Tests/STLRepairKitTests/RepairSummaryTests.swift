import Testing
import Foundation
@testable import STLRepairKit

@Suite("Plain-language summary")
struct RepairSummaryTests {

    /// Builds a diagnosis directly so each case can isolate one signal.
    func diagnosis(faces: Int = 100, boundary: Int = 0, nonManifold: Int = 0,
                   components: Int = 1, winding: Bool = true, inverted: Bool = false,
                   degenerate: Int = 0, duplicate: Int = 0,
                   volume: Double = 10, watertight: Bool = true) -> Diagnosis {
        Diagnosis(vertices: faces / 2, faces: faces, empty: false,
                  watertight: watertight, windingConsistent: winding,
                  boundaryEdges: boundary, nonmanifoldEdges: nonManifold,
                  duplicateFaces: duplicate, degenerateFaces: degenerate,
                  unreferencedVertices: 0, components: components, eulerNumber: 2,
                  inverted: inverted, isVolume: watertight && winding,
                  volumeCm3: volume, areaCm2: 5, bboxMm: [1, 1, 1])
    }

    @Test("closed holes are counted")
    func closedHoles() {
        let s = RepairSummary(before: diagnosis(boundary: 240, watertight: false),
                              after: diagnosis(boundary: 0))
        #expect(s.fixes.contains { $0.contains("240") && $0.contains("open edges") })
    }

    @Test("a clean mesh says so rather than listing nothing")
    func nothingToDo() {
        let clean = diagnosis()
        let s = RepairSummary(before: clean, after: clean)
        #expect(s.fixes == ["Nothing needed fixing"])
        #expect(s.warning == nil)
        #expect(s.wasHealthy)
    }

    @Test("each defect class is reported")
    func everyDefectClass() {
        let s = RepairSummary(
            before: diagnosis(boundary: 12, nonManifold: 4, components: 3,
                              winding: false, inverted: false,
                              degenerate: 7, duplicate: 5, watertight: false),
            after: diagnosis())
        let all = s.fixes.joined(separator: " | ")
        #expect(all.contains("open edges"))
        #expect(all.contains("non-manifold"))
        #expect(all.contains("stray fragment"))
        #expect(all.contains("normals"))
        #expect(all.contains("zero-area"))
        #expect(all.contains("duplicate"))
    }

    @Test("one stray fragment is singular")
    func fragmentPluralisation() {
        let s = RepairSummary(before: diagnosis(components: 2), after: diagnosis(components: 1))
        #expect(s.fixes.contains("Removed 1 stray fragment"))
    }

    /// The integrity guards are the whole point of the summary: they are the
    /// only signal that a repair may have changed the model's actual shape.
    @Test("a big volume change on an already-closed solid warns")
    func volumeChangeWarns() {
        let s = RepairSummary(before: diagnosis(volume: 100), after: diagnosis(volume: 130))
        #expect(s.warning?.contains("volume") == true)
        #expect(s.warning?.contains("+30.0%") == true)
    }

    @Test("a small volume change stays quiet")
    func smallVolumeChangeIsQuiet() {
        let s = RepairSummary(before: diagnosis(volume: 100), after: diagnosis(volume: 100.5))
        #expect(s.warning == nil)
    }

    @Test("triangles invented to close holes are declared")
    func addedTrianglesWarn() {
        let s = RepairSummary(before: diagnosis(faces: 1000, boundary: 40, watertight: false),
                              after: diagnosis(faces: 1080))
        #expect(s.warning?.contains("80 triangles were added") == true)
        #expect(s.warning?.contains("reconstructed, not recovered") == true)
    }
}

@Suite("Output naming")
struct OutputLocationTests {

    @Test("a repaired file gets the _repaired suffix")
    func basicName() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("stlout-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let first = OutputLocation.destination(for: "widget.stl", in: dir)
        #expect(first.lastPathComponent == "widget_repaired.stl")
    }

    /// The input is often the user's only copy, and the output folder is
    /// shared across runs — silently overwriting a previous repair is the one
    /// unrecoverable mistake this app could make.
    @Test("an existing result is never overwritten")
    func neverOverwrites() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("stlout-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }

        let first = OutputLocation.destination(for: "widget.stl", in: dir)
        try Data("x".utf8).write(to: first)
        let second = OutputLocation.destination(for: "widget.stl", in: dir)
        #expect(second.lastPathComponent == "widget_repaired_2.stl")

        try Data("x".utf8).write(to: second)
        let third = OutputLocation.destination(for: "widget.stl", in: dir)
        #expect(third.lastPathComponent == "widget_repaired_3.stl")
    }

    @Test("names with dots keep only the real extension")
    func dottedNames() {
        let dir = URL(fileURLWithPath: "/tmp/definitely-not-here-\(UUID().uuidString)")
        let out = OutputLocation.destination(for: "v1.2.final.stl", in: dir)
        #expect(out.lastPathComponent == "v1.2.final_repaired.stl")
    }
}
