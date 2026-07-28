import { useMemo } from "react";

import { dayHeading, dayKey } from "../lib/time";
import type { Scope, Thread } from "../lib/types";
import { EntryItem } from "./EntryItem";

interface Props {
  threads: Thread[];
  loading: boolean;
  scope: Scope;
  reflecting: Set<string>;
  processing: Set<string>;
  onReflect: (id: string) => void;
  onConnect: (id: string) => void;
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

function groupByDay(threads: Thread[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const thread of threads) {
    const key = dayKey(thread.entry.created);
    const last = groups.at(-1);
    if (last?.key === key) last.threads.push(thread);
    else groups.push({ key, heading: dayHeading(thread.entry.created), threads: [thread] });
  }
  return groups;
}

function emptyMessage(scope: Scope): { line: string; hint: string } {
  if (scope.type === "theme") {
    return { line: `Nothing in ${scope.label} yet.`, hint: "This folder is empty." };
  }
  if (scope.type === "tag") {
    return { line: `Nothing tagged ${scope.tag}.`, hint: "Try another tag." };
  }
  return {
    line: "Nothing here yet.",
    hint: "Write above and press ⌘↵. Everything stays on this machine, as Markdown.",
  };
}

export function Stream({ threads, loading, scope, ...handlers }: Props) {
  const groups = useMemo(() => groupByDay(threads), [threads]);

  if (loading) {
    // No spinner. An empty field is quieter than a loading state, and the wait
    // is milliseconds against a local service.
    return <div className="stream__placeholder" aria-busy="true" />;
  }

  if (threads.length === 0) {
    const { line, hint } = emptyMessage(scope);
    return (
      <div className="stream__empty fade">
        <p className="stream__empty-line">{line}</p>
        <p className="mono stream__empty-hint">{hint}</p>
      </div>
    );
  }

  return (
    <div className="stream">
      {groups.map((group) => (
        <section key={group.key} className="stream__day">
          <h2 className="micro stream__day-heading">{group.heading}</h2>
          {group.threads.map((thread) => (
            <EntryItem
              key={thread.entry.id}
              thread={thread}
              reflecting={handlers.reflecting.has(thread.entry.id)}
              processing={handlers.processing.has(thread.entry.id)}
              onReflect={handlers.onReflect}
              onConnect={handlers.onConnect}
              onUpdate={handlers.onUpdate}
              onDelete={handlers.onDelete}
              onDismissLink={handlers.onDismissLink}
              onOpenEntry={handlers.onOpenEntry}
              onScope={handlers.onScope}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
