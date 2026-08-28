# STL Repair

Fixes 3D-print files that a slicer rejects — holes, non-manifold edges,
flipped normals, stray fragments. **No file size limit.** Everything runs on
your own Mac; nothing is uploaded to the internet.

---

## Install

1. Drag **STL Repair.app** into your **Applications** folder.
2. Double-click it. That's it.

---

## Use

The app opens a page in your web browser. That page *is* the app.

- **Drag STL files onto the box** — or click it to pick files.
- You can drop several at once; they queue up.
- Repaired files are saved to **Downloads → STL Repaired**, with
  `_repaired` added to the name. Your original file is never modified.
- Click **Open results folder** to jump straight there in Finder.

A 90 MB file takes about 10 seconds. Very large files may sit on
"repairing" for a while — that's normal, let it finish.

**When you're done, quit the app** (⌘Q, or right-click its Dock icon → Quit).
Closing the browser tab alone leaves it running in the background.

---

## Reading the results

Each file gets a card showing **before → after**:

| row | what it means |
|---|---|
| **Watertight** | No holes. Must say *yes* for a reliable print. |
| **Manifold** | No impossible edges. Must say *yes*. |
| **Open edges** | Holes found. Should be **0** after. |
| **Shells** | Separate pieces in the file. |
| **Triangles** | Detail level — a small change here is expected. |

A green **repaired** or **already fine** tag means it's good to slice.
An orange **partly fixed** tag means something survived the repair — the file
is still usable, but look it over before printing.

### The orange note

If you see a note about triangles being added, read it. Closing a hole means
inventing new surface. The app closes holes *plausibly*, but it can't know how
the original surface actually ran — so if a big chunk was missing, check that
area looks right before you commit to a long print.

A note about **volume change** on an already-closed model is a stronger
warning: the repair altered the actual shape. Inspect before printing.

---

## If it won't open at all

The app is built for **Apple Silicon** Macs (M1 and later). On an older Intel
Mac it won't launch — see **BUILD.md**, which rebuilds it from source in one
command on any Mac.

## Formats

Reads STL (binary and text), OBJ, PLY, OFF, 3MF, GLB. Always writes binary STL.
