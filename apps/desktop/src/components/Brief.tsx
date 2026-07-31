/**
 * The brief — reading that has not happened yet.
 *
 * Built out of the Stream's vocabulary rather than its own: the same dot rail,
 * the same borderless composer, the same tag chips. A candidate is a thought
 * you have not had yet, and it should look like one.
 *
 * Two-way on purpose. The scout puts things here; so do you, and the two look
 * the same once they land, because a link you saved on Tuesday and one the
 * agent found are both just candidates. Only the "from" line distinguishes
 * them, and only so you know whose idea it was.
 *
 * Deliberately not a to-do list, and the design carries that rather than a
 * disclaimer. No tick box, no count of what is outstanding, no order you are
 * meant to work through. Three things happen to an item: you read it, which
 * turns it into a source entry and takes it off this list; you dismiss it; or
 * it sits there, which is not a failure and is never dressed up as one.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { compose, findUrl } from "../lib/compose";
import { openExternal } from "../lib/shell";
import { tagStyle } from "../lib/tagColor";
import { stamp } from "../lib/time";
import type { BriefItem, Scope } from "../lib/types";
import { useIsDark } from "../lib/useTheme";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Something was read and is now in the journal, so the Stream is stale. */
  onRead: () => void;
  /** Clicking a tag goes to what you have already written under it. */
  onScope: (scope: Scope) => void;
}

const MAX_LINES = 6;

/** The host, which is all of a URL worth showing beside a title. */
function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 40);
  }
}

export function Brief({ open, onClose, onRead, onScope }: Props) {
  const dark = useIsDark();
  const [items, setItems] = useState<BriefItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  /** The id currently being distilled. One at a time: reading is the expensive
   *  call, and firing three at once is a way to spend a dollar by accident. */
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.brief());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the brief.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onClose]);

  // Grows with what you type, like the composer downstairs.
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    const line = parseFloat(getComputedStyle(el).lineHeight) || 24;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, line * MAX_LINES)}px`;
  }, [note, open]);

  if (!open) return null;

  const typed = findUrl(note);
  const ready = Boolean(note.trim() || title.trim());

  const add = async () => {
    if (!ready) return;
    setError("");
    const { url, tags, why } = compose(note);
    try {
      const item = await api.addToBrief({ url, tags, why, title: title.trim() });
      setTitle("");
      setNote("");
      // Replace rather than prepend: adding something already here returns the
      // one already here, and two copies of the same row would be a lie.
      setItems((current) => [item, ...current.filter((i) => i.id !== item.id)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add that.");
    }
  };

  const read = async (item: BriefItem) => {
    if (busy) return;
    setBusy(item.id);
    setError("");
    try {
      await api.readBriefItem(item.id);
      setItems((current) => current.filter((i) => i.id !== item.id));
      onRead();
    } catch (err) {
      // The item stays. A failed reading must not quietly consume the thing
      // you asked to read.
      setError(err instanceof Error ? err.message : "That could not be read.");
    } finally {
      setBusy(null);
    }
  };

  const dismiss = async (item: BriefItem) => {
    setItems((current) => current.filter((i) => i.id !== item.id));
    try {
      await api.dismissBriefItem(item.id);
    } catch {
      void load();
    }
  };

  const goToTag = (tag: string) => {
    onScope({ type: "tag", tag });
    onClose();
  };

  return (
    <div className="sheet-scrim fade" onMouseDown={() => !busy && onClose()} role="presentation">
      <div
        className="sheet sheet--wide glass glass--heavy"
        role="dialog"
        aria-modal="true"
        aria-label="Brief"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="sheet__head">
          <h2 className="sheet__title sheet__title--wide">Brief</h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose} disabled={!!busy}>
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="sheet__body sheet__body--grow scroll">
          {items.length === 0 && !loading ? (
            <section className="sheet__section">
              {/* Not "you're all caught up". Empty is the resting state of a
                  shelf, and congratulating someone for it would make this the
                  inbox it is designed not to be. */}
              <p className="sheet__note sheet__note--quiet">
                Nothing waiting. Add something below, or leave it — the scout looks once
                a day and most days it finds nothing worth your time. Nothing here is in
                your journal until you read it.
              </p>
            </section>
          ) : (
            <ul className="brief__list">
              {items.map((item) => (
                <li key={item.id} className="brief__item stagger">
                  {/* The Stream's own gutter and dot, not a copy of them. No
                      connector: that line means "these belong to one thread",
                      and these are independent of each other. */}
                  <span className="row__gutter">
                    <span className="row__dot" />
                  </span>

                  <div className="brief__main">
                    <p className="brief__title">
                      {item.url ? (
                        <a
                          href={item.url}
                          onClick={(e) => {
                            e.preventDefault();
                            void openExternal(item.url ?? "");
                          }}
                        >
                          {item.title || host(item.url)}
                        </a>
                      ) : (
                        item.title || item.why
                      )}
                    </p>
                    {item.why && (item.title || item.url) && (
                      <p className="brief__why">{item.why}</p>
                    )}

                    {item.tags.length > 0 && (
                      <div className="brief__tags">
                        {item.tags.map((tag) => (
                          <button
                            key={tag}
                            className="chip chip--tag"
                            style={tagStyle(tag, dark)}
                            title={`Everything tagged ${tag}`}
                            onClick={() => goToTag(tag)}
                          >
                            {tag}
                          </button>
                        ))}
                      </div>
                    )}

                    <div className="brief__foot">
                      <p className="brief__meta">
                        {item.origin === "scout" ? "found for you" : "yours"}
                        {item.url && ` · ${host(item.url)}`} · {stamp(item.created)}
                      </p>
                      <div className="brief__actions">
                        {item.url && (
                          <button
                            className="link-btn"
                            onClick={() => void read(item)}
                            disabled={!!busy}
                            title="Read it and distil it into the journal"
                          >
                            {busy === item.id ? "Reading…" : "Read"}
                          </button>
                        )}
                        <button
                          className="link-btn link-btn--quiet"
                          onClick={() => void dismiss(item)}
                          disabled={!!busy}
                          title="Not this one — and do not offer it again"
                        >
                          Dismiss
                        </button>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {error && (
            <p className="sheet__note brief__error" role="alert">
              {error}
            </p>
          )}
        </div>

        {/* One box, nothing labelled. A form with a URL field and a tag field is
            a form, and nobody fills one in to save a link they meant to read. */}
        <div className="brief__compose">
          <input
            className="brief__compose-title"
            value={title}
            placeholder="Title — what is this?"
            aria-label="Title"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                area.current?.focus();
              }
            }}
          />
          <textarea
            ref={area}
            className="composer__input brief__compose-note"
            value={note}
            rows={1}
            spellCheck
            placeholder="Why you want to read it. Paste a link anywhere, and #tag it."
            aria-label="Why this is here"
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void add();
              }
            }}
          />
          <div className="brief__compose-bar">
            <button
              className="ghost-btn"
              disabled={!typed}
              title={typed ? `Open ${host(typed)}` : "Paste a link to open it"}
              onClick={() => void openExternal(typed)}
            >
              Open
            </button>
            <button className="ghost-btn ghost-btn--primary" disabled={!ready} onClick={() => void add()}>
              Add
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
