#!/bin/bash
# Sign, notarise and staple "STL Repair.app" so it opens with no warning.
#
#   bash sign_and_notarize.sh              # sign only
#   bash sign_and_notarize.sh myprofile    # sign + notarise + staple
#
# The notary profile is created once, by you, with:
#   xcrun notarytool store-credentials myprofile \
#       --apple-id you@example.com --team-id TEAMID --password APP_SPECIFIC_PASSWORD
# (create the app-specific password at https://account.apple.com -> Sign-In and Security)

set -euo pipefail
cd "$(dirname "$0")"

APP="${APP:-dist/STL Repair.app}"
PROFILE="${1:-}"
ENT="entitlements.plist"

[ -d "$APP" ] || { echo "Not found: $APP  (run build.sh first)"; exit 1; }
[ -f "$ENT" ] || { echo "Missing $ENT"; exit 1; }

# ---- find the Developer ID Application certificate -------------------------
ID="${IDENTITY:-}"
if [ -z "$ID" ]; then
  ID=$(security find-identity -v -p codesigning \
       | grep "Developer ID Application" | head -1 | sed 's/.*"\(.*\)"/\1/' || true)
fi
if [ -z "$ID" ]; then
  cat <<'MSG'
No "Developer ID Application" certificate found in your keychain.

Create one (about 5 minutes):
  1. Keychain Access -> menu Keychain Access -> Certificate Assistant ->
     "Request a Certificate From a Certificate Authority..."
     Enter your email + name, choose "Saved to disk", save the .certSigningRequest.
  2. https://developer.apple.com/account/resources/certificates/add
     Pick "Developer ID Application", upload the request, download the .cer.
  3. Double-click the .cer to install it into your login keychain.
  4. Re-run this script.

Note: only the team's Account Holder can create a Developer ID certificate.
MSG
  exit 1
fi
echo "==> signing as: $ID"

# ---- sign inside-out -------------------------------------------------------
# Nested code must be signed before the bundle that contains it.
echo "==> signing nested libraries"
find "$APP" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 \
  | xargs -0 -n 16 codesign --force --timestamp --options runtime --sign "$ID"

echo "==> signing embedded frameworks"
for ver in "$APP"/Contents/Frameworks/Python.framework/Versions/*/; do
  case "$ver" in *Current/) continue;; esac
  if [ -d "$ver" ]; then
    codesign --force --timestamp --options runtime --sign "$ID" "$ver"
  fi
done
for f in "$APP"/Contents/Frameworks/*; do
  if [ -f "$f" ] && file "$f" | grep -q "Mach-O"; then
    codesign --force --timestamp --options runtime --sign "$ID" "$f"
  fi
done

echo "==> signing the app bundle"
codesign --force --timestamp --options runtime \
         --entitlements "$ENT" --sign "$ID" "$APP"

echo "==> verifying"
codesign --verify --strict --verbose=2 "$APP"

if [ -z "$PROFILE" ]; then
  echo
  echo "Signed. Not notarised yet - macOS will still warn on other Macs."
  echo "Re-run with your notary profile name to finish:  bash $0 PROFILE"
  exit 0
fi

# ---- notarise --------------------------------------------------------------
echo "==> uploading to Apple for notarisation (a few minutes)"
rm -f notarize.zip
ditto -c -k --sequesterRsrc --keepParent "$APP" notarize.zip
xcrun notarytool submit notarize.zip --keychain-profile "$PROFILE" --wait
rm -f notarize.zip

echo "==> stapling the ticket"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "==> final Gatekeeper check"
spctl -a -vvv -t exec "$APP" || true

echo
echo "Done. This app now opens on any Mac with no warning."
