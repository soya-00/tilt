"""The agent's identity.

Tilt has exactly one agent, not a roster. It has a name you choose and a manner
you write, and both live *in* the journal folder rather than in app
preferences — because unlike the index, the vectors and the API key, this is
something you authored. It is the one file the machine keeps that belongs on
your side of that line.

Markdown with frontmatter, like everything else in that folder. The name is a
field because the app substitutes it into prompts; the manner is the body,
because it is prose you wrote and it should read like prose in the file.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
from pydantic import BaseModel, Field

DEFAULT_NAME = "Tilt"
DEFAULT_PERSONALITY = (
    "Direct and unsentimental. Names the claim underneath what I wrote, "
    "especially when I did not state it. Never flatters."
)


class Persona(BaseModel):
    name: str = Field(default=DEFAULT_NAME, min_length=1, max_length=32)
    personality: str = Field(default=DEFAULT_PERSONALITY, max_length=600)

    def as_instruction(self) -> str:
        """The persona as a line the reflection prompt can absorb."""
        trait = self.personality.strip()
        line = f'Your name is "{self.name}".'
        return f"{line}\n\nYour manner: {trait}" if trait else line


class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    personality: str | None = Field(default=None, max_length=600)


class PersonaStore:
    """Reads and writes ``agent.md`` in the journal folder.

    A malformed or missing file yields the default persona rather than an
    error — the agent must always have an identity to speak with, and losing
    the ability to reflect because someone mistyped YAML would be absurd.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Persona:
        try:
            post = frontmatter.load(self.path)
        except (OSError, Exception):  # noqa: B014 - frontmatter raises broadly
            return Persona()
        name = str(post.metadata.get("name") or DEFAULT_NAME)
        try:
            return Persona(name=name, personality=post.content.strip())
        except ValueError:
            # A name edited to something the model rejects — empty, or longer
            # than the field allows. The manner is still worth keeping.
            return Persona(personality=post.content.strip()[:600])

    def save(self, persona: Persona) -> Persona:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(persona.personality, name=persona.name)
        self.path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return persona

    def update(self, payload: PersonaUpdate) -> Persona:
        current = self.load()
        if payload.name is not None:
            current.name = payload.name.strip() or DEFAULT_NAME
        if payload.personality is not None:
            current.personality = payload.personality.strip()
        return self.save(current)
