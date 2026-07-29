import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import { stamp } from "../lib/time";
import type { AgentRun } from "../lib/types";

/** Jobs the agent runs on its own, and what pressing them means. */
const JOBS = [
  { name: "sweep", label: "Catch up", hint: "File and connect anything missed" },
  { name: "themes", label: "Tidy folders", hint: "Merge duplicates, retire quiet ones" },
] as const;

/**
 * What the agent has been doing.
 *
 * The reason this screen exists: once work happens on a schedule, a job that
 * fails at 3am fails silently, and the app goes on looking like it is keeping
 * up long after it stopped. Every run leaves a row here whether it succeeded,
 * failed, or stopped at the spending ceiling.
 *
 * Both jobs are also runnable from here. Waiting until the small hours to learn
 * whether a scheduled job works is not a way to build one.
 */
export function ActivityLog() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRuns(await api.runs());
    } catch {
      /* The log failing to load must not take the settings sheet with it. */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const trigger = async (name: (typeof JOBS)[number]["name"]) => {
    setBusy(name);
    try {
      await api.runJob(name);
    } catch {
      // The failure is about to appear in the list below as a row of its own,
      // which says more than an alert would.
    } finally {
      setBusy(null);
      await load();
    }
  };

  return (
    <>
      <div className="job-row">
        {JOBS.map((job) => (
          <button
            key={job.name}
            className="ghost-btn"
            title={job.hint}
            disabled={busy !== null}
            onClick={() => void trigger(job.name)}
          >
            {busy === job.name ? "Running…" : job.label}
          </button>
        ))}
      </div>

      {runs.length === 0 ? (
        <p className="sheet__note sheet__note--quiet">
          Nothing yet. The agent files what you write, and sweeps for anything it missed.
        </p>
      ) : (
        <ul className="runs">
          {runs.slice(0, 12).map((run) => (
            <li key={run.id} className={"run run--" + run.status}>
              <span className="run__job">{run.job}</span>
              <span className="run__detail">{summarise(run)}</span>
              <span className="run__when">{stamp(run.started)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/** One line about a run: what it did, or what it cost, or why it stopped. */
function summarise(run: AgentRun): string {
  if (run.status === "error") return run.error ?? "failed";
  if (run.detail) return run.detail;
  // Single model calls have no detail. Their cost is the interesting part —
  // and sub-cent spend reads as "0.00", which looks like a bug rather than a
  // rounding, so say what it is.
  if (run.cost_usd > 0) return run.cost_usd < 0.01 ? "under a cent" : `$${run.cost_usd.toFixed(2)}`;
  return "no spend";
}
