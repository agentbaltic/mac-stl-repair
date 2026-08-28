# Building STL Repair from source

For when the prebuilt app won't run — most often an **Intel Mac**, since the
bundled app is Apple Silicon only. Rebuilding on the target Mac fixes that.

This file is self-contained: hand it to a developer, or paste it into an AI
coding assistant (Claude Code, etc.) and it has everything needed.

---

## Quick path

Open **Terminal**, then:

```bash
cd path/to/source
bash build.sh
```

The script creates a virtual environment, installs everything, and produces
`dist/STL Repair.app`. Drag that to Applications. Takes a few minutes.

It needs `python3`. If missing, install from
<https://www.python.org/downloads/macos/> (any 3.10–3.14) and re-run.

---

## What the pieces are

| file | role |
|---|---|
| `stlrepair.py` | the repair engine + command-line tool. Standalone and fully usable on its own. |
| `stlrepair_app.py` | local web server + drag-and-drop page. Imports `stlrepair`. |
| `build.sh` | venv → dependencies → PyInstaller bundle |
| `icon.png` | app icon source; `build.sh` converts it to `.icns` |

Dependencies: `numpy`, `scipy`, `networkx`, `trimesh`, `pymeshfix`
(+ `pyinstaller` to build). Verified on Python 3.14, macOS 26, arm64.

## Manual build

```bash
python3 -m venv .venv
./.venv/bin/pip install numpy scipy networkx trimesh pymeshfix pyinstaller
./.venv/bin/pyinstaller --name "STL Repair" --windowed --onedir --noconfirm \
  --osx-bundle-identifier com.stlrepair.app --icon icon.icns \
  --hidden-import stlrepair --collect-submodules pymeshfix \
  --exclude-module matplotlib --exclude-module tkinter --exclude-module PIL \
  --exclude-module IPython --exclude-module pytest --exclude-module pyvista \
  stlrepair_app.py
```

Run without bundling at all:

```bash
./.venv/bin/python stlrepair_app.py     # browser UI
./.venv/bin/python stlrepair.py --help  # command line
```

---

## How the repair works

1. **Weld** duplicate vertices (STL stores every triangle standalone, so this
   is what turns a triangle soup into a real surface), drop degenerate,
   duplicate and unreferenced geometry.
2. **Rebuild** face winding and normal direction.
3. **Split into shells** — each object repaired independently, so multi-part
   plates keep their parts separate.
4. **MeshFix** on each broken shell: closes every hole, removes
   self-intersections, guarantees a manifold watertight solid.
5. **Re-verify** and report before/after.

Healthy meshes are passed through untouched.

### Two traps worth knowing about

Both were hit while building this. If you rewrite or upgrade any of it, check
these first — they fail *silently*, producing a file that looks repaired.

- **`trimesh.Trimesh.split()` quietly fills holes as a side effect.** It turned
  a 10-face open cube into a 12-face "watertight" one by chording across a
  corner, shaving 16.7% off the volume — before the real repair stage ever ran.
  `split_components()` in `stlrepair.py` therefore walks face adjacency and
  rebuilds submeshes by hand, touching no geometry. Do not replace it with
  `mesh.split()`.
- **`pymeshfix` 0.18 returns results as `.points` / `.faces`**, not the `.v` /
  `.f` shown in older docs and examples. The old names still exist but are
  `None`, so the wrong one fails quietly rather than raising.

Also: trimesh's own `fill_holes` is fine on small holes but gives up on large
ones and can chord awkwardly across others, which is why MeshFix is the default
filler. `--filler simple` selects the fast trimesh path if you ever want it.

### The integrity guards

Closing a hole invents geometry, so the tool reports how much it invented:

- **volume change** when the input was already a closed solid — anything over
  1% means the repair changed the actual shape.
- **triangles added** when it wasn't — patched regions are reconstructed, not
  recovered.

Keep these if you refactor. They're what stops a silently-wrong repair from
being mistaken for a good one.

---

## Signing and notarising (removes the Gatekeeper warning)

With an Apple Developer account the app can be signed and notarised, after
which it opens on any Mac with no warning at all.

**One-time setup**

1. **Developer ID Application certificate.** Keychain Access → Certificate
   Assistant → *Request a Certificate From a Certificate Authority*, save to
   disk. Then at
   <https://developer.apple.com/account/resources/certificates/add> choose
   **Developer ID Application**, upload the request, download the `.cer` and
   double-click it to install. Only the team's Account Holder can create this
   type.
2. **Notary credentials.** Create an app-specific password at
   <https://account.apple.com> → *Sign-In and Security* → *App-Specific
   Passwords*, then store it once:

   ```bash
   xcrun notarytool store-credentials stlrepair \
     --apple-id you@example.com --team-id YOURTEAMID \
     --password xxxx-xxxx-xxxx-xxxx
   ```

**Every build**

```bash
bash sign_and_notarize.sh stlrepair
```

That signs inside-out (all nested `.so`/`.dylib` files, then the embedded
Python framework, then the bundle), uploads to Apple, waits for the ticket,
staples it, and runs a final Gatekeeper check. Omit the profile name to sign
without notarising.

### Why the entitlements file exists

`entitlements.plist` grants `allow-unsigned-executable-memory` and
`disable-library-validation`. CPython needs both under the hardened runtime —
without them the app notarises successfully and then refuses to launch, which
is a confusing failure to debug. Don't drop them.

### Distribution

After stapling, rebuild the handoff archive so recipients get the stapled copy:

```bash
cp -R "dist/STL Repair.app" ../
cd .. && ditto -c -k --sequesterRsrc --keepParent . "../STL Repair Handoff.zip"
```

The stapled ticket travels inside the app, so it works even on a Mac that is
offline the first time it runs.
