import { useState } from "react";

import { tagStyle } from "../lib/tagColor";
import { useIsDark } from "../lib/useTheme";
import { useLiquidGlass } from "../lib/useLiquidGlass";
import type { Persona, Scope, Status, TagCount, Theme } from "../lib/types";
import { AgentCard } from "./AgentCard";
import { NavRow, SectionLabel } from "./primitives";

interface Props {
  themes: Theme[];
  tags: TagCount[];
  scope: Scope;
  entryCount: number;
  status: Status | null;
  persona: Persona | null;
  onScope: (scope: Scope) => void;
  onRenameTheme: (themeId: string, label: string) => void;
  onSavePersona: (payload: Partial<Persona>) => void;
}

function isActive(scope: Scope, candidate: Scope): boolean {
  if (scope.type !== candidate.type) return false;
  if (scope.type === "theme" && candidate.type === "theme") return scope.id === candidate.id;
  if (scope.type === "tag" && candidate.type === "tag") return scope.tag === candidate.tag;
  return true;
}

/**
 * Navigation over structure the agent produced.
 *
 * Nothing here is authored by hand: folders are themes discovered from what you
 * wrote, tags are extracted per entry. Renaming a folder pins its name against
 * future agent edits. There is deliberately no way to create one — a folder you
 * maintain is filing work, and filing is what this app exists to remove.
 */
export function Sidebar({
  themes,
  tags,
  scope,
  entryCount,
  status,
  persona,
  onScope,
  onRenameTheme,
  onSavePersona,
}: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const dark = useIsDark();
  const glass = useLiquidGlass<HTMLElement>();

  const commit = (id: string) => {
    if (draft.trim()) onRenameTheme(id, draft);
    setEditing(null);
  };

  return (
    <aside
      ref={glass.ref}
      className="sidebar scroll glass-live"
      onPointerMove={glass.onPointerMove}
      onPointerLeave={glass.onPointerLeave}
    >
      <div className="sidebar__section">
        <NavRow
          icon="home"
          label="Everything"
          count={entryCount}
          selected={scope.type === "all"}
          onClick={() => onScope({ type: "all" })}
        />
      </div>

      <div className="sidebar__section">
        <SectionLabel>Agent</SectionLabel>
        <AgentCard persona={persona} status={status} onSave={onSavePersona} />
      </div>

      {themes.length > 0 && (
        <div className="sidebar__section">
          <SectionLabel>Folders</SectionLabel>
          {themes.map((theme, i) =>
            editing === theme.id ? (
              <input
                key={theme.id}
                className="rename"
                autoFocus
                value={draft}
                aria-label={`Rename ${theme.label}`}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => commit(theme.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit(theme.id);
                  if (e.key === "Escape") setEditing(null);
                }}
              />
            ) : (
              <div
                key={theme.id}
                className="stagger"
                style={{ animationDelay: `${Math.min(i, 8) * 28}ms` }}
              >
                <NavRow
                  icon="folder"
                  label={theme.label}
                  count={theme.count}
                  title={theme.description || `Show everything in ${theme.label}`}
                  selected={isActive(scope, { type: "theme", id: theme.id, label: theme.label })}
                  onClick={() => onScope({ type: "theme", id: theme.id, label: theme.label })}
                  onDoubleClick={() => {
                    setDraft(theme.label);
                    setEditing(theme.id);
                  }}
                />
              </div>
            ),
          )}
        </div>
      )}

      {tags.length > 0 && (
        <div className="sidebar__section">
          <SectionLabel>Tags</SectionLabel>
          <div className="tag-cloud">
            {tags.slice(0, 28).map(({ tag, count }, i) => (
              <button
                key={tag}
                className={
                  "tag stagger" +
                  (isActive(scope, { type: "tag", tag }) ? " tag--selected" : "")
                }
                style={{ ...tagStyle(tag, dark), animationDelay: `${Math.min(i, 12) * 22}ms` }}
                onClick={() => onScope({ type: "tag", tag })}
              >
                {tag}
                <span className="tag__count">{count}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {themes.length === 0 && (
        <p className="sidebar__hint">
          Folders and tags appear here as Tilt finds themes in what you write.
        </p>
      )}
    </aside>
  );
}
