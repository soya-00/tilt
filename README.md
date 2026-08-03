# Tilt

A thinking instrument for macOS.

Tilt is a journal that notices things. You write into a single stream with no
folders and no filing, and the app's job is to give you back understanding —
what you were actually circling, where today echoes something from March, what
you now contradict. There are no todos, no boards, and no due dates anywhere in
it, by design.

> Status: early but real, and feature-complete against the roadmap it was
> written to. Writing, categorising, connecting, distilling sources, the
> constellation, on-demand diagrams, the research scout and the weekly notice
> all work end to end, offline, with no API key, and the agent keeps working on
> a schedule after you close the window. One capability needs a key and always
> will — see [docs/design.md](docs/design.md#the-one-thing-tilt-cannot-do-on-its-own).
>
> What is *not* done is distribution. There is no signed build and no installer:
> the `.dmg` is something you compile on your own Mac, and the container is how
> you would give it to anyone else. See
> [docs/install.md](docs/install.md#installing-a-build-you-made).

---

## What exists today

Five loops are in: **inputting, categorising, connecting, distilling, seeing.**

- **The Stream** — one column, anchored at the bottom. Write, press Enter, done.
- **Categorising** — the agent tags each entry and files it under a folder. You
  never tag or file anything by hand.
- **Connecting** — meaningful relationships with earlier entries, threaded
  underneath as `echoes`, `builds on`, `contradicts`, `offers a counterpoint to`
  or `bridges to`, each with a one-line reason.
- **Distilling** — a transcript, subtitle file, PDF or pasted notes becomes
  **one** entry with the ideas it contains nested beneath, and only the ones
  that meet your own writing are surfaced.
- **The constellation** (`⌘G`) — the journal as a graph, in a rail beside the
  Stream, where clicking a node takes you to the thought.
- **Diagram this** — the agent draws the structure of a folder, a tag or a
  search, and picks the form.
- **The brief** (`⌘B`) — reading that has not happened yet, filled from both
  sides. Nothing in it reaches your journal until you choose it.
- **Upkeep you are asked about** — a folder that has become two subjects, an
  entry that sits closer to a folder it is not in. Neither happens until you
  click, and what you turn down is remembered.
- **The week, when there is something to say** — two free queries on Sundays,
  and silence most weeks, on purpose.
- **Search, a command palette** (`⌘K`) **and quick capture** (`⌥Space`), plus a
  reflection on any entry, threaded underneath and arriving word by word.
- **It keeps working when you close it** — a sweep every quarter hour, a nightly
  folder pass, a daily scout. Every run leaves a record in Settings, and every
  model call is priced against a ceiling unattended work stops at.
- **Settings, in six parts**, the last of which forgets your key, erases
  everything, or exports the journal as one file another machine can import.

Why each of these is shaped the way it is: [docs/design.md](docs/design.md).

Your journal is a folder of Markdown files, and it holds only what you wrote:
entries, the brief, diagrams, and your agent's name and manner. What the machine
derived or was handed — the search index, the vectors, your API key — lives in
`~/Library/Application Support/Tilt` instead, so the folder you grep, sync and
put in git contains no credential and no database. The database is a cache that
can be deleted and rebuilt at any time — folders, connections, dismissals, the
promotion bar, and the record of what the agent has already examined all live
in each entry's own frontmatter, so nothing is re-derived and nothing is
re-billed.

## Installing it

One command, on the Mac you intend to run it on:

```bash
./scripts/install.sh
```

That checks the tools it needs and names the fix for any that are missing,
builds the interface, freezes the Python service into the bundle, compiles the
shell, and copies `Tilt.app` into `/Applications`. Add `--build-only` to stop
before the last step and keep the bundle in `target/`.

The first run takes a while — most of it is compiling Rust — and later runs
reuse the cache. If Tilt is already installed and running, the script quits it
first: replacing the bundle underneath a running app is how you end up with one
that reports one version and behaves like another.

It requires **macOS**, Xcode command line tools, [Rust](https://rustup.rs),
Node 22+, and Python 3.11+.

Why there is no download to click: [docs/install.md](docs/install.md), which
also covers running from a checkout, `tauri dev`, upgrading, and the container.

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 0 | Store, index, search, the Stream | done |
| 1 | Tauri shell, global hotkey, `.dmg` | done |
| 2 | Scheduled agents: catch-up sweep, theme upkeep | done |
| 3 | Source distillation — transcript, subtitles, PDF, link | done |
| 4 | Constellation graph, on-demand diagrams | done |
| 5 | Research scout, daily brief | done |
| 6 | Folder splitting, weekly notice | done |

**There is no phase 7, and that is a state rather than an omission.** Every
phase this app was planned to have is built, and the last item that was pencilled
in past phase 6 — a growth timeline — is struck off rather than deferred, for
reasons kept in [docs/design.md](docs/design.md).
What remains is not a phase: it is a handful of measurements that need a real
key and a real journal, a build that needs a Mac, and whatever a few months of
actual use turns out to demand. All of it is written down in `upcoming.md`,
which exists so that none of it lives in a pull request body or in somebody's
head.

## Documentation

| | |
|---|---|
| [docs/design.md](docs/design.md) | What each loop does in full, why it behaves that way, how it looks, and the decisions recorded so they are not reopened |
| [docs/architecture.md](docs/architecture.md) | The layout, the choices and their reasons, what runs on its own, and what the tests hold down |
| [docs/install.md](docs/install.md) | Running from a checkout, building the Mac app, installing an unsigned build, upgrading, and the container |
| [docs/tour.md](docs/tour.md) | The first ten minutes, ending at the files on disk |
| [SECURITY.md](SECURITY.md) | What the token protects, and what it does not |
| [upcoming.md](upcoming.md) | What is known to be unfinished, and why each item is waiting |
