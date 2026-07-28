import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

import { useLiquidGlass } from "../lib/useLiquidGlass";
import { IconButton } from "./primitives";

export interface ComposerHandle {
  focus: () => void;
}

interface Props {
  onSubmit: (body: string) => Promise<void>;
  placeholder?: string;
  autoFocus?: boolean;
  compact?: boolean;
  /** Opens the source sheet, optionally pre-filled from a picked file. */
  onAddSource?: (prefill?: { title: string; text: string }) => void;
}

/** Text-like files we can read in the browser without a parser. */
const TEXT_TYPES = [".txt", ".md", ".markdown", ".srt", ".vtt", ".csv", ".json", ".log"];

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
  { onSubmit, placeholder = "What are you thinking?", autoFocus, compact, onAddSource },
  ref,
) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [rejected, setRejected] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const filePicker = useRef<HTMLInputElement>(null);
  const glass = useLiquidGlass<HTMLDivElement>();

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

  const takeFile = async (file: File | undefined) => {
    if (!file) return;
    const named = file.name.toLowerCase();
    if (!TEXT_TYPES.some((ext) => named.endsWith(ext)) && !file.type.startsWith("text/")) {
      // Be explicit rather than silently doing nothing: PDFs and audio need a
      // parser Tilt does not have yet.
      setRejected(`${file.name} is not a text file. Paste its contents instead.`);
      return;
    }
    setRejected(null);
    const text = await file.text();
    onAddSource?.({ title: file.name.replace(/\.[^.]+$/, ""), text });
  };

  const ready = value.trim().length > 0;

  return (
    <div
      ref={glass.ref}
      className={"composer glass-live" + (compact ? " composer--compact" : "")}
      onPointerMove={glass.onPointerMove}
      onPointerLeave={glass.onPointerLeave}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        void takeFile(e.dataTransfer.files?.[0]);
      }}
    >
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
          <input
            ref={filePicker}
            type="file"
            className="visually-hidden"
            accept=".txt,.md,.markdown,.srt,.vtt,.csv,.json,.log,text/*"
            onChange={(e) => {
              void takeFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <IconButton
            name="paperclip"
            label="Attach a text file"
            outlined
            onClick={() => filePicker.current?.click()}
          />
          <IconButton
            name="folder"
            label="Add source material"
            outlined
            onClick={() => onAddSource?.()}
          />
        </div>
        <div className="composer__right">
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

      {rejected && (
        <p className="composer__reject" role="alert">
          {rejected}
        </p>
      )}
    </div>
  );
});
