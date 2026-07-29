import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { CommandPalette, type Command } from "./components/CommandPalette";
import { Composer, type ComposerHandle } from "./components/Composer";
import { Constellation } from "./components/Constellation";
import { DiagramSheet, label as scopeName } from "./components/DiagramSheet";
import { QuickCapture } from "./components/QuickCapture";
import { SearchBar } from "./components/SearchBar";
import { Settings } from "./components/Settings";
import { SourceSheet } from "./components/SourceSheet";
import { Sidebar } from "./components/Sidebar";
import { Stream } from "./components/Stream";
import { Icon } from "./components/Icon";
import { api } from "./lib/api";
import { onCaptured } from "./lib/shell";
import { describe, useAway } from "./lib/useAway";
import { useJournal } from "./lib/useJournal";
import { useTheme } from "./lib/useTheme";

/** Past this distance from the bottom, the user is reading history — never
 *  yank them back to the newest message. */
const STICK_THRESHOLD = 120;

/** Wait for a row to appear after a scope change, and highlight it when it does.
 *
 *  The Stream reloads over the network, so the row does not exist on the next
 *  frame — polling frames is what makes "take me to that entry" survive the
 *  round trip without threading a promise through the journal hook. */
function settle(
  entryId: string,
  highlight: (id: string) => boolean,
  ms = 1600,
): Promise<boolean> {
  return new Promise((resolve) => {
    const deadline = Date.now() + ms;
    const attempt = () => {
      if (highlight(entryId)) resolve(true);
      else if (Date.now() > deadline) resolve(false);
      else requestAnimationFrame(attempt);
    };
    requestAnimationFrame(attempt);
  });
}

export default function App() {
  const journal = useJournal();
  const away = useAway();
  const [theme, toggleTheme] = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const [diagramOpen, setDiagramOpen] = useState(false);
  const [sourcePrefill, setSourcePrefill] = useState<{ title: string; text: string } | null>(null);
  const composer = useRef<ComposerHandle>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);

  const { scope, setScope, themes, tags, status, persona, settings, threads } = journal;

  const focusComposer = useCallback(() => composer.current?.focus(), []);

  const highlight = useCallback((entryId: string) => {
    const el = document.getElementById(`entry-${entryId}`);
    if (!el) return false;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("row--highlight");
    setTimeout(() => el.classList.remove("row--highlight"), 1600);
    return true;
  }, []);

  /** Go to an entry, wherever it is.
   *
   *  The Stream holds one page of one scope, so an entry named by the palette
   *  or the constellation is often not on screen: filed under a folder you are
   *  not browsing, or simply older than the page. Widening the scope brings
   *  back the recent ones; for anything older, the entry's own opening words
   *  find it through search. A click that silently lands nowhere is what turns
   *  a graph into a decoration, and it is the failure this exists to prevent.
   */
  const openEntry = useCallback(
    async (entryId: string, hint?: string) => {
      if (highlight(entryId)) return;
      setScope({ type: "all" });
      if (await settle(entryId, highlight)) return;

      const query = (hint ?? "").replace(/[^\p{L}\p{N} ]+/gu, " ").trim();
      if (!query) return;
      setScope({ type: "search", q: query });
      await settle(entryId, highlight);
    },
    [highlight, setScope],
  );

  // Track whether the user is pinned to the bottom before content changes.
  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD;
  }, []);

  const count = threads.reduce((n, t) => n + 1 + t.replies.length + t.links.length, 0);
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !atBottom.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [count]);

  // A scope change is a fresh view; always start at its end.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    atBottom.current = true;
    el.scrollTop = el.scrollHeight;
  }, [scope]);

  const commands = useMemo<Command[]>(
    () => [
      { id: "write", label: "Write an entry", hint: "⌘N", run: focusComposer },
      { id: "capture", label: "Quick capture", hint: "⌥Space", run: () => setCaptureOpen(true) },
      {
        id: "reflect-latest",
        label: "Reflect on the latest entry",
        run: () => {
          const latest = threads[0];
          if (latest && !latest.entry.id.startsWith("pending-")) {
            void journal.reflect(latest.entry.id);
          }
        },
      },
      {
        id: "constellation",
        label: "Show the constellation",
        hint: "⌘G",
        run: () => setGraphOpen(true),
      },
      {
        // Disabled rather than absent when nothing is scoped. A command that
        // vanishes teaches nothing; one that says why teaches where to start.
        id: "diagram",
        label:
          scope.type === "all"
            ? "Diagram this — open a folder or a search first"
            : `Diagram ${scopeName(scope)}`,
        run: () => scope.type !== "all" && setDiagramOpen(true),
      },
      { id: "all", label: "Show everything", run: () => setScope({ type: "all" }) },
      ...themes.map((theme) => ({
        id: `theme-${theme.id}`,
        label: `Open ${theme.label}`,
        hint: String(theme.count),
        run: () => setScope({ type: "theme", id: theme.id, label: theme.label }),
      })),
      { id: "theme-toggle", label: "Toggle light and dark", run: toggleTheme },
      { id: "settings", label: "Settings", hint: "⌘,", run: () => setSettingsOpen(true) },
      {
        id: "source",
        label: "Add source material",
        run: () => {
          setSourcePrefill(null);
          setSourceOpen(true);
        },
      },
      {
        id: "rebuild",
        label: "Rebuild the search index from disk",
        run: () => void api.rebuildIndex().then(() => journal.refresh()),
      },
    ],
    [focusComposer, journal, scope, setScope, themes, threads, toggleTheme],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (mod && e.key.toLowerCase() === "n") {
        e.preventDefault();
        focusComposer();
      } else if (mod && e.key.toLowerCase() === "g") {
        e.preventDefault();
        setGraphOpen((o) => !o);
      } else if (mod && e.key === ",") {
        e.preventDefault();
        setSettingsOpen(true);
      } else if (e.altKey && e.code === "Space") {
        e.preventDefault();
        setCaptureOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusComposer]);

  // A thought captured in the ⌥Space panel is written by a different window;
  // without this the journal would not show it until something else reloaded.
  const { refresh } = journal;
  useEffect(() => onCaptured(() => void refresh()), [refresh]);

  const scopeLabel =
    scope.type === "theme" ? scope.label : scope.type === "tag" ? `#${scope.tag}` : null;

  return (
    <div className="app">
      <Sidebar
        themes={themes}
        tags={tags}
        scope={scope}
        entryCount={status?.entries ?? 0}
        status={status}
        persona={persona}
        onScope={setScope}
        onOpenGraph={() => setGraphOpen(true)}
        onRenameTheme={journal.renameTheme}
        onDeleteTheme={journal.deleteTheme}
        onSavePersona={journal.savePersona}
      />

      {/* Flat paper, never glass: what you wrote does not sit on a card. */}
      <main className="pane">
        {/* Not a header: transparent, no border, scrolls nothing. */}
        <div className="pane__strip">
          <SearchBar scope={scope} onScope={setScope} />
          {scopeLabel && (
            <button className="scope-chip" onClick={() => setScope({ type: "all" })}>
              {scopeLabel}
              <span className="scope-chip__clear">clear</span>
            </button>
          )}
          {journal.error ? (
            <button className="pane__error" onClick={journal.dismissError} role="alert">
              {journal.error}
            </button>
          ) : (
            away.activity && (
              <button className="pane__away" onClick={away.dismiss} title="Dismiss">
                {describe(away.activity)}
              </button>
            )
          )}

          <button
            className="strip-btn"
            aria-label="Settings"
            title="Settings (⌘,)"
            onClick={() => setSettingsOpen(true)}
          >
            <Icon name="settings" size={18} />
          </button>
        </div>

        <div className="pane__scroll scroll" ref={scroller} onScroll={onScroll}>
          {/* justify-content:flex-end pins a short thread to the bottom. */}
          <div className="pane__inner">
            <Stream
              threads={threads}
              loading={journal.loading}
              scope={scope}
              freshReplies={journal.freshReplies}
              onReflect={journal.reflect}
              onUpdate={journal.update}
              onDelete={journal.remove}
              onDismissLink={journal.dismissLink}
              onOpenEntry={(id) => void openEntry(id)}
              onScope={setScope}
            />
          </div>
        </div>

        <div className="pane__composer glass glass--edge-top">
          <div className="pane__composer-inner">
            <Composer
              ref={composer}
              autoFocus
              onSubmit={journal.create}
              onAddSource={(prefill) => {
                setSourcePrefill(prefill ?? null);
                setSourceOpen(true);
              }}
              onUploadSource={journal.ingestFile}
            />
          </div>
        </div>
      </main>

      <Constellation
        open={graphOpen}
        scope={scope}
        onClose={() => setGraphOpen(false)}
        onOpenEntry={(id, hint) => void openEntry(id, hint)}
        onScope={setScope}
      />

      <CommandPalette
        open={paletteOpen}
        commands={commands}
        onClose={() => setPaletteOpen(false)}
        onOpenEntry={(id) => void openEntry(id)}
      />

      <QuickCapture
        open={captureOpen}
        onSubmit={journal.create}
        onClose={() => setCaptureOpen(false)}
      />

      <Settings
        open={settingsOpen}
        settings={settings}
        status={status}
        theme={theme}
        onClose={() => setSettingsOpen(false)}
        onSave={journal.saveSettings}
        onToggleTheme={toggleTheme}
      />

      <DiagramSheet
        open={diagramOpen}
        scope={scope}
        onClose={() => setDiagramOpen(false)}
      />

      <SourceSheet
        open={sourceOpen}
        initial={sourcePrefill}
        onClose={() => setSourceOpen(false)}
        onIngest={journal.ingest}
      />
    </div>
  );
}
