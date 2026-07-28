import { useEffect, useRef, useState } from "react";

import { precise, stamp } from "../lib/time";
import type { Scope, Thread } from "../lib/types";
import { Connection } from "./Connection";
import { Reply, ReplyPending } from "./Reply";

interface Props {
  thread: Thread;
  reflecting: boolean;
  processing: boolean;
  onReflect: (id: string) => void;
  onConnect: (id: string) => void;
  onUpdate: (id: string, body: string) => void;
  onDelete: (id: string) => void;
  onDismissLink: (linkId: string) => void;
  onOpenEntry: (entryId: string) => void;
  onScope: (scope: Scope) => void;
}

/**
 * One thought and everything the machine said about it.
 *
 * Actions stay hidden until hover or keyboard focus. At rest the Stream is text
 * on a dark field and nothing else — no toolbars, no icon rows, no chrome
 * competing with what you wrote.
 */
export function EntryItem({
  thread,
  reflecting,
  processing,
  onReflect,
  onConnect,
  onUpdate,
  onDelete,
  onDismissLink,
  onOpenEntry,
  onScope,
}: Props) {
  const { entry, replies, themes, links } = thread;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.body);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const pending = entry.id.startsWith("pending-");

  useEffect(() => {
    if (!editing) return;
    const el = area.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [editing]);

  // A stray click should not silently arm a destructive action forever.
  useEffect(() => {
    if (!confirmingDelete) return;
    const timer = setTimeout(() => setConfirmingDelete(false), 4000);
    return () => clearTimeout(timer);
  }, [confirmingDelete]);

  const commit = () => {
    const next = draft.trim();
    if (next && next !== entry.body) onUpdate(entry.id, next);
    setEditing(false);
  };

  return (
    <article id={`entry-${entry.id}`} className={`entry${pending ? " entry--pending" : ""}`}>
      <header className="entry__meta">
        <time
          className="micro tnum entry__stamp"
          dateTime={entry.created}
          title={precise(entry.created)}
        >
          {stamp(entry.created)}
        </time>

        {themes.map((theme) => (
          <button
            key={theme.id}
            className="micro entry__folder"
            onClick={() => onScope({ type: "theme", id: theme.id, label: theme.label })}
            title={theme.description || `Show everything in ${theme.label}`}
          >
            {theme.label}
          </button>
        ))}

        {/* Filing runs on its own after an entry is kept; this says so
            without demanding attention. */}
        {processing && (
          <span className="micro entry__filing" aria-live="polite">
            filing<span className="cursor" aria-hidden="true">▍</span>
          </span>
        )}

        {!pending && (
          <div className="entry__actions">
            <button
              className="micro entry__action"
              onClick={() => onReflect(entry.id)}
              disabled={reflecting}
            >
              {reflecting ? "reflecting" : "reflect"}
            </button>
            <button
              className="micro entry__action"
              onClick={() => onConnect(entry.id)}
              disabled={processing}
            >
              connect
            </button>
            <button
              className="micro entry__action"
              onClick={() => {
                setDraft(entry.body);
                setEditing(true);
              }}
            >
              edit
            </button>
            <button
              className={`micro entry__action${confirmingDelete ? " entry__action--danger" : ""}`}
              onClick={() => {
                if (confirmingDelete) onDelete(entry.id);
                else setConfirmingDelete(true);
              }}
            >
              {confirmingDelete ? "confirm" : "delete"}
            </button>
          </div>
        )}
      </header>

      {editing ? (
        <textarea
          ref={area}
          className="entry__editor"
          value={draft}
          aria-label="Edit entry"
          onChange={(e) => {
            setDraft(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${e.target.scrollHeight}px`;
          }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setEditing(false);
            }
          }}
        />
      ) : (
        <div className="entry__body">
          {entry.body.split(/\n{2,}/).map((paragraph, i) => (
            <p key={i}>{paragraph}</p>
          ))}
        </div>
      )}

      {entry.tags.length > 0 && (
        <ul className="entry__tags">
          {entry.tags.map((tag) => (
            <li key={tag}>
              <button
                className="micro entry__tag"
                onClick={() => onScope({ type: "tag", tag })}
              >
                {tag}
              </button>
            </li>
          ))}
        </ul>
      )}

      {(replies.length > 0 || reflecting || links.length > 0) && (
        <div className="entry__replies">
          {links.map((linked) => (
            <Connection
              key={linked.link.id}
              linked={linked}
              onOpen={onOpenEntry}
              onDismiss={onDismissLink}
            />
          ))}
          {replies.map((reply) => (
            <Reply key={reply.id} entry={reply} />
          ))}
          {reflecting && <ReplyPending />}
        </div>
      )}
    </article>
  );
}
