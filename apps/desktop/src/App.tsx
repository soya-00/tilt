import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CommandPalette, type Command } from "./components/CommandPalette";
import { Composer, type ComposerHandle } from "./components/Composer";
import { QuickCapture } from "./components/QuickCapture";
import { StatusBar } from "./components/StatusBar";
import { Stream } from "./components/Stream";
import { api } from "./lib/api";
import { useJournal } from "./lib/useJournal";
import { useTheme } from "./lib/useTheme";

export default function App() {
  const journal = useJournal();
  const [, toggleTheme] = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const composer = useRef<ComposerHandle>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const focusComposer = useCallback(() => composer.current?.focus(), []);

  const highlight = useCallback((entryId: string) => {
    const el = document.getElementById(`entry-${entryId}`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("entry--highlight");
    setTimeout(() => el.classList.remove("entry--highlight"), 1600);
  }, []);

  const commands = useMemo<Command[]>(
    () => [
      { id: "write", label: "Write an entry", hint: "⌘N", run: focusComposer },
      {
        id: "capture",
        label: "Quick capture",
        hint: "⌥Space",
        run: () => setCaptureOpen(true),
      },
      {
        id: "reflect-latest",
        label: "Reflect on the latest entry",
        run: () => {
          const latest = journal.threads[0];
          if (latest && !latest.entry.id.startsWith("pending-")) {
            void journal.reflect(latest.entry.id);
          }
        },
      },
      { id: "theme", label: "Toggle light and dark", run: toggleTheme },
      {
        id: "rebuild",
        label: "Rebuild the search index from disk",
        run: () => {
          void api.rebuildIndex().then(() => journal.refresh());
        },
      },
      { id: "refresh", label: "Reload the stream", run: () => void journal.refresh() },
    ],
    [focusComposer, journal, toggleTheme],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      } else if (mod && e.key.toLowerCase() === "n") {
        e.preventDefault();
        focusComposer();
      } else if (e.altKey && e.code === "Space") {
        e.preventDefault();
        setCaptureOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusComposer]);

  // Keep the newest entry in view when one is added.
  const count = journal.threads.length;
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [count]);

  return (
    <div className="app">
      {/* Drag region standing in for the hidden titlebar; traffic lights inset. */}
      <div className="titlebar" data-tauri-drag-region>
        <span className="micro titlebar__mark">tilt</span>
      </div>

      <main className="main scroll" ref={scroller}>
        <div className="column">
          <Composer ref={composer} autoFocus onSubmit={journal.create} />
          <Stream
            threads={journal.threads}
            loading={journal.loading}
            reflecting={journal.reflecting}
            onReflect={journal.reflect}
            onUpdate={journal.update}
            onDelete={journal.remove}
          />
        </div>
      </main>

      <StatusBar
        status={journal.status}
        error={journal.error}
        onDismissError={journal.dismissError}
      />

      <CommandPalette
        open={paletteOpen}
        commands={commands}
        onClose={() => setPaletteOpen(false)}
        onOpenEntry={highlight}
      />

      <QuickCapture
        open={captureOpen}
        onSubmit={journal.create}
        onClose={() => setCaptureOpen(false)}
      />
    </div>
  );
}
