# Tilt

A thinking instrument for macOS, not a productivity tool.

Tilt is a journal that notices things. You write into a single stream with no
folders and no filing, and the app's job is to give you back understanding —
what you were actually circling, where today echoes something from March, what
you now contradict. There are no todos, no boards, and no due dates anywhere in
it, by design.

> Status: early but real. Writing, categorising, and connecting all work end to
> end, offline, with no API key. Source distillation, the constellation graph,
> the research scout, and weekly synthesis are designed but unbuilt — see the
> roadmap.

---

## What exists today

The three core loops are in: **inputting, categorising, connecting.**

- **The Stream** — one column, oldest to newest, anchored at the bottom so the
  newest thought sits by your hands. Write, press Enter, done.
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
- **Search** — full-text from the bar at the top; results arrive as whole
  threads, folders and connections intact.
- **One agent, yours** — a single reflective voice with a name and a personality
  you write. Not a roster to assemble; what is configurable is who it *is*.
- **Reflection** — ask any entry for a reflection and it threads underneath,
  grounded in your related earlier writing, arriving word by word.
- **Command palette** (`⌘K`) — commands and journal content in one list.
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

**Content is the interface.** No header, no footer, no toolbar. Structure comes
from whitespace, one hairline, and one accent used once per screen. Your own
words are plain text; only the agent's replies sit in an outlined bubble, so the
two voices are separated by containment rather than by colour.

**Colour answers attention.** Each tag is assigned its own hue from a muted
palette by hashing its name — stable forever, never random at render. The colour
stays hidden until you hover the tag or scope to it. A wall of permanently
coloured tags would shout over the writing.

Entry actions stay invisible until hover or focus. A reflection arrives word by
word rather than pasted whole. Every transition respects
`prefers-reduced-motion`.

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

Requires Python 3.11+ and Node 20+. Nothing else — no `uv`, no global installs.

**Terminal 1 — the service**

```bash
cd core
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn tilt.api.app:app --port 8765
```

**Terminal 2 — the interface**

```bash
cd apps/desktop
npm install          # or pnpm install
npm run dev
```

Open **http://localhost:5173**.

With no API key configured, Tilt runs an offline provider that derives its
output from your prompt and says so — the whole app is explorable without a key
and without spending anything.

To use a real model, set these before starting the service:

```bash
export TILT_GEMINI_API_KEY=...   # falls back to offline if unset
export TILT_DATA_DIR=~/Tilt      # where your journal lives
```

See `core/.env.example` for the full set.

> On Windows the venv paths are `.venv\Scripts\python` instead of
> `.venv/bin/python`.

## Trying the MVP

With both processes running, open http://localhost:5173 and walk this path:

1. **Write.** Type a thought and press Enter (Shift+Enter for a new line). It
   appears instantly — the save happens behind it, and a failed save puts the
   text back rather than losing it.
2. **Watch it get filed.** A `filing…` marker appears, then tags and a folder
   attach themselves. The folder shows up in the sidebar. You did nothing.
3. **Write a second thought on the same subject.** Once it is filed, a
   connection threads underneath it pointing back at the first, labelled
   `echoes` with a one-line reason.
4. **Write something unrelated** — the classic test. It should connect to
   *nothing*. A connector that links everything is worthless, so silence here is
   the result that matters.
5. **Click a folder or tag** in the sidebar to scope the Stream. Double-click a
   folder to rename it, which pins the name against future agent edits.
6. **Hover a tag** to see its colour; click it to scope. **Search** from the top
   bar. **`⌘K`** for commands, **`⌥Space`** for quick capture, and **reflect** on
   any entry for a threaded response.
7. **Rename the agent.** Click it in the sidebar, give it a name and a
   personality — that text goes straight into the reflection prompt.
8. **Check the files.** `ls ~/Tilt/entries/**/*.md` — your thoughts are plain
   Markdown with YAML frontmatter, and folders and connections are written there
   too. Delete `~/Tilt/.tilt/index.db`, restart, and everything comes back; the
   database is only a cache.

Offline mode is lexical, not intelligent: it matches on repeated keywords, so
tags are decent and connections are conservative. Add a Gemini key for real
judgement — particularly for `contradiction`, which keyword overlap cannot find.

## Tests

```bash
cd core && .venv/bin/python -m pytest && .venv/bin/python -m ruff check tilt tests
cd apps/desktop && npm test && npm run typecheck && npm run build
```

121 tests: 75 backend, 46 frontend.

The load-bearing one writes entries, deletes the database, rebuilds from disk,
and asserts nothing was lost — that guarantee is what the file-as-truth design
rests on. Others worth knowing about: a dismissed connection is never proposed
again from either direction; a failed submit preserves what you typed; and the
connector stays silent on unrelated entries.

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
