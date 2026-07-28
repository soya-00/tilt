# Tilt

A thinking instrument for macOS, not a productivity tool.

Tilt is a journal that notices things. You write into a single stream with no
folders and no filing, and the app's job is to give you back understanding —
what you were actually circling, where today echoes something from March, what
you now contradict. There are no todos, no boards, and no due dates anywhere in
it, by design.

> Status: early. The writing surface and one agent job are implemented end to
> end. The connection graph, source distillation, research scout, and synthesis
> jobs are designed but not yet built — see the roadmap below.

---

## What exists today

- **The Stream** — one reverse-chronological column. Write, press `⌘↵`, done.
- **Reflection** — ask any entry for a reflection and it threads underneath as a
  reply, grounded in your related earlier writing.
- **Search** — full-text across the journal, reachable from the command palette.
- **Command palette** (`⌘K`) — the only navigation surface. Commands and journal
  content in one list.
- **Quick capture** (`⌥Space`) — a small window for one thought.
- **Cost ledger** — every model call is priced and recorded; spend is always
  visible in the status bar.

Your journal is a folder of Markdown files. The database is a cache that can be
deleted and rebuilt at any time.

## Design

Two voices, two typefaces. What you write is set in a humanist face; what the
machine says is set in mono behind a hairline accent rule. That distinction
carries the hierarchy, so agent output needs no boxes, badges, or "AI" labels to
read as not-you.

Everything else is restraint: dark-first, one accent colour reserved exclusively
for the machine, hierarchy from contrast and spacing rather than shadows or
cards, no toolbars, no spinners. At rest the Stream is text on a dark field and
nothing else.

## Architecture

```
apps/desktop/   React + TypeScript UI (Tauri v2 shell to follow)
core/           Python service: Markdown store, SQLite index, agent layer
```

The Python service owns all product logic. The desktop shell will own only
window management, the global hotkey, the tray, and notifications.

| Concern | Choice | Why |
|---|---|---|
| Source of truth | Markdown + YAML frontmatter | Portable, greppable, outlives the app |
| Index | SQLite + FTS5 | Rebuildable projection, never the record |
| Retrieval | BM25 today, fused via RRF | Vector ranking drops in without reworking callers |
| Models | Provider protocol | Offline provider by default; Gemini when a key is present |

## Running it

Requires Python 3.11+ and Node 20+.

```bash
# Service
cd core
uv venv && uv pip install -e ".[dev]" --python .venv/bin/python
.venv/bin/python -m uvicorn tilt.api.app:app --port 8765

# UI
cd apps/desktop
pnpm install
pnpm dev
```

Open http://localhost:5173. With no API key configured, Tilt runs an offline
provider that derives its output from your prompt and labels itself as such —
the whole app is explorable without a key or any spend.

To use a real model:

```bash
export TILT_GEMINI_API_KEY=...      # falls back to the offline provider if unset
export TILT_DATA_DIR=~/Tilt         # where your journal lives
```

See `core/.env.example` for the full set.

## Tests

```bash
cd core && .venv/bin/python -m pytest && .venv/bin/python -m ruff check tilt tests
cd apps/desktop && pnpm test && pnpm build
```

The load-bearing test writes entries, deletes the database, rebuilds from disk,
and asserts nothing was lost. That guarantee is what the file-as-truth design
rests on.

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 0 | Store, index, search, the Stream | done |
| 1 | Tauri shell, global hotkey, `.dmg` | next |
| 2 | Connection surfacing, emergent themes | designed |
| 3 | Source distillation — video, transcript, PDF, article | designed |
| 4 | Constellation graph, on-demand diagrams | designed |
| 5 | Research scout, daily brief | designed |
| 6 | Weekly synthesis, growth timeline | designed |

Every proposed feature answers one question: does its output make you *do*
something, or *understand* something? Only the second ships.
