import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import { stamp } from "../lib/time";
import type { AgentRun } from "../lib/types";

/** Jobs the agent runs on its own, and what pressing them means.
 *
 * All five, not the two that happened to be wired first. A scheduled job you
 * cannot trigger is one whose behaviour you can only learn by waiting up for
 * it — and the weekly pass in particular is designed to say nothing most of the
 * time, which is indistinguishable from a job that has quietly stopped unless
 * you can press it and watch it say so. */
const JOBS = [
  { name: "sweep", label: "Catch up", hint: "File and connect anything missed" },
  { name: "themes", label: "Tidy folders", hint: "Merge duplicates, retire quiet ones" },
  { name: "vectors", label: "Embed", hint: "Place recent entries by meaning. Needs a key" },
  { name: "scout", label: "Look outward", hint: "Read your feeds for something worth your time" },
  {
    name: "week",
    label: "Look back",
    hint: "Anything from this week worth a second look. Usually nothing, and costs nothing",
  },
] as const;

/**
 * What the agent has been doing.
 *
 * The reason this screen exists: once work happens on a schedule, a job that
 * fails at 3am fails silently, and the app goes on looking like it is keeping
 * up long after it stopped. Every run leaves a row here whether it succeeded,
 * failed, or stopped at the spending ceiling.
 *
 * Every job is also runnable from here. Waiting until the small hours to learn
 * whether a scheduled job works is not a way to build one — and a job whose
 * correct answer is silence needs this more than the others, not less.
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
