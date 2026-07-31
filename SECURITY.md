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
  serialisable out.
- **Prompt injection is bounded.** A hostile page you ingest can steer the
  model, but output is parsed as JSON, tags and folder names are snapped
  against the existing vocabulary and length-capped, and diagrams are
  sanitised. The worst case is a misleading card in your own journal.

## What did not hold, and what was done

| Finding | Fix |
|---|---|
| The token middleware was added only when a token existed, so `TILT_HOST=0.0.0.0` with the token forgotten served the journal to anyone | `api/limits.py::check_exposure` refuses to start off loopback without a token, naming the variable to set |
| Feed URLs from the settings route were fetched in-process with `follow_redirects=True` and no address check — an SSRF whose output is summarised into the brief | `feeds.py` follows redirects by hand, at most 3 hops, checking the resolved address at every hop against loopback, private, link-local, reserved, multicast |
| A feed response was buffered whatever its size | `MAX_FEED_BYTES`, refused rather than read |
| `EntryCreate.body` had no `max_length`, and the ingest limit ran after the body was in memory | `MAX_BODY` on the models, plus `BodyLimitMiddleware` rejecting an oversized declared `Content-Length` |
| Provider errors were relayed to the browser verbatim, and an SDK exception can carry the request that produced it | `agents/redact.py` strips key-shaped runs before the message is wrapped; the full text goes to the log |
| Path traversal through an id was blocked only by uvicorn's decode order, not by this code | `store/files.py::contained` asserts the resolved path stays in the directory |

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

So `~/Tilt` contains entries, the brief, diagrams, and `agent.md` — your
agent's name and manner, which you wrote. The support folder contains
`index.db`, `vectors.db` and `settings.json`. Syncing your journal therefore
cannot corrupt a WAL-mode database and cannot carry your API key to another
machine or into a git remote, because neither is in there.

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
