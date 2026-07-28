import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

import { IconButton } from "./primitives";

export interface ComposerHandle {
  focus: () => void;
}

interface Props {
  onSubmit: (body: string) => Promise<void>;
  placeholder?: string;
  autoFocus?: boolean;
  compact?: boolean;
}

const MAX_LINES = 8;

/**
 * The writing surface, anchored at the bottom.
 *
 * Enter sends and Shift+Enter breaks the line — the chat convention the layout
 * implies. Escape blurs. The textarea has no border or fill of its own; the
 * composer's separation is a single hairline above it.
 *
 * The send control is an outlined circle, never filled with the accent. With
 * input present its border and glyph strengthen — that is the entire
 * affordance.
 */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { onSubmit, placeholder = "What are you thinking?", autoFocus, compact },
  ref,
) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus() }));

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    const line = parseFloat(getComputedStyle(el).lineHeight) || 24;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, line * MAX_LINES)}px`;
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

  const ready = value.trim().length > 0;

  return (
    <div className={"composer" + (compact ? " composer--compact" : "")}>
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
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void send();
          } else if (e.key === "Escape") {
            area.current?.blur();
          }
        }}
      />

      <div className="composer__bar">
        <div className="composer__left">
          <IconButton name="camera" label="Attach an image" outlined />
          <IconButton name="paperclip" label="Attach a file" outlined />
        </div>
        <div className="composer__right">
          <IconButton name="waveform" label="Dictate" />
          <IconButton
            name="arrow-up"
            label="Keep this entry"
            outlined
            ready={ready}
            disabled={!ready || busy}
            onClick={() => void send()}
          />
        </div>
      </div>
    </div>
  );
});
