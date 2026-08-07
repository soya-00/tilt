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
from tilt.api.limits import check_exposure
from tilt.config import Settings, get_settings

log = logging.getLogger(__name__)

READY_PREFIX = "TILT_READY "
"""What the shell greps stdout for. Everything after it is one line of JSON."""


def hold_journal(settings: Settings):
    """Take an exclusive claim on this journal, or refuse to start.

    Two Tilts on one directory is not a hypothetical: the installed app hides
    rather than quits when its window closes, and ``npm run tauri dev`` reads the
    same ``~/Tilt`` by default, so the ordinary way to try a change runs a second
    copy over the first. SQLite arbitrates its own writers, so the damage is not
    a corrupt database — it is two schedulers doing the same unattended work
    twice, and an entry's frontmatter being read-modify-written by both, where
    one of the two writes is simply lost.

    An advisory ``flock`` rather than a pid file, because the kernel drops it
    when the holder dies however it dies. A crashed Tilt leaves nothing to clean
    up and nothing to explain.

    Lives here rather than in ``create_app`` on purpose: the test suite builds
    hundreds of apps against temporary directories, and a lock taken there would
    be a lock the suite takes against itself.

    Returns the open file object, which the caller must keep — closing it
    releases the claim. ``None`` where the platform has no ``fcntl``, which is
    Windows; there the risk stands, and saying so is better than a lock that
    silently is not one.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - POSIX in every supported build
        log.warning("no fcntl on this platform; not claiming %s", settings.data_dir)
        return None

    settings.internal_dir.mkdir(parents=True, exist_ok=True)
    handle = (settings.internal_dir / "tilt.lock").open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit(
            f"Another Tilt is already using {settings.data_dir}.\n"
            "Two copies sharing one journal overwrite each other's edits, so "
            "this one is stopping.\n"
            "Quit the running Tilt — closing its window only hides it — and "
            "start this again."
        ) from None
    return handle


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

    # Held for the life of the process: the claim ends when this file object is
    # collected, so it has to outlive everything below it.
    claim = hold_journal(settings)  # noqa: F841 - the handle is the lock

    sock = _bind(settings.host, settings.port)
    # The address the socket actually got, not the one that was asked for. The
    # check at app construction reads configuration, which is the same thing
    # only as long as nobody passes a host on the command line — and the
    # container's uvicorn does exactly that.
    check_exposure(sock.getsockname()[0], settings.auth_token)
    announce(settings.host, sock.getsockname()[1])

    app = create_app(settings)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            # Logs go to stderr so stdout stays a clean channel for the ready
            # line — the shell parses one and shows the other.
            log_config=None,
            access_log=False,
        )
    )
    # Handed to the app so `POST /erase` can stop the process it has just
    # removed the files from. Only the thing that owns the server can take it
    # down, and under a test client there is no server here at all — which is
    # what makes that route inert in tests without anyone stubbing it.
    app.state.server = server
    if settings.exit_with_parent:
        watch_parent(server)
    server.run(sockets=[sock])


if __name__ == "__main__":  # pragma: no cover - exercised by the shell
    main()
