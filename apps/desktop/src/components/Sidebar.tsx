import { useState } from "react";

import { tagStyle } from "../lib/tagColor";
import { useIsDark } from "../lib/useTheme";
import type { Persona, Scope, Status, TagCount, Theme, ThemeSplit } from "../lib/types";
import { AgentCard } from "./AgentCard";
import { Icon } from "./Icon";
import { NavRow, SectionLabel } from "./primitives";

interface Props {
  themes: Theme[];
  splits: ThemeSplit[];
  tags: TagCount[];
  scope: Scope;
  entryCount: number;
  status: Status | null;
  persona: Persona | null;
  onScope: (scope: Scope) => void;
  onOpenGraph: () => void;
  onOpenBrief: () => void;
  onRenameTheme: (themeId: string, label: string) => void;
  onDeleteTheme: (themeId: string) => void;
  onAcceptSplit: (splitId: string) => void;
  onDismissSplit: (splitId: string) => void;
  onSavePersona: (payload: Partial<Persona>) => void;
}

/** Dormant folders say so on hover. Dimming alone reads as a rendering quirk. */
function dormantTitle(theme: Theme): string {
  const base = theme.description || `Show everything in ${theme.label}`;
  return theme.status === "dormant" ? `${base} — quiet for a while` : base;
}

interface SplitProposalProps {
  split: ThemeSplit;
  onAccept: (splitId: string) => void;
  onDismiss: (splitId: string) => void;
}

/**
 * A folder the keeper thinks has become two, offered rather than done.
 *
 * The one place in the app where the agent has found something structural and
 * deliberately stopped. A wrong merge is visible in the sidebar and the next
 * pass can undo it; a wrong split names its halves differently, so the merge
 * pass never looks at them together again and nothing puts the subject back.
 * That asymmetry is why this is two buttons rather than a change and a log
 * line.
 *
 * "Not this" rather than "no": the answer is about this proposal, and the
 * folder is asked about again once it has really grown.
 */
function SplitProposal({ split, onAccept, onDismiss }: SplitProposalProps) {
  return (
    <div className="split" role="group" aria-label={`Split ${split.theme_label}`}>
      <p className="split__body">
        This looks like two: <strong>{split.keep_label}</strong> ({split.keep_ids.length})
        and <strong>{split.move_label}</strong> ({split.move_ids.length}).
      </p>
      <div className="split__actions">
        <button className="split__action" onClick={() => onAccept(split.id)}>
          Split it
        </button>
        <button className="split__action split__action--quiet" onClick={() => onDismiss(split.id)}>
          Not this
        </button>
      </div>
    </div>
  );
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
 *
 * Deleting one is a different matter, and is offered: the agent's guess about
 * how your thinking divides up is sometimes simply wrong, and a folder you
 * disagree with is noise you cannot otherwise clear. It removes the folder and
 * its filing, never the entries — every thought that was in it stays exactly
 * where it was written.
 */
export function Sidebar({
  themes,
  splits,
  tags,
  scope,
  entryCount,
  status,
  persona,
  onScope,
  onOpenGraph,
  onOpenBrief,
  onRenameTheme,
  onDeleteTheme,
  onAcceptSplit,
  onDismissSplit,
  onSavePersona,
}: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // Armed, not confirmed. Deleting a folder is cheap to undo by hand but
  // annoying to have done by accident, which is exactly the weight of a second
  // click — the same bargain the entry rows strike.
  const [armed, setArmed] = useState<string | null>(null);
  const dark = useIsDark();
  const proposed = new Map(splits.map((s) => [s.theme_id, s]));

  const commit = (id: string) => {
    if (draft.trim()) onRenameTheme(id, draft);
    setEditing(null);
  };

  return (
    /* The panel itself never scrolls: its rim is a specular highlight pinned to
       the window edge, and a highlight that scrolled away with the content
       would stop being a property of the panel. The list inside scrolls. */
    <aside className="sidebar glass glass--edge-right">
      <div className="sidebar__scroll scroll">
        <div className="sidebar__section">
          <NavRow
            icon="home"
            label="Everything"
            count={entryCount}
            selected={scope.type === "all"}
            onClick={() => onScope({ type: "all" })}
          />
          {/* A keyboard shortcut nobody discovers is a feature nobody has. */}
          <NavRow
            icon="constellation"
            label="Constellation"
            title="See how it all connects (⌘G)"
            onClick={onOpenGraph}
          />
          {/* No count. A number beside this would turn a shelf into a backlog,
              and the whole design rests on it not being one. */}
          <NavRow
            icon="bookmark"
            label="Brief"
            title="Reading you have not done yet (⌘B)"
            onClick={onOpenBrief}
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
                  className={"stagger" + (theme.status === "dormant" ? " nav-dormant" : "")}
                  style={{ animationDelay: `${Math.min(i, 8) * 28}ms` }}
                  onPointerLeave={() => setArmed((id) => (id === theme.id ? null : id))}
                >
                  <NavRow
                    icon="folder"
                    label={theme.label}
                    count={theme.count}
                    title={dormantTitle(theme)}
                    selected={isActive(scope, {
                      type: "theme",
                      id: theme.id,
                      label: theme.label,
                    })}
                    onClick={() =>
                      onScope({
                        type: "theme",
                        id: theme.id,
                        label: theme.label,
                      })
                    }
                    onDoubleClick={() => {
                      setDraft(theme.label);
                      setEditing(theme.id);
                    }}
                    action={
                      <button
                        type="button"
                        className={
                          "nav-slot__delete" +
                          (armed === theme.id ? " nav-slot__delete--armed" : "")
                        }
                        aria-label={
                          armed === theme.id
                            ? `Confirm deleting ${theme.label}`
                            : `Delete ${theme.label}`
                        }
                        title={
                          armed === theme.id
                            ? "Click again to delete. Your entries are kept."
                            : `Delete ${theme.label} — the entries in it are kept`
                        }
                        onClick={() => {
                          if (armed === theme.id) {
                            onDeleteTheme(theme.id);
                            setArmed(null);
                          } else {
                            setArmed(theme.id);
                          }
                        }}
                        onBlur={() => setArmed((id) => (id === theme.id ? null : id))}
                      >
                        <Icon name={armed === theme.id ? "close" : "trash"} size={15} />
                      </button>
                    }
                  />
                  {/* Under the folder it is about, because that is the only
                      place it means anything. Nothing here is a badge or a
                      count: the nightly pass proposes at most one of these and
                      usually none, and a permanent slot for it would make the
                      sidebar look like it were waiting for you. */}
                  {proposed.has(theme.id) && (
                    <SplitProposal
                      split={proposed.get(theme.id)!}
                      onAccept={onAcceptSplit}
                      onDismiss={onDismissSplit}
                    />
                  )}
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
                  style={{
                    ...tagStyle(tag, dark),
                    animationDelay: `${Math.min(i, 12) * 22}ms`,
                  }}
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
      </div>
    </aside>
  );
}
