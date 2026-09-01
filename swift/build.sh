#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/scripts.sh"
CONFIG="${1:-debug}"
swift build "${SWIFT_COMMON[@]}" -c "$CONFIG"
echo
echo "binary: $SCRATCH/$CONFIG/stlrepair-swift"
