import type { Entry } from "../lib/types";

/**
 * Machine output, threaded under its entry.
 *
 * Set entirely in mono and marked with a hairline accent rule. There is no
 * badge, avatar, or "AI" label anywhere: the typeface already says this is not
 * you, which is the whole point of the two-voice type system.
 */
export function Reply({ entry }: { entry: Entry }) {
  const label = entry.reply_kind ?? "reflection";
  const paragraphs = entry.body.split(/\n{2,}/).filter(Boolean);
  const note = paragraphs.at(-1)?.startsWith("[") ? paragraphs.pop() : undefined;

  return (
    <article className="reply rise" aria-label={`${label} on this entry`}>
      <span className="micro reply__label">{label}</span>
      <div className="reply__body mono">
        {paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
        {note && <p className="reply__note">{note}</p>}
      </div>
    </article>
  );
}

/** Placeholder shown while a reflection is in flight. */
export function ReplyPending() {
  return (
    <article className="reply reply--pending fade" aria-live="polite">
      <span className="micro reply__label">reflecting</span>
      <div className="reply__body mono">
        <p>
          <span className="cursor" aria-hidden="true">
            ▍
          </span>
          <span className="visually-hidden">Thinking</span>
        </p>
      </div>
    </article>
  );
}
