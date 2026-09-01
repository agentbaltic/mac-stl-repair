// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "STLRepair",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "STLRepairKit", targets: ["STLRepairKit"]),
        .executable(name: "stlrepair-swift", targets: ["stlrepair-swift"]),
        .executable(name: "STLRepairApp", targets: ["STLRepairApp"]),
    ],
    targets: [
        // Vendored MeshFix (IMATI-GE / CNR, GPLv3) behind a C ABI.
        // Its headers include each other flatly ("tin.h", not <TMesh/tin.h>),
        // so both vendor header directories go on the search path.
        .target(
            name: "CMeshFix",
            exclude: [
                "meshfix/MeshFix-README.txt",
                "meshfix/gpl-3.0.txt",
            ],
            cSettings: [
                .headerSearchPath("meshfix/include/Kernel"),
                .headerSearchPath("meshfix/include/TMesh"),
                // Without this MeshFix types its pointer-sized integer as a
                // 32-bit int, which does not compile on arm64.
                .define("IS64BITPLATFORM"),
            ],
            cxxSettings: [
                .headerSearchPath("meshfix/include/Kernel"),
                .headerSearchPath("meshfix/include/TMesh"),
                .define("IS64BITPLATFORM"),
            ],
            linkerSettings: [.linkedLibrary("c++")]
        ),
        .target(name: "STLRepairKit", dependencies: ["CMeshFix"]),
        .executableTarget(name: "stlrepair-swift", dependencies: ["STLRepairKit"]),
        .executableTarget(name: "STLRepairApp", dependencies: ["STLRepairKit"]),
        .testTarget(name: "STLRepairKitTests", dependencies: ["STLRepairKit"]),
    ]
)
