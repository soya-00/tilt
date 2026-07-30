# Tilt

A thinking instrument for macOS, not a productivity tool.

Tilt is a journal that notices things. You write into a single stream with no
folders and no filing, and the app's job is to give you back understanding —
what you were actually circling, where today echoes something from March, what
you now contradict. There are no todos, no boards, and no due dates anywhere in
it, by design.

> Status: early but real. Writing, categorising, connecting, distilling sources,
> the constellation and on-demand diagrams all work end to end, offline, with no
> API key, and the agent keeps working on a schedule after you close the window.
> One capability needs a key and always will — see below. The research scout and
> weekly synthesis are designed but unbuilt; see the roadmap.

---

## What exists today

Five loops are in: **inputting, categorising, connecting, distilling, seeing.**

- **The Stream** — one column, oldest to newest, anchored at the bottom so the
  newest thought sits by your hands. Write, press Enter, done.
- **Categorising** — after you keep an entry, the agent tags it and files it
  under a theme, reusing an existing theme when one fits. You never tag or file
  anything by hand.
- **Connecting** — the agent looks for meaningful relationships with earlier
  entries and threads them under the entry as `echoes`, `builds on`,
  `contradicts`, `offers a counterpoint to`, or `bridges to`, each with a
  one-line reason. Dismiss in one click; a dismissed pair is never proposed
  again, and the dismissal is written to disk so that stays true after the
  index is rebuilt.
- **Distilling** — drop in a transcript, a subtitle file, a PDF, or pasted
  notes, and it becomes **one** entry in the Stream with the ideas it contains
  nested beneath. Those ideas then join the same connection graph as your own
  writing, which is the point: a talk can answer a question you asked yourself
  in June. Most of what a source says stays quiet — see below.
- **The constellation** (`⌘G`) — a collapsible rail beside the Stream showing
  the journal as a graph: every thought and folder a dot, sized by how
  connected it is, joined by the lines the agent drew. Greyscale throughout,
  and only the hubs are named — everything else answers to hover. Click a
  thought and the Stream scrolls to it with the graph still open, so following
  a chain of connections costs nothing. Filter by time, by folder, and by
  whether to include what you have read.
- **Diagram this** — ask the agent to draw the structure of a folder, a tag, or
  a search, and it picks the form: a mindmap when these are facets of one
  preoccupation, a flowchart when one thing leads to another, a state diagram
  when a position moved. Saved as Markdown beside your journal.
- **The brief** (`⌘B`) — reading that has not happened yet, filled from both
  sides. You put things there; once a day the agent looks through the feeds you
  named and whatever arXiv has on your subjects, and adds at most two, each with
  one line on which of your open questions it might answer. Everything carries
  tags in the same vocabulary your entries use, so a candidate can be recognised
  at a glance and followed back to what you have already written under it. Read
  one and it goes through the same distillation as anything you paste; dismiss it
  and it is never offered again. Nothing in it is in your journal until you
  choose it.
- **Sidebar** — navigate folders and tags the agent produced, kept deliberately
  few (see below). Rename a folder to pin its name against future agent edits;
  delete one, in two clicks, when the agent's guess about how your thinking
  divides up is simply wrong. Deleting a folder keeps every entry that was in
  it. There is deliberately no way to create one by hand — a folder you
  maintain is filing work.
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
deleted and rebuilt at any time — folders, connections, dismissals, the
promotion bar, and the record of what the agent has already examined all live
in each entry's own frontmatter, so nothing is re-derived and nothing is
re-billed.

### Ingesting is filtering

A thirty-card video that shows you thirty cards has filtered nothing. Every
idea a source contains is extracted and indexed, but only the ones that meet
something you have actually written are surfaced; the rest sit under a line
saying how many there are. They are searchable the moment you go looking, and
they are never pushed at you.

On an empty journal there is nothing to be relevant to, so everything shows.

### Does the graph ever make you open an old entry?

The constellation was built against that question, because the answer decides
whether it is a feature or a screensaver. Three things came out of taking it
seriously:

It is a **rail, not an overlay**. Clicking a node scrolls the Stream to that
entry with the graph still on screen, so a chain of connections can be followed
without reopening the picture between each step.

It **reaches entries that are not loaded**. The Stream holds one page of one
scope, so a node usually names something that is not on screen. Clicking one
widens the scope, and for anything older than the page it falls back to
searching for the entry's own opening words. A click that silently lands nowhere
is exactly what turns a graph into decoration.

It **carries its own filter**. The graph opens on the folder you were browsing,
but that filter can be cleared from inside the rail without moving the Stream.
Locked to where you already are, it could never take you anywhere new.

Only connected nodes are drawn. Entries nothing has met yet are reported as a
count rather than added as a cloud of dust — inventory belongs in the sidebar.

Two things are rationed rather than thresholded, because a threshold that suits
twenty thoughts is wrong at three thousand and the reverse. **Labels** are a
budget: six folders and eight thoughts are named at rest, ranked by how
connected they are, and hovering names anything. There are two budgets rather
than one because a folder's degree is its membership — on a large journal
folders would take every place in a shared budget and no thought would ever be
named, and on a small one they would lose every place and take your bearings
with them. **The node cap** is ranked the same way. It only bites past a few
hundred entries, which is exactly where drawing the most recent ones is wrong:
it discards every hub older than the recent window and makes a dense journal
look sparse.

### Diagrams are model output being handed to a parser

A diagram may describe your thinking; it has no business opening pages or
reconfiguring the renderer. `click` directives, `href`, and `%%{init}%%` blocks
are stripped server-side before anything is saved, what is left has to open with
a diagram keyword from an allowlist, and Mermaid runs in strict mode on top of
that.

Mermaid's parser is JavaScript, so the check can only happen in the app. It
parses; on failure the parser's own words go back for exactly one repair; on a
second failure it shows you the error and the source and stops. Two failures
means the model cannot draw this one, and a third paid attempt is a loop rather
than a fix.

Diagrams are Markdown files under `artifacts/diagrams/`, not rows in the index —
a diagram is cheap to list and never searched, so caching it would only add a
migration and something else that can drift from the files.

### The sidebar is a vocabulary, not an index

Folders and tags are only worth having if there are few enough of them to
recognise. Left to itself a model mints "Attention", "Attentional Control" and
"Attention Economy" across three nights, each holding one entry, and the
sidebar becomes a list of things you wrote once. Nothing groups, which is the
only thing a tag is for.

So the agent is shown the vocabulary already in use — the folders and the
commonest tags, with their counts — and asked to place the entry among them,
extending the list only when it genuinely does not reach. Asking is not a
mechanism, so what comes back is normalised too: case, punctuation and
plurality collapse, and a near-miss folds onto the term already in use.

That folding is deliberately timid, because the costs are not symmetric. A
duplicate folder is cheap to fix — the nightly keeper merges it, and you can
delete one in two clicks — while merging two subjects wrongly destroys a
distinction you were making and cannot be undone from the interface. When
unsure it mints the duplicate. Tags fold more readily than folders: a tag is a
label, a folder is a place.

### The one thing Tilt cannot do on its own

`bridges to` — two unrelated areas turning out to touch — is the only link kind
whose value is in pairs sharing no vocabulary. Proofing dough and a polling
interval are alike because waiting is a thing in the world, and that is a fact
about the world rather than about your journal. Nothing built from your own
writing can know it, which is why this capability needs a key and always will.

It was worse than that until recently. The connector's candidates came from a
full-text search and the recency window, and the model only ever judges pairs it
is shown — so such a pair was presentable only while both entries were recent.
After that the link could never be proposed however good the model was. The
feature was shipped, prompted for, rendered with its own label, and unreachable.

Entries are now embedded on a schedule and the nearest by meaning join the
candidate set, which is the path that does not require shared words. An offline
embedder was built for this and then removed: measured on a corpus with a
deliberately planted bridge, it separated subjects cleanly and bridged nothing,
which was the one job it was there for.

Settings lists what is asleep without a key rather than leaving you to notice.
Everything else still runs offline.

Vectors live in `.tilt/vectors.db`, beside the index and deliberately not in it.
The index is free to rebuild from Markdown and the app says so; vectors were
bought from a hosted model, so throwing them away has a price. Two files means
either can be discarded without paying for the other.

### A shelf, not a queue

A daily list of things to read is the one shape this app's own rule excludes:
*does its output make you do something, or understand something?* A digest that
fills faster than it empties makes you do something, and the something is
triage.

Two decisions are what keep the brief on the right side of that line.

**The scout never writes to the journal.** It proposes; you decide. Gathering
is free — feeds are XML — and triage is one call over titles and abstracts,
asked for at most two and told that zero is the usual answer. Reading is the
expensive step and it never happens without you. An unattended scout distilling
five findings a day would spend about $2.50 a month on your behalf; this one
pays for a triage call and stops.

**The brief is two-way.** It is not a digest the machine fills. You add what
you have been meaning to read — a link, or a plain note with no link at all,
because "the second half of that book" has no address. Both kinds carry why
they are there, which is the first thing to go a fortnight later.

Nothing in it is a task and nothing is completed. There is no count, no
progress, no tick box, and an empty brief is not congratulated — an item leaves
by becoming journal content or by being turned down, and one that simply sits
there is not a failure. Dismissals are kept as tombstones so the same paper is
never offered twice, which is the fastest way to teach someone to stop opening
a list.

**Feeds and arXiv, and nothing else.** An open web search was built for this and
removed. A search result arrives as a headline and a snippet, so triage would be
ranking headlines — the thing the two-pass design exists to avoid. A feed item
arrives with a real title and a real abstract, and anything that turns up
without a description is dropped before a model ever sees it.

It looks like the Stream on purpose: the same dot rail, the same tag chips, the
same composer you type into rather than a form you complete. A candidate is a
thought you have not had yet, and it should not look like a different kind of
object.

### Reading someone you disagree with

`contradicts` is reserved for you disagreeing with yourself — a changed mind is
worth noticing. When a source pulls against something you wrote, that is a
`counterpoint`, and it is a different thing. Holding two opposed views at once
is how a position gets tested, and an app that logged it as self-contradiction
would be punishing exactly the reading habit worth having.

## Design

Three influences, each doing a specific job.

**Liquid glass.** Surfaces are translucent and layered — a saturating blur for
refraction, a broad sheen for the light scattering inside the slab, and a
specular rim around the edge. The rim is the part that sells it: a glass edge is
a curved surface, so its brightness varies with the angle between the surface
normal and the light. It runs near-white where the edge turns into the light,
falls away on the flanks, and picks up a second, weaker highlight on the far
side where light leaves through the back face. On a pale ground the dim stops
are ink rather than white, because an edge turned away from the light stops
reflecting and starts showing its own thickness.

There is one light, fixed in the window, and every highlight in the app derives
from it. Nothing is lit by the pointer: a highlight that chases the cursor only
tells you where your cursor is, and it breaks the illusion the material depends
on — that these are objects sitting in a lit room rather than rectangles
reacting to input. Glass has nothing to refract over a flat fill, so a fixed
ambient gradient wash sits behind everything and each panel picks it up as it
scrolls past.

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
core/tilt/ingest/        What a source is, and how to read it
scripts/                 Packaging the sidecar, rendering the icon
```

The Python service owns all product logic. The shell owns four things and no
more: the windows, the global hotkey, the tray, and the lifetime of the Python
process behind them.

| Concern | Choice | Why |
|---|---|---|
| Source of truth | Markdown + YAML frontmatter | Portable, greppable, outlives the app |
| Index | SQLite + FTS5 | Rebuildable projection, never the record |
| Retrieval | BM25 fused with vector kNN via RRF | Two rankers when there is a key, one when there is not |
| Models | Provider protocol | Offline provider by default; Gemini when a key is present |
| Unattended work | APScheduler in the service | Missed runs coalesce rather than stampede when a laptop wakes |
| Reading sources | Route on metadata, extract in the service | A pure function decides *what this is*; the browser never needs a parser |

### What runs on its own

| Job | When | What it does |
|---|---|---|
| **Sweep** | every 15 min | Files and connects entries the interface never got to |
| **Vectors** | hourly | Embeds what has been written since the last pass |
| **Theme-keeper** | nightly, 03:17 | Merges duplicate folders, retires quiet ones, drops empty ones |
| **Scout** | daily, 06:41 | Looks through your feeds and proposes at most two things to read |

They are shaped differently on purpose. A backlog can appear at any hour — a
thought caught with `⌥Space` while the window was closed, one written when a
call failed — so the sweep is an interval, cheap enough to run constantly
because it costs one indexed query when there is nothing waiting. The
theme-keeper rearranges the sidebar, and watching folders move under the cursor
is disorienting, so it is a cron and it runs overnight. Not on the hour:
everything else that runs at 3am runs at 3:00. The scout is a cron for a
different reason — nothing accumulates that it drains, so running it more often
would only fill the brief faster than anyone empties it.

Both are bounded, both are idempotent, and both stop at 80% of the monthly
ceiling rather than spending it — an interactive request must never be refused
because a background job got there first. Neither waits for a schedule to prove
itself: both are runnable from Settings, and every run leaves a row there
whether it succeeded, failed, or stopped at the ceiling.

The sweep also leaves entries alone for their first three minutes. The interface
is already filing anything just written, and without a quiet period the two
would race and the same judgement would be paid for twice.

Ideas pulled out of a source go through the sweep too, but only its connecting
half. They are born filed, because a card belongs to the source it came out of
rather than to a folder of your preoccupations, and filing borrowed material
into those would dilute every one of them. Two ideas from the same document are
never proposed to each other: they were adjacent in one argument before Tilt
ever saw them, and that is not a discovery.

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
cd apps/desktop && npm run tauri build
```

That produces `Tilt.app` and a `.dmg` in
`apps/desktop/src-tauri/target/release/bundle/`. Freezing the Python service
with PyInstaller is part of it — `beforeBuildCommand` runs
`scripts/build-sidecar.sh`, so the bundle can never ship a service older than
the checkout it was built from. It used to be a separate command you were
expected to remember, and forgetting it produced an app that looked new,
reported the previous version in Settings, and behaved like the release you
thought you had replaced.

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
cd ../apps/desktop && npm install                        # also not optional
```

The reinstall is the step that catches people out, on either side. `git pull`
updates `pyproject.toml` and `package.json`; it does not touch your `.venv` or
`node_modules`, so a new dependency in either one is invisible until you
reinstall. v0.2 added a Python dependency (APScheduler, for the unattended
jobs) — skip that reinstall and the service exits at startup with
`ModuleNotFoundError`, which the interface reports as *Cannot reach the Tilt
service*, reading like a crash rather than a missing package. v0.3 added a
frontend one (`mermaid`, for Diagram-this) — skip that one and `npm run tauri
build` or `npm run dev` fails at compile time with `Cannot find module
'mermaid'`.

Then restart whatever you were running: both terminals, or `npm run tauri dev`.

> **A built `Tilt.app` does not update with `git pull`.** It carries its own
> frozen copy of the service, so it has to be rebuilt:
> `cd apps/desktop && npm run tauri build`. Quit the running app first — the
> old one holds the journal open.
>
> This is the likeliest reason Settings still shows the version you replaced:
> the app you are looking at is not the checkout you pulled into.

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
   folder to rename it, which pins the name against future agent edits. Hover a
   folder and press the bin, twice, to delete it — the folder goes, the thoughts
   filed under it stay exactly where you wrote them.
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

270 tests: 194 backend, 76 frontend.

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

A family of them exists because the same mistake keeps being available: writing
something to SQLite and calling it saved. Each is phrased as the failure rather
than the feature — dismiss a connection, throw the index away, rebuild, and it
must still be dismissed; rename a folder and the new name must still be there
after a restart, with no copy of the old one beside it; edit an entry's text
and it must keep its folders and its connections; delete the index entirely and
the sweep must still report nothing waiting. That last one is the expensive
failure: without it a rebuild silently re-bills the whole journal for answers
already sitting on disk.

The rename case was found the way these usually are — by using the app rather
than by reading it. A folder renamed while taking screenshots was back under
its old name after the next restart, with the renamed one standing empty
beside it.

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 0 | Store, index, search, the Stream | done |
| 1 | Tauri shell, global hotkey, `.dmg` | done |
| 2 | Scheduled agents: catch-up sweep, theme upkeep | done |
| 3 | Source distillation — transcript, subtitles, PDF, link | done |
| 4 | Constellation graph, on-demand diagrams | done |
| 5 | Research scout, daily brief | built, unmerged |
| 6 | Weekly synthesis, growth timeline | designed |

Some of what is designed is deliberately still open.

Phase 3 ships without audio or video transcription. Doing it locally means MLX,
which is Apple-Silicon-only and around a gigabyte of native libraries in the
bundle, and a recorded talk is served today by pasting its transcript. Dropping
an `.mp3` says that rather than failing.

Reading a link — a page, or a YouTube video the model watches directly — is
wired but needs a key: there is no page to fetch offline, and storing an empty
source would imply something had been read.

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
one subject across two folders with no way for you to see why. The embedding
layer it was waiting for now exists, so this and from-scratch clustering are
buildable — they are simply not built.

And the connector's precision has not been measured. The gate for this phase is
≥0.8 on hand-labelled pairs, which requires a real corpus and a real key; the
offline provider matches keywords and would only measure itself. What is in
place is everything the measurement needs: dismissals are kept as tombstones
rather than deleted, so the rate per link kind is recoverable from the index
whenever there is a corpus worth measuring.

Phase 5 sits on its own branch and stays there until it has earned a merge. The
concern is recorded rather than argued away: a brief is the closest thing in
this app to a queue, and the way to find out whether it is one is to use it for
a while, not to reason about it harder. Offline, the loop does close — the scout
picked a paper because of a question written nine days earlier, and after
distillation the sweep linked one of its ideas back to that question without
being asked. That proves the plumbing, not the judgement: offline both the pick
and the link are keyword overlap. Whether a real model finds something worth an
afternoon often enough to justify the sheet is the question the branch is open
to answer.

Every proposed feature answers one question: does its output make you *do*
something, or *understand* something? Only the second ships.
