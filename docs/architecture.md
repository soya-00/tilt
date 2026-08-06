# Architecture

How Tilt is put together, what runs without being asked, and what the tests hold
down. [Back to the README](../README.md).

---

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
| **Theme-keeper** | nightly, 03:17 | Merges duplicate folders, retires quiet ones, drops empty ones, and proposes a split when one has become two or a move when an entry is in the wrong one |
| **Scout** | daily, 06:41 | Looks through your feeds and proposes at most two things to read |
| **Week** | Sundays, 18:53 | Notices at most one thing worth a second look, and usually nothing |
| **Overdue** | every 15 min | Runs whichever of the three crons above the machine was asleep for |

The last one exists because the other three were never running. A cron only
fires if the process is alive at that minute, and the machine this app is for is
a laptop: shut at 03:17, shut at 06:41, opened at nine. APScheduler then
schedules the *next* 03:17, which is tomorrow, which is also a night the laptop
was shut. The keeper, the scout and the weekly pass had therefore never run
once — and every symptom of that looks like something else, because an empty
brief reads as "the scout found nothing" and a sidebar nobody proposes splitting
reads as "my folders are fine".

`misfire_grace_time` does not cover it: that governs a fire time that passed
while the scheduler was alive, and says nothing about the hours the process did
not exist for. What covers it is asking a different question — not "did the
moment arrive" but "has it been long enough since this last ran", which the
index can answer because every run leaves a row there. On the sweep's interval,
so it inherits the recovery property the crons lack, and it costs one indexed
query per job.

The rest are shaped differently on purpose. A backlog can appear at any hour — a
thought caught with `⌥Space` while the window was closed, one written when a
call failed — so the sweep is an interval, cheap enough to run constantly
because it costs one indexed query when there is nothing waiting. The
theme-keeper rearranges the sidebar, and watching folders move under the cursor
is disorienting, so it is a cron and it runs overnight. Not on the hour:
everything else that runs at 3am runs at 3:00. The scout is a cron for a
different reason — nothing accumulates that it drains, so running it more often
would only fill the brief faster than anyone empties it. The weekly pass is a
cron for a third reason again: it is about a period rather than a backlog, and
running it more often would report on a week that had barely changed since the
last report.

The weekly pass is also the only one that cannot spend anything. It runs two
queries over what the index and the vector store already hold, which is what
makes an unattended weekly job defensible at all — the expensive half happens
when you press the button on what it found.

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

## Tests

```bash
cd core && .venv/bin/python -m pytest && .venv/bin/python -m ruff check tilt tests
cd apps/desktop && npm test && npm run typecheck && npm run build
cd apps/desktop/src-tauri && cargo build
```

654 tests: 470 backend, 184 frontend.

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

Everything you author is in one folder, and that took two corrections to get
right. `settings.json` was moved *out* of it when the API key was sitting in it
in plain text — the right call about the key and the wrong one about everything
else, because the feeds you typed and the model you chose are yours too, and a
journal folder that silently omitted them was not the whole journal it claimed
to be. The key is in the keychain now, so the file has come back, and the key
has its own file in the support directory on a machine with no keychain. The
rule keeps no exceptions: nothing secret is ever written into the journal
folder.

The pin itself lives in `folders.md`, beside your entries. A folder has no file
of its own — it is only implied by the labels its members carry — so there was
nowhere for a fact *about a folder* to be written, and two decisions ended up
in `index.db` and nowhere else: a name you typed, and a split you turned down.
That made the one operation the README calls costless the only one that could
lose something. Both are matched on the label rather than on a theme id, because
a rebuild from an empty index mints new ids and the label is the only durable
name a folder has.

