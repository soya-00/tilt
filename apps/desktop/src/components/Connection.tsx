import { stamp } from "../lib/time";
import type { LinkKind, LinkedEntry } from "../lib/types";

const KIND_LABEL: Record<LinkKind, string> = {
  echo: "echoes",
  elaboration: "builds on",
  contradiction: "contradicts",
  bridge: "bridges to",
};

interface Props {
  linked: LinkedEntry;
  onOpen: (entryId: string) => void;
  onDismiss: (linkId: string) => void;
}

/**
 * A connection the agent found, threaded under the entry it belongs to.
 *
 * Dismissal is deliberately easy and one click. A connector that cannot be
 * corrected is a connector you stop trusting, and every dismissal is recorded
 * so the same pair is never proposed again.
 */
export function Connection({ linked, onOpen, onDismiss }: Props) {
  const { link, entry } = linked;

  return (
    <article className={`connection connection--${link.kind} rise`}>
      <header className="connection__head">
        <span className="micro connection__kind">{KIND_LABEL[link.kind]}</span>
        <time className="micro tnum connection__stamp" dateTime={entry.created}>
          {stamp(entry.created)}
        </time>
        <button
          className="micro connection__dismiss"
          onClick={() => onDismiss(link.id)}
          aria-label="Dismiss this connection"
        >
          dismiss
        </button>
      </header>

      <button className="connection__body" onClick={() => onOpen(entry.id)}>
        <span className="connection__quote">{entry.body.slice(0, 160)}</span>
      </button>

      {link.rationale && <p className="mono connection__rationale">{link.rationale}</p>}
    </article>
  );
}
