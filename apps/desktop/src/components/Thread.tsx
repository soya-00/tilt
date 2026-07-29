/**
 * The thread: date groups, entries, and agent replies.
 *
 * Rows sit in a 40px dot gutter with a connector running between consecutive
 * dots. Your own entries are plain text — no bubble, no fill, no shadow. Agent
 * replies get a hairline-outlined bubble with a transparent background, so the
 * difference reads as containment rather than colour.
 */

import { useEffect, useState } from "react";

import { tagStyle } from "../lib/tagColor";
import { precise, stamp } from "../lib/time";
import { useIsDark } from "../lib/useTheme";
import type { Entry, LinkKind, LinkedEntry, Scope, Thread } from "../lib/types";
import { Icon } from "./Icon";
import { Avatar } from "./primitives";

/* ------------------------------------------------------------------ DatePill */

export function DatePill({ label }: { label: string }) {
  return (
    <div className="date-rule">
      <span className="date-rule__line" />
      <span className="date-pill">{label}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ EntryRow */

interface EntryRowProps {
  entry: Entry;
  themes: Thread["themes"];
  connected: boolean;
  onScope: (scope: Scope) => void;
  onReflect: (id: string) => void;
  onEdit: (id: string, body: string) => void;
  onDelete: (id: string) => void;
}

export function EntryRow({
  entry,
  themes,
  connected,
  onScope,
  onReflect,
  onEdit,
  onDelete,
}: EntryRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.body);
  const [confirming, setConfirming] = useState(false);
  const pending = entry.id.startsWith("pending-");
  const dark = useIsDark();

  useEffect(() => {
    if (!confirming) return;
    const t = setTimeout(() => setConfirming(false), 4000);
    return () => clearTimeout(t);
  }, [confirming]);

  const commit = () => {
    const next = draft.trim();
    if (next && next !== entry.body) onEdit(entry.id, next);
    setEditing(false);
  };

  return (
    <article id={`entry-${entry.id}`} className={"row" + (pending ? " row--pending" : "")}>
      <span className="row__gutter">
        <span className="row__dot" />
        {connected && <span className="row__connector" />}
      </span>

      <div className="row__main">
        {editing ? (
          <textarea
            className="row__editor"
            autoFocus
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
          <div className="row__text">
            {entry.body.split(/\n{2,}/).map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
        )}

        {(themes.length > 0 || entry.tags.length > 0) && (
          <div className="row__meta">
            {themes.map((t) => (
              <button
                key={t.id}
                className="chip"
                onClick={() => onScope({ type: "theme", id: t.id, label: t.label })}
              >
                {t.label}
              </button>
            ))}
            {entry.tags.map((tag) => (
              <button
                key={tag}
                className="chip chip--tag"
                style={tagStyle(tag, dark)}
                onClick={() => onScope({ type: "tag", tag })}
              >
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="row__aside">
        <time className="row__time" dateTime={entry.created} title={precise(entry.created)}>
          {stamp(entry.created)}
        </time>
        {!pending && (
          <div className="row__actions">
            <button className="row__action" onClick={() => onReflect(entry.id)}>
              reflect
            </button>
            <button
              className="row__action"
              onClick={() => {
                setDraft(entry.body);
                setEditing(true);
              }}
            >
              edit
            </button>
            <button
              className={"row__action" + (confirming ? " row__action--armed" : "")}
              onClick={() => (confirming ? onDelete(entry.id) : setConfirming(true))}
            >
              {confirming ? "confirm" : "delete"}
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

/* ------------------------------------------------------------------ ReplyRow */

const KIND_LABEL: Record<LinkKind, string> = {
  echo: "echoes",
  elaboration: "builds on",
  // Kept for the writer disagreeing with the writer. Something they only read
  // pulling the other way is a counterpoint — worth holding, not a mistake.
  contradiction: "contradicts",
  counterpoint: "offers a counterpoint to",
  bridge: "bridges to",
};

/**
 * Reveals text word by word so it reads as being thought rather than pasted.
 *
 * The backend returns a whole reply at once, so this is a reveal rather than
 * true streaming — an honest distinction, but the perceptual effect is the one
 * the design is after. Under reduced motion it lands fully opaque immediately.
 */
function useWordReveal(text: string, active: boolean): number {
  const words = text.split(/\s+/).length;
  const [landed, setLanded] = useState(active ? 0 : words);

  useEffect(() => {
    if (!active) {
      setLanded(words);
      return;
    }
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setLanded(words);
      return;
    }
    setLanded(0);
    const timer = setInterval(() => {
      setLanded((n) => {
        if (n >= words) {
          clearInterval(timer);
          return n;
        }
        return n + 1;
      });
    }, 40);
    return () => clearInterval(timer);
  }, [text, active, words]);

  return landed;
}

/** What the machine's contribution should be called under a bubble. */
function attributionFor(entry: Entry): string {
  if (entry.kind === "card") return entry.reply_kind === "question" ? "open question" : "idea";
  return entry.reply_kind ?? "reflection";
}

interface ReplyRowProps {
  entry: Entry;
  fresh: boolean;
  connected: boolean;
}

export function ReplyRow({ entry, fresh, connected }: ReplyRowProps) {
  const landed = useWordReveal(entry.body, fresh);
  const words = entry.body.split(/(\s+)/);
  let index = 0;

  return (
    <article className="row row--reply">
      <span className="row__gutter">
        <span className="row__dot" />
        {connected && <span className="row__connector" />}
      </span>

      <div className="row__main">
        <div className="bubble">
          {words.map((w, i) => {
            if (/^\s+$/.test(w)) return w;
            const settled = index++ < landed;
            return (
              <span key={i} className={settled ? "word" : "word word--pending"}>
                {w}
              </span>
            );
          })}
        </div>
        <div className="attribution">
          <Avatar icon="spark" size={20} />
          <span>{attributionFor(entry)}</span>
        </div>
      </div>

      <div className="row__aside">
        <time className="row__time" dateTime={entry.created}>
          {stamp(entry.created)}
        </time>
      </div>
    </article>
  );
}

/* ---------------------------------------------------------------- ConnectionRow */

interface ConnectionRowProps {
  linked: LinkedEntry;
  connected: boolean;
  onOpen: (id: string) => void;
  onDismiss: (id: string) => void;
}

export function ConnectionRow({ linked, connected, onOpen, onDismiss }: ConnectionRowProps) {
  const { link, entry } = linked;

  return (
    <article className="row row--reply">
      <span className="row__gutter">
        <span className="row__dot" />
        {connected && <span className="row__connector" />}
      </span>

      <div className="row__main">
        <div className="bubble bubble--connection">
          <button className="connection-quote" onClick={() => onOpen(entry.id)}>
            <span className="connection-kind">
              <Icon name="link" size={15} />
              {KIND_LABEL[link.kind]}
            </span>
            {entry.body.slice(0, 150)}
          </button>
          {link.rationale && <p className="connection-why">{link.rationale}</p>}
        </div>
        <div className="attribution">
          <Avatar icon="spark" size={20} />
          <span>connection</span>
          <button className="attribution__action" onClick={() => onDismiss(link.id)}>
            dismiss
          </button>
        </div>
      </div>

      <div className="row__aside">
        <time className="row__time" dateTime={entry.created}>
          {stamp(entry.created)}
        </time>
      </div>
    </article>
  );
}
