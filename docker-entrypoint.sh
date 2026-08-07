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
#
# Done in Python rather than with `sed`, for two reasons that both bite.
# `sed -i "s|<head>|<head>${BRIDGE}|"` interpolates the token into the
# expression, so an operator-supplied TILT_AUTH_TOKEN containing `&`, `|` or a
# backslash is either mangled or is markup injected into the page. And the
# guard that skipped the rewrite when `__TILT__` was already present meant a
# mounted or reused `static` volume kept serving a previous container's token.
# Replacing any existing bridge is both correct and idempotent.
INDEX="${TILT_STATIC_DIR:-/app/static}/index.html"
if [ -f "$INDEX" ]; then
  TILT_INDEX="$INDEX" python - <<'PY'
import json
import os
import re

path = os.environ["TILT_INDEX"]
token = os.environ["TILT_AUTH_TOKEN"]

with open(path, encoding="utf-8") as handle:
    page = handle.read()

# Any bridge from a previous container goes, whatever token it carried.
page = re.sub(r"<script>window\.__TILT__=.*?</script>", "", page, flags=re.S)

# json.dumps escapes the token for a JS string literal; the closing tag is
# split so a token containing "</script>" cannot end the block early.
bridge = (
    "<script>window.__TILT__={baseUrl:location.origin,token:"
    + json.dumps(token).replace("</", "<\\/")
    + "};</script>"
)
# Before any module script runs, so the api client sees it on first import.
page = page.replace("<head>", "<head>" + bridge, 1)

with open(path, "w", encoding="utf-8") as handle:
    handle.write(page)
PY
fi

exec python -m uvicorn tilt.api.app:app \
  --host "${TILT_HOST:-0.0.0.0}" \
  --port "${TILT_PORT:-8765}" \
  --no-server-header
