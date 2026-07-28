import { useEffect, useState } from "react";

import { useLiquidGlass } from "../lib/useLiquidGlass";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  /** Pre-filled when the sheet was opened by dropping or picking a file. */
  initial?: { title: string; text: string } | null;
  onClose: () => void;
  onIngest: (payload: { title: string; text: string; url?: string }) => Promise<void>;
}

const WARN_CHARS = 24_000;

/**
 * Adding long source material — a transcript, an article, pasted notes.
 *
 * Deliberately separate from the composer. A transcript is not a thought, and
 * putting it through the same path would flood the Stream with material you
 * did not write. This produces one source entry with its ideas nested inside.
 */
export function SourceSheet({ open, initial, onClose, onIngest }: Props) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const glass = useLiquidGlass<HTMLDivElement>();

  useEffect(() => {
    if (!open) return;
    setTitle(initial?.title ?? "");
    setText(initial?.text ?? "");
    setUrl("");
  }, [open, initial]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onClose]);

  if (!open) return null;

  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      await onIngest({ title: title.trim(), text, ...(url.trim() ? { url: url.trim() } : {}) });
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const chars = text.length;

  return (
    <div className="sheet-scrim fade" onMouseDown={() => !busy && onClose()} role="presentation">
      <div
        ref={glass.ref}
        className="sheet sheet--wide glass-live"
        role="dialog"
        aria-modal="true"
        aria-label="Add source material"
        onMouseDown={(e) => e.stopPropagation()}
        onPointerMove={glass.onPointerMove}
        onPointerLeave={glass.onPointerLeave}
      >
        <header className="sheet__head">
          <h2 className="sheet__title">Add source</h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose} disabled={busy}>
            <Icon name="close" size={18} />
          </button>
        </header>

        <section className="sheet__section">
          <input
            className="field__input"
            value={title}
            placeholder="Title — what is this?"
            aria-label="Source title"
            onChange={(e) => setTitle(e.target.value)}
          />
        </section>

        <section className="sheet__section sheet__section--grow">
          <textarea
            className="field__input field__input--source"
            value={text}
            placeholder="Paste a transcript, an article, or notes…"
            aria-label="Source text"
            onChange={(e) => setText(e.target.value)}
          />
          <p className="sheet__note sheet__note--quiet">
            {chars.toLocaleString()} characters
            {chars > WARN_CHARS && (
              <>
                {" — "}
                only the opening and closing {WARN_CHARS.toLocaleString()} go to the model, but
                the full text is saved beside your journal.
              </>
            )}
          </p>
        </section>

        <section className="sheet__section">
          <input
            className="field__input"
            value={url}
            placeholder="Where it came from (optional)"
            aria-label="Source URL"
            onChange={(e) => setUrl(e.target.value)}
          />
        </section>

        <footer className="sheet__foot">
          <button className="ghost-btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="ghost-btn ghost-btn--primary"
            onClick={() => void submit()}
            disabled={!text.trim() || busy}
          >
            {busy ? "Distilling…" : "Distil"}
          </button>
        </footer>
      </div>
    </div>
  );
}
