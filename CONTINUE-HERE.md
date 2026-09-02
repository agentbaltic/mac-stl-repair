# STL Repair — finish on the Mac Studio

Everything needed is in this folder:

    iCloud Drive / 3D Printing / STL Repair Tool

It syncs automatically, so it is already on the Studio. Work through this
top to bottom on the Studio. You can also hand this file to Claude Code and
say "follow CONTINUE-HERE.md".

**Goal:** build the app on this machine, sign and notarise it with the Apple
Developer account, and produce a zip that opens on any Mac with no warning.

**Time:** ~10 min of your attention, plus a few minutes waiting on Apple.

---

## What this is

`STL Repair` makes broken STL files printable — closes holes, fixes
non-manifold edges and flipped normals, drops stray fragments. It exists
because Formware's online repair tool caps uploads at 50 MB and most of
David's files are bigger. It has no size limit (tested: 93 MB / 1.96M
triangles in ~11 s).

The app bundles its own Python, so the person receiving it installs nothing.
They drag STL files onto a browser page; repaired files land in
`Downloads/STL Repaired`.

## State of play

Done already, on the laptop:

- Repair engine + CLI (`stlrepair.py`) — tested against deliberately broken
  meshes, all outputs verified watertight/manifold.
- Drag-and-drop browser front end (`stlrepair_app.py`) — tested end to end.
- `build.sh` — verified from scratch in a clean directory.
- `sign_and_notarize.sh` + `entitlements.plist` — signing pipeline validated
  with an ad-hoc identity (all 156 nested binaries), and the app confirmed to
  still launch with the **hardened runtime enabled**.

Not done, because it needs the Developer ID private key:

- **Signing and notarising.** That's what's left.

Nothing here depends on the laptop. Building fresh on the Studio is expected —
both machines are Apple Silicon, so the result is identical.

---

---

# DONE — shipped 2026-08-23

The app is built, signed, notarised and stapled, and packaged as
**`~/stlrepair-build/STL Repair.dmg`** (~29 MB). Verified with a simulated
download: mounts and launches with no Gatekeeper warning on any Mac.

That .dmg is the whole deliverable. Send only that file.

## Shipping an updated version

Notary credentials live in the keychain as profile `stlrepair`.

**The Swift app (current).** Three commands, and nothing to stage by hand -
`make_app.sh` already builds under `~/stlrepair-build`:

    cd swift
    bash make_app.sh
    bash sign.sh stlrepair
    cd .. && APP=~/stlrepair-build/"STL Repair.app" bash make_dmg.sh

**The Python app (legacy).** Kept until the Swift one has been in real use
for a while:

    bash build.sh
    rm -rf ~/stlrepair-build/dist
    ditto --norsrc --noextattr --noqtn dist ~/stlrepair-build/dist
    cp entitlements.plist sign_and_notarize.sh make_dmg.sh "Read Me.txt" ~/stlrepair-build/
    cd ~/stlrepair-build && xattr -cr "dist/STL Repair.app"
    bash sign_and_notarize.sh stlrepair
    bash make_dmg.sh stlrepair

Steps 1-6 further down remain accurate as reference for a fresh machine,
except that the Swift app needs no entitlements and has no nested binaries.

## Two things that bit us on the Studio

- **Never build inside iCloud Drive.** iCloud adds extended attributes and
  `codesign` fails with *"resource fork, Finder information, or similar
  detritus not allowed"*. Build under `~/` instead. If it happens anyway:
  `ditto --norsrc --noextattr --noqtn dist ~/somewhere/dist` then `xattr -cr`.
- **Never let PyInstaller use miniconda's Python** (it's first on David's
  PATH). It produces bundles that fail to launch. `build.sh` now skips any
  conda prefix automatically and prefers `/opt/homebrew/bin/python3.14`.

## Where the source lives

In this git repo. The old working folder,
`iCloud Drive/3D Printing/STL Repair Tool/`, was a stale copy of what is
here and has been deleted — everything in it was already committed at an
equal or older state. Do not build inside iCloud Drive (see below).

---

## Step 1 — Developer ID certificate

Skip to Step 2 if `security find-identity -v -p codesigning` already lists a
**Developer ID Application** entry.

Two routes:

**A. Already have the identity on the laptop** — export it there
(Keychain Access → My Certificates → right-click the *Developer ID
Application* entry → Export → `.p12`, set a password), copy the `.p12` over,
double-click to import. Same identity on both machines, no extra certificate
slot used.

**B. Create it fresh here:**

1. **Keychain Access** → menu *Certificate Assistant* → *Request a Certificate
   From a Certificate Authority*. Enter your email and name, choose **Saved to
   disk**, save the `.certSigningRequest`.
2. Go to <https://developer.apple.com/account/resources/certificates/add>,
   choose **Developer ID Application**, upload the request, download the `.cer`.
3. Double-click the `.cer` to install it into the login keychain.

It must be **Developer ID Application** — not "Apple Development" or "Mac App
Distribution". Those are for other distribution channels and won't work for an
app handed out directly. Only the team's Account Holder can create this type,
and Apple caps how many a team may hold, so prefer route A if the identity
already exists.

Confirm:

```bash
security find-identity -v -p codesigning
```

You want a line containing `Developer ID Application: ... (TEAMID)`.

## Step 2 — Notary credentials

Create an app-specific password at <https://account.apple.com> → *Sign-In and
Security* → *App-Specific Passwords*. Then store it once:

```bash
xcrun notarytool store-credentials stlrepair --apple-id YOU@EMAIL.com --team-id YOURTEAMID --password xxxx-xxxx-xxxx-xxxx
```

Team ID is the 10-character code at the top right of the developer portal, and
also in brackets at the end of the identity line from Step 1. The password is
stored in this Mac's keychain; nothing else needs it again.

## Step 3 — Build

```bash
bash build.sh
```

Run it from the root of this repo.

Creates a virtualenv, installs numpy / scipy / networkx / trimesh / pymeshfix,
and produces `dist/STL Repair.app` (~71 MB). Takes a few minutes. Needs
`python3` — any 3.10–3.14; install from <https://www.python.org/downloads/macos/>
if missing.

## Step 4 — Sign, notarise, staple

```bash
bash sign_and_notarize.sh stlrepair
```

Signs inside-out (156 nested `.so`/`.dylib` files → embedded Python framework →
bundle), uploads to Apple, waits for the ticket, staples it, and runs a final
Gatekeeper check. Expect a few minutes at "uploading to Apple".

Success looks like `status: Accepted`, then
`The staple and validate action worked!`, then from `spctl`:
`source=Notarized Developer ID`.

## Step 5 — Verify properly

```bash
spctl -a -vvv -t exec "dist/STL Repair.app"
xcrun stapler validate "dist/STL Repair.app"
open "dist/STL Repair.app"
```

The `open` should launch it with **no warning dialog at all** and pop a browser
page. Drop an STL on it to confirm the repair still works after signing.

Quit it when done (⌘Q) — it keeps running otherwise.

## Step 6 — Package for the recipient

```bash
mkdir -p handoff && cp -R "dist/STL Repair.app" handoff/
mkdir -p handoff/source && cp stlrepair.py stlrepair_app.py build.sh sign_and_notarize.sh entitlements.plist icon.png handoff/source/
cp "README-for-recipient-SIGNED.md" "handoff/README - Start Here.md"
ditto -c -k --sequesterRsrc --keepParent handoff "STL Repair Handoff.zip"
```

Use `README-for-recipient-SIGNED.md` — it's the version with the "first launch
will be blocked" section removed, which is now wrong. Also copy `BUILD.md` from
the laptop's handoff folder into `handoff/` if you want the rebuild notes to
travel too.

Send them the zip. They drag the app to Applications and double-click.

---

## Troubleshooting

**Notarisation rejected.** Get the detail — the summary alone won't say why:

```bash
xcrun notarytool log <SUBMISSION-ID> --keychain-profile stlrepair
```

Nearly always an unsigned nested binary. Re-run `sign_and_notarize.sh`; it
signs inside-out, which is the usual fix.

**Notarised fine but the app won't launch on another Mac.** The entitlements
were dropped. CPython needs `allow-unsigned-executable-memory` and
`disable-library-validation` under the hardened runtime — without them the app
notarises successfully and then dies silently on launch. Check they're present:

```bash
codesign -dv --entitlements - "dist/STL Repair.app"
```

**"resource fork, Finder information, or similar detritus not allowed."**
Extended attributes crept in:

```bash
xattr -cr "dist/STL Repair.app" && bash sign_and_notarize.sh stlrepair
```

**Recipient on an Intel Mac.** This bundle is arm64-only — Mac Studio and the
laptop are both Apple Silicon, so neither can produce an Intel build. They must
run `build.sh` on their own Intel Mac.

---

## If you end up editing the code

Two traps, both found the hard way. They fail **silently**, producing a file
that looks repaired but isn't:

- **`trimesh.Trimesh.split()` quietly fills holes as a side effect.** It turned
  a 10-face open cube into a 12-face "watertight" one by chording across a
  corner, shaving 16.7% off the volume — before the real repair stage ran.
  `split_components()` in `stlrepair.py` therefore walks face adjacency and
  rebuilds submeshes by hand. Do not replace it with `mesh.split()`.
- **`pymeshfix` 0.18 returns `.points` / `.faces`**, not the `.v` / `.f` in
  older docs. The old names still exist but are `None`.

Also keep the two integrity guards in the report — the **volume change**
warning and the **triangles added** note. Closing a hole invents geometry, and
those are what stop a silently-wrong repair from passing as a good one.

Test with `python stlrepair.py somefile.stl --check` before rebuilding the app.
