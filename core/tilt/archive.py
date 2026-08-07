"""One file you can carry to another machine.

Your journal is already portable — it is a folder of Markdown, and copying it is
the whole of the operation. This exists because "copy this folder, and also that
one database out of a directory you have never opened, but not the key" is not
an instruction anybody should have to follow correctly.

So: the journal folder, plus the vectors because they were bought, plus a
manifest. Never the API key, and the test that greps for it is the one that has
to keep passing as the contents grow.

Written into the support directory rather than beside the journal, which was the
obvious place and the wrong one. Journals live in synced folders — macOS syncs
``~/Documents`` by default — so an archive dropped next to one uploads a second
complete copy of everything, silently, at whatever the source texts and the
vectors weigh. The support directory is never synced by design.

Import replaces; it does not merge. Two machines both written to is sync by
another name, and that was decided against. Two files claiming one entry is
already detected and reported, which is the honest handling of that case rather
than a half-built merge that guesses.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from tilt import __version__
from tilt.models import utcnow
from tilt.store.index import SCHEMA_VERSION

log = logging.getLogger(__name__)

MANIFEST = "tilt.json"
JOURNAL = "journal"
VECTORS = "support/vectors.db"


class ArchiveError(Exception):
    """Something about the archive means it should not be opened."""


def name_for(when: datetime | None = None) -> str:
    return f"tilt-{(when or utcnow()):%Y-%m-%d-%H%M}.zip"


def build(
    *, data_dir: Path, vectors: Path | None, destination: Path, entries: int = 0
) -> Path:
    """Write an archive and return where it went.

    Assembled into a temporary file and moved into place, so a run that fails
    part-way leaves nothing that looks like a complete backup. A journal with
    real source transcripts is not small enough to build in memory.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "tilt": __version__,
        "schema": SCHEMA_VERSION,
        "created": utcnow().isoformat(),
        "entries": entries,
    }

    with tempfile.NamedTemporaryFile(
        suffix=".zip", dir=destination.parent, delete=False
    ) as handle:
        staging = Path(handle.name)
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
            for path in sorted(data_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{JOURNAL}/{path.relative_to(data_dir)}")
            # Bought from a hosted model, so worth carrying even though it is
            # derived — the index is not, because it rebuilds for nothing.
            if vectors is not None and vectors.exists():
                archive.write(vectors, VECTORS)
        staging.replace(destination)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise

    log.info("wrote %s", destination)
    return destination


def manifest_of(path: Path) -> dict:
    """The manifest, or a refusal that says which part was wrong."""
    if not path.exists():
        raise ArchiveError(f"No file at {path}.")
    try:
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ArchiveError(
            f"{path.name} is not a Tilt archive — no {MANIFEST} inside it."
        ) from exc


def check(path: Path) -> dict:
    """Whether this archive can be opened by *this* build.

    A newer schema is refused rather than half-loaded. The index is rebuilt from
    Markdown either way, so most of it would appear to work — and the parts that
    silently did not would be whichever fields this version has never heard of.
    """
    manifest = manifest_of(path)
    schema = manifest.get("schema")
    if isinstance(schema, int) and schema > SCHEMA_VERSION:
        raise ArchiveError(
            f"That archive was written by a newer Tilt (format {schema}; this one "
            f"reads {SCHEMA_VERSION}). Update Tilt and try again — importing it "
            "now would quietly drop whatever this version does not understand."
        )
    return manifest


MAX_MEMBERS = 100_000
"""How many files an archive may carry.

Not a guess at a real journal's size — it is orders of magnitude above one — but
a bound on what a hostile zip can make this loop do."""

MAX_MEMBER_BYTES = 500_000_000
"""How large any single member may claim to be, uncompressed.

A source transcript is generous at a few megabytes. This is the line past which
a member is a decompression bomb rather than a file."""


def _safe(name: str, prefix: str) -> str | None:
    """The path inside ``prefix`` this member unpacks to, or ``None``.

    An archive is an untrusted file that arrived from somewhere. A member named
    ``../../.ssh/authorized_keys`` is the oldest trick there is, and refusing by
    construction is cheaper than remembering to check.

    Backslash is rejected alongside the obvious cases because ``Path.parts`` does
    not split on it under POSIX: ``a\\..\\..\\b`` arrives here as a single
    innocent-looking component and traverses once it reaches Windows.
    """
    if not name.startswith(f"{prefix}/") or name.endswith("/"):
        return None
    relative = name[len(prefix) + 1 :]
    if not relative or relative.startswith("/") or "\\" in relative:
        return None
    if ".." in Path(relative).parts:
        return None
    return relative


def restore(path: Path, *, data_dir: Path, vectors: Path | None) -> dict:
    """Replace the journal with the one in this archive. Returns the manifest.

    The caller is expected to have closed its stores and to stop afterwards.
    Replacing files a running process holds open is the same hazard erasing
    them is: on macOS the old file lives until the last handle closes, so the
    app would go on reading a journal that is no longer on disk.
    """
    manifest = check(path)

    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        if len(members) > MAX_MEMBERS:
            raise ArchiveError(
                f"That archive holds {len(members):,} files, more than the "
                f"{MAX_MEMBERS:,} this will unpack."
            )

        journal = [(name, _safe(name, JOURNAL)) for name in members]
        journal = [(name, rel) for name, rel in journal if rel]
        if not journal:
            raise ArchiveError("That archive has no journal in it.")

        for name, _ in journal:
            declared = archive.getinfo(name).file_size
            if declared > MAX_MEMBER_BYTES:
                raise ArchiveError(
                    f"{name} unpacks to {declared:,} bytes, more than the "
                    f"{MAX_MEMBER_BYTES:,} this will write."
                )

        # Everything lands in a staging directory first, and the journal is only
        # replaced once every member is on disk. Extracting over the real
        # directory is how an archive that fails halfway — a bad CRC, a full
        # disk — used to leave no journal and no replacement, with nothing to
        # roll back to. Beside `data_dir` rather than in a temp directory so the
        # swap is a rename on one filesystem rather than a copy across two.
        staging = data_dir.parent / f".{data_dir.name}.incoming"
        displaced = data_dir.parent / f".{data_dir.name}.replaced"
        for leftover in (staging, displaced):
            if leftover.exists():
                shutil.rmtree(leftover)

        try:
            staging.mkdir(parents=True)
            for name, relative in journal:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as out:
                    shutil.copyfileobj(source, out)

            staged_vectors = None
            if vectors is not None and VECTORS in members:
                staged_vectors = staging.parent / f".{data_dir.name}.vectors"
                with archive.open(VECTORS) as source, staged_vectors.open("wb") as out:
                    shutil.copyfileobj(source, out)

            # The point of no return, and the only place the real journal moves.
            if data_dir.exists():
                data_dir.replace(displaced)
            staging.replace(data_dir)
            if staged_vectors is not None:
                vectors.parent.mkdir(parents=True, exist_ok=True)
                staged_vectors.replace(vectors)
        except BaseException:
            # Nothing has moved unless the swap above completed, so cleaning up
            # staging is the whole rollback.
            shutil.rmtree(staging, ignore_errors=True)
            if displaced.exists() and not data_dir.exists():
                displaced.replace(data_dir)
            raise
        finally:
            shutil.rmtree(displaced, ignore_errors=True)

    log.warning("restored %s from %s", data_dir, path)
    return manifest
