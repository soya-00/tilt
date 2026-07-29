/** What happened while the app was closed.
 *
 * The agent now works on a schedule, which means the journal can change with
 * nobody watching. Without some trace of that, the only way to discover an
 * overnight connection is to scroll back through entries you have already read
 * and hope you notice something new underneath one.
 *
 * This is deliberately not an inbox. It reports two numbers and goes away. The
 * connections themselves stay threaded under the entries they belong to, which
 * is the only place they mean anything.
 */

import { useEffect, useState } from "react";

import { api } from "./api";
import type { Activity } from "./types";

const KEY = "tilt:last-seen";

/** Private-mode browsers and locked-down webviews throw on access rather than
 *  returning null, and a missing convenience must never break the journal. */
function remembered(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function remember(iso: string): void {
  try {
    window.localStorage.setItem(KEY, iso);
  } catch {
    /* nothing to do; the notice simply will not appear next time */
  }
}

export function describe(activity: Activity): string {
  const parts: string[] = [];
  if (activity.filed) parts.push(`${activity.filed} filed`);
  if (activity.connected) {
    parts.push(`${activity.connected} connection${activity.connected === 1 ? "" : "s"}`);
  }
  return `${parts.join(", ")} while you were away`;
}

export function useAway(): { activity: Activity | null; dismiss: () => void } {
  const [activity, setActivity] = useState<Activity | null>(null);

  useEffect(() => {
    const previous = remembered();
    // Stamped before the request, not after it. This marks the start of the
    // current visit, so reopening the window is not treated as a new absence
    // and the same overnight work is never reported twice.
    remember(new Date().toISOString());

    // Nothing to compare against on a first launch. There is no "away" yet.
    if (!previous) return;

    let cancelled = false;
    api
      .activity(previous)
      .then((next) => {
        if (!cancelled && next.filed + next.connected > 0) setActivity(next);
      })
      .catch(() => {
        /* Ambient. A failure here must never disturb writing. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { activity, dismiss: () => setActivity(null) };
}
