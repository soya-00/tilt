"""Bearer-token gate for the local service.

The core runs as a plain HTTP server on the loopback interface. That is not, on
its own, private: any process on the machine — including a page open in a
browser — can reach ``127.0.0.1``. So when the desktop shell spawns the sidecar
it mints a random token per launch, passes it in the environment, and hands the
same value to the webview. Nothing else can read the journal.

The token is optional. Run the service by hand with no token and it stays open,
which is what makes ``npm run dev`` against a bare ``uvicorn`` still work.
"""

from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

OPEN_PATHS = frozenset({"/health"})
"""Reachable without a token. ``/health`` is how the shell learns the sidecar is
up, and it discloses nothing but the fact that a process is listening."""

INTERFACE_PREFIXES = ("/assets/",)
"""Where the built interface lives, when this process is serving it.

Open by necessity rather than by choice, and the necessity is worth stating: a
browser cannot attach an ``Authorization`` header to a document or a script tag
request, so the page cannot be behind the token — and the page is what carries
the token to the API. In that topology the token is not the perimeter; whatever
authenticates the visitor in front of this process is. What the token still
buys is that reaching the port directly, without ever loading the page, gets
you nothing. See SECURITY.md."""


def _is_interface(path: str, static_dir: Path) -> bool:
    """Whether the static mount, not the URL's spelling, owns this path.

    This used to match on filename suffix, which is a gate that trusts the
    request to describe itself: every API route ending in a caller-supplied
    segment could be given a ``.png`` and walk straight through. The exemption
    has to be decided by what is actually behind the mount, so that is what this
    asks — the same question ``StaticFiles`` will ask a moment later.

    Contained before the existence check, because the path is still attacker
    controlled and ``../`` in it would otherwise probe the filesystem.
    """
    if path == "/" or path.startswith(INTERFACE_PREFIXES):
        return True
    try:
        target = (static_dir / path.lstrip("/")).resolve()
    except (OSError, ValueError):
        return False
    if not target.is_relative_to(static_dir.resolve()):
        return False
    return target.is_file()


def _presented(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer <token>`` on everything but open paths."""

    def __init__(self, app, token: str, *, static_dir: Path | None = None) -> None:
        super().__init__(app)
        self.token = token
        # The directory rather than a flag: the exemption is a question about
        # what is on disk, so the gate needs the disk to ask it. ``None`` means
        # this process serves the API and nothing else, and the gate is total.
        self.static_dir = static_dir

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # Preflight carries no Authorization header by specification, so gating
        # it would break every cross-origin call before it was ever made. Checked
        # by the header that makes it a preflight rather than by the method
        # alone, so an ordinary OPTIONS is still gated like anything else.
        is_preflight = (
            request.method == "OPTIONS" and "access-control-request-method" in request.headers
        )
        if is_preflight or path in OPEN_PATHS:
            return await call_next(request)

        # Only when this process is also serving the page. The desktop app is
        # an API and nothing else, and there the gate stays total.
        if self.static_dir is not None and _is_interface(path, self.static_dir):
            return await call_next(request)

        if not hmac.compare_digest(_presented(request), self.token):
            return JSONResponse({"detail": "Not authorised."}, status_code=401)

        return await call_next(request)
