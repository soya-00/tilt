# Upcoming

What is known to be unfinished, so it stops living in pull request bodies and
in somebody's head. Not a backlog to burn down — most of these are here because
they need a machine, a corpus, or a judgement that does not exist yet, and
saying so is more useful than pretending they are scheduled.

The roadmap in the README says what the app is for. This says what is owed.

---

## Needs a Mac

None of these can be checked in CI or in a Linux container, and all are shipped
unverified. Each fails visibly rather than silently — a button that does
nothing, a `/status` that still reports a key — which is the only reason they
ship at all. The dead opener is what taught that distinction.

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
- **The keychain genuinely forgetting a key.** The file path is covered by
  tests; whether `keyring.delete_password` reaches the login keychain from a
  frozen sidecar is not. Settings → Danger → Forget it, then check `/status`.
- **Quitting after an erase or an import.** Both routes stop the service and
  expect the shell to follow. `core:app:allow-exit` is not in
  `src-tauri/capabilities/default.json` yet; until it is, the window stays open
  on a journal that is gone and the interface says to quit and reopen. One line,
  and only a Mac can say whether it works.

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
- **Both measured thresholds, on a real journal.** `SEPARATION` for splitting
  and `MARGIN` for refiling were each measured on planted vectors and each
  separate cleanly there. What a real embedder does to a real set of folders is
  unmeasured for both. The number to watch is the same: not how often something
  is proposed, but how often a proposal is dismissed.
- **The split threshold on a real journal.** `SEPARATION = 0.15` separates one
  subject from two by roughly a factor of four on planted vectors, and the
  planting is the part that needs replacing: what a real embedder does to a real
  set of folders is unmeasured. The number to watch is not how often it proposes
  a split, it is how often a proposal is dismissed.

## Wanted, not started

- **Clustering from scratch.** Ruled out rather than pending. It proposes a
  whole sidebar at once with no way to accept part of it, cannot respect a name
  you typed, and needs a `k` nobody has measured. The useful half of it —
  finding the entries that incremental filing got wrong — is built, per entry
  and one click each. See `jobs/misfiled.py`.
- **Audio and video transcription.** Locally that means MLX: Apple-Silicon-only
  and about a gigabyte of native libraries in the bundle. Dropping an `.mp3`
  currently says so rather than failing.
- **A macOS CI job** for the Tauri build, if checking it by hand gets tiresome.
  Deliberately not bought yet: it needs the whole Rust toolchain and signing
  configuration and runs an order of magnitude slower than the three jobs that
  exist.

## Decided, and recorded so they are not reopened

- **No growth timeline.** Struck off rather than deferred. A view charting how
  your thinking has developed is a progress chart, and a progress chart is the
  productivity app this is not. The weekly notice is the honest version of the
  same idea: it says one specific thing when there is one to say, rather than
  drawing a line that always goes somewhere.
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

## Known limits, recorded so they are not rediscovered

- **The statistic cannot tell a subject that drifted from a folder that is two
  subjects.** Measured, not assumed: stretch one subject far enough along an
  axis and it scores like two. That is what the model veto and the accept click
  are for, and no threshold would help.
- **The weekly pass only ever looks for two things.** A contradiction between
  two things you wrote, and an old question this week came near. That is a
  deliberately short list, and whether it is too short is a question a few
  months of real weeks will answer better than more design.

## Surfaces the API has and the interface does not

Both found by running the app rather than by reading it, and they are the same
mistake twice: an endpoint that works, a client method that calls it, and no
component that ever renders the result.

- **Saved diagrams.** `GET /diagrams` and `DELETE /diagrams/{id}` exist and
  `api.diagrams()` is in the client. Nothing reads either. A diagram is drawn,
  written to `artifacts/diagrams/`, and is unreachable the moment the sheet is
  closed — you can only draw it again, which costs another model call. **Ruled
  out rather than pending**: a gallery was proposed and turned down. Recorded
  because the hole is real, not because it is scheduled.
- ~~**Diagram this** has no button.~~ Fixed: it sits in the strip beside the
  scope chip, present exactly when something is scoped. The gallery below is
  the half that is still missing.

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
- **`StatusBar.tsx` was dead code** and is gone. Nothing imported it and its CSS
  had already been deleted in an earlier redesign, so it was found by running the
  app rather than by reading it. Worth knowing because the same thing can happen
  again: a component with no import and no test looks alive in the file tree.
