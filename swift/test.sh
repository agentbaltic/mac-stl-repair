#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/scripts.sh"
swift test "${SWIFT_COMMON[@]}" "${TEST_FLAGS[@]}" "$@"
