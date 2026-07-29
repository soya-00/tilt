import { useEffect, useState } from "react";

import type { PublicSettings, Status } from "../lib/types";
import { ActivityLog } from "./ActivityLog";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  settings: PublicSettings | null;
  status: Status | null;
  theme: "light" | "dark";
  onClose: () => void;
  onSave: (payload: { gemini_api_key?: string; gemini_model?: string }) => Promise<void>;
  onToggleTheme: () => void;
}

/**
 * Settings: the key, the model, and appearance.
 *
 * The key is write-only from here on. Once saved, the service returns only its
 * last four characters — enough to recognise which key is set, never enough to
 * exfiltrate it back through the UI.
 */
export function Settings({
  open,
  settings,
  status,
  theme,
  onClose,
  onSave,
  onToggleTheme,
}: Props) {
  const [key, setKey] = useState("");
  const [model, setModel] = useState(settings?.gemini_model ?? "gemini-3.6-flash");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setKey("");
      setModel(settings?.gemini_model ?? "gemini-3.6-flash");
    }
  }, [open, settings]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const save = async () => {
    setSaving(true);
    try {
      // An empty field means "leave the existing key alone", not "clear it".
      await onSave({
        ...(key.trim() ? { gemini_api_key: key.trim() } : {}),
        gemini_model: model,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="sheet-scrim fade" onMouseDown={onClose} role="presentation">
      <div
        className="sheet glass glass--heavy"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="sheet__head">
          <h2 className="sheet__title">Settings</h2>
          {/* The service reports its own version, not the interface's. They are
              separate processes and can be different builds — which is the only
              way to tell a rebuilt app from one still running a stale service. */}
          {status && <span className="sheet__version">Tilt {status.version}</span>}
          <button className="icon-btn" aria-label="Close settings" onClick={onClose}>
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="sheet__body scroll">
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
              onChange={(e) => setKey(e.target.value)}
            />
            <p className="sheet__note sheet__note--quiet">
              Stored in your journal folder at <code>.tilt/settings.json</code>, readable only
              by you. It never leaves this machine except in calls to Google.
            </p>
          </section>

          <section className="sheet__section">
            <h3 className="sheet__label">Model</h3>
            <input
              className="field__input"
              value={model}
              spellCheck={false}
              aria-label="Gemini model"
              onChange={(e) => setModel(e.target.value)}
            />
          </section>

          <section className="sheet__section">
            <h3 className="sheet__label">Activity</h3>
            <p className="sheet__note">
              Tilt files what you write as you write it, sweeps every quarter hour for anything
              missed, and tidies the folders overnight.
            </p>
            <ActivityLog />
          </section>

          <section className="sheet__section">
            <h3 className="sheet__label">Appearance</h3>
            {/* The thumb is the same glass as the panels, and it carries both
              glyphs at once — the sun and the moon cross-fade under it as it
              travels, so the control shows what it is moving toward rather
              than only what it currently is. */}
            <button
              className={"switch" + (theme === "dark" ? " switch--on" : "")}
              role="switch"
              aria-checked={theme === "dark"}
              onClick={onToggleTheme}
            >
              <span className="switch__track">
                <span className="switch__glyphs" aria-hidden="true">
                  <Icon name="sun" size={14} className="switch__sun" />
                  <Icon name="moon" size={14} className="switch__moon" />
                </span>
                <span className="switch__thumb glass" />
              </span>
              <span className="switch__label">{theme === "dark" ? "Dark" : "Light"}</span>
            </button>
          </section>
        </div>

        <footer className="sheet__foot">
          <button className="ghost-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="ghost-btn ghost-btn--primary"
            onClick={() => void save()}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </footer>
      </div>
    </div>
  );
}
