/** Journal state.
 *
 * Deliberately a single hook over a state library: the surface is one list of
 * threads plus a handful of mutations, and the interaction that matters most
 * (writing) must never wait on a network round trip. Creation is optimistic —
 * the entry appears the instant you press send, then reconciles or rolls back.
 *
 * Filing happens on its own after that. You write; the agent categorises and
 * looks for connections in the background, and the sidebar fills in. You are
 * never asked to file anything yourself.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "./api";
import type { Entry, Persona, Scope, Status, TagCount, Theme, Thread } from "./types";

const PAGE = 50;

export interface JournalState {
  threads: Thread[];
  themes: Theme[];
  tags: TagCount[];
  status: Status | null;
  persona: Persona | null;
  scope: Scope;
  loading: boolean;
  error: string | null;
  /** Entry ids with a reflection in flight. */
  reflecting: Set<string>;
  /** Entry ids being categorised or connected. */
  processing: Set<string>;
  /** Reply ids that arrived this session, so they reveal word by word. */
  freshReplies: Set<string>;
  setScope: (scope: Scope) => void;
  create: (body: string) => Promise<void>;
  reflect: (entryId: string) => Promise<void>;
  connect: (entryId: string) => Promise<void>;
  update: (entryId: string, body: string) => Promise<void>;
  remove: (entryId: string) => Promise<void>;
  dismissLink: (linkId: string) => Promise<void>;
  renameTheme: (themeId: string, label: string) => Promise<void>;
  savePersona: (payload: Partial<Persona>) => Promise<void>;
  refresh: () => Promise<void>;
  dismissError: () => void;
}

function optimisticEntry(body: string): Entry {
  const now = new Date().toISOString();
  return {
    id: `pending-${crypto.randomUUID()}`,
    created: now,
    updated: now,
    kind: "note",
    provenance: "self",
    parent: null,
    source_id: null,
    anchor: null,
    source_url: null,
    reply_kind: null,
    tags: [],
    body,
  };
}

export function useJournal(): JournalState {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [scope, setScope] = useState<Scope>({ type: "all" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reflecting, setReflecting] = useState<Set<string>>(new Set());
  const [processing, setProcessing] = useState<Set<string>>(new Set());
  const [freshReplies, setFresh] = useState<Set<string>>(new Set());

  const mounted = useRef(true);
  // Read inside callbacks so they never need `threads` as a dependency, which
  // would rebuild every handler on each keystroke-driven render.
  const threadsRef = useRef<Thread[]>([]);
  threadsRef.current = threads;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const describe = (err: unknown): string =>
    err instanceof ApiError ? err.message : "Something went wrong.";

  const track = (
    set: React.Dispatch<React.SetStateAction<Set<string>>>,
    id: string,
    on: boolean,
  ) =>
    set((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const refreshLibrary = useCallback(async () => {
    try {
      const [nextThemes, nextTags, nextStatus, nextPersona] = await Promise.all([
        api.themes(),
        api.tags(),
        api.status(),
        api.persona(),
      ]);
      if (!mounted.current) return;
      setThemes(nextThemes);
      setTags(nextTags);
      setStatus(nextStatus);
      setPersona(nextPersona);
    } catch {
      /* Ambient data; a failure here must never disrupt writing. */
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await api.stream(PAGE, scope);
      if (!mounted.current) return;
      setThreads(next);
      setError(null);
    } catch (err) {
      if (mounted.current) setError(describe(err));
    } finally {
      if (mounted.current) setLoading(false);
    }
    await refreshLibrary();
  }, [scope, refreshLibrary]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** Categorise and connect in the background, then fold the result in. */
  const process = useCallback(
    async (entryId: string) => {
      track(setProcessing, entryId, true);
      try {
        const filed = await api.process(entryId);
        if (!mounted.current) return;
        setThreads((prev) => prev.map((t) => (t.entry.id === entryId ? filed : t)));
        await refreshLibrary();
      } catch {
        // Filing is best-effort. A failure here must not surface as an error
        // over the writing surface — the thought is already safely saved.
      } finally {
        if (mounted.current) track(setProcessing, entryId, false);
      }
    },
    [refreshLibrary],
  );

  const create = useCallback(
    async (body: string) => {
      const trimmed = body.trim();
      if (!trimmed) return;

      const pending = optimisticEntry(trimmed);
      setThreads((prev) => [
        { entry: pending, replies: [], themes: [], links: [] },
        ...prev,
      ]);

      try {
        const saved = await api.create(trimmed);
        setThreads((prev) => prev.map((t) => (t.entry.id === pending.id ? saved : t)));
        void process(saved.entry.id);
      } catch (err) {
        setThreads((prev) => prev.filter((t) => t.entry.id !== pending.id));
        setError(describe(err));
        throw err;
      }
    },
    [process],
  );

  const reflect = useCallback(
    async (entryId: string) => {
      track(setReflecting, entryId, true);
      try {
        const reply = await api.reflect(entryId);
        // Marked fresh so it reveals word by word. Only replies that arrive
        // while you are watching animate; reloads render settled.
        setFresh((prev) => new Set(prev).add(reply.id));
        setThreads((prev) =>
          prev.map((t) =>
            t.entry.id === entryId ? { ...t, replies: [...t.replies, reply] } : t,
          ),
        );
        void refreshLibrary();
      } catch (err) {
        setError(describe(err));
      } finally {
        track(setReflecting, entryId, false);
      }
    },
    [refreshLibrary],
  );

  const connect = useCallback(async (entryId: string) => {
    track(setProcessing, entryId, true);
    try {
      const linked = await api.connect(entryId);
      setThreads((prev) => prev.map((t) => (t.entry.id === entryId ? linked : t)));
    } catch (err) {
      setError(describe(err));
    } finally {
      track(setProcessing, entryId, false);
    }
  }, []);

  const update = useCallback(async (entryId: string, body: string) => {
    const trimmed = body.trim();
    if (!trimmed) return;
    const snapshot = threadsRef.current;
    setThreads((prev) =>
      prev.map((t) =>
        t.entry.id === entryId ? { ...t, entry: { ...t.entry, body: trimmed } } : t,
      ),
    );
    try {
      const saved = await api.update(entryId, trimmed);
      setThreads((prev) => prev.map((t) => (t.entry.id === entryId ? { ...t, entry: saved } : t)));
    } catch (err) {
      setThreads(snapshot);
      setError(describe(err));
    }
  }, []);

  const remove = useCallback(
    async (entryId: string) => {
      const snapshot = threadsRef.current;
      setThreads((prev) => prev.filter((t) => t.entry.id !== entryId));
      try {
        await api.remove(entryId);
        await refreshLibrary();
      } catch (err) {
        setThreads(snapshot);
        setError(describe(err));
      }
    },
    [refreshLibrary],
  );

  const dismissLink = useCallback(async (linkId: string) => {
    const snapshot = threadsRef.current;
    setThreads((prev) =>
      prev.map((t) => ({ ...t, links: t.links.filter((l) => l.link.id !== linkId) })),
    );
    try {
      await api.dismissLink(linkId);
    } catch (err) {
      setThreads(snapshot);
      setError(describe(err));
    }
  }, []);

  const renameTheme = useCallback(
    async (themeId: string, label: string) => {
      const trimmed = label.trim();
      if (!trimmed) return;
      try {
        await api.renameTheme(themeId, trimmed);
        await refreshLibrary();
      } catch (err) {
        setError(describe(err));
      }
    },
    [refreshLibrary],
  );

  const savePersona = useCallback(
    async (payload: Partial<Persona>) => {
      try {
        setPersona(await api.savePersona(payload));
      } catch (err) {
        setError(describe(err));
      }
    },
    [],
  );

  return {
    threads,
    themes,
    tags,
    status,
    persona,
    scope,
    loading,
    error,
    reflecting,
    processing,
    freshReplies,
    setScope,
    create,
    reflect,
    connect,
    update,
    remove,
    dismissLink,
    renameTheme,
    savePersona,
    refresh,
    dismissError: () => setError(null),
  };
}
