# Installing and running it

Every way to run Tilt: from a checkout, as a Mac app, and in a container. The
one-command install is in the [README](../README.md#installing-it); this is
everything around it. [Back to the README](../README.md).

---

## Running it

Requires Python 3.11+ and Node 22+. Nothing else — no `uv`, no global installs.

> Node **22**, not 20. `apps/desktop/package.json` pins `pnpm@11`, which does
> not run on Node 20 — which is how CI found out, on a commit that passed on a
> Node 22 laptop.

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

### Why it does not just download

There is no signed build to download, because notarising one requires a paid
Apple Developer membership and this is an app one person wrote for themselves.
Building on the machine you run it on is what makes that a non-event rather
than a problem: nothing is downloaded, so nothing is quarantined, and Gatekeeper
never gets a say. See **Installing a build you made** below for the case where a
`.dmg` does move between machines.

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

### Installing a build you made

The build is **unsigned and unnotarised**, and that is a standing decision
rather than an oversight. Notarisation requires a paid Apple Developer
membership, and buying one to distribute an app nobody has asked for yet is the
wrong order to do things in.

The consequence is specific. macOS quarantines anything downloaded, and refuses
to open a quarantined app it cannot attribute to a developer. Building on the
machine you run it on avoids that entirely — nothing downloaded, nothing
quarantined. If you move a `.dmg` between your own machines, clear the flag
yourself:

```bash
xattr -dr com.apple.quarantine /Applications/Tilt.app
```

Do that only for a build you made. The correct response to being told an app
cannot be verified is usually to believe it, and turning Gatekeeper off system
wide — which some projects suggest — is never the answer to this. If clearing
one attribute on one app is more than you want to explain to someone, give them
a container instead; see **Running it somewhere other than your machine**. It
serves the same interface from the same service, and asks nothing of Apple.

One thing to expect on an unsigned build: keychain permissions are granted to a
code signature, and an unsigned binary's changes with every compile. macOS may
therefore ask again for keychain access after each rebuild. Annoying rather than
broken, and `/status` always reports whether the key is in the keychain or in a
file at mode 600.

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
columns rather than rebuilding. Entries, folders, and connections are untouched.

A rebuild used to be the one operation the README called costless that could
still lose something: a folder name you had pinned by renaming lived in the
database and nowhere else. It now lives in `folders.md` beside your entries,
along with every split and move you have turned down, so the index is once again
a cache in the way the rest of this document claims it is.

One thing does not fix itself. v0.2 corrected the offline provider's stopword
list, which had been letting words like "than" become tags and folder names.
That applies to filing from here on; a folder already named `Than` stays until
you rename it or delete its entries.

## Running it somewhere other than your machine

Tilt is a single-user local app whose backend happens to speak HTTP, and that
is the whole security model. There is no user id anywhere in the schema, so two
people on one instance share a journal — reading, editing and deleting each
other's entries.

If you want to show it to people, give each of them their own container:

```
docker build -t tilt-demo .
docker run --rm -p 8765:8765 tilt-demo
```

That image serves the interface and the API from one process, keeps the
visitor's API key in memory instead of writing it down, and starts a journal
that dies with the container. It refuses to start on a non-loopback address
without a token, so the mistake with no recovery is not one you can make by
forgetting.

**[upcoming.md](../upcoming.md)** is the ledger of what is known-unfinished —
what needs a Mac, what needs a real key, and what was decided against.

**[SECURITY.md](../SECURITY.md)** has the audit behind that: what was checked and
holds, what did not and what was done about it, what the token protects and
what it demonstrably does not once the page is served from the same process,
and why the spending ceiling still exempts anything you asked for yourself.

