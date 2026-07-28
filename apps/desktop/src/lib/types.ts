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

export interface Thread {
  entry: Entry;
  replies: Entry[];
}

export interface Status {
  ok: boolean;
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
}
