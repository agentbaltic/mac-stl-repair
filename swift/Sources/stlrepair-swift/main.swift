import Foundation
import STLRepairKit

// A deliberately small CLI. Its job is to be diffable against the Python
// engine (`stlrepair.py --json`) on the same files, so it mirrors that
// output shape rather than inventing a nicer one.

func usage() -> Never {
    print("""
    stlrepair-swift - STL diagnosis and repair

      stlrepair-swift diagnose <file.stl|file.obj> [--json]
      stlrepair-swift repair   <file.stl|file.obj> [-o out.stl] [--json]
                               [--parts separate|merge] [--min-part-faces N]
                               [--backend meshfix|native]
                               [--merge-tol X] [--force]

    Exit status is 0 when the mesh ends up printable, 1 otherwise.
    """)
    exit(2)
}

var args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first, ["diagnose", "repair"].contains(command) else { usage() }
args.removeFirst()

@MainActor func takeFlag(_ name: String) -> Bool {
    guard let i = args.firstIndex(of: name) else { return false }
    args.remove(at: i)
    return true
}

@MainActor func takeValue(_ name: String) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    let v = args[i + 1]
    args.removeSubrange(i...(i + 1))
    return v
}

let asJSON = takeFlag("--json")
let force = takeFlag("--force")
let output = takeValue("-o") ?? takeValue("--output")
let partsMode = takeValue("--parts") ?? "separate"
let minPartFaces = Int(takeValue("--min-part-faces") ?? "") ?? 8
let mergeTolerance = Double(takeValue("--merge-tol") ?? "") ?? 1e-8
let backendName = takeValue("--backend") ?? "meshfix"

guard let path = args.first(where: { !$0.hasPrefix("-") }) else { usage() }
let inputURL = URL(fileURLWithPath: path)

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("error: \(message)\n".utf8))
    exit(2)
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

do {
    var mesh = try MeshFile.read(contentsOf: inputURL)
    let options = RepairOptions(mergeParts: partsMode == "merge",
                                minPartFaces: minPartFaces,
                                mergeTolerance: mergeTolerance,
                                force: force)

    if command == "diagnose" {
        // Weld first: a raw STL is a triangle soup and would otherwise score
        // every edge as a hole. Deliberately no orientation fix here — that
        // would repair winding problems before they could be reported.
        let log = RepairLog()
        Repair.basicClean(&mesh, options: options, log: log)
        let d = Diagnosis.of(mesh)

        if asJSON {
            print(String(data: try encoder.encode(d), encoding: .utf8)!)
        } else {
            print("\(inputURL.lastPathComponent)")
            print("  \(human(d.faces)) triangles, \(human(d.vertices)) vertices, \(d.components) shell(s)")
            print("  volume \(d.volumeCm3) cm3, area \(d.areaCm2) cm2")
            print("  bbox \(d.bboxMm.map { String(format: "%.2f", $0) }.joined(separator: " x ")) mm")
            for p in d.problems { print("  - \(p)") }
        }
        exit(d.isHealthy ? 0 : 1)
    }

    let started = Date()
    // Spelled out rather than inlined: the ternary gives the optional
    // @Sendable closure nothing to infer from.
    var printer: (@Sendable (String) -> Void)?
    if !asJSON { printer = { print("  \($0)") } }
    let log = RepairLog(onLine: printer)
    let backend: RepairBackend
    switch backendName {
    case "native": backend = NativeBackend()
    case "meshfix": backend = MeshFixBackend()
    default: fail("unknown backend '\(backendName)' (expected meshfix or native)")
    }
    let result = try Repair.run(mesh, backend: backend, options: options, log: log)
    let elapsed = Date().timeIntervalSince(started)

    let destination = output.map { URL(fileURLWithPath: $0) }
        ?? inputURL.deletingLastPathComponent()
            .appendingPathComponent(inputURL.deletingPathExtension().lastPathComponent + "_repaired.stl")
    try STL.write(result.mesh, to: destination)

    if asJSON {
        struct Report: Encodable {
            let input: String, output: String, seconds: Double
            let before: Diagnosis, after: Diagnosis, log: [String]
        }
        let report = Report(input: inputURL.path, output: destination.path,
                            seconds: (elapsed * 1000).rounded() / 1000,
                            before: result.before, after: result.after, log: result.log)
        print(String(data: try encoder.encode(report), encoding: .utf8)!)
    } else {
        print("  wrote \(destination.path) in \(String(format: "%.2f", elapsed))s")
        print("  \(result.after.isHealthy ? "printable" : "still has problems: \(result.after.problems.joined(separator: ", "))")")
    }
    exit(result.after.isHealthy ? 0 : 1)

} catch {
    fail("\(error)")
}
