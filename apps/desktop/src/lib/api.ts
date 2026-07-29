/** Typed client for the Tilt core service.
 *
 * The desktop shell injects the sidecar's port and per-launch token at runtime;
 * in development this falls back to the local dev server.
 */

import type {
  Activity,
  AgentRun,
  Entry,
  JobSummary,
  Persona,
  PublicSettings,
  Scope,
  Status,
  TagCount,
  Theme,
  Thread,
} from "./types";

import type { ShellBridge } from "./shell";

declare global {
  interface Window {
    __TILT__?: ShellBridge;
  }
}

const BASE_URL =
  window.__TILT__?.baseUrl ??
  (import.meta.env.VITE_TILT_API as string | undefined) ??
  "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = window.__TILT__?.token;
  let response: Response;

  // An upload must not declare its own content type: only the browser knows
  // the multipart boundary it is about to generate, and setting the header by
  // hand produces a body the server cannot parse.
  const isUpload = init?.body instanceof FormData;

  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(isUpload ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    });
  } catch {
    // A dead sidecar is the most likely failure in the desktop shell, and it
    // deserves a human sentence rather than "Failed to fetch". When the shell
    // already knows why it never started, that reason beats any guess here.
    throw new ApiError(window.__TILT__?.error ?? "Cannot reach the Tilt service.", 0);
  }

  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || `Request failed (${response.status})`;
}

function scopeQuery(scope: Scope): string {
  if (scope.type === "theme") return `&theme_id=${encodeURIComponent(scope.id)}`;
  if (scope.type === "tag") return `&tag=${encodeURIComponent(scope.tag)}`;
  if (scope.type === "search") return `&q=${encodeURIComponent(scope.q)}`;
  return "";
}

export const api = {
  status: () => request<Status>("/status"),

  stream: (limit = 50, scope: Scope = { type: "all" }, before?: string) =>
    request<Thread[]>(
      `/entries?limit=${limit}` +
        (before ? `&before=${encodeURIComponent(before)}` : "") +
        scopeQuery(scope),
    ),

  themes: () => request<Theme[]>("/themes"),

  renameTheme: (id: string, label: string) =>
    request<Theme>(`/themes/${id}`, { method: "PATCH", body: JSON.stringify({ label }) }),

  /** Removes the folder and its filing. The entries in it are untouched. */
  deleteTheme: (id: string) => request<void>(`/themes/${id}`, { method: "DELETE" }),

  tags: () => request<TagCount[]>("/tags"),

  dismissLink: (id: string) => request<void>(`/links/${id}`, { method: "DELETE" }),

  thread: (id: string) => request<Thread>(`/entries/${id}`),

  create: (body: string, extra: Partial<{ source_url: string; tags: string[] }> = {}) =>
    request<Thread>("/entries", {
      method: "POST",
      body: JSON.stringify({ body, ...extra }),
    }),

  update: (id: string, body: string) =>
    request<Entry>(`/entries/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ body }),
    }),

  remove: (id: string) => request<void>(`/entries/${id}`, { method: "DELETE" }),

  search: (q: string, limit = 20) =>
    request<Entry[]>(`/entries/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  reflect: (entryId: string) =>
    request<Entry>("/agent/reflect", {
      method: "POST",
      body: JSON.stringify({ entry_id: entryId }),
    }),

  /** Categorise then connect — what runs after an entry is kept. */
  process: (entryId: string) =>
    request<Thread>("/agent/process", {
      method: "POST",
      body: JSON.stringify({ entry_id: entryId }),
    }),

  connect: (entryId: string) =>
    request<Thread>("/agent/connect", {
      method: "POST",
      body: JSON.stringify({ entry_id: entryId }),
    }),

  runs: () => request<AgentRun[]>("/agent/runs"),

  /** Run a scheduled job now, rather than waiting to find out at 3am. */
  runJob: (name: "sweep" | "themes") =>
    request<JobSummary>(`/agent/jobs/${name}`, { method: "POST" }),

  activity: (since: string) =>
    request<Activity>(`/agent/activity?since=${encodeURIComponent(since)}`),

  persona: () => request<Persona>("/agent/persona"),

  savePersona: (payload: Partial<Persona>) =>
    request<Persona>("/agent/persona", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  settings: () => request<PublicSettings>("/settings"),

  saveSettings: (payload: { gemini_api_key?: string; gemini_model?: string }) =>
    request<PublicSettings>("/settings", { method: "PATCH", body: JSON.stringify(payload) }),

  ingest: (payload: { title: string; text: string; url?: string }) =>
    request<Thread>("/ingest", { method: "POST", body: JSON.stringify(payload) }),

  /** Sends the file itself. A PDF has no text the browser can read, and the
   *  service has the extractor. */
  ingestFile: (file: File, title = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    return request<Thread>("/ingest/file", { method: "POST", body: form });
  },

  rebuildIndex: () => request<{ indexed: number }>("/index/rebuild", { method: "POST" }),
};
