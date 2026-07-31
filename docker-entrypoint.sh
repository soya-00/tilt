#!/bin/sh
# Start one visitor's Tilt.
#
# Two jobs before uvicorn: make sure there is a token, and hand it to the page.

set -eu

# A container with no token would be refused by check_exposure, which is the
# right behaviour and a poor first impression. Mint one instead — it is per
# container, so it is exactly as long-lived as the journal it protects.
if [ -z "${TILT_AUTH_TOKEN:-}" ]; then
  TILT_AUTH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  export TILT_AUTH_TOKEN
fi

# The desktop shell injects `window.__TILT__`; a browser has no shell, so the
# same shape is stamped into the page here. Reusing the existing ShellBridge
# contract rather than inventing a second way in.
#
# The token ends up readable by anyone who can load the page. That is not a
# leak, it is the consequence of serving the page and the API from one process:
# a browser cannot attach an Authorization header to a document request. The
# perimeter in this topology is whatever authenticates the visitor in front of
# this container. See SECURITY.md.
INDEX="${TILT_STATIC_DIR:-/app/static}/index.html"
if [ -f "$INDEX" ] && ! grep -q "__TILT__" "$INDEX"; then
  BRIDGE="<script>window.__TILT__={baseUrl:location.origin,token:\"${TILT_AUTH_TOKEN}\"};</script>"
  # Before any module script runs, so the api client sees it on first import.
  sed -i "s|<head>|<head>${BRIDGE}|" "$INDEX"
fi

exec python -m uvicorn tilt.api.app:app \
  --host "${TILT_HOST:-0.0.0.0}" \
  --port "${TILT_PORT:-8765}" \
  --no-server-header
