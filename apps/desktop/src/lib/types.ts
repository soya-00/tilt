/** Mirrors the Pydantic models in `core/tilt/models.py`. */

export type EntryKind = "note" | "capture" | "source" | "card" | "reply";
export type Provenance = "self" | "source";
export type ReplyKind = "reflection" | "connection" | "question";

export interface Entry {
  id: string;
  created: string;
  updated: string;
  kind: EntryKind;
  provenance: Provenance;
  parent: string | null;
  source_id: string | null;
  anchor: string | null;
  source_url: string | null;
  reply_kind: ReplyKind | null;
  tags: string[];
  body: string;
}

export type LinkKind = "echo" | "elaboration" | "contradiction" | "counterpoint" | "bridge";

export interface Link {
  id: string;
  src_id: string;
  dst_id: string;
  kind: LinkKind;
  rationale: string;
  created: string;
  dismissed: boolean;
}

export interface LinkedEntry {
  link: Link;
  entry: Entry;
}

/** Dormant is quiet, not gone. A subject you set down still shows in the
 *  sidebar — it just stops competing for attention with the live ones. */
export type ThemeStatus = "active" | "dormant";

export interface Theme {
  id: string;
  label: string;
  description: string;
  created: string;
  updated: string;
  pinned_label: boolean;
  count: number;
  status: ThemeStatus;
  last_active: string | null;
}

export interface TagCount {
  tag: string;
  count: number;
}

export interface Thread {
  entry: Entry;
  replies: Entry[];
  themes: Theme[];
  links: LinkedEntry[];
  /** Ideas from this source that did not clear the relevance bar. Still
   *  indexed and still searchable — just not pushed at you. */
  quiet: number;
}

export interface Persona {
  name: string;
  personality: string;
}

export interface PublicSettings {
  has_key: boolean;
  key_hint: string;
  gemini_model: string;
  monthly_cost_ceiling_usd: number;
}

/** What the view is currently showing. */
export type Scope =
  | { type: "all" }
  | { type: "theme"; id: string; label: string }
  | { type: "tag"; tag: string }
  | { type: "search"; q: string };

export interface Status {
  ok: boolean;
  /** The version of the *service*, which is a separate process from this UI. */
  version: string;
  provider: string;
  offline: boolean;
  model: string;
  entries: number;
  spend_this_month_usd: number;
  cost_ceiling_usd: number;
  data_dir: string;
}

export interface AgentRun {
  id: string;
  job: string;
  model: string;
  status: string;
  started: string;
  finished: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  error: string | null;
  /** What an unattended run actually did. Empty for single model calls. */
  detail: string;
}

/** The outcome of one scheduled pass. */
export interface JobSummary {
  job: string;
  considered: number;
  filed: number;
  connected: number;
  merged: number;
  dormant: number;
  detail: string;
  /** Stopped at the spending ceiling — unfinished, but nothing is broken. */
  paused: boolean;
}

/** What the agent did while the app was closed. */
export interface Activity {
  since: string;
  filed: number;
  connected: number;
}
