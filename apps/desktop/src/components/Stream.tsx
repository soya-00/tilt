import { useMemo } from "react";

import { dayHeading, dayKey } from "../lib/time";
import type { Misfiled, Notice, Scope, Thread } from "../lib/types";
import {
  ConnectionRow,
  DatePill,
  EntryRow,
  MisfiledRow,
  NoticeRow,
  ReplyRow,
} from "./Thread";

interface Props {
  threads: Thread[];
  loading: boolean;
  scope: Scope;
  /** What the weekly pass noticed. Empty most weeks. */
  notices: Notice[];
  /** Notice ids with a synthesis in flight. */
  synthesising: Set<string>;
  /** Entries the filing pass thinks are in the wrong folder. Usually empty. */
  moves: Misfiled[];
  /** Move ids being carried out. */
  moving: Set<string>;
  freshReplies: Set<string>;
  onReflect: (id: string) => void;
  onUpdate: (id: string, body: string) => void;
  onDelete: (id: string) => void;
  onDismissLink: (linkId: string) => void;
  onOpenEntry: (entryId: string) => void;
  onScope: (scope: Scope) => void;
  onSynthesise: (noticeId: string) => void;
  onDismissNotice: (noticeId: string) => void;
  onAcceptMove: (moveId: string) => void;
  onDismissMove: (moveId: string) => void;
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

export function Stream({
  threads,
  loading,
  scope,
  notices,
  synthesising,
  moves,
  moving,
  freshReplies,
  ...on
}: Props) {
  // Keyed by entry so a thread can find its own without scanning. Almost always
  // empty: filing is right most of the time, and this exists for the entries
  // written before the better folder existed.
  const misfiled = new Map(moves.map((m) => [m.entry_id, m]));
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
                {misfiled.has(thread.entry.id) && (
                  <MisfiledRow
                    move={misfiled.get(thread.entry.id)!}
                    busy={moving.has(misfiled.get(thread.entry.id)!.id)}
                    onAccept={on.onAcceptMove}
                    onDismiss={on.onDismissMove}
                  />
                )}
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

      {/* At the foot rather than the head: the stream reads downward and ends
          at the composer, so the bottom is where attention already is. And only
          in the unfiltered view — the notice is about the journal rather than
          about the folder you happen to be looking at. */}
      {scope.type === "all" &&
        notices.map((notice) => (
          <NoticeRow
            key={notice.id}
            notice={notice}
            busy={synthesising.has(notice.id)}
            onSynthesise={on.onSynthesise}
            onDismiss={on.onDismissNotice}
          />
        ))}
    </div>
  );
}
