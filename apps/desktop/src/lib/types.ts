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
  /** Atom or RSS the scout watches. Not a secret — these are public addresses,
   *  and seeing which ones are set is the point of them living here. */
  feeds: string[];
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
  /** Where the API key is kept: "keychain", "file", or "memory". */
  key_storage: "keychain" | "file" | "memory";
  /** The key is held in memory only and dies with the process. */
  ephemeral: boolean;
  /** What is asleep for want of a key. Empty when one is configured. */
  dormant: Dormant[];
  /** Two files on disk claiming one entry, seen at the last rebuild. Empty on
   *  a healthy journal; not empty means one of them is not being read, which
   *  is invisible otherwise because both files look fine sitting there. */
  conflicts: Conflict[];
}

export interface Dormant {
  capability: string;
  why: string;
}

/** What you have told the keeper about your folders, kept in `folders.md`
 *  beside your entries so it survives the index being thrown away. */
export interface Decisions {
  /** Folders you renamed. The agent will not rename them back. */
  pinned: string[];
  declined: Declined[];
}

export interface Declined {
  folder: string;
  /** How many entries were in it when you said no. It is not raised again
   *  until the folder has grown by half as much. */
  at: number;
}

export interface Exported {
  path: string;
  entries: number;
}

export interface Imported {
  path: string;
  entries: number;
  written_by: string;
}

export interface Conflict {
  entry_id: string;
  /** The file that was indexed — the one with the newer `updated`. */
  kept: string;
  /** The file that was not. Still on disk, untouched. */
  ignored: string;
}

/** A folder the keeper thinks has become two subjects.
 *
 *  Never applied on its own. A wrong merge is visible in the sidebar and the
 *  next pass can still undo it; a wrong split names its halves differently and
 *  nothing ever looks at them together again. */
export interface ThemeSplit {
  id: string;
  theme_id: string;
  theme_label: string;
  keep_label: string;
  move_label: string;
  keep_ids: string[];
  move_ids: string[];
  /** How far apart the halves measured, so a proposal can be argued with. */
  separation: number;
  created: string;
}

/** Something the weekly pass noticed, found without spending anything.
 *
 *  Not the synthesis — the observation that there might be one worth paying
 *  for. Usually there is no notice at all, which is the design. */
export interface Notice {
  id: string;
  kind: "contradiction" | "question";
  body: string;
  entry_ids: string[];
  subject: string;
  created: string;
  dismissed: boolean;
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
  /** Suggestions left for you rather than changes made. */
  proposed: number;
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

/* ------------------------------------------------------------- constellation */

export interface GraphNode {
  id: string;
  label: string;
  /** An entry kind, or "theme". */
  kind: EntryKind | "theme";
  provenance: Provenance;
  created: string | null;
  /** Members, for a folder. Always 1 for an entry. */
  weight: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  /** A link kind, or "member" for an entry's place in a folder. */
  kind: LinkKind | "member";
  rationale: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** The node cap bit. The view says so rather than implying there is no more. */
  truncated: boolean;
  total: number;
}

export interface GraphQuery {
  since?: string;
  theme_id?: string;
  include_sources?: boolean;
  include_themes?: boolean;
  limit?: number;
}

/* ------------------------------------------------------------------ diagrams */

export interface Artifact {
  id: string;
  /** The Mermaid diagram type — "flowchart", "mindmap", and so on. */
  kind: string;
  path: string;
  title: string;
  /** The Mermaid source. */
  body: string;
  /** One sentence from the agent on the structure it saw. */
  note: string;
  subject_ids: string[];
  created: string;
}

/** What to draw. One of these, never all of them — see the diagram route. */
export interface DiagramScope {
  theme_id?: string;
  tag?: string;
  q?: string;
}

/* -------------------------------------------------------------------- brief */

/** Reading that has not happened yet.
 *
 *  Not an entry, and not a task. Nothing here is completed — an item leaves by
 *  being read, at which point the usual distil path turns it into a source
 *  entry, or by being dismissed as not worth it. One that simply sits there is
 *  in no way a failure. */
export interface BriefItem {
  id: string;
  title: string;
  url: string | null;
  /** What made this worth proposing — the question it might answer, or your own
   *  note. Without it a list of links is unreadable a fortnight later. */
  why: string;
  /** `scout` if the agent went looking, `you` if you put it there. */
  origin: "scout" | "you";
  /** The same vocabulary entries use — snapped against it before storing, so a
   *  brief tag and an entry tag are the same word. */
  tags: string[];
  created: string;
  dismissed: boolean;
  path: string;
}
