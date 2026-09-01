#!/usr/bin/env bash
# Assembles "STL Repair.app" from the SPM build.
#
# Built by hand rather than by Xcode because this machine has Command Line
# Tools only. The bundle is written under $HOME, never inside iCloud Drive:
# iCloud adds extended attributes that make codesign refuse the bundle.
source "$(dirname "${BASH_SOURCE[0]}")/scripts.sh"

APP_NAME="STL Repair"
STAGE="${STLREPAIR_STAGE:-$HOME/stlrepair-build}"
APP="$STAGE/$APP_NAME.app"
REPO="$(cd "$HERE/.." && pwd)"

swift build "${SWIFT_COMMON[@]}" -c release --product STLRepairApp

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$SCRATCH/release/STLRepairApp" "$APP/Contents/MacOS/$APP_NAME"

# Icon: build an .icns from the repo's icon.png if one isn't cached already.
if [ -f "$REPO/icon.png" ]; then
    ICONSET="$STAGE/AppIcon.iconset"
    rm -rf "$ICONSET"; mkdir -p "$ICONSET"
    for size in 16 32 128 256 512; do
        sips -z $size $size "$REPO/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1
        sips -z $((size*2)) $((size*2)) "$REPO/icon.png" \
             --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1
    done
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null
    rm -rf "$ICONSET"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleExecutable</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>com.agentbaltic.stlrepair</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>2.0</string>
    <key>CFBundleVersion</key><string>2.0</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSHumanReadableCopyright</key>
    <string>GPLv3. Repair engine: MeshFix (c) IMATI-GE / CNR.</string>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key><string>STL Mesh</string>
            <key>CFBundleTypeRole</key><string>Viewer</string>
            <key>LSItemContentTypes</key><array><string>public.standard-tesselated-geometry-format</string></array>
            <key>LSHandlerRank</key><string>Alternate</string>
        </dict>
    </array>
</dict>
</plist>
PLIST

# iCloud/Finder xattrs are what break codesign later; strip them now.
xattr -cr "$APP" 2>/dev/null || true

echo "built: $APP"
du -sh "$APP" | sed 's/^/size:  /'
