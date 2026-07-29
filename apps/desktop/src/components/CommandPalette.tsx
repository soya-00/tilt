import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { stamp } from "../lib/time";
import type { Entry } from "../lib/types";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface Props {
  open: boolean;
  commands: Command[];
  onClose: () => void;
  onOpenEntry: (entryId: string) => void;
}

type Row =
  | { type: "command"; command: Command }
  | { type: "entry"; entry: Entry };

/**
 * ⌘K — the primary navigation surface.
 *
 * Tilt has no toolbars and no sidebar, so this is how every feature is reached.
 * It searches commands and journal content in one list: you should not have to
 * know whether the thing you want is an action or a memory.
 */
export function CommandPalette({ open, commands, onClose, onOpenEntry }: Props) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Entry[]>([]);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setHits([]);
      setActive(0);
      // Wait for the element to exist before focusing it.
      requestAnimationFrame(() => input.current?.focus());
    }
  }, [open]);

  // Debounced search. 140ms is below the threshold where typing feels laggy but
  // high enough to avoid a request per keystroke.
  useEffect(() => {
    if (!open) return;
    const term = query.trim();
    if (!term) {
      setHits([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const found = await api.search(term, 8);
        if (!cancelled) setHits(found);
      } catch {
        if (!cancelled) setHits([]);
      }
    }, 140);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, open]);

  const rows = useMemo<Row[]>(() => {
    const term = query.trim().toLowerCase();
    const matched = term
      ? commands.filter((c) => c.label.toLowerCase().includes(term))
      : commands;
    return [
      ...matched.map((command) => ({ type: "command" as const, command })),
      ...hits.map((entry) => ({ type: "entry" as const, entry })),
    ];
  }, [commands, hits, query]);

  useEffect(() => {
    setActive((current) => Math.min(current, Math.max(rows.length - 1, 0)));
  }, [rows.length]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>('[data-active="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const choose = (row: Row) => {
    onClose();
    if (row.type === "command") row.command.run();
    else onOpenEntry(row.entry.id);
  };

  return (
    <div className="palette-scrim fade" onMouseDown={onClose} role="presentation">
      <div
        className="palette rise glass glass--heavy"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={input}
          className="palette__input"
          value={query}
          placeholder="Search or run a command"
          aria-label="Search or run a command"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((i) => (rows.length ? (i + 1) % rows.length : 0));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((i) => (rows.length ? (i - 1 + rows.length) % rows.length : 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              const row = rows[active];
              if (row) choose(row);
            }
          }}
        />

        {rows.length > 0 && (
          <ul className="palette__list scroll" ref={listRef} role="listbox">
            {rows.map((row, i) => {
              const isActive = i === active;
              const key = row.type === "command" ? row.command.id : row.entry.id;
              return (
                <li
                  key={key}
                  role="option"
                  aria-selected={isActive}
                  data-active={isActive}
                  className={`palette__row${isActive ? " palette__row--active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(row)}
                >
                  {row.type === "command" ? (
                    <>
                      <span className="palette__label">{row.command.label}</span>
                      {row.command.hint && (
                        <span className="micro palette__hint">{row.command.hint}</span>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="palette__label palette__label--entry">
                        {row.entry.body.slice(0, 90)}
                      </span>
                      <span className="micro tnum palette__hint">
                        {stamp(row.entry.created)}
                      </span>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {query.trim() && rows.length === 0 && (
          <p className="mono palette__none">No matches.</p>
        )}
      </div>
    </div>
  );
}
