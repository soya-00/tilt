import { useState } from "react";

import { api } from "../../lib/api";
import { quitShell } from "../../lib/shell";
import type { Status } from "../../lib/types";

interface Props {
  status: Status | null;
  onForgetKey: () => Promise<void>;
}

const WORD = "DELETE";

/**
 * The three things that take something away, and they are not alike.
 *
 * Rebuilding the index is the documented recovery step and destroys nothing —
 * it sits above the line with the ordinary controls. Forgetting the key is
 * reversible by pasting it back. Deleting everything is neither, and is the
 * only thing in the app that removes writing.
 *
 * The confirmation is a typed word rather than a second click. A second click
 * is reachable by a double-fire, a replayed request, or a handler wired to the
 * wrong element; typing DELETE is reachable only on purpose.
 */
export function Danger({ status, onForgetKey }: Props) {
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuilt, setRebuilt] = useState<number | null>(null);
  const [forgetting, setForgetting] = useState(false);
  const [typed, setTyped] = useState("");
  const [erasing, setErasing] = useState(false);
  const [erased, setErased] = useState(false);
  const [error, setError] = useState("");

  const rebuild = async () => {
    setRebuilding(true);
    try {
      setRebuilt((await api.rebuildIndex()).indexed);
    } finally {
      setRebuilding(false);
    }
  };

  const forget = async () => {
    setForgetting(true);
    try {
      await onForgetKey();
    } finally {
      setForgetting(false);
    }
  };

  const erase = async () => {
    setErasing(true);
    setError("");
    try {
      await api.erase(WORD);
      setErased(true);
      // The service has stopped and the journal is gone; there is nothing left
      // for this window to be a window onto. In a browser this does nothing and
      // the sentence below is the whole answer.
      void quitShell();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing was deleted.");
    } finally {
      setErasing(false);
    }
  };

  // Nothing else on screen matters once the journal is gone, including the rest
  // of this sheet. The service has stopped; the shell may or may not have taken
  // the hint, so this says what to do either way rather than assuming.
  if (erased) {
    return (
      <section className="sheet__section">
        <h3 className="sheet__label">Erased</h3>
        <p className="sheet__note">
          Your journal and everything derived from it have been deleted, and Tilt has stopped.
          Quit and reopen to start again.
        </p>
      </section>
    );
  }

  return (
    <>
      <section className="sheet__section">
        <h3 className="sheet__label">Rebuild the index</h3>
        <p className="sheet__note">
          Re-reads every Markdown file and rebuilds the database from it. Destroys nothing —
          this is the fix when search or the sidebar looks wrong.
        </p>
        <div className="panel__actions">
          <button className="ghost-btn" onClick={() => void rebuild()} disabled={rebuilding}>
            {rebuilding ? "Rebuilding…" : "Rebuild"}
          </button>
          {rebuilt !== null && (
            <span className="sheet__note sheet__note--quiet">{rebuilt} entries read back</span>
          )}
        </div>
      </section>

      <section className="sheet__section">
        <h3 className="sheet__label">Forget the API key</h3>
        <p className="sheet__note">
          Removes it from{" "}
          {status?.key_storage === "keychain" ? "your login keychain" : "the settings file"}.
          Tilt keeps working offline. Paste the key back in to undo this.
        </p>
        <div className="panel__actions">
          <button className="ghost-btn" onClick={() => void forget()} disabled={forgetting}>
            {forgetting ? "Forgetting…" : "Forget it"}
          </button>
        </div>
      </section>

      <hr className="panel__rule" />

      <section className="sheet__section">
        <h3 className="sheet__label sheet__label--danger">Delete everything</h3>
        <p className="sheet__note">
          Every entry, folder, connection, diagram and saved reading, plus the database and the
          settings. This cannot be undone and there is no copy anywhere else.
        </p>
        {/* The path, because the folder may be in Dropbox, iCloud or a git
            repository — in which case this deletes it there too, and the only
            way to know that is to be shown which folder it is. */}
        <p className="sheet__note sheet__note--quiet">
          Deletes <code>{status?.data_dir ?? "your journal folder"}</code> and the app's support
          folder.
        </p>
        <input
          className="field__input"
          value={typed}
          spellCheck={false}
          autoComplete="off"
          placeholder={`Type ${WORD} to confirm`}
          aria-label={`Type ${WORD} to confirm deleting everything`}
          onChange={(e) => setTyped(e.target.value)}
        />
        {error && <p className="sheet__note sheet__note--danger">{error}</p>}
        <div className="panel__actions">
          <button
            className="ghost-btn ghost-btn--danger"
            disabled={typed !== WORD || erasing}
            onClick={() => void erase()}
          >
            {erasing ? "Deleting…" : "Delete everything"}
          </button>
        </div>
      </section>
    </>
  );
}
