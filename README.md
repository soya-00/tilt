# Tilt

A thinking instrument for macOS, not a productivity tool.

Tilt is a journal that notices things. You write into a single stream with no
folders and no filing, and the app's job is to give you back understanding —
what you were actually circling, where today echoes something from March, what
you now contradict. There are no todos, no boards, and no due dates anywhere in
it, by design.

> Status: early but real. Writing, categorising, and connecting all work end to
> end, offline, with no API key, and the agent keeps working on a schedule after
> you close the window. Source distillation, the constellation graph, the
> research scout, and weekly synthesis are designed but unbuilt — see the
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
- **It keeps working when you close it** — a sweep every quarter hour files and
  connects anything the interface missed, and a nightly pass merges folders that
  drifted into duplicates and retires ones that have gone quiet. Both are
  runnable on the spot from Settings, and every run leaves a record there.
- **Cost ledger** — every model call is priced and recorded; spend is always
  visible in the status bar. Unattended work stops at 80% of your ceiling;
  anything you asked for yourself always proceeds.

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

**Quiet things recede rather than vanish.** A folder nothing has landed in for
two months drops to half strength and sorts below the live ones, and comes back
to full weight the moment you hover or select it. Deleting it would be easier and
wrong: what you have stopped thinking about is part of the shape of how you
think, and a sidebar showing only this month's preoccupations has no memory.

Entry actions stay invisible until hover or focus. A reflection arrives word by
word rather than pasted whole. The app never congratulates you — work done in
your absence is reported as one dismissible line, never a badge or an alert.
Every transition respects `prefers-reduced-motion`.

## Architecture

```
apps/desktop/            React + TypeScript UI
apps/desktop/src-tauri/  Tauri v2 shell: windows, hotkey, tray, sidecar lifetime
core/                    Python service: Markdown store, SQLite index, agents
core/tilt/agents/        What runs because you asked
core/tilt/jobs/          What runs because time passed
scripts/                 Packaging the sidecar, rendering the icon
```

The Python service owns all product logic. The shell owns four things and no
more: the windows, the global hotkey, the tray, and the lifetime of the Python
process behind them.

| Concern | Choice | Why |
|---|---|---|
| Source of truth | Markdown + YAML frontmatter | Portable, greppable, outlives the app |
| Index | SQLite + FTS5 | Rebuildable projection, never the record |
| Retrieval | BM25 today, fused via RRF | Vector ranking drops in without reworking callers |
| Models | Provider protocol | Offline provider by default; Gemini when a key is present |
| Unattended work | APScheduler in the service | Missed runs coalesce rather than stampede when a laptop wakes |

### What runs on its own

| Job | When | What it does |
|---|---|---|
| **Sweep** | every 15 min | Files and connects entries the interface never got to |
| **Theme-keeper** | nightly, 03:17 | Merges duplicate folders, retires quiet ones, drops empty ones |

The two are shaped differently on purpose. A backlog can appear at any hour — a
thought caught with `⌥Space` while the window was closed, one written when a
call failed — so the sweep is an interval, cheap enough to run constantly
because it costs one indexed query when there is nothing waiting. The
theme-keeper rearranges the sidebar, and watching folders move under the cursor
is disorienting, so it is a cron and it runs overnight. Not on the hour:
everything else that runs at 3am runs at 3:00.

Both are bounded, both are idempotent, and both stop at 80% of the monthly
ceiling rather than spending it — an interactive request must never be refused
because a background job got there first. Neither waits for a schedule to prove
itself: both are runnable from Settings, and every run leaves a row there
whether it succeeded, failed, or stopped at the ceiling.

The sweep also leaves entries alone for their first three minutes. The interface
is already filing anything just written, and without a quiet period the two
would race and the same judgement would be paid for twice.

Two details do most of the work. The service records that it has *considered* an
entry, so a thought the connector correctly found nothing for is never judged a
second time; without it the nightly sweep would re-examine the whole journal for
as long as the journal exists. And a merge rewrites the affected entries'
Markdown, not just the database — themes are restored from frontmatter on boot,
so a merge that touched only SQLite would bring the folder it deleted straight
back on the next restart.

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

## Running it as a Mac app

The two-terminal setup above is the browser path. The desktop shell wraps the
same two pieces into one application: it starts the Python service itself, on a
port the operating system picks, and stops it again when you quit.

```bash
cd apps/desktop
npm run tauri dev
```

Requires [Rust](https://rustup.rs) and Xcode command line tools. Nothing else
changes — the shell runs the Python in `core/` straight from the checkout, so
edits on either side reload as usual.

To build the app itself:

```bash
./scripts/build-sidecar.sh     # freeze the Python service into the bundle
cd apps/desktop && npm run tauri build
```

The first command produces `Tilt.app`'s copy of the service with PyInstaller;
the second produces `Tilt.app` and a `.dmg` in
`apps/desktop/src-tauri/target/release/bundle/`.

> **The `.dmg` can only be built on macOS.** Apple's linker and code-signing
> tools have no equivalent elsewhere, so there is no cross-compile: the two
> commands above must run on the Mac the app is for.

### What the shell adds

| | |
|---|---|
| **⌥Space, anywhere** | A small always-on-top panel that takes one thought and disappears. It sits on real macOS vibrancy rather than the app's own glass, and it is built at launch and kept hidden so the first press is instant. |
| **Menu bar** | Open Tilt, quick capture, quit. Closing the window hides it rather than quitting, the way a Mac app should. |
| **No visible chrome** | The titlebar is hidden and content runs to the window edge; the sidebar insets itself around the traffic lights. |
| **One process pair** | The service listens on loopback, on a port the OS assigns, behind a bearer token minted fresh each launch. It never touches disk, and nothing else on your machine can read the journal. |
| **No leftovers** | The shell kills the service on quit — and the service also watches the pipe between them, so even a crash or a `kill -9` cannot leave a server running with your journal open and no window attached. |

Both windows load the same bundle; a query string decides which is which. In a
browser every shell-specific path is inert, so `npm run dev` still renders the
design exactly as written.

## Upgrading

Check which build is answering first: **Settings** shows the version next to the
title. That number comes from the *service*, not the interface — they are
separate processes and can be different builds, which is the only way to tell a
rebuilt app from one still running a stale copy of the service.

```bash
git pull
cd core && .venv/bin/python -m pip install -e ".[dev]"   # not optional
```

The reinstall is the step that catches people out. v0.2 added a dependency
(APScheduler, for the unattended jobs), and without it the service exits at
startup with `ModuleNotFoundError` — the interface then shows *Cannot reach the
Tilt service*, which looks like a crash rather than a missing package.

Then restart whatever you were running: both terminals, or `npm run tauri dev`.

> **A built `Tilt.app` does not update with `git pull`.** It carries its own
> frozen copy of the service, so it has to be rebuilt:
> `./scripts/build-sidecar.sh && cd apps/desktop && npm run tauri build`.
> Quit the running app first — the old one holds the journal open.

Your journal needs nothing. The index migrates itself on first boot, adding
columns rather than rebuilding, because a rebuild would discard every folder
name you have pinned by renaming it — that lives in the database and nowhere
else. Entries, folders, and connections are untouched.

One thing does not fix itself. v0.2 corrected the offline provider's stopword
list, which had been letting words like "than" become tags and folder names.
That applies to filing from here on; a folder already named `Than` stays until
you rename it or delete its entries.

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
8. **Watch it catch up on its own.** Capture a thought with `⌥Space` — that
   window saves and closes without filing anything. Open **Settings → Activity**
   and press **Catch up**: the entry gets tagged, filed, and judged for
   connections, and a row appears saying what the run did. Left alone it would
   have happened within fifteen minutes anyway.
9. **Check the files.** `ls ~/Tilt/entries/**/*.md` — your thoughts are plain
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
cd apps/desktop/src-tauri && cargo build
```

200 tests: 135 backend, 65 frontend.

The load-bearing one writes entries, deletes the database, rebuilds from disk,
and asserts nothing was lost — that guarantee is what the file-as-truth design
rests on. Others worth knowing about: a dismissed connection is never proposed
again from either direction; a failed submit preserves what you typed; and the
connector stays silent on unrelated entries.

On the shell side the load-bearing ones are the two halves of the boundary
between the app and the service: that the journal answers nobody without the
launch token, and that the service reports the port it actually got rather than
the one anyone assumed.

For the scheduled agents it is the two ways unattended work goes wrong quietly.
One asserts that a second sweep over settled entries considers nothing, because
the failure it prevents — re-judging the whole journal every night — costs money
without changing anything and would never show up as a bug. The other merges two
folders, rebuilds the index from disk, and asserts the merged-away folder does
not come back.

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 0 | Store, index, search, the Stream | done |
| 1 | Tauri shell, global hotkey, `.dmg` | done |
| 2 | Scheduled agents: catch-up sweep, theme upkeep | done |
| 3 | Source distillation — video, transcript, PDF, article | designed |
| 4 | Constellation graph, on-demand diagrams | designed |
| 5 | Research scout, daily brief | designed |
| 6 | Weekly synthesis, growth timeline | designed |

Some of what is designed is deliberately still open.

The API key lives in `~/Tilt/.tilt/settings.json` at mode 600 rather than in the
macOS Keychain — moving it there means the key stops travelling through the
settings API, which is a change to how the app is configured and not just to
where a string is kept.

There are no system notifications, and that is now a decision rather than a gap.
The plan had the shell raise one when a scheduled job found something; against a
journal, a banner announcing that a note has been tagged is exactly the
congratulatory interruption the design rules out. What replaced it is one line
above the Stream when you come back — *3 filed, 2 connections while you were
away* — that dismisses on click and never returns. The connections themselves
stay threaded under the entries they belong to, which is the only place they
mean anything.

The theme-keeper merges folders and retires quiet ones, but it does not *split*
them. Splitting on lexical evidence alone is guesswork, and a bad split scatters
one subject across two folders with no way for you to see why. It needs the
embedding layer, and so does clustering themes from scratch rather than
repairing what accumulated filing produced.

And the connector's precision has not been measured. The gate for this phase is
≥0.8 on hand-labelled pairs, which requires a real corpus and a real key; the
offline provider matches keywords and would only measure itself. What is in
place is everything the measurement needs: dismissals are kept as tombstones
rather than deleted, so the rate per link kind is recoverable from the index
whenever there is a corpus worth measuring.

Every proposed feature answers one question: does its output make you *do*
something, or *understand* something? Only the second ships.
