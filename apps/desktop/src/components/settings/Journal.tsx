import type { Status } from "../../lib/types";

interface Props {
  status: Status | null;
}

/**
 * Where your journal actually is.
 *
 * The strongest claim this app makes is that your writing is a folder of
 * Markdown you own rather than rows in somebody's database — and until now
 * nothing in the interface said where that folder is. A promise you have to
 * read the source to verify is not much of a promise.
 */
export function Journal({ status }: Props) {
  return (
    <>
      <section className="sheet__section">
        <h3 className="sheet__label">Where it lives</h3>
        <p className="sheet__note">
          Everything you have written is plain Markdown here, one file per entry, with folders
          and connections in each file's own frontmatter. Open it, grep it, edit it, put it in
          git — Tilt reads whatever is there the next time it starts.
        </p>
        <p className="sheet__path">
          <code>{status?.data_dir ?? "…"}</code>
        </p>
      </section>

      <section className="sheet__section">
        <h3 className="sheet__label">What is not in it</h3>
        <p className="sheet__note">
          The database and the vectors live outside your journal, in the app's support folder.
          Both are derived: the database rebuilds from your Markdown for nothing, and the
          vectors would have to be bought again. They are kept apart so that a cloud client
          syncing your journal never has to fight a database being written to.
        </p>
        {/* Named from what actually happened rather than described in general.
            "Or in a file" is no use to somebody deciding whether to hand this
            folder to Dropbox. */}
        <p className="sheet__note sheet__note--quiet">
          Your API key is in neither —{" "}
          {status?.key_storage === "memory"
            ? "it is held in memory for this session and never written down at all"
            : status?.key_storage === "keychain"
              ? "it is in your login keychain"
              : "this machine has no keychain, so it is in a file in the support folder"}
          .
        </p>
      </section>
    </>
  );
}
