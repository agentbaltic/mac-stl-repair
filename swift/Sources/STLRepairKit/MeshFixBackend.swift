import Foundation
import CMeshFix

/// Repair backed by MeshFix (IMATI-GE / CNR).
///
/// This is the engine that actually guarantees a watertight manifold, and the
/// reason the app is GPLv3: MeshFix is dual-licensed GPLv3 or commercial, so
/// distributing this app means distributing its source under the same terms.
public struct MeshFixBackend: RepairBackend {
    public let name = "meshfix"
    public let isAvailable = true
    public let licenseNote: String? =
        "MeshFix (c) IMATI-GE / CNR, distributed under GPLv3. "
        + "Using it obliges this app to be GPLv3 as well."

    public init() {}

    public func repairShell(_ mesh: Mesh, options: RepairOptions, log: RepairLog) throws -> Mesh {
        guard mesh.faceCount > 0 else { throw RepairError.emptyResult(name) }
        log("running MeshFix on \(human(mesh.faceCount)) faces ...")

        var result = MFMesh()
        var errorBuffer = [CChar](repeating: 0, count: 512)

        let status: Int32 = mesh.vertices.withUnsafeBufferPointer { vertices in
            mesh.faces.withUnsafeBufferPointer { faces in
                meshfix_repair(vertices.baseAddress,
                               Int32(mesh.vertexCount),
                               faces.baseAddress,
                               Int32(mesh.faceCount),
                               options.mergeParts ? 1 : 0,
                               &result,
                               &errorBuffer,
                               Int32(errorBuffer.count))
            }
        }
        defer { meshfix_free(&result) }

        guard Int(status) == MF_OK else {
            let detail = String(decoding: errorBuffer.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) },
                                as: UTF8.self)
            throw MeshFixError(status: status,
                               detail: detail.isEmpty ? "no detail reported" : detail)
        }
        guard let vertexData = result.vertices,
              let faceData = result.faces,
              result.face_count > 0 else {
            throw RepairError.emptyResult(name)
        }

        let repaired = Mesh(
            vertices: Array(UnsafeBufferPointer(start: vertexData,
                                                count: Int(result.vertex_count) * 3)),
            faces: Array(UnsafeBufferPointer(start: faceData,
                                             count: Int(result.face_count) * 3)))
        log("MeshFix -> \(human(repaired.vertexCount)) vertices, \(human(repaired.faceCount)) faces")
        return repaired
    }
}

public struct MeshFixError: Error, CustomStringConvertible {
    public let status: Int32
    public let detail: String

    public var description: String {
        let reason: String
        switch status {
        case Int32(MF_BAD_INPUT): reason = "MeshFix rejected the input"
        case Int32(MF_EMPTY_RESULT): reason = "MeshFix consumed the whole mesh"
        default: reason = "MeshFix failed"
        }
        return "\(reason): \(detail)"
    }
}
