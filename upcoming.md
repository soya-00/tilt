# Upcoming

What is known to be unfinished, so it stops living in pull request bodies and
in somebody's head. Not a backlog to burn down — most of these are here because
they need a machine, a corpus, or a judgement that does not exist yet, and
saying so is more useful than pretending they are scheduled.

The roadmap in the README says what the app is for. This says what is owed.

---

## Needs a Mac

Neither can be checked in CI or in a Linux container, and both are shipped and
unverified.

- **The Tauri opener.** External links were dead in the packaged app — the
  webview never created the window and the CSP had no `navigate-to`, so a link
  that worked perfectly in `npm run dev` did nothing at all in the `.dmg`.
  `tauri-plugin-opener` is wired and scoped to http/https. One `npm run tauri
  build`, then click a brief item's title and the Open button.
- **The frozen sidecar finding the keychain.** `keyring` resolves its backend
  through entry points at runtime, which PyInstaller cannot see, so
  `keyring.backends.macOS` is named in the spec's hidden list. If that is wrong
  the app silently falls back to storing the API key in a file — and only on
  the machines that actually ship. Check `/status` reports
  `key_storage: keychain` in a built app.

## Needs a real key

The offline provider is deliberately useful, but it can only ever measure
itself.

- **The connector's precision has never been measured.** The gate is ≥0.8 on
  hand-labelled pairs. Everything the measurement needs is in place —
  dismissals are kept as tombstones rather than deleted, so the rate per link
  kind is recoverable from the index — but it needs a real corpus and a key.
- **Whether the scout earns its place.** Its gate was answered offline: the
  scout picked a paper because of a question written nine days earlier and the
  sweep linked one of its ideas back to that question. That proves the
  plumbing and explicitly not the judgement, because offline both the pick and
  the link are keyword overlap. The question is whether a real model finds
  something worth an afternoon often enough to justify the sheet.
- **The embedding path has never run against a real key.** `bridges to` depends
  on it, and bridge recall was measured on a planted corpus rather than on
  anything anyone wrote.

## Wanted, not started

- **Folder splitting, and clustering from scratch.** The nightly keeper merges
  duplicates and retires quiet folders but never splits one, because splitting
  on lexical evidence alone is guesswork and a bad split scatters a subject
  with no way to see why. The embedding layer it was waiting for now exists.
- **Audio and video transcription.** Locally that means MLX: Apple-Silicon-only
  and about a gigabyte of native libraries in the bundle. Dropping an `.mp3`
  currently says so rather than failing.
- **A macOS CI job** for the Tauri build, if checking it by hand gets tiresome.
  Deliberately not bought yet: it needs the whole Rust toolchain and signing
  configuration and runs an order of magnitude slower than the three jobs that
  exist.

## Decided, and recorded so they are not reopened

- **No accounts, and no hosted sync.** The journal is local, file-based
  Markdown and that is the product rather than a stage before a server. See
  SECURITY.md.
- **The spending ceiling does not apply to anything you triggered.** Correct
  for a personal app; the consequence is that a shared instance must never run
  on a key of your own.
- **The API key still arrives over loopback through `PATCH /settings`.** Moving
  the key to the keychain closed the real exposure — a plaintext file any
  process running as you could read. Closing the other half would mean a second
  key owner in the Tauri shell and a sidecar reload path, which is a great deal
  of machinery for a request you made yourself from the app's own webview
  behind a bearer token.

## Loose ends worth knowing

- **`pnpm install --ignore-scripts`** in CI and the Dockerfile. pnpm 10+ exits
  non-zero when it skips a dependency's install script, and the settings field
  that would allow one instead — `pnpm.onlyBuiltDependencies` in package.json —
  is ignored by pnpm 11. If esbuild ever needs its postinstall for real rather
  than for the platform binary it currently ships as an optional dependency,
  this has to be revisited.
- **`packageManager` is pinned** in `apps/desktop/package.json`. Its absence is
  what let three environments each resolve their own pnpm, one of which did not
  run on the Node version CI had.
