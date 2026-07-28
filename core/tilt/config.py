"""Runtime configuration.

Settings resolve from environment variables prefixed ``TILT_`` so the desktop
shell can inject a data directory and API key at spawn time without writing
secrets to disk.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TILT_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path.home() / "Tilt")
    """Root of the journal. Markdown here is the source of truth."""

    provider: str = Field(default="auto")
    """Agent provider: ``auto`` | ``gemini`` | ``echo``. ``auto`` picks gemini
    when an API key is present, otherwise the offline echo provider."""

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    gemini_fallback_model: str = "gemini-3.5-flash"

    monthly_cost_ceiling_usd: float = 20.0
    """Scheduled agent work stops at 80% of this. User-initiated calls continue."""

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def entries_dir(self) -> Path:
        return self.data_dir / "entries"

    @property
    def internal_dir(self) -> Path:
        return self.data_dir / ".tilt"

    @property
    def index_path(self) -> Path:
        return self.internal_dir / "index.db"

    def ensure_dirs(self) -> None:
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.internal_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
