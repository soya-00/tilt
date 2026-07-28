"""The agent's identity.

Tilt has exactly one agent, not a roster. It has a name you choose and a
personality you write, and both are stored beside the journal as plain JSON so
they travel with your data rather than living in app preferences.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    """Reads and writes ``.tilt/agent.json``.

    A malformed or missing file yields the default persona rather than an
    error — the agent must always have an identity to speak with.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Persona:
        try:
            return Persona(**json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            return Persona()

    def save(self, persona: Persona) -> Persona:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(persona.model_dump_json(indent=2), encoding="utf-8")
        return persona

    def update(self, payload: PersonaUpdate) -> Persona:
        current = self.load()
        if payload.name is not None:
            current.name = payload.name.strip() or DEFAULT_NAME
        if payload.personality is not None:
            current.personality = payload.personality.strip()
        return self.save(current)
