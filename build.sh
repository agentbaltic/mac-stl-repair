#!/bin/bash
# Builds "STL Repair.app" from source. Run:  bash build.sh
set -euo pipefail
cd "$(dirname "$0")"

# Anaconda/miniconda Python builds broken .app bundles with PyInstaller, so
# prefer Homebrew or python.org and skip anything under a conda prefix.
# Override explicitly with:  PY=/path/to/python3 bash build.sh
PY="${PY:-}"
if [ -z "$PY" ]; then
  for c in /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 \
           /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 \
           /usr/local/bin/python3.13 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
           python3.14 python3.13 python3.12 python3; do
    found="$(command -v "$c" 2>/dev/null || true)"
    [ -z "$found" ] && continue
    case "$found" in *conda*|*Anaconda*) continue;; esac
    PY="$found"; break
  done
fi
[ -z "$PY" ] && { echo "No suitable python3 found. Install one:  brew install python@3.13"; exit 1; }
case "$PY" in
  *conda*|*Anaconda*) echo "WARNING: $PY is a conda Python; the bundle may not launch."; ;;
esac
echo "Using $PY  ($($PY -V))"

echo "==> creating virtual environment"
rm -rf .venv && "$PY" -m venv .venv

echo "==> installing dependencies"
./.venv/bin/pip -q install --upgrade pip
./.venv/bin/pip -q install numpy scipy networkx trimesh pymeshfix pyinstaller

echo "==> generating icon"
if [ -f icon.png ]; then
  rm -rf icon.iconset && mkdir -p icon.iconset
  for s in 16 32 64 128 256 512; do
    sips -z $s $s icon.png --out icon.iconset/icon_${s}x${s}.png >/dev/null 2>&1
    sips -z $((s*2)) $((s*2)) icon.png --out icon.iconset/icon_${s}x${s}@2x.png >/dev/null 2>&1
  done
  cp icon.png icon.iconset/icon_512x512@2x.png
  iconutil -c icns icon.iconset -o icon.icns || true
fi
ICON=""; [ -f icon.icns ] && ICON="--icon icon.icns"

echo "==> building the app (a few minutes)"
rm -rf build dist "STL Repair.spec"
# shellcheck disable=SC2086
./.venv/bin/pyinstaller \
  --name "STL Repair" --windowed --onedir --noconfirm --clean \
  --osx-bundle-identifier com.stlrepair.app $ICON \
  --hidden-import stlrepair --collect-submodules pymeshfix \
  --exclude-module matplotlib --exclude-module tkinter --exclude-module PIL \
  --exclude-module IPython --exclude-module pytest --exclude-module pyvista \
  --exclude-module PyInstaller \
  stlrepair_app.py

echo
echo "Done -> dist/STL Repair.app"
echo "Drag it to your Applications folder."
