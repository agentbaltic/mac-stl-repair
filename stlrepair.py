#!/usr/bin/env python3
"""
stlrepair - repair STL meshes for 3D printing.

A local replacement for online STL repair services, with no file size limit.

Pipeline:
  1. load (binary or ASCII STL, OBJ, PLY, 3MF, OFF)
  2. weld duplicate vertices, drop degenerate/duplicate/unreferenced geometry
  3. fix face winding and normal direction
  4. fill simple holes
  5. hand anything still broken to MeshFix (removes self-intersections,
     fills every remaining hole, guarantees a watertight manifold shell)
  6. verify and write a binary STL

Usage:
  stlrepair model.stl
  stlrepair model.stl -o fixed.stl
  stlrepair ./stls -r --check          # diagnose a whole folder, change nothing
  stlrepair ./stls -r --out-dir ./fixed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("TRIMESH_LOG_LEVEL", "ERROR")
import logging

logging.getLogger("trimesh").setLevel(logging.ERROR)

import trimesh
from trimesh import repair as tmrepair

SUPPORTED = {".stl", ".obj", ".ply", ".off", ".3mf", ".glb"}


# ----------------------------------------------------------------- utilities

class Log:
    def __init__(self, quiet=False):
        self.quiet = quiet
        self.lines = []

    def __call__(self, msg, indent=1):
        line = ("  " * indent) + msg
        self.lines.append(line)
        if not self.quiet:
            print(line, flush=True)

    def head(self, msg):
        if not self.quiet:
            print(msg, flush=True)
        self.lines.append(msg)


def human(n):
    return f"{n:,}"


def size_str(path):
    b = Path(path).stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.1f} {unit}" if unit != "B" else f"{b} B"
        b /= 1024


# ----------------------------------------------------------------- diagnosis

def edge_stats(mesh):
    """Count boundary (hole) edges and non-manifold edges."""
    faces = mesh.faces
    if len(faces) == 0:
        return 0, 0
    e = np.sort(mesh.edges_sorted, axis=1)
    n = int(mesh.vertices.shape[0]) + 1
    key = e[:, 0].astype(np.int64) * n + e[:, 1].astype(np.int64)
    _, counts = np.unique(key, return_counts=True)
    boundary = int((counts == 1).sum())
    nonmanifold = int((counts > 2).sum())
    return boundary, nonmanifold


def diagnose(mesh):
    d = {}
    d["vertices"] = int(len(mesh.vertices))
    d["faces"] = int(len(mesh.faces))

    if d["faces"] == 0:
        d.update(dict(watertight=False, winding_consistent=False, is_volume=False,
                      boundary_edges=0, nonmanifold_edges=0, duplicate_faces=0,
                      degenerate_faces=0, unreferenced_vertices=0, components=0,
                      euler_number=0, volume_cm3=0.0, area_cm2=0.0,
                      bbox_mm=[0, 0, 0], inverted=False, empty=True))
        return d

    d["empty"] = False
    d["watertight"] = bool(mesh.is_watertight)
    d["winding_consistent"] = bool(mesh.is_winding_consistent)

    b, nm = edge_stats(mesh)
    d["boundary_edges"] = b
    d["nonmanifold_edges"] = nm

    try:
        d["degenerate_faces"] = int((~mesh.nondegenerate_faces()).sum())
    except Exception:
        d["degenerate_faces"] = 0
    try:
        d["duplicate_faces"] = int(d["faces"] - mesh.unique_faces().sum())
    except Exception:
        d["duplicate_faces"] = 0

    d["unreferenced_vertices"] = int(d["vertices"] - len(np.unique(mesh.faces)))

    try:
        d["components"] = len(trimesh.graph.connected_components(
            mesh.face_adjacency, nodes=np.arange(len(mesh.faces))))
    except Exception:
        d["components"] = -1

    try:
        d["euler_number"] = int(mesh.euler_number)
    except Exception:
        d["euler_number"] = 0

    vol = float(mesh.volume) if d["watertight"] else 0.0
    d["inverted"] = bool(d["watertight"] and vol < 0)
    d["volume_cm3"] = round(abs(vol) / 1000.0, 3)
    d["area_cm2"] = round(float(mesh.area) / 100.0, 2)
    d["bbox_mm"] = [round(float(x), 2) for x in mesh.extents]
    d["is_volume"] = bool(mesh.is_volume)
    return d


def is_healthy(d):
    return (
        not d["empty"]
        and d["watertight"]
        and d["winding_consistent"]
        and d["nonmanifold_edges"] == 0
        and d["boundary_edges"] == 0
        and d["degenerate_faces"] == 0
        and d["duplicate_faces"] == 0
        and not d["inverted"]
    )


def problem_list(d):
    p = []
    if d["empty"]:
        return ["mesh contains no faces"]
    if not d["watertight"]:
        p.append(f"not watertight ({human(d['boundary_edges'])} open edges / holes)")
    if d["nonmanifold_edges"]:
        p.append(f"{human(d['nonmanifold_edges'])} non-manifold edges")
    if not d["winding_consistent"]:
        p.append("inconsistent face winding")
    if d["inverted"]:
        p.append("inside-out normals (negative volume)")
    if d["degenerate_faces"]:
        p.append(f"{human(d['degenerate_faces'])} degenerate (zero-area) faces")
    if d["duplicate_faces"]:
        p.append(f"{human(d['duplicate_faces'])} duplicate faces")
    if d["unreferenced_vertices"]:
        p.append(f"{human(d['unreferenced_vertices'])} unused vertices")
    if d["components"] > 1:
        p.append(f"{d['components']} separate shells")
    return p or ["none"]


# ------------------------------------------------------------------- repairs

def basic_clean(mesh, log, merge_tol=1e-8):
    """Cheap, lossless-ish topology cleanup. Returns True if anything changed."""
    changed = False
    v0, f0 = len(mesh.vertices), len(mesh.faces)

    mesh.remove_infinite_values()

    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    if len(mesh.vertices) != v0:
        log(f"welded {human(v0 - len(mesh.vertices))} duplicate vertices")
        changed = True

    mask = mesh.nondegenerate_faces()
    if not mask.all():
        n = int((~mask).sum())
        mesh.update_faces(mask)
        log(f"removed {human(n)} degenerate faces")
        changed = True

    mask = mesh.unique_faces()
    if not mask.all():
        n = int((~mask).sum())
        mesh.update_faces(mask)
        log(f"removed {human(n)} duplicate faces")
        changed = True

    nref = len(mesh.vertices) - len(np.unique(mesh.faces)) if len(mesh.faces) else 0
    if nref > 0:
        mesh.remove_unreferenced_vertices()
        log(f"removed {human(nref)} unreferenced vertices")
        changed = True

    if len(mesh.faces) != f0 or len(mesh.vertices) != v0:
        changed = True
    return changed


def fix_orientation(mesh, log):
    if len(mesh.faces) == 0:
        return
    if not mesh.is_winding_consistent:
        tmrepair.fix_winding(mesh)
        log("rebuilt face winding")
    try:
        if mesh.is_watertight and mesh.volume < 0:
            tmrepair.fix_inversion(mesh)
            log("flipped inside-out normals")
    except Exception:
        pass


def try_fill_holes(mesh, log):
    if len(mesh.faces) == 0 or mesh.is_watertight:
        return
    before, _ = edge_stats(mesh)
    try:
        tmrepair.fill_holes(mesh)
    except Exception:
        return
    after, _ = edge_stats(mesh)
    if after < before:
        log(f"filled simple holes ({human(before)} -> {human(after)} open edges)")


def meshfix(vertices, faces, join_components, log, label=""):
    """MeshFix: guarantees a single watertight manifold shell."""
    import pymeshfix

    tag = f" [{label}]" if label else ""
    log(f"running MeshFix{tag} on {human(len(faces))} faces ...")
    mf = pymeshfix.MeshFix(np.asarray(vertices, dtype=np.float64),
                           np.asarray(faces, dtype=np.int32))
    mf.repair(joincomp=join_components,
              remove_smallest_components=not join_components)
    v = np.asarray(mf.points, dtype=np.float64)
    f = np.asarray(mf.faces, dtype=np.int64)
    log(f"MeshFix{tag} -> {human(len(v))} vertices, {human(len(f))} faces")
    return v, f


def split_components(mesh, min_faces):
    """Split into connected components without altering any geometry.

    trimesh's own .split() quietly fills holes as a side effect, which would
    corrupt shells before the real repair stage ever sees them, so this walks
    face adjacency and rebuilds the submeshes by hand.
    """
    if len(mesh.faces) == 0:
        return [mesh], 0
    try:
        comps = trimesh.graph.connected_components(
            mesh.face_adjacency, nodes=np.arange(len(mesh.faces)))
    except Exception:
        return [mesh], 0
    if len(comps) <= 1:
        return [mesh], 0

    parts, dropped = [], 0
    for c in comps:
        if len(c) < min_faces:
            dropped += 1
            continue
        faces = mesh.faces[c]
        uniq, inv = np.unique(faces, return_inverse=True)
        parts.append(trimesh.Trimesh(vertices=mesh.vertices[uniq],
                                     faces=inv.reshape(-1, 3),
                                     process=False))
    if not parts:
        return [mesh], 0
    return parts, dropped


def repair_mesh(mesh, opts, log):
    """Full repair pipeline. Returns (repaired_mesh, before_diag, after_diag)."""
    log.head("  cleaning topology")
    basic_clean(mesh, log, opts.merge_tol)
    fix_orientation(mesh, log)
    before = diagnose(mesh)

    log.head("  diagnosis")
    for p in problem_list(before):
        log(f"- {p}")

    if is_healthy(before) and not opts.force:
        log.head("  mesh is already printable - nothing to repair")
        return mesh, before, before

    log.head("  repairing")

    # trimesh's hole filler is exact on simple holes but silently chords across
    # awkward ones (and gives up on large ones), so MeshFix is the default.
    if opts.filler == "simple" or opts.no_meshfix:
        try_fill_holes(mesh, log)
        fix_orientation(mesh, log)
    else:
        parts, dropped = ([mesh], 0)
        if opts.parts != "merge":
            parts, dropped = split_components(mesh, opts.min_part_faces)
            if dropped:
                log(f"discarded {dropped} shell(s) below {opts.min_part_faces} faces "
                    f"(likely stray debris)")
            if len(parts) > 1:
                log(f"repairing {len(parts)} shells independently "
                    f"(use --parts merge to fuse them instead)")

        fixed = []
        for i, part in enumerate(parts):
            label = f"shell {i + 1}/{len(parts)}" if len(parts) > 1 else ""
            if is_healthy(diagnose(part)) and not opts.force:
                log(f"{label or 'mesh'}: already sound, left untouched")
                fixed.append(part)
                continue
            try:
                v, f = meshfix(part.vertices, part.faces,
                               join_components=(opts.parts == "merge"),
                               log=log, label=label)
                if len(f) == 0:
                    raise ValueError("MeshFix returned an empty mesh")
                fixed.append(trimesh.Trimesh(vertices=v, faces=f, process=False))
            except Exception as e:
                log(f"MeshFix failed on {label or 'mesh'} ({e}); "
                    f"falling back to simple hole filling")
                try_fill_holes(part, log)
                fixed.append(part)

        mesh = fixed[0] if len(fixed) == 1 else trimesh.util.concatenate(fixed)

    basic_clean(mesh, log, opts.merge_tol)
    fix_orientation(mesh, log)
    after = diagnose(mesh)
    return mesh, before, after


# -------------------------------------------------------------------- report

def print_summary(before, after, log):
    rows = [
        ("triangles", human(before["faces"]), human(after["faces"])),
        ("vertices", human(before["vertices"]), human(after["vertices"])),
        ("watertight", yn(before["watertight"]), yn(after["watertight"])),
        ("manifold", yn(before["nonmanifold_edges"] == 0),
         yn(after["nonmanifold_edges"] == 0)),
        ("open edges", human(before["boundary_edges"]), human(after["boundary_edges"])),
        ("consistent normals", yn(before["winding_consistent"]),
         yn(after["winding_consistent"])),
        ("shells", str(before["components"]), str(after["components"])),
        ("volume (cm3)", f"{before['volume_cm3']:g}", f"{after['volume_cm3']:g}"),
    ]
    log.head("  result")
    log(f"{'':22}{'before':>14}{'after':>14}")
    for name, b, a in rows:
        log(f"{name:22}{b:>14}{a:>14}")
    dims = after["bbox_mm"]
    log(f"{'size (mm)':22}{'':>14}{f'{dims[0]} x {dims[1]} x {dims[2]}':>14}")

    # Closing a hole always invents geometry. If the input was already a closed
    # solid, any real volume change means the repair altered the actual shape.
    if before["watertight"] and after["watertight"] and before["volume_cm3"] > 0:
        delta = (after["volume_cm3"] - before["volume_cm3"]) / before["volume_cm3"]
        log(f"{'volume change':22}{'':>14}{f'{delta * 100:+.2f}%':>14}")
        if abs(delta) > 0.01:
            log(f"WARNING: repair changed the solid volume by {delta * 100:+.1f}% - "
                f"inspect the result before printing", indent=1)
    elif not before["watertight"]:
        added = after["faces"] - before["faces"]
        if added > 0:
            log(f"{'triangles added':22}{'':>14}{human(added):>14}")
            log("note: closed regions are reconstructed, not recovered - "
                "check that patched areas match your intent", indent=1)


def yn(v):
    return "yes" if v else "NO"


# ---------------------------------------------------------------------- main

def load_mesh(path):
    m = trimesh.load(str(path), force="mesh", process=False)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(tuple(m.geometry.values()))
    if not isinstance(m, trimesh.Trimesh):
        raise ValueError("file does not contain a triangle mesh")
    return m


def output_path(src, opts):
    src = Path(src)
    if opts.output:
        return Path(opts.output)
    name = src.stem + opts.suffix + ".stl"
    if opts.out_dir:
        out = Path(opts.out_dir)
        if opts.recursive and opts.root and src.is_relative_to(opts.root):
            out = out / src.parent.relative_to(opts.root)
        out.mkdir(parents=True, exist_ok=True)
        return out / name
    return src.with_name(name)


def process_file(path, opts):
    log = Log(quiet=opts.quiet)
    t0 = time.time()
    log.head(f"\n{path.name}  ({size_str(path)})")

    try:
        mesh = load_mesh(path)
    except Exception as e:
        log.head(f"  ERROR: could not read file - {e}")
        return {"file": str(path), "ok": False, "error": str(e)}

    log(f"loaded {human(len(mesh.faces))} triangles")

    if opts.check:
        basic_clean(mesh, Log(quiet=True), opts.merge_tol)
        d = diagnose(mesh)
        log.head("  diagnosis")
        for p in problem_list(d):
            log(f"- {p}")
        log(f"verdict: {'PRINTABLE' if is_healthy(d) else 'NEEDS REPAIR'}")
        return {"file": str(path), "ok": True, "checked_only": True,
                "healthy": is_healthy(d), "diagnosis": d}

    mesh, before, after = repair_mesh(mesh, opts, log)

    if len(mesh.faces) == 0:
        log.head("  ERROR: repair produced an empty mesh; nothing written")
        return {"file": str(path), "ok": False, "error": "empty result"}

    dst = output_path(path, opts)
    if dst.resolve() == path.resolve() and not opts.overwrite:
        log.head("  ERROR: refusing to overwrite the input (use --overwrite)")
        return {"file": str(path), "ok": False, "error": "would overwrite input"}

    mesh.export(str(dst), file_type="stl")
    log.head(f"  wrote {dst}  ({size_str(dst)})")

    print_summary(before, after, log)
    ok = is_healthy(after)
    log(f"{'REPAIRED - watertight and printable' if ok else 'PARTIAL - still has issues (see above)'}"
        f"   [{time.time() - t0:.1f}s]")

    return {"file": str(path), "output": str(dst), "ok": True,
            "healthy_after": ok, "before": before, "after": after}


def gather(inputs, recursive, suffix=""):
    """Collect input meshes. Folder scans skip this tool's own output files
    so repeat runs don't produce name_repaired_repaired.stl."""
    files, skipped = [], 0
    for item in inputs:
        p = Path(item).expanduser()
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(it):
                if f.suffix.lower() not in SUPPORTED or not f.is_file():
                    continue
                if suffix and f.stem.endswith(suffix):
                    skipped += 1
                    continue
                files.append(f)
        elif p.is_file():
            files.append(p)          # explicitly named files are always honoured
        else:
            print(f"skipping (not found): {item}", file=sys.stderr)
    if skipped:
        print(f"skipping {skipped} already-repaired file(s) ending in '{suffix}'",
              file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(
        prog="stlrepair",
        description="Repair STL meshes for 3D printing. No file size limit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  stlrepair model.stl                    repair -> model_repaired.stl
  stlrepair model.stl -o fixed.stl       repair to a named file
  stlrepair model.stl --check            diagnose only, write nothing
  stlrepair ./stls -r --out-dir ./fixed  repair a whole tree
  stlrepair model.stl --parts merge      fuse touching shells into one solid
""")
    ap.add_argument("inputs", nargs="+", help="STL file(s) or folder(s)")
    ap.add_argument("-o", "--output", help="output file (single input only)")
    ap.add_argument("-d", "--out-dir", help="write repaired files into this folder")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="recurse into subfolders")
    ap.add_argument("--suffix", default="_repaired",
                    help="suffix for output names (default: _repaired)")
    ap.add_argument("--check", action="store_true",
                    help="diagnose only; do not write anything")
    ap.add_argument("--force", action="store_true",
                    help="run the full repair even if the mesh looks healthy")
    ap.add_argument("--parts", choices=["separate", "merge"], default="separate",
                    help="separate: repair each shell independently (default); "
                         "merge: fuse all shells into one solid")
    ap.add_argument("--min-part-faces", type=int, default=8,
                    help="discard shells smaller than this many faces (default: 8)")
    ap.add_argument("--filler", choices=["auto", "simple"], default="auto",
                    help="auto: MeshFix closes holes, most reliable (default); "
                         "simple: fast trimesh filler, only handles small holes")
    ap.add_argument("--no-meshfix", action="store_true",
                    help="skip the heavy MeshFix stage (cleanup only)")
    ap.add_argument("--merge-tol", type=float, default=1e-8,
                    help="vertex welding tolerance (default: 1e-8)")
    ap.add_argument("--overwrite", action="store_true",
                    help="allow writing over the input file")
    ap.add_argument("--json", metavar="FILE", help="write a machine-readable report")
    ap.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    opts = ap.parse_args()

    files = gather(opts.inputs, opts.recursive, opts.suffix)
    if not files:
        print("no mesh files found", file=sys.stderr)
        return 2
    if opts.output and len(files) > 1:
        print("-o/--output only works with a single input file", file=sys.stderr)
        return 2

    root = Path(opts.inputs[0]).expanduser()
    opts.root = root if root.is_dir() else None

    results = [process_file(f, opts) for f in files]

    if len(files) > 1 and not opts.quiet:
        good = sum(1 for r in results if r.get("healthy_after") or r.get("healthy"))
        failed = sum(1 for r in results if not r.get("ok"))
        print(f"\n{'=' * 52}")
        print(f"{len(files)} file(s):  {good} clean,  "
              f"{len(files) - good - failed} partial,  {failed} error(s)")

    if opts.json:
        Path(opts.json).write_text(json.dumps(results, indent=2))
        print(f"report written to {opts.json}")

    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
