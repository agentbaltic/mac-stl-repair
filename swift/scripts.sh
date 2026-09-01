#!/usr/bin/env bash
# Shared settings for the Swift build.
#
# Two things are non-obvious and both are forced on us by the environment:
#
#  1. Never build inside iCloud Drive. iCloud attaches extended attributes that
#     make codesign fail with "resource fork, Finder information, or similar
#     detritus not allowed", so the scratch path lives under $HOME.
#  2. This machine has Command Line Tools but no Xcode. swift-testing ships in
#     CLT but is not on the default search path, and its Foundation cross-import
#     overlay has no shipped .swiftmodule, so tests need the -F, -rpath and
#     -disable-cross-import-overlays flags below. Drop them if a full Xcode is
#     ever installed and `swift test` works bare.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="${STLREPAIR_SCRATCH:-$HOME/stlrepair-swift-build}"
FRAMEWORKS="$(xcode-select -p)/Library/Developer/Frameworks"

SWIFT_COMMON=(--package-path "$HERE" --scratch-path "$SCRATCH")
TEST_FLAGS=(
    -Xswiftc -F -Xswiftc "$FRAMEWORKS"
    -Xlinker -F -Xlinker "$FRAMEWORKS"
    -Xlinker -rpath -Xlinker "$FRAMEWORKS"
    -Xswiftc -Xfrontend -Xswiftc -disable-cross-import-overlays
)
