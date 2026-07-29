"""Diagrams on disk.

Deliberately not in SQLite. The index exists for things that are expensive to
derive — full-text search, link topology, the backlog — and a handful of
diagrams is neither expensive nor searched. Listing them is a directory read,
which means no schema version, no migration, and one less thing that can drift
from the files.

They are Markdown for the same reason entries are: a diagram you can open in any
editor five years from now is a diagram you still have.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from tilt.models import Artifact, utcnow


def _created(value: object) -> datetime:
    """PyYAML turns a bare ISO timestamp into a datetime and leaves a quoted one
    a string, so both shapes turn up in a file a human may have edited."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return utcnow()


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, artifact_id: str) -> Path:
        return self.root / f"{artifact_id}.md"

    def save(self, artifact: Artifact) -> Artifact:
        """Write atomically, overwriting any earlier version of the same id.

        A repaired diagram keeps its id and replaces the broken one. Keeping
        failed drafts would fill the folder with files whose only property is
        that they do not render.
        """
        path = self._path(artifact.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(
            artifact.body,
            id=artifact.id,
            kind=artifact.kind,
            title=artifact.title,
            created=artifact.created.isoformat(),
            **({"note": artifact.note} if artifact.note else {}),
            **({"subjects": artifact.subject_ids} if artifact.subject_ids else {}),
        )

        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(frontmatter.dumps(post))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

        return artifact.model_copy(update={"path": str(path)})

    def load(self, artifact_id: str) -> Artifact | None:
        path = self._path(artifact_id)
        if not path.exists():
            return None
        return self._parse(path)

    def all(self) -> list[Artifact]:
        """Every diagram, newest first."""
        if not self.root.exists():
            return []
        found = []
        for path in self.root.glob("*.md"):
            try:
                found.append(self._parse(path))
            except Exception:
                # A file someone edited into invalid YAML should cost that one
                # diagram, not the whole list.
                continue
        return sorted(found, key=lambda a: a.created, reverse=True)

    def delete(self, artifact_id: str) -> bool:
        path = self._path(artifact_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _parse(path: Path) -> Artifact:
        post = frontmatter.load(path)
        meta = post.metadata
        subjects = meta.get("subjects") or []
        return Artifact(
            id=str(meta.get("id") or path.stem),
            kind=str(meta.get("kind") or "flowchart"),
            path=str(path),
            title=str(meta.get("title") or ""),
            body=post.content.strip(),
            note=str(meta.get("note") or ""),
            subject_ids=[str(s) for s in subjects],
            created=_created(meta.get("created")),
        )
