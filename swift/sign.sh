#!/usr/bin/env bash
# Sign, notarise and staple the native "STL Repair.app".
#
#   bash sign.sh              # sign only
#   bash sign.sh stlrepair    # sign + notarise + staple
#
# This is much simpler than the Python app's sign_and_notarize.sh, and
# deliberately so:
#
#  * There is one Mach-O binary, not 156 nested .so/.dylib files, so there is
#    no inside-out signing pass.
#  * No entitlements. The Python bundle needed
#    com.apple.security.cs.allow-unsigned-executable-memory and
#    disable-library-validation purely because CPython writes executable memory
#    at runtime. Swift does not, so the hardened runtime is applied with no
#    exceptions at all. Do not reintroduce them.
set -euo pipefail

APP="${APP:-$HOME/stlrepair-build/STL Repair.app}"
PROFILE="${1:-}"

[ -d "$APP" ] || { echo "Not found: $APP   (run make_app.sh first)"; exit 1; }

case "$APP" in
  *"Mobile Documents"*)
    echo "Refusing to sign inside iCloud Drive: its extended attributes make"
    echo "codesign fail with 'resource fork, Finder information, or similar"
    echo "detritus not allowed'. Stage the bundle under \$HOME instead."
    exit 1;;
esac

ID="${IDENTITY:-}"
if [ -z "$ID" ]; then
  ID=$(security find-identity -v -p codesigning \
       | grep "Developer ID Application" | head -1 | sed 's/.*"\(.*\)"/\1/' || true)
fi
[ -n "$ID" ] || { echo "No 'Developer ID Application' certificate in the keychain."; exit 1; }
echo "==> signing as: $ID"

# iCloud and Finder leave xattrs that codesign rejects outright.
xattr -cr "$APP"

codesign --force --timestamp --options runtime --sign "$ID" "$APP"

echo "==> verifying signature"
codesign --verify --strict --deep --verbose=2 "$APP"

if [ -z "$PROFILE" ]; then
  echo
  echo "Signed but not notarised - other Macs will still warn."
  echo "Finish with:  bash $0 PROFILE"
  exit 0
fi

echo "==> uploading to Apple (usually a few minutes)"
ZIP="${TMPDIR:-/tmp}/stlrepair-notarize.zip"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
rm -f "$ZIP"

echo "==> stapling the ticket"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "==> Gatekeeper check"
spctl -a -vvv -t exec "$APP"

echo
echo "Done. Opens on any Mac with no warning."
