import { useCallback, useEffect, useState } from "react";

import { api } from "../../lib/api";
import { quitShell } from "../../lib/shell";
import type { Decisions, Status } from "../../lib/types";

interface Props {
  status: Status | null;
}

const WORD = "REPLACE";

/**
 * Where your journal actually is, how to carry it somewhere else, and what you
 * have told the keeper about your folders.
 *
 * The strongest claim this app makes is that your writing is a folder of
 * Markdown you own rather than rows in somebody's database. Until now nothing
 * in the interface said where that folder is, and two things you had authored —
 * your feeds and your model — were not in it. A promise you have to read the
 * source to verify is not much of a promise.
 */
export function Journal({ status }: Props) {
  const [decisions, setDecisions] = useState<Decisions | null>(null);
  const [exported, setExported] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [source, setSource] = useState("");
  const [typed, setTyped] = useState("");
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setDecisions(await api.folderDecisions());
    } catch {
      /* Ambient. A panel that cannot list your pins should still show the path. */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runExport = async () => {
    setExporting(true);
    setError("");
    try {
      setExported((await api.exportArchive()).path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The export did not finish.");
    } finally {
      setExporting(false);
    }
  };

  const runImport = async () => {
    setImporting(true);
    setError("");
    try {
      await api.importArchive(source.trim(), WORD);
      setImported(true);
      // Same as an erase: the service has stopped, and what is on disk now is
      // not what this process opened.
      void quitShell();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing was replaced.");
    } finally {
      setImporting(false);
    }
  };

  if (imported) {
    return (
      <section className="sheet__section">
        <h3 className="sheet__label">Imported</h3>
        <p className="sheet__note">
          Your journal has been replaced and Tilt has stopped. Quit and reopen — everything,
          including the vectors, is read fresh on the next start.
        </p>
      </section>
    );
  }

  return (
    <>
      <section className="sheet__section">
        <h3 className="sheet__label">Where it lives</h3>
        <p className="sheet__note">
          Everything you have written is plain Markdown here, one file per entry, with folders
          and connections in each file's own frontmatter — and your feeds and model beside them.
          Open it, grep it, edit it, put it in git. Copy this folder to another machine and it
          is your whole journal.
        </p>
        <p className="sheet__path">
          <code>{status?.data_dir ?? "…"}</code>
        </p>
        {/* Named from what actually happened rather than described in general.
            "Or in a file" is no use to somebody deciding whether to hand this
            folder to Dropbox. */}
        <p className="sheet__note sheet__note--quiet">
          Not in it: the database, which rebuilds from your Markdown for nothing, the vectors,
          which would have to be bought again, and your API key —{" "}
          {status?.key_storage === "memory"
            ? "held in memory for this session and never written down at all"
            : status?.key_storage === "keychain"
              ? "in your login keychain"
              : "in a file in the support folder, since this machine has no keychain"}
          .
        </p>
      </section>

      <section className="sheet__section">
        <h3 className="sheet__label">Take it with you</h3>
        <p className="sheet__note">
          Writes one file holding the journal and the vectors — never the key. It goes to your
          Downloads folder rather than beside your journal, because journals usually live
          somewhere synced and an archive next to one would quietly upload a second copy of
          everything.
        </p>
        <p className="sheet__note sheet__note--quiet">
          Outside both folders Tilt owns, so <em>Delete everything</em> leaves it alone. That is
          the point of it.
        </p>
        <div className="panel__actions">
          <button className="ghost-btn" onClick={() => void runExport()} disabled={exporting}>
            {exporting ? "Writing…" : "Export"}
          </button>
        </div>
        {exported && (
          <p className="sheet__path">
            <code>{exported}</code>
          </p>
        )}
      </section>

      <section className="sheet__section">
        <h3 className="sheet__label">Bring one back</h3>
        <p className="sheet__note">
          Replaces everything here with the contents of an archive, then stops so the next start
          reads it clean. It replaces rather than merges — two journals both written to is sync
          by another name, and Tilt does not do that.
        </p>
        <input
          className="field__input"
          value={source}
          spellCheck={false}
          placeholder="Path to a tilt-….zip"
          aria-label="Path to an archive"
          onChange={(e) => setSource(e.target.value)}
        />
        <input
          className="field__input"
          value={typed}
          spellCheck={false}
          autoComplete="off"
          placeholder={`Type ${WORD} to confirm`}
          aria-label={`Type ${WORD} to confirm replacing this journal`}
          onChange={(e) => setTyped(e.target.value)}
        />
        {error && <p className="sheet__note sheet__note--danger">{error}</p>}
        <div className="panel__actions">
          <button
            className="ghost-btn ghost-btn--danger"
            disabled={!source.trim() || typed !== WORD || importing}
            onClick={() => void runImport()}
          >
            {importing ? "Replacing…" : "Replace this journal"}
          </button>
        </div>
      </section>

      <section className="sheet__section">
        <h3 className="sheet__label">What you have ruled on</h3>
        {decisions?.pinned.length || decisions?.declined.length || decisions?.refused.length ? (
          <ul className="decisions">
            {decisions.pinned.map((label) => (
              <li key={`pin-${label}`} className="decision">
                <span className="decision__what">
                  <strong>{label}</strong> keeps the name you gave it
                </span>
                <button
                  className="decision__undo"
                  onClick={() => void api.unpinFolder(label).then(load)}
                >
                  let the agent rename it
                </button>
              </li>
            ))}
            {decisions.declined.map((item) => (
              <li key={`split-${item.folder}`} className="decision">
                <span className="decision__what">
                  <strong>{item.folder}</strong> was not split, at {item.at} entries
                </span>
                <button
                  className="decision__undo"
                  onClick={() => void api.askAgainAbout(item.folder).then(load)}
                >
                  ask me again
                </button>
              </li>
            ))}
            {/* The entry rather than its id, because a refusal is the only one
                of these three that is about something you wrote. An id here
                would be a row nobody could place. */}
            {decisions.refused.map((item) => (
              <li key={`move-${item.entry}-${item.to}`} className="decision">
                <span className="decision__what decision__what--quoted">
                  <span className="decision__quote">{`“${item.opening}”`}</span>
                  <span className="decision__tail">
                    stays out of <strong>{item.to}</strong>
                  </span>
                </span>
                <button
                  className="decision__undo"
                  onClick={() => void api.reconsiderMove(item.entry, item.to).then(load)}
                >
                  ask me again
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sheet__note sheet__note--quiet">
            Nothing yet, which is the normal state. Renaming a folder pins its name here, and
            turning down a proposed split or a proposed move is remembered here too.
          </p>
        )}
      </section>
    </>
  );
}
