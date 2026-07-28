import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

export interface ComposerHandle {
  focus: () => void;
}

interface Props {
  onSubmit: (body: string) => Promise<void>;
  placeholder?: string;
  autoFocus?: boolean;
  /** Compact styling for the quick-capture window. */
  compact?: boolean;
}

const MAX_ROWS_PX = 420;

/**
 * The writing surface.
 *
 * Auto-growing rather than scrolling, because a fixed-height box makes long
 * thoughts feel unwelcome. Enter inserts a newline and Cmd/Ctrl+Enter sends:
 * in a journal, paragraph breaks are far more common than submissions, so the
 * unmodified key belongs to the more frequent action.
 */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { onSubmit, placeholder = "What are you thinking?", autoFocus, compact },
  ref,
) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({
    focus: () => area.current?.focus(),
  }));

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS_PX)}px`;
  }, [value]);

  const send = async () => {
    const body = value.trim();
    if (!body || busy) return;
    setBusy(true);
    try {
      await onSubmit(body);
      setValue("");
    } catch {
      // The thought stays in the box so it is never lost to a failed request.
    } finally {
      setBusy(false);
      area.current?.focus();
    }
  };

  return (
    <div className={`composer${compact ? " composer--compact" : ""}`}>
      <textarea
        ref={area}
        className="composer__input"
        value={value}
        rows={1}
        autoFocus={autoFocus}
        spellCheck
        placeholder={placeholder}
        aria-label="Write an entry"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void send();
          }
        }}
      />
      <div className="composer__footer">
        <span className="micro composer__hint">
          {value.trim() ? "⌘↵ to keep" : "⌘K for commands"}
        </span>
        <button
          className="composer__send mono"
          onClick={() => void send()}
          disabled={!value.trim() || busy}
        >
          {busy ? "keeping…" : "Keep"}
        </button>
      </div>
    </div>
  );
});
