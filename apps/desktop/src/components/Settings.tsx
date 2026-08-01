import { useEffect, useState } from "react";

import type { IconName } from "./Icon";
import type { PublicSettings, Status } from "../lib/types";
import { ActivityLog } from "./ActivityLog";
import { Icon } from "./Icon";
import { NavRow } from "./primitives";
import { Agent } from "./settings/Agent";
import { Danger } from "./settings/Danger";
import { Appearance } from "./settings/Appearance";
import { Journal } from "./settings/Journal";
import { Reading } from "./settings/Reading";

type Panel = "agent" | "reading" | "journal" | "appearance" | "activity" | "danger";

interface Group {
  id: Panel;
  icon: IconName;
  label: string;
}

/** Danger last, and separated below. It is the one group that should never be
 *  arrived at by accident. */
const GROUPS: Group[] = [
  { id: "agent", icon: "spark", label: "Agent" },
  { id: "reading", icon: "bookmark", label: "Reading" },
  { id: "journal", icon: "folder", label: "Journal" },
  { id: "appearance", icon: "sun", label: "Appearance" },
  { id: "activity", icon: "refresh", label: "Activity" },
];

const DANGER: Group = { id: "danger", icon: "trash", label: "Danger" };

interface Props {
  open: boolean;
  settings: PublicSettings | null;
  status: Status | null;
  theme: "light" | "dark";
  onClose: () => void;
  onSave: (payload: {
    gemini_api_key?: string;
    gemini_model?: string;
    feeds?: string[];
  }) => Promise<void>;
  onToggleTheme: () => void;
}

/**
 * Settings: a rail and one panel.
 *
 * It was a single column of stacked sections, which worked at three and did not
 * at seven — and the thing that would have been furthest down the scroll is the
 * button that deletes your journal. A rail gives every group a destination
 * instead of a position, and gives that one a deliberate one.
 *
 * The single Save at the foot went with it. It existed because the key, the
 * model and the feeds were written in one request, which is also why they had
 * to be adjacent. Each panel now saves its own fields, and the two that act
 * immediately — Journal and Danger — have no Save at all, because a button that
 * deletes a journal should not be waiting on a second button to mean it.
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
  const [panel, setPanel] = useState<Panel>("agent");

  useEffect(() => {
    if (open) setPanel("agent");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="sheet-scrim fade" onMouseDown={onClose} role="presentation">
      <div
        className="sheet sheet--wide glass glass--heavy"
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

        <div className="settings">
          <nav className="settings__rail" aria-label="Settings sections">
            {GROUPS.map((group) => (
              <NavRow
                key={group.id}
                icon={group.icon}
                label={group.label}
                selected={panel === group.id}
                onClick={() => setPanel(group.id)}
              />
            ))}
            <hr className="settings__rule" />
            <NavRow
              icon={DANGER.icon}
              label={DANGER.label}
              selected={panel === DANGER.id}
              onClick={() => setPanel(DANGER.id)}
            />
          </nav>

          <div className="settings__panel scroll">
            {panel === "agent" && (
              <Agent settings={settings} status={status} onSave={onSave} />
            )}
            {panel === "reading" && <Reading settings={settings} onSave={onSave} />}
            {panel === "journal" && <Journal status={status} />}
            {panel === "appearance" && (
              <Appearance theme={theme} onToggle={onToggleTheme} />
            )}
            {panel === "activity" && <ActivityLog />}
            {panel === "danger" && (
              <Danger status={status} onForgetKey={() => onSave({ gemini_api_key: "" })} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
