# The first ten minutes

A path through the app that shows every loop working, ending where it should —
at the files on disk. [Back to the README](../README.md).

---


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
   too. Delete the index — `~/Library/Application Support/Tilt/index.db` —
   restart, and everything comes back; the database is only a cache. That now
   includes the decisions you made about your folders, which are kept in
   `~/Tilt/folders.md` because no entry could carry them.
10. **Take it to another machine.** Copy `~/Tilt` and point Tilt at it — your
   entries, folders, connections, agent, feeds and model are all in there.
   **Settings → Journal → Export** writes the same thing as one file, with the
   vectors included because those were bought. The API key is in neither, and
   never will be.

Offline mode is lexical, not intelligent: it matches on repeated keywords, so
tags are decent and connections are conservative. Add a Gemini key for real
judgement — particularly for `contradiction`, which keyword overlap cannot find.

