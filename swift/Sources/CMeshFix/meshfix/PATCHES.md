# Local changes to vendored MeshFix

Upstream: https://github.com/MarcoAttene/MeshFix-V2.1
Commit:   ac8c0c990555f26cdad31bf712286b85b20af384

MeshFix is vendored rather than fetched so the build is reproducible and so the
GPLv3 source obligation is satisfied by this repository alone. The source is
unmodified except for the following, which are listed here so the delta from
upstream stays obvious.

## Removed

- `src/MeshFix/meshfix.cpp` — the command-line program. It defines `main()`, so
  it cannot be linked into a library. The two functions from it that we do need,
  `closestPair` and `joinClosestComponents`, are reproduced in `../shim.cpp`.

## Modified

- `src/Algorithms/holeFilling.cpp` — a leftover `printf` fired on every hole
  fill and wrote to stdout, which corrupts the CLI's `--json` output and would
  pollute the app's logs. Now guarded by `TMesh::quiet`.

- `src/Algorithms/marchIntersections.cpp` — a diagnostic dump next to a
  "should not happen" warning, likewise unguarded. Now guarded by `TMesh::quiet`.

## Build settings

- `IS64BITPLATFORM` must be defined, or MeshFix types its pointer-sized integer
  (`j_voidint`) as a 32-bit `int` and will not compile on arm64.
- `USE_HYBRID_KERNEL` is deliberately **not** defined. With it, coordinates
  become exact rationals and the build needs GMP or CGAL. Without it they are
  plain doubles. pymeshfix builds the same way, which is what makes the Python
  engine a valid reference to check our results against.
