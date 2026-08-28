#!/bin/bash
# Builds "STL Repair.dmg" - the single file you hand to someone.
#
#   bash make_dmg.sh
#
# Run this AFTER signing (and notarising, if Apple is cooperating), so the
# app inside the disk image is the finished one.

set -euo pipefail
cd "$(dirname "$0")"

APP="${APP:-dist/STL Repair.app}"
VOL="STL Repair"
DMG="STL Repair.dmg"

[ -d "$APP" ] || { echo "Not found: $APP"; echo "Set APP=/path/to/STL Repair.app or run build.sh first."; exit 1; }

echo "==> staging"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE" rw.dmg' EXIT

# --noextattr keeps iCloud/Finder metadata out of the image
ditto --norsrc --noextattr --noqtn "$APP" "$STAGE/STL Repair.app"
ln -s /Applications "$STAGE/Applications"
[ -f "Read Me.txt" ] && cp "Read Me.txt" "$STAGE/"

echo "==> creating disk image"
rm -f "$DMG" rw.dmg
hdiutil create -srcfolder "$STAGE" -volname "$VOL" \
  -fs HFS+ -format UDRW -ov -quiet rw.dmg

# Lay the window out so the app sits next to the Applications shortcut.
# Purely cosmetic - if Finder automation is blocked, carry on regardless.
echo "==> arranging window"
MNT="$(hdiutil attach rw.dmg -readwrite -noverify -nobrowse | \
       awk '/\/Volumes\//{ $1=$2=""; sub(/^ +/,""); print; exit }')"
if [ -n "${MNT:-}" ]; then
  osascript <<OSA >/dev/null 2>&1 || echo "    (skipped - Finder automation not permitted)"
tell application "Finder"
  tell disk "$VOL"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 150, 780, 520}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to 112
    set position of item "STL Repair.app" of container window to {150, 170}
    set position of item "Applications" of container window to {430, 170}
    try
      set position of item "Read Me.txt" of container window to {290, 310}
    end try
    close
    open
    update without registering applications
    delay 1
  end tell
end tell
OSA
  sync
  hdiutil detach "$MNT" -quiet || hdiutil detach "$MNT" -force -quiet
fi

echo "==> compressing"
hdiutil convert rw.dmg -format UDZO -imagekey zlib-level=9 -o "$DMG" -quiet

# Notarise the disk image itself. The app inside is already stapled, but the
# .dmg is what actually gets downloaded, so Gatekeeper checks it first.
PROFILE="${1:-}"
if [ -n "$PROFILE" ]; then
  echo "==> notarising the disk image"
  xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  # A .dmg container is never itself code-signed - only the .app inside is -
  # so a "primary-signature" Gatekeeper check on the .dmg always reports
  # rejected. That is expected and does not affect the notarised app inside;
  # print it only as a labelled note so it cannot be mistaken for a failure.
  echo "(the line below is expected and can be ignored - the .dmg container has no signature of its own, only the .app inside does):"
  spctl -a -vvv -t open --context context:primary-signature "$DMG" || true
fi

echo
echo "Done -> $DMG  ($(du -h "$DMG" | cut -f1))"
echo "This single file is what you send. Nothing else."
[ -z "$PROFILE" ] && echo "(Not notarised. Re-run as: bash make_dmg.sh stlrepair)"
