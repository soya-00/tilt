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

    schedule_enabled: bool = True
    """Run the unattended jobs. Off in tests, and worth turning off for anyone
    who wants the agent to act only when asked."""

    sweep_interval_minutes: int = 15
    """How often to look for entries nothing has filed yet. Cheap when the
    backlog is empty, which it usually is."""

    theme_keeper_hour: int = 3
    """Local hour for the nightly folder tidy. Overnight because it rearranges
    the sidebar, and watching folders move under the cursor is unsettling."""

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            # The webview serves the UI from a custom scheme, so every call it
            # makes to the sidecar is cross-origin. The bearer token, not the
            # origin list, is what actually guards the journal.
            "tauri://localhost",
            "http://tauri.localhost",
        ]
    )

    host: str = "127.0.0.1"
    """Loopback only. The journal is not a network service and never should be."""

    port: int = 8765
    """0 asks the operating system for a free port — what the desktop shell does,
    so two copies of Tilt never fight over a fixed number."""

    auth_token: str | None = None
    """When set, every request but ``/health`` must present it as a bearer token.
    The shell mints a fresh one per launch; running by hand leaves it unset."""

    exit_with_parent: bool = False
    """Shut down when stdin closes. The desktop shell sets this so a crash on
    its side cannot leave the journal served by a process nobody can see. Off by
    default: run from a terminal, stdin never closes, and this would do nothing
    — run with stdin redirected from /dev/null and it would exit immediately."""

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
