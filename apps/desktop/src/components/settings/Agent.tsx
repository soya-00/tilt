import { useEffect, useState } from "react";

import type { PublicSettings, Status } from "../../lib/types";

interface Props {
  settings: PublicSettings | null;
  status: Status | null;
  onSave: (payload: { gemini_api_key?: string; gemini_model?: string }) => Promise<void>;
}

/**
 * The key and the model — everything about what is answering.
 *
 * The key is write-only from here. Once saved the service returns only its last
 * four characters: enough to recognise which key is set, never enough to get it
 * back out through the interface.
 */
export function Agent({ settings, status, onSave }: Props) {
  const [key, setKey] = useState("");
  const [model, setModel] = useState(settings?.gemini_model ?? "gemini-3.6-flash");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setModel(settings?.gemini_model ?? "gemini-3.6-flash");
  }, [settings]);

  const save = async () => {
    setSaving(true);
    try {
      // An empty field means "leave the existing key alone", not "clear it".
      // Clearing is a deliberate act and lives in the danger panel.
      await onSave({ ...(key.trim() ? { gemini_api_key: key.trim() } : {}), gemini_model: model });
      setKey("");
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <section className="sheet__section">
        <h3 className="sheet__label">Gemini API key</h3>
        <p className="sheet__note">
          {settings?.has_key
            ? `A key ending ${settings.key_hint} is in use. Type a new one to replace it.`
            : "Without a key, Tilt runs offline: replies match keywords and cannot follow a personality."}
        </p>
        <input
          className="field__input"
          type="password"
          value={key}
          spellCheck={false}
          autoComplete="off"
          placeholder={settings?.has_key ? "Replace key…" : "AIza…"}
          aria-label="Gemini API key"
          onChange={(e) => {
            setKey(e.target.value);
            setSaved(false);
          }}
        />
        {/* Three different promises, and saying the wrong one is worse than
            saying nothing — a file mode means nothing to someone whose key is
            never filed, and claiming the keychain on a machine that has none
            would be a straight untruth. */}
        <p className="sheet__note sheet__note--quiet">
          {status?.key_storage === "memory"
            ? "Held in memory for this session only and never written to disk. Closing this instance forgets it."
            : status?.key_storage === "keychain"
              ? "Kept in your login keychain, not in a file — encrypted by macOS and never in your journal folder."
              : "This machine has no keychain, so the key is in a file outside your journal, readable only by you."}{" "}
          It never leaves this machine except in calls to Google.
        </p>

        {/* Named rather than left to be discovered. Without a key the app still
            writes, files, connects and draws, so nothing looks broken — and
            what is missing is exactly what you would never think to look for. */}
        {!!status?.dormant?.length && (
          <ul className="dormant">
            {status.dormant.map((item) => (
              <li key={item.capability} className="dormant__item">
                <span className="dormant__what">{item.capability}</span>
                <span className="dormant__why">{item.why}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="sheet__section">
        <h3 className="sheet__label">Model</h3>
        <input
          className="field__input"
          value={model}
          spellCheck={false}
          aria-label="Gemini model"
          onChange={(e) => {
            setModel(e.target.value);
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
