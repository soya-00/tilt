import { useEffect, useState } from "react";

import type { PublicSettings } from "../../lib/types";

interface Props {
  settings: PublicSettings | null;
  onSave: (payload: { feeds: string[] }) => Promise<void>;
}

/**
 * What the scout looks through.
 *
 * A textarea rather than a chip editor: these are long, they are pasted rather
 * than typed, and a list you can select and delete wholesale is the right
 * weight for something changed twice a year.
 */
export function Reading({ settings, onSave }: Props) {
  const [feeds, setFeeds] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setFeeds((settings?.feeds ?? []).join("\n"));
  }, [settings]);

  const save = async () => {
    setSaving(true);
    try {
      await onSave({ feeds: feeds.split(/\n+/).map((f) => f.trim()).filter(Boolean) });
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <section className="sheet__section">
        <h3 className="sheet__label">Feeds</h3>
        <p className="sheet__note">
          Atom or RSS the scout looks through once a day. arXiv is searched already, from what
          your folders are about — this is for anything else worth following. Leave it empty and
          the scout still works.
        </p>
        <textarea
          className="field__input field__input--feeds"
          value={feeds}
          spellCheck={false}
          placeholder={"https://example.com/feed.xml\nhttps://another.org/rss"}
          aria-label="Feed URLs, one per line"
          onChange={(e) => {
            setFeeds(e.target.value);
            setSaved(false);
          }}
        />
      </section>

      <div className="panel__save">
        <button className="ghost-btn ghost-btn--primary" onClick={() => void save()} disabled={saving}>
          {saving ? "Saving…" : saved ? "Saved" : "Save"}
        </button>
      </div>
    </>
  );
}
