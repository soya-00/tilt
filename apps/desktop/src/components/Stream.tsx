import { useMemo } from "react";

import { dayHeading, dayKey } from "../lib/time";
import type { Thread } from "../lib/types";
import { EntryItem } from "./EntryItem";

interface Props {
  threads: Thread[];
  loading: boolean;
  reflecting: Set<string>;
  onReflect: (id: string) => void;
  onUpdate: (id: string, body: string) => void;
  onDelete: (id: string) => void;
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

export function Stream({ threads, loading, reflecting, onReflect, onUpdate, onDelete }: Props) {
  const groups = useMemo(() => groupByDay(threads), [threads]);

  if (loading) {
    // No spinner. An empty field is quieter than a loading state and the wait
    // is measured in milliseconds against a local service.
    return <div className="stream__placeholder" aria-busy="true" />;
  }

  if (threads.length === 0) {
    return (
      <div className="stream__empty fade">
        <p className="stream__empty-line">Nothing here yet.</p>
        <p className="mono stream__empty-hint">
          Write above and press ⌘↵. Everything stays on this machine, as Markdown.
        </p>
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
              reflecting={reflecting.has(thread.entry.id)}
              onReflect={onReflect}
              onUpdate={onUpdate}
              onDelete={onDelete}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
