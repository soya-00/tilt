#!/usr/bin/env bash
# Build Tilt and install it, on the Mac you intend to run it on.
#
#   ./scripts/install.sh              build, then copy to /Applications
#   ./scripts/install.sh --build-only build and stop, leaving the bundle in target/
#
# This is the whole path from a checkout to an application in the Dock. It does
# what the README used to describe in five steps, in the order that works, and
# it stops with an actionable sentence rather than a compiler error when a tool
# is missing.
#
# It builds *unsigned*. There is no Apple Developer membership behind this, so
# the app is not notarised and macOS will not vouch for it to anyone. Building on
# the machine you run it on is what makes that a non-event: nothing is
# downloaded, so nothing is quarantined, and Gatekeeper never gets a say. Moving
# the .dmg to another machine is the case that needs an attribute cleared by
# hand — see docs/install.md.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/core"
DESKTOP="$ROOT/apps/desktop"
BUNDLE="$DESKTOP/src-tauri/target/release/bundle"
APPS="/Applications"
NAME="Tilt.app"

BUILD_ONLY=0
[ "${1:-}" = "--build-only" ] && BUILD_ONLY=1

say() { printf '\n→ %s\n' "$1"; }
die() {
  printf '\n%s\n' "$1" >&2
  exit 1
}

# ------------------------------------------------------------------- preflight
#
# Every check below failed for somebody at least once. The messages name the fix
# rather than the symptom, because the symptom always arrives several minutes
# into a build that has already started.

[ "$(uname -s)" = "Darwin" ] || die "This builds a Mac app, and it has to run on the Mac.
Apple's linker and bundling tools have no equivalent elsewhere — there is no
cross-compile. To run Tilt on this machine instead, see 'Running it' in
docs/install.md, or use the container."

xcode-select -p >/dev/null 2>&1 || die "Xcode command line tools are missing.
  xcode-select --install"

command -v cargo >/dev/null 2>&1 || die "Rust is missing. The shell is a Rust program.
  https://rustup.rs"

command -v node >/dev/null 2>&1 || die "Node is missing. Install Node 22 or newer."

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
# 22, not 20: package.json pins pnpm 11, which does not run on Node 20. CI found
# that out on a commit that passed on somebody's laptop.
[ "$NODE_MAJOR" -ge 22 ] || die "Node $NODE_MAJOR is too old — the pinned pnpm needs Node 22 or newer."

# How to run pnpm, resolved once and checked here rather than discovered
# halfway through the build.
#
# This used to be `corepack enable || true` followed by a bare `pnpm`, which is
# two mistakes in one line: `corepack enable` writes shims into the directory
# holding the `node` binary and fails when that is not writable or not on PATH,
# and `|| true` then threw away the only evidence of it. The next line died with
# `pnpm: command not found`, naming the symptom and hiding the cause.
#
# `corepack pnpm` needs no shims and no write access. It reads the
# `packageManager` field in package.json and fetches exactly that pnpm, which is
# the version CI uses, so it is the more correct answer as well as the more
# reliable one.
if command -v pnpm >/dev/null 2>&1; then
  PNPM=(pnpm)
elif command -v corepack >/dev/null 2>&1; then
  PNPM=(corepack pnpm)
  # Corepack asks before its first download. Nothing here is interactive.
  export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
else
  die "Neither pnpm nor corepack is available, and the lockfile is pnpm's.
Corepack ships with Node and is the shortest route:
  corepack enable
Or install pnpm directly:
  npm install -g pnpm@11"
fi

command -v python3 >/dev/null 2>&1 || die "Python 3.11 or newer is missing."

python3 - <<'PY' || die "Python 3.11 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

# ----------------------------------------------------------------------- build

say "preparing the Python core"
if [ ! -x "$CORE/.venv/bin/python" ]; then
  python3 -m venv "$CORE/.venv"
fi
"$CORE/.venv/bin/python" -m pip install --quiet --upgrade pip
# The `package` extra is PyInstaller and what it needs. Without it the sidecar
# step fails halfway through a build that has already compiled the Rust.
"$CORE/.venv/bin/python" -m pip install --quiet -e "$CORE[package]"

say "preparing the interface"
cd "$DESKTOP"
# --ignore-scripts matches CI and the image. pnpm 10+ exits non-zero when it
# skips a dependency's install script, so this is not only a hardening choice.
"${PNPM[@]}" install --frozen-lockfile --ignore-scripts

say "building the app — this takes a while the first time"
# beforeBuildCommand freezes the Python core into the bundle, so there is no
# separate step to forget. Forgetting it used to produce an app that looked new
# and reported the previous version in Settings.
"${PNPM[@]}" tauri build

APP="$BUNDLE/macos/$NAME"
[ -d "$APP" ] || die "The build finished but produced no $NAME.
Looked in: $BUNDLE/macos"

say "checking the bundle carries its own service"
# The one failure this catches is the expensive one: an app that launches, shows
# a window, and cannot reach a journal because the sidecar never made it in.
[ -x "$APP/Contents/Resources/tilt-core/tilt-core" ] ||
  die "The bundle has no frozen core inside it. Run scripts/build-sidecar.sh on its own to see why."

if [ "$BUILD_ONLY" = "1" ]; then
  say "built, not installed"
  echo "$APP"
  find "$BUNDLE/dmg" -name '*.dmg' 2>/dev/null | head -1
  exit 0
fi

# --------------------------------------------------------------------- install

if [ -d "$APPS/$NAME" ]; then
  say "closing the copy that is already installed"
  # It holds the journal open, and replacing the bundle underneath a running app
  # is how you get a version that reports one number and behaves like another.
  osascript -e 'quit app "Tilt"' >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -x Tilt >/dev/null 2>&1 || break
    sleep 1
  done
  pgrep -x Tilt >/dev/null 2>&1 && die "Tilt is still running. Quit it and run this again."
  rm -rf "${APPS:?}/$NAME"
fi

say "installing to $APPS"
cp -R "$APP" "$APPS/$NAME"

# Nothing was downloaded, so there should be no quarantine attribute at all.
# Clearing it is a no-op in the ordinary case and the fix in the one where the
# bundle passed through something that sets it.
xattr -dr com.apple.quarantine "$APPS/$NAME" 2>/dev/null || true

say "installed"
echo "$APPS/$NAME"
if ! codesign -v "$APPS/$NAME" >/dev/null 2>&1; then
  echo
  echo "Note: the bundle has no valid signature, which is expected — this build is"
  echo "unsigned. It runs here because you built it here. Copying it to another"
  echo "machine needs the quarantine attribute cleared by hand; see docs/install.md."
fi
echo
echo "Open it from Spotlight or the Applications folder. Your journal lives in"
echo "~/Tilt by default, and Settings says where."
