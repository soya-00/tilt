import { useMemo } from "react";

import { dayHeading, dayKey } from "../lib/time";
import type { Scope, Thread } from "../lib/types";
import { ConnectionRow, DatePill, EntryRow, ReplyRow } from "./Thread";

interface Props {
  threads: Thread[];
  loading: boolean;
  scope: Scope;
  freshReplies: Set<string>;
  onReflect: (id: string) => void;
  onUpdate: (id: string, body: string) => void;
  onDelete: (id: string) => void;
  onDismissLink: (linkId: string) => void;
  onOpenEntry: (entryId: string) => void;
  onScope: (scope: Scope) => void;
}

interface DayGroup {
  key: string;
  heading: string;
  threads: Thread[];
}

/** Oldest first: the thread reads downward and ends at the composer. */
function groupByDay(threads: Thread[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const thread of [...threads].reverse()) {
    const key = dayKey(thread.entry.created);
    const last = groups.at(-1);
    if (last?.key === key) last.threads.push(thread);
    else groups.push({ key, heading: dayHeading(thread.entry.created), threads: [thread] });
  }
  return groups;
}

function emptyMessage(scope: Scope): string {
  if (scope.type === "theme") return `Nothing in ${scope.label} yet.`;
  if (scope.type === "tag") return `Nothing tagged ${scope.tag} yet.`;
  return "Write a line about your day.";
}

export function Stream({ threads, loading, scope, freshReplies, ...on }: Props) {
  const groups = useMemo(() => groupByDay(threads), [threads]);

  if (loading) return <div className="stream" aria-busy="true" />;

  if (threads.length === 0) {
    return (
      <div className="stream">
        <p className="stream__empty">{emptyMessage(scope)}</p>
      </div>
    );
  }

  return (
    <div className="stream">
      {groups.map((group) => (
        <section key={group.key} className="group">
          <DatePill label={group.heading} />
          {group.threads.map((thread) => {
            const below = thread.links.length + thread.replies.length;
            return (
              <div key={thread.entry.id} className="group__thread">
                <EntryRow
                  entry={thread.entry}
                  themes={thread.themes}
                  connected={below > 0}
                  onScope={on.onScope}
                  onReflect={on.onReflect}
                  onEdit={on.onUpdate}
                  onDelete={on.onDelete}
                />
                {thread.links.map((linked, i) => (
                  <ConnectionRow
                    key={linked.link.id}
                    linked={linked}
                    connected={i < below - 1}
                    onOpen={on.onOpenEntry}
                    onDismiss={on.onDismissLink}
                  />
                ))}
                {thread.replies.map((reply, i) => (
                  <ReplyRow
                    key={reply.id}
                    entry={reply}
                    fresh={freshReplies.has(reply.id)}
                    connected={thread.links.length + i < below - 1}
                  />
                ))}
                {/* Said rather than hidden. The rest of the source is still
                    indexed and still turns up in search — this is the app
                    admitting it filtered, not pretending it didn't. */}
                {thread.quiet > 0 && (
                  <button
                    className="thread__quiet"
                    onClick={() => on.onScope({ type: "search", q: thread.entry.body.split("\n")[0] ?? "" })}
                    title="Search this source's other ideas"
                  >
                    {thread.quiet} more {thread.quiet === 1 ? "idea" : "ideas"} from this source,
                    kept quiet
                  </button>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
