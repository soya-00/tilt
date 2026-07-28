import { useState } from "react";

import type { Scope, TagCount, Theme } from "../lib/types";

interface Props {
  themes: Theme[];
  tags: TagCount[];
  scope: Scope;
  entryCount: number;
  onScope: (scope: Scope) => void;
  onRenameTheme: (themeId: string, label: string) => void;
}

type Section = "folders" | "tags";

function isActive(scope: Scope, candidate: Scope): boolean {
  if (scope.type !== candidate.type) return false;
  if (scope.type === "theme" && candidate.type === "theme") return scope.id === candidate.id;
  if (scope.type === "tag" && candidate.type === "tag") return scope.tag === candidate.tag;
  return true;
}

/**
 * Navigation over structure the agent produced.
 *
 * Nothing here is authored by hand: folders are themes discovered from what
 * you wrote, tags are extracted per entry. You can rename a folder — which
 * pins the name so the agent stops rewriting it — but you cannot create one,
 * because a folder you have to maintain is filing work, and filing is the
 * thing this app exists to take off you.
 */
export function Sidebar({ themes, tags, scope, entryCount, onScope, onRenameTheme }: Props) {
  const [section, setSection] = useState<Section>("folders");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const commit = (themeId: string) => {
    if (draft.trim()) onRenameTheme(themeId, draft);
    setEditing(null);
  };

  return (
    <aside className="sidebar">
      <button
        className={`sidebar__all${scope.type === "all" ? " sidebar__row--active" : ""}`}
        onClick={() => onScope({ type: "all" })}
      >
        <span className="sidebar__label">Everything</span>
        <span className="micro tnum sidebar__count">{entryCount}</span>
      </button>

      <div className="segmented" role="tablist" aria-label="Browse by">
        {(["folders", "tags"] as const).map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={section === s}
            className={`segmented__option${section === s ? " segmented__option--on" : ""}`}
            onClick={() => setSection(s)}
          >
            {s === "folders" ? "Folders" : "Tags"}
          </button>
        ))}
      </div>

      <div className="sidebar__list scroll">
        {section === "folders" ? (
          themes.length === 0 ? (
            <p className="micro sidebar__empty">
              Folders appear as Tilt finds themes in what you write.
            </p>
          ) : (
            <ul className="sidebar__items">
              {themes.map((theme) => {
                const active = isActive(scope, { type: "theme", id: theme.id, label: theme.label });
                return (
                  <li key={theme.id}>
                    {editing === theme.id ? (
                      <input
                        className="sidebar__rename"
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
                      <button
                        className={`sidebar__row${active ? " sidebar__row--active" : ""}`}
                        onClick={() => onScope({ type: "theme", id: theme.id, label: theme.label })}
                        onDoubleClick={() => {
                          setDraft(theme.label);
                          setEditing(theme.id);
                        }}
                        title={theme.description || theme.label}
                      >
                        <span className="sidebar__glyph" aria-hidden="true" />
                        <span className="sidebar__label">{theme.label}</span>
                        <span className="micro tnum sidebar__count">{theme.count}</span>
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )
        ) : tags.length === 0 ? (
          <p className="micro sidebar__empty">Tags appear once entries are filed.</p>
        ) : (
          <ul className="sidebar__tags">
            {tags.map(({ tag, count }) => (
              <li key={tag}>
                <button
                  className={`sidebar__tag${
                    isActive(scope, { type: "tag", tag }) ? " sidebar__tag--active" : ""
                  }`}
                  onClick={() => onScope({ type: "tag", tag })}
                >
                  {tag}
                  <span className="tnum sidebar__tag-count">{count}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
