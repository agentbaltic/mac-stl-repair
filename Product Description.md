# Mac STL Repair — copy for listings, video descriptions and the download page

By Dave Tries This · youtube.com/@davetriesthis
Download: https://rebrand.ly/stlrepair

---

## One-liner

Free Mac app that makes broken STL files printable. No size limit, nothing uploaded.

## Short (social / app blurb, ~50 words)

Mesh repair is the weak spot in a Mac 3D-printing setup — the desktop tools are
Windows-only, and online repair services cap uploads at around 50 MB. Mac STL
Repair runs natively on your own machine. Drag a file on, get a watertight one
back. No upload, no size ceiling, nothing leaves your Mac.

## Long (product page / video description)

**Why this exists**

Mesh repair has always been the weak spot in a Mac 3D-printing setup. The
desktop tools everyone recommends are Windows-only, which leaves Mac users on
browser-based repair services — and those cap what you can upload, commonly
around 50 MB. A detailed sculpt or a scanned part sails past that limit long
before it stops being an ordinary file, and you are handing your model to
someone else's server to get it back. Mac STL Repair runs natively on your own
machine. No upload, no queue, no size ceiling, and nothing ever leaves your Mac.

**How to use it**

Drag one or more files onto the box. Each is welded and checked, then repaired —
holes closed, non-manifold edges resolved, flipped normals corrected, stray
fragments dropped. Repaired copies are written to Downloads › STL Repaired and
your originals are never modified. The card that appears shows before and after:
when Watertight and Manifold both read yes, the file is ready to slice. If a
note says triangles were added, glance at that area first — closing a hole means
inventing new surface, and the app fills it plausibly rather than knowing what
was originally there.

## Feature bullets

- No file size limit — a 93 MB, 1.9 million triangle model repairs in about 11 seconds
- Runs entirely on your Mac. Nothing is uploaded, nothing is queued, no account
- Closes holes, fixes non-manifold edges, corrects flipped normals, removes stray fragments
- Multi-part plates are handled per object, so separate parts stay separate
- Plain-English before/after report — no need to know what "manifold" means
- Warns you when a repair changed the model's actual shape, instead of hiding it
- Reads STL (binary and text) and OBJ. Always writes binary STL
- Signed and notarised by Apple — installs with no security warnings
- Your original files are never modified

## Honest caveats (worth stating up front)

- Apple Silicon only (M1 and later). Intel Macs need a rebuild from source.
- Closing a hole means inventing surface. The app says how much it invented and
  flags when a repair altered a closed model's volume — check patched areas
  before a long print.

## Suggested video talking points

1. The problem: your slicer rejects a file, and every fix-it tool is Windows-only.
2. The wall: online repair services stop at ~50 MB, and big models blow past it.
3. The privacy angle: repair services want you to upload your model.
4. Demo: drag a large broken file on, watch it come back watertight in seconds.
5. Read the before/after card — watertight no → yes, shells 3 → 1.
6. The honesty bit: it tells you when it invented geometry. Most tools don't.

## Screenshots

In the `screenshots/` folder beside this file, 1760 × 1400:

- `mac-stl-repair-hero.png` — main product shot, light
- `mac-stl-repair-hero-dark.png` — dark, better over dark thumbnails
- `mac-stl-repair-full-page.png` — full page including both paragraphs

All show a genuine repair of a real 93 MB model. The figures are not mocked.
