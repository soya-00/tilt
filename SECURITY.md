# Security

Tilt is a single-user local application whose backend happens to speak HTTP.
That sentence is the whole threat model, and most of what follows is a
consequence of it.

This document records an audit done before demoing the app, what held, what did
not, and the rules for running it anywhere other than your own machine.

## The thing to understand first

**There is no user model.** One data directory, one `settings.json`, one API
key, no user id anywhere in the schema. Two people reaching the same instance
share a journal — reading, editing and deleting each other's entries, and each
able to replace the Gemini key.

This is not a defect to be patched. It is what the app is. Any deployment
serving more than one person has to give each of them their own instance and
their own data directory, and the moment that stops being true the guarantees
below stop holding too.

## What was checked and holds

- **SQL injection is unreachable.** Every f-string in `store/index.py`
  interpolates internal constants — placeholder runs built from `","*n`, the
  `_THEME_STATS` fragment, the hardcoded `_ADDED_COLUMNS` migration list. All
  user values are bound parameters.
- **FTS5 syntax injection is handled.** `store/search.py::sanitize_query`
  strips operators and quotes each term before a `MATCH`.
- **YAML cannot execute.** `python-frontmatter` uses `SafeLoader`, so a journal
  file that arrived by folder sync, or was hand-edited, cannot run code.
- **XSS is layered.** The only `dangerouslySetInnerHTML` in the app is
  mermaid's rendered SVG. Model output first has `%%{init}%%`, `click`, `link`
  and `href` removed and must open with a diagram keyword
  (`agents/diagram.py`), then mermaid renders with `securityLevel: "strict"`.
  React escapes everything else.
- **The API key never leaves.** `PublicSettings` exposes only whether a key is
  set and its last four characters, and a test asserts the secret is not
  serialisable out. It is held in the OS keychain rather than in a file, and
  falls back to a mode-600 file only where there is no keychain — a container,
  CI, a headless box. `/status` names which of the two is in force, so the
  weaker mode is never silent.
- **Prompt injection cannot reach your files.** A hostile page you ingest can
  steer the model, but output is parsed as JSON, tags and folder names are
  snapped against the existing vocabulary and length-capped, and diagrams are
  sanitised. Nothing the model returns chooses a path, runs a command, or
  decides what to delete.

  It is **not** bounded to "a misleading card in your own journal", which is
  what this said before and was too kind to itself. Reading a link enables
  Gemini's `url_context` tool, and that tool is not scoped to the link you
  asked about, while the same prompt carries excerpts of your recent entries as
  context. A page that gets itself into your brief and then gets read can
  therefore try to have your own writing fetched back out to an address it
  chooses. Nothing downstream catches that, because the leak would happen
  during the model turn rather than in the JSON that comes back.

  Open, and listed in [upcoming.md](upcoming.md): closing it means either
  giving up reading articles or scoping the tool to one URL, and that is a
  decision about what the app is rather than a patch.

## What did not hold, and what was done

| Finding | Fix |
|---|---|
| The token middleware was added only when a token existed, so `TILT_HOST=0.0.0.0` with the token forgotten served the journal to anyone | `api/limits.py::check_exposure` refuses to start off loopback without a token, naming the variable to set |
| Feed URLs from the settings route were fetched in-process with `follow_redirects=True` and no address check — an SSRF whose output is summarised into the brief | `feeds.py` follows redirects by hand, at most 3 hops, checking the resolved address at every hop against loopback, private, link-local, reserved, multicast |
| A feed response was buffered whatever its size | `MAX_FEED_BYTES`. **Refused after the body is read, not before** — `_bounded` reads `response.content` and then compares, so the memory is spent either way. The cap bounds what is parsed and stored, not what is received |
| `EntryCreate.body` had no `max_length`, and the ingest limit ran after the body was in memory | `MAX_BODY` on the models, plus `BodyLimitMiddleware` rejecting an oversized declared `Content-Length` |
| Provider errors were relayed to the browser verbatim, and an SDK exception can carry the request that produced it | `agents/redact.py` strips key-shaped runs — including a credential spelled as a JSON field — before the message is wrapped **and before it is logged** |
| Path traversal through an id was blocked only by uvicorn's decode order, not by this code | `store/files.py::contained` asserts the resolved path stays in the directory |

## What a second review found, and what was done

The audit above missed four things, each confirmed by a working proof before it
was fixed and each now covered by a test that fails without the fix.

| Finding | Fix |
|---|---|
| An entry's `id` comes from frontmatter and `path_for` interpolated it into a path, so a file arriving by import or sync could write outside the journal — triggered by the nightly folder pass, with nobody present. `contained` was applied by the artifact and brief stores but not the entry store | Checked at both ends: `store/files.py::usable_id` when the id is read, containment in `path_for` when the path is composed. An id that cannot be a filename costs the id and not the entry — it is indexed under its filename and reported in `/status` beside the conflicts a sync client causes |
| The token gate exempted any path *spelled* like a static file, so API routes ending in a caller-supplied segment could be handed a `.png` and reached unauthenticated. Container topology only; the desktop gate was always total | `api/auth.py::_is_interface` asks the static mount what it owns, and the mount and the gate are derived from one expression so they cannot drift apart |
| `/import` deleted the journal and *then* extracted, so an archive that failed partway left no journal, no replacement and no rollback | Extraction is staged and swapped only once every member is on disk. Archives are bounded by member count and size, and a member name containing a backslash is refused — `Path.parts` does not split on it under POSIX |
| Nothing stopped two instances sharing one journal: two schedulers doing the same unattended work, and entry frontmatter read-modify-written by both with one write lost | An advisory `flock` in `serve.py::hold_journal`, taken at startup and released by the kernel however the process dies |

Smaller, in the same pass: the exposure check reads the address actually bound
rather than the configured one; the body limit sits inside the auth gate as its
comment claimed; `OPTIONS` is exempt only when it is a real preflight; exports
are written outside every directory `/erase` removes, so "export first, then
erase" no longer destroys the archive; the served page carries a CSP and
`frame-ancestors`, which only the webview had before; the container no longer
ships the dev CORS origin or source maps; the entrypoint stamps its token with
Python rather than `sed`; `/status` reports where the key actually landed
rather than whether a keychain exists; the key file is created at mode 600
rather than chmodded to it; export no longer follows a symlink out of the
journal; and arXiv is fetched over HTTPS.

### Two findings that testing withdrew

Recorded so they are not raised again by the next reader.

- **Feed XML entity expansion is not a denial of service.** Internal entities do
  expand — 436 bytes to 1.35 million characters, measured — but the runtime's
  own amplification guard refuses the document past a threshold, and the
  `ParseError` it raises is already caught by `feeds.parse`. External entities
  do not resolve at all. Bounded, not runaway.
- **The chunked-request body-limit bypass is real and already handled.**
  `BodyLimitMiddleware` only inspects a declared `Content-Length`, so a chunked
  request skips it — which its own docstring says, naming the model-level
  `max_length` as the floor. Tested: the route's own check answers with a 413.
  The residue is that the body is materialised before rejection.

## Deliberate non-goals

**The spending ceiling does not apply to anything a person triggered.**
`agents/ledger.py` exempts interactive calls: the ceiling stops unattended
jobs at 80% and leaves the rest for work you are present for. That is correct
for a personal application, and under bring-your-own-key it is the visitor's
key and their choice. Capping it would be this app deciding how somebody else
may spend their own money.

The consequence, stated plainly: **do not run a shared instance on your own
API key.** There is no rate limit and no interactive ceiling, so one visitor
can spend without bound.

**The journal is not encrypted at rest.** FileVault covers a stolen laptop, and
encrypting the Markdown would defend against a cloud provider at the cost of
opening the files in Obsidian, grepping them, and reading them in five years —
which is most of the reason they are Markdown.

**There are no accounts and no hosted sync, and there will not be.** The
journal is a folder of Markdown on your machine; that is the product, not a
stage before a server. Accounts would mean a user model the schema does not
have, and end-to-end encrypted sync would mean a key-recovery problem harder
than its cryptography — lose the passphrase and the journal is gone, offer a
reset and you have put back the trust you were removing. Neither buys anything
a local, file-based journal does not already have.

If you want it on two machines, the folder is the sync layer: iCloud, Dropbox,
Syncthing or a git remote all work, and `index.rebuild` reconciles whatever it
finds on boot.

That is safe now because of where things live, which is worth stating as a rule
because it is the one that decides these questions:

> **The journal folder holds only what you authored. `~/Library/Application
> Support/Tilt` holds only what the machine derived or was handed.**

So `~/Tilt` contains entries, the brief, diagrams, `agent.md` — your agent's
name and manner — and `settings.json`, which holds the feeds you typed and the
model you chose. All of it is yours. The support folder contains `index.db`,
`vectors.db` and, where there is no keychain, `key.json`. Syncing your journal
therefore cannot corrupt a WAL-mode database and cannot carry your API key to
another machine or into a git remote, because neither is in there.

One thing that rule understates, worth saying plainly: **what the machine
derived includes your text**. `index.db` stores entry bodies, because full-text
search needs them — so there is a second complete copy of the journal in the
support folder. It is not synced and not exported, and deleting an entry
removes it from the search index rather than orphaning it. But anything that
backs up Application Support — Time Machine, a full-disk backup, a migration —
carries your journal whether or not it touched `~/Tilt`.

The remaining sync hazard is one the app cannot fix: two machines editing the
same entry produce a provider's "(conflicted copy)" file carrying a duplicate
`id`, and `index.rebuild` upserts by id, so one silently wins. Use git if that
matters to you — it is Markdown, which is what git is for.

## What the token is, and what it is not

Worth being exact, because it is easy to over-read.

When the desktop shell runs the service, the token is a real perimeter: the
shell mints one per launch, passes it to the webview, and nothing else on the
machine can read the journal.

When this process also serves the **page** — `TILT_STATIC_DIR`, which is what
the container does — that stops being true. A browser cannot attach an
`Authorization` header to a document request, so the page must be reachable
without the token; and the page is what carries the token to the API. Anyone
who can load the page therefore has the token.

**So in a browser deployment the token is not the perimeter.** Whatever
authenticates the visitor in front of this process is: an unguessable per-visitor
URL, an auth proxy, SSO, basic auth — something. What the token still buys is
that reaching the port directly, without ever loading the page, gets you
nothing, which matters when the container's port is mapped on a shared host.

## Running it anywhere but your own machine

1. **One instance per person.** Own process, own `TILT_DATA_DIR`. There is no
   other way to keep two people's journals apart.
2. **Put something in front that authenticates the visitor.** See above — the
   token does not do this once the page is served from the same process.
3. **`TILT_AUTH_TOKEN` is mandatory off loopback.** The app refuses to start
   without it; the container mints one if you do not.
4. **TLS is mandatory if anyone types a key.** Asking someone to paste a live
   credential over cleartext HTTP is not defensible. Terminate TLS in front of
   the service; the service itself only ever speaks HTTP.
5. **Set `TILT_EPHEMERAL_SETTINGS=true` for a bring-your-own-key demo.** The
   key is then held in memory and never written, and Settings says so instead
   of promising a file mode.
6. **Do not put a key of your own in a shared instance.** See the non-goal
   above.

## Reporting

This is a personal project without a disclosure process. Open an issue, or if
it is genuinely sensitive, say so in the issue without the details and a
private channel can be arranged.
