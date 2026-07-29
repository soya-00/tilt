/**
 * The brief — reading that has not happened yet.
 *
 * Two-way on purpose. The scout puts things here; so do you, and the two look
 * the same once they land, because a link you saved on Tuesday and one the
 * agent found are both just candidates. Only the "from" line distinguishes
 * them, and only so you know whose idea it was.
 *
 * Deliberately not a to-do list, and the design carries that rather than a
 * disclaimer. There is no tick box, no count of what is outstanding, no order
 * you are meant to work through. Three things happen to an item: you read it,
 * which turns it into a source entry and takes it off this list; you dismiss
 * it; or it sits there, which is not a failure and is never dressed up as one.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { BriefItem } from "../lib/types";
import { stamp } from "../lib/time";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Something was read and is now in the journal, so the Stream is stale. */
  onRead: () => void;
}

/** The host, which is all of a URL worth showing beside a title. */
function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 40);
  }
}

export function Brief({ open, onClose, onRead }: Props) {
  const [items, setItems] = useState<BriefItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [url, setUrl] = useState("");
  const [why, setWhy] = useState("");
  /** The id currently being distilled. One at a time: reading is the expensive
   *  call, and firing three at once is a way to spend a dollar by accident. */
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

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

  if (!open) return null;

  const add = async () => {
    if (!url.trim() && !why.trim()) return;
    setError("");
    try {
      const item = await api.addToBrief({ url: url.trim(), why: why.trim() });
      setUrl("");
      setWhy("");
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
          <h2 className="sheet__title">Brief</h2>
          <p className="sheet__version">reading, not yet read</p>
          <button className="icon-btn" aria-label="Close" onClick={onClose} disabled={!!busy}>
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="sheet__body sheet__body--grow scroll">
          <section className="sheet__section brief__add">
            <input
              className="field__input"
              value={url}
              placeholder="A link you have been meaning to read"
              aria-label="Link to add"
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void add()}
            />
            <input
              className="field__input"
              value={why}
              placeholder="Why — or just a note to yourself, if there is no link"
              aria-label="Why this is here"
              onChange={(e) => setWhy(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void add()}
            />
            <div className="sheet__foot">
              <button
                className="ghost-btn"
                onClick={() => void add()}
                disabled={!url.trim() && !why.trim()}
              >
                Add
              </button>
            </div>
          </section>

          {error && (
            <p className="sheet__note brief__error" role="alert">
              {error}
            </p>
          )}

          {items.length === 0 && !loading ? (
            <section className="sheet__section">
              {/* Not "you're all caught up". Empty is the resting state of a
                  shelf, and congratulating someone for it would make this the
                  inbox it is designed not to be. */}
              <p className="sheet__note sheet__note--quiet">
                Nothing waiting. Add a link above, or leave it — the scout looks once a
                day and most days it finds nothing worth your time.
              </p>
            </section>
          ) : (
            <ul className="brief__list">
              {items.map((item) => (
                <li key={item.id} className="brief__item stagger">
                  <p className="brief__title">
                    {item.url ? (
                      <a href={item.url} target="_blank" rel="noreferrer noopener">
                        {item.title || host(item.url)}
                      </a>
                    ) : (
                      item.title || item.why
                    )}
                  </p>
                  {item.why && (item.title || item.url) && (
                    <p className="brief__why">{item.why}</p>
                  )}

                  {/* The actions sit on the meta line rather than in a column
                      of their own. A column would take its width from every row
                      whether or not it is showing, and the titles — the thing
                      you are actually here to read — would wrap around it. */}
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
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="sheet__foot sheet__foot--note">
          <p className="sheet__note sheet__note--quiet">
            Nothing here is in your journal. Reading one distils it into the Stream;
            everything else stays a candidate.
          </p>
        </footer>
      </div>
    </div>
  );
}
