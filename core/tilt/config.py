"""Runtime configuration.

Settings resolve from environment variables prefixed ``TILT_`` so the desktop
shell can inject a data directory and API key at spawn time without writing
secrets to disk.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_support_dir() -> Path:
    """Where this machine keeps what it derived, per platform convention.

    Six lines rather than a dependency on ``platformdirs``: the app targets
    macOS, and the fallback only has to be somewhere sensible rather than
    exhaustively correct.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Tilt"
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Tilt"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg or Path.home() / ".local" / "share") / "tilt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TILT_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path.home() / "Tilt")
    """Root of the journal. Markdown here is the source of truth."""

    export_dir: Path | None = None
    """Where exported archives are written. Defaults to Downloads, then home.

    Overridable because the default is deliberately outside every directory this
    app owns — which is the point of it, and also means a test that exported
    without this would drop archives in whoever ran it's Downloads folder."""

    support_dir: Path | None = None
    """Where the index, the vectors and the API key live. Defaults per platform.

    Set explicitly by the demo container, which has no home directory worth
    the name, and by the tests, which want everything under one tmp_path."""

    provider: str = Field(default="auto")
    """Agent provider: ``auto`` | ``gemini`` | ``echo``. ``auto`` picks gemini
    when an API key is present, otherwise the offline echo provider."""

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    gemini_fallback_model: str = "gemini-3.5-flash"

    embeddings_enabled: bool = True
    """Whether to embed entries at all. Needs a key regardless — off is for
    anyone who wants a key for the agent but not a second thing spending on a
    schedule."""

    embed_dims: int = 768
    """Vector width. Changing this invalidates every stored vector, because two
    widths are not comparable; the store drops the old signature rather than
    mixing them."""

    monthly_cost_ceiling_usd: float = 20.0
    """Scheduled agent work stops at 80% of this. User-initiated calls continue."""

    schedule_enabled: bool = True
    """Run the unattended jobs. Off in tests, and worth turning off for anyone
    who wants the agent to act only when asked."""

    sweep_interval_minutes: int = 15
    """How often to look for entries nothing has filed yet. Cheap when the
    backlog is empty, which it usually is."""

    embed_interval_minutes: int = 60
    """How often to embed what has been written since the last pass. Hourly:
    nothing waits on it, and each pass is a network call and a small charge."""

    theme_keeper_hour: int = 3
    """Local hour for the nightly folder tidy. Overnight because it rearranges
    the sidebar, and watching folders move under the cursor is unsettling."""

    scout_hour: int = 6
    """Local hour for the daily look outward. Early, so whatever it found is
    already there the first time you open the brief, and daily rather than
    hourly because a list that fills faster than it is read is a backlog
    whatever it is called."""

    week_hour: int = 18
    """Local hour on Sunday for the look back over the week.

    Evening rather than morning, and Sunday rather than Monday: what it may
    find is something to sit with, not something to start the week by being
    handed. It costs nothing to run — no model call — so the only thing the
    time affects is when a sentence might appear."""

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

    static_dir: Path | None = None
    """Serve the built interface from this process too.

    Unset for the desktop app, where the Tauri shell owns the window and this
    process is only ever an API. Set for a browser demo, where the page and the
    API being one origin is what makes the whole thing a single container.

    Note what this does to the token: a browser cannot send an Authorization
    header when it asks for a document, so the page has to be reachable without
    one — and the page carries the token so the app can call its own API. The
    token therefore is not the perimeter in this topology. See SECURITY.md."""

    ephemeral_settings: bool = False
    """Keep runtime settings — including the API key — in memory only.

    For a shared demo where each visitor brings their own key: nothing is
    written, so the key lives exactly as long as the process and the app can
    say so rather than asking a stranger to trust a file mode. Off by default,
    because on your own machine a key that survives a restart is the point."""

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
        """Where the machine's own files live, outside the journal.

        The journal folder is one you are invited to touch — open it in
        Obsidian, grep it, put it in git, hand it to Dropbox. Two things that
        used to live inside it are hazardous under that invitation: an API key
        you might commit or share, and WAL-mode SQLite that a cloud client
        corrupts. macOS syncs ``~/Documents`` by default, so this is not a
        hypothetical for anyone who keeps their journal in the obvious place.

        So the line is: **the journal folder holds only what you authored; this
        one holds only what the machine derived or was handed.**
        """
        return self.support_dir or default_support_dir()

    @property
    def vectors_path(self) -> Path:
        """Beside the index, deliberately not inside it.

        ``index.db`` is free to rebuild from Markdown and the app says so.
        Vectors were bought from a hosted model, so throwing them away has a
        price — and the two have to be discardable independently or deleting
        the cheap one silently costs money."""
        return self.internal_dir / "vectors.db"

    @property
    def brief_dir(self) -> Path:
        """Reading that has not happened yet. Beside the journal rather than in
        it: none of this is a thought until you read it and it becomes one."""
        return self.data_dir / "brief"

    @property
    def diagrams_dir(self) -> Path:
        """Diagrams the agent drew. Beside the journal rather than inside it —
        they are readings of your entries, not entries."""
        return self.data_dir / "artifacts" / "diagrams"

    @property
    def persona_path(self) -> Path:
        """In the journal, unlike everything else the app keeps for itself.

        The agent's name and manner are the one thing here you wrote. Keeping
        them with your entries is what makes the journal folder the whole
        record of what you made — and Markdown rather than JSON because every
        other file in that folder is readable."""
        return self.data_dir / "agent.md"

    @property
    def settings_path(self) -> Path:
        """Model, ceiling and feeds — beside your entries, not in the support
        directory where they started.

        They were moved out when the API key was in this file in plain text.
        That was right about the key and wrong about everything else: the feeds
        you typed are things you authored, and a journal folder that silently
        omitted them was not the whole journal it claimed to be."""
        return self.data_dir / "settings.json"

    @property
    def archive_dir(self) -> Path:
        """Where an exported archive goes — outside everything ``/erase`` removes.

        It used to be written into the support directory, which erasing deletes.
        So the careful sequence, export and then erase, destroyed the archive it
        had just made: the one file whose whole purpose is to survive that.

        Downloads because it is what a Mac already means by "a file I asked for
        and will do something with", and because an archive nobody can find is
        not a backup either. Home when there is no Downloads, which is the
        container and anything headless.
        """
        if self.export_dir is not None:
            return self.export_dir
        downloads = Path.home() / "Downloads"
        return downloads if downloads.is_dir() else Path.home()

    @property
    def key_path(self) -> Path:
        """The API key, on a machine with no keychain. Its own file, outside
        the journal, so that *nothing secret is ever written into the journal
        folder* stays a rule with no exceptions."""
        return self.internal_dir / "key.json"

    @property
    def legacy_settings_path(self) -> Path:
        """Where settings lived before. Read once at boot and moved; see
        :func:`tilt.settings_store.migrate`."""
        return self.internal_dir / "settings.json"

    @property
    def folders_path(self) -> Path:
        """Decisions you made about your folders, beside your entries.

        In the journal folder for the same reason ``agent.md`` is: a name you
        typed and a suggestion you declined are things you authored. They used
        to live only in ``index.db``, which the app calls disposable and means
        it — so the one operation advertised as costless was quietly discarding
        the only state that could not be re-derived."""
        return self.data_dir / "folders.md"

    @property
    def index_path(self) -> Path:
        return self.internal_dir / "index.db"

    def ensure_dirs(self) -> None:
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.internal_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
