"""Keeping a credential out of anything the browser will see.

Provider errors are relayed to the client — `ingest.py` and `diagram.py` both
turn an :class:`~tilt.agents.base.AgentError` into a 502 whose body is the
exception's own text. That is the right behaviour: "your key is not valid" is
worth reading, and a generic "something went wrong" is not.

It is also the one place a key could plausibly surface, because an SDK's
exception may carry the request that produced it. Under bring-your-own-key that
credential is somebody else's, which makes this worth a file of its own rather
than an inline regex.
"""

from __future__ import annotations

import re

PLACEHOLDER = "[redacted]"

_PATTERNS = (
    # Google API keys are a fixed, recognisable shape.
    (re.compile(r"AIza[0-9A-Za-z_\-]{10,}"), PLACEHOLDER),
    # Anything passed as a query parameter, whatever the SDK calls it.
    (re.compile(r"(?i)\b(key|api_key|apikey|access_token|token)=[^&\s\"']+"), PLACEHOLDER),
    # The same names as a JSON field, which is how an SDK that echoes back the
    # request body it sent will spell them. The query-parameter pattern above
    # requires an `=` and so matches none of these.
    #
    # The field name is kept and only the value replaced: "which credential was
    # rejected" is the diagnostic this whole file exists to preserve.
    (
        re.compile(
            r"(?i)([\"'](?:key|api_key|apikey|access_token|token)[\"']\s*:\s*)[\"'][^\"']*[\"']"
        ),
        rf'\1"{PLACEHOLDER}"',
    ),
    # A bearer token in a header echoed back inside an error.
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"), PLACEHOLDER),
)


def redact(text: str) -> str:
    """Every credential-shaped run replaced, the rest left alone.

    Deliberately a denylist of shapes rather than an attempt to prove the string
    is clean. A denylist is the weaker guarantee, and the honest reason to
    accept it here is that the alternative — refusing to relay upstream errors
    at all — costs the user the only diagnostic they get when their own key is
    rejected.
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
