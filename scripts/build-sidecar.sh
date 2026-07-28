#!/usr/bin/env bash
# Package the Python core into the desktop bundle.
#
# Output is PyInstaller's `--onedir` layout — an executable beside a folder of
# native libraries — copied to apps/desktop/src-tauri/binaries/tilt-core/, which
# tauri.conf.json declares as a bundle resource.
#
# Deliberately not `--onefile`: that variant unpacks the whole bundle to a
# temporary directory on every launch, and the plan's cold-start budget is three
# seconds. It is also not an `externalBin`, because those are single files and
# this is a directory.
#
#   ./scripts/build-sidecar.sh
#
# Run it before `npm run tauri build`. Development builds do not need it: the
# shell runs core/ directly from the checkout.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/core"
DEST="$ROOT/apps/desktop/src-tauri/binaries/tilt-core"
PY="${PYTHON:-$CORE/.venv/bin/python}"

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY." >&2
  echo "Create one:  cd core && python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev,package]'" >&2
  exit 1
fi

echo "→ ensuring PyInstaller is available"
"$PY" -m pip install --quiet --upgrade 'pyinstaller>=6.11'

echo "→ packaging the core"
rm -rf "$CORE/build" "$CORE/dist/tilt-core"
"$PY" -m PyInstaller --clean --noconfirm \
  --distpath "$CORE/dist" --workpath "$CORE/build" "$ROOT/scripts/tilt-core.spec"

echo "→ installing into the bundle"
# Keep the README: the directory is tracked precisely so the bundler has a
# resource path to point at even before anyone has run this script.
find "$DEST" -mindepth 1 ! -name README.md -delete
cp -R "$CORE/dist/tilt-core/." "$DEST/"

echo "→ verifying it starts and reports a port"
if ! timeout 60 "$DEST/tilt-core" --self-check; then
  echo "The packaged core did not come up. The bundle is incomplete." >&2
  exit 1
fi

echo "done: $DEST"
du -sh "$DEST"
