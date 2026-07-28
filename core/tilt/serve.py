"""Process entrypoint for the core service.

Run by hand this is a normal uvicorn server. Run as the desktop shell's sidecar
it does one extra thing: it binds the listening socket itself, so it can ask the
operating system for a free port and then *tell the parent which port it got*.

The alternative — the shell picking a port and hoping — loses a race whenever
something else on the machine takes it first, and the failure surfaces as a
blank window. Here the shell reads a single line from stdout and knows.
"""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn

from tilt.api.app import create_app
from tilt.config import Settings, get_settings

READY_PREFIX = "TILT_READY "
"""What the shell greps stdout for. Everything after it is one line of JSON."""


def _bind(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def announce(host: str, port: int, *, stream=sys.stdout) -> str:
    """Emit the one line the shell parses, and return it for tests."""
    line = READY_PREFIX + json.dumps({"host": host, "port": port})
    print(line, file=stream, flush=True)
    return line


def watch_parent(server: uvicorn.Server, stream=None) -> threading.Thread:
    """Shut down when the process that spawned us goes away.

    The desktop shell kills the core on quit, but only if the shell itself
    exits in an orderly way. A panic or a `kill -9` skips that, and what is left
    behind is a server still holding someone's journal open with no window
    attached to it — a worse outcome than any crash.

    The signal is stdin reaching end of file. The shell opens the pipe and never
    writes to it, so the read blocks for exactly as long as the shell lives, and
    the kernel closes it however the shell dies.
    """
    source = stream if stream is not None else sys.stdin

    def wait() -> None:
        # A torn-down pipe raises rather than returning; the conclusion is the
        # same either way, so both paths fall through to the shutdown below.
        with contextlib.suppress(OSError, ValueError):
            source.read()
        logging.info("parent process is gone, shutting down")
        server.should_exit = True

    thread = threading.Thread(target=wait, name="parent-watch", daemon=True)
    thread.start()
    return thread


def self_check() -> int:
    """Prove a packaged build can start, without touching anyone's journal.

    Freezing a Python app fails by omission — a module the analyser did not see
    is missing only at runtime, in a bundle nobody has opened yet. Building the
    application imports every one of them, so this catches it on the machine
    that did the packaging rather than on the machine that installed it.
    """
    with tempfile.TemporaryDirectory() as scratch:
        settings = Settings(data_dir=Path(scratch) / "journal", provider="echo")
        settings.ensure_dirs()
        create_app(settings)
    print("self-check ok", file=sys.stderr)
    return 0


def main(settings: Settings | None = None, argv: list[str] | None = None) -> None:
    if "--self-check" in (argv if argv is not None else sys.argv[1:]):
        raise SystemExit(self_check())

    settings = settings or get_settings()
    settings.ensure_dirs()

    # Everything diagnostic goes to stderr. A sidecar that dies silently is the
    # worst version of this failure, so make sure the reason reaches the parent.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")

    sock = _bind(settings.host, settings.port)
    announce(settings.host, sock.getsockname()[1])

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            # Logs go to stderr so stdout stays a clean channel for the ready
            # line — the shell parses one and shows the other.
            log_config=None,
            access_log=False,
        )
    )
    if settings.exit_with_parent:
        watch_parent(server)
    server.run(sockets=[sock])


if __name__ == "__main__":  # pragma: no cover - exercised by the shell
    main()
