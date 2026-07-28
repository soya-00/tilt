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

The three core loops are in: **inputting, categorising, connecting.**

- **The Stream** — one reverse-chronological column. Write, press `⌘↵`, done.
- **Categorising** — after you keep an entry, the agent tags it and files it
  under a theme, reusing an existing theme when one fits. You never tag or file
  anything by hand.
- **Connecting** — the agent looks for meaningful relationships with earlier
  entries and threads them under the entry as `echoes`, `builds on`,
  `contradicts`, or `bridges to`, each with a one-line reason. Dismiss in one
  click; a dismissed pair is never proposed again.
- **Sidebar** — navigate folders and tags the agent produced. Rename a folder to
  pin its name against future agent edits; there is deliberately no way to
  create one by hand.
- **Reflection** — ask any entry for a reflection and it threads underneath,
  grounded in your related earlier writing.
- **Search** and **command palette** (`⌘K`) — the only navigation surface, with
  commands and journal content in one list.
- **Quick capture** (`⌥Space`) — a small window for one thought.
- **Cost ledger** — every model call is priced and recorded; spend is always
  visible in the status bar.

Your journal is a folder of Markdown files. The database is a cache that can be
deleted and rebuilt at any time.

## Design

Three influences, each doing a specific job.

**Liquid glass.** Surfaces are translucent and layered, with a specular top edge
and a saturating blur, so panels read as material over a lit backdrop rather
than opaque rectangles. Glass has nothing to refract over a flat fill, so a
fixed ambient gradient wash sits behind everything and each panel picks it up as
it scrolls past.

**Threaded elevation.** A machine reply is connected to its entry by a rail with
a node where the two meet — the way a reply hangs off a post or nests in a mail
thread. Depth reads as connection rather than as another floating card.

**Dim and neutral, in both modes.** Dark is a dim neutral black; light is a dim
neutral white. Neither carries a colour cast — the ambient wash behind the glass
is greyscale, so panels read as smoked or frosted glass rather than as a tinted
gradient. Blue is the single accent and the only colour in the app. Theme
follows the system appearance until you choose otherwise.

The structural constant underneath all of it is **two voices, two typefaces**:
what you write is set in a humanist face, what the machine says is set in mono.
That distinction carries the hierarchy, so agent output needs no badge, avatar,
or "AI" label to read as not-you.

Restraint still governs the rest. One accent colour, reserved for the machine
and the single primary action. No toolbars and no sidebar — `⌘K` is the only
navigation surface. Entry actions stay invisible until hover or focus. Background
work shows a slow block-cursor pulse rather than a spinner, which reads as
composing without implying a deadline.

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
