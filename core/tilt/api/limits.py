"""Bounds on what a request may be, and on where the service may listen.

Two unrelated-looking guards live together because they answer the same
question: what stops this from being abused by whoever can reach it. On a
laptop that is nobody. The moment it is served anywhere else, it is everybody.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

MAX_REQUEST_BYTES = 4_000_000
"""Comfortably past the 2MB a source may be, short of a memory problem.

Bigger than :data:`tilt.api.routes.ingest.MAX_BYTES` on purpose: that limit is
about what is worth distilling and answers with an explanation, while this one
is about what the process will hold in memory and answers with a number."""


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Refuse an oversized request before it is read into memory.

    A declared ``Content-Length`` is the cheap case and the common one. A
    chunked request declares no length and slips past this — which is why the
    models carry their own ``max_length`` and this is the early exit rather than
    the only defence. Saying so here because a limit that looks total and is not
    is worse than one whose edges are written down.
    """

    def __init__(self, app, limit: int = MAX_REQUEST_BYTES) -> None:
        super().__init__(app)
        self.limit = limit

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.limit:
            # Literal 413: the starlette constant is mid deprecation rename.
            return JSONResponse(
                {"detail": f"That request is larger than {self.limit // 1_000_000}MB."},
                status_code=413,
            )
        return await call_next(request)


def is_loopback(host: str) -> bool:
    """Whether binding here means "this machine only".

    ``localhost`` is included by name because it is what people type, and it
    resolves to a loopback address on every system this runs on.
    """
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname that is not an address literal. Not provably loopback, so
        # treat it as exposed — the failure mode of guessing wrong in the other
        # direction is an open journal.
        return False


def check_exposure(host: str, auth_token: str | None) -> None:
    """Refuse to start open to a network.

    Serving on a loopback address with no token is fine and is what
    ``npm run dev`` does. Serving anywhere else with no token publishes the
    journal — and the settings route, which accepts an API key — to whoever can
    route to the machine.

    Failing at startup rather than warning: a warning in a log nobody reads is
    indistinguishable from no warning at all, and this is the one mistake with
    no recovery once someone has read your journal.
    """
    if is_loopback(host) or auth_token:
        return
    raise RuntimeError(
        f"Refusing to serve on {host} without an auth token: that would publish "
        "your journal to anyone who can reach this machine. Set TILT_AUTH_TOKEN "
        "to a random secret, or bind 127.0.0.1."
    )
