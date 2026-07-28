/** Journal state.
 *
 * Deliberately a single hook over a state library: the surface is one list of
 * threads plus a handful of mutations, and the interaction that matters most
 * (writing) must never wait on a network round trip. Creation and reflection
 * are therefore optimistic — the entry appears the instant you press send, and
 * only reconciles or rolls back afterwards.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "./api";
import type { Entry, Status, Thread } from "./types";

const PAGE = 50;

export interface JournalState {
  threads: Thread[];
  status: Status | null;
  loading: boolean;
  error: string | null;
  /** Entry ids currently awaiting a reflection. */
  reflecting: Set<string>;
  create: (body: string) => Promise<void>;
  reflect: (entryId: string) => Promise<void>;
  update: (entryId: string, body: string) => Promise<void>;
  remove: (entryId: string) => Promise<void>;
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
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reflecting, setReflecting] = useState<Set<string>>(new Set());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const describe = (err: unknown): string =>
    err instanceof ApiError ? err.message : "Something went wrong.";

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.status();
      if (mounted.current) setStatus(next);
    } catch {
      /* Status is ambient; a failure here must not disrupt writing. */
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await api.stream(PAGE);
      if (!mounted.current) return;
      setThreads(next);
      setError(null);
    } catch (err) {
      if (mounted.current) setError(describe(err));
    } finally {
      if (mounted.current) setLoading(false);
    }
    await refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (body: string) => {
      const trimmed = body.trim();
      if (!trimmed) return;

      const pending = optimisticEntry(trimmed);
      setThreads((prev) => [{ entry: pending, replies: [] }, ...prev]);

      try {
        const saved = await api.create(trimmed);
        setThreads((prev) => prev.map((t) => (t.entry.id === pending.id ? saved : t)));
        void refreshStatus();
      } catch (err) {
        setThreads((prev) => prev.filter((t) => t.entry.id !== pending.id));
        setError(describe(err));
        throw err;
      }
    },
    [refreshStatus],
  );

  const reflect = useCallback(
    async (entryId: string) => {
      setReflecting((prev) => new Set(prev).add(entryId));
      try {
        const reply = await api.reflect(entryId);
        setThreads((prev) =>
          prev.map((t) =>
            t.entry.id === entryId ? { ...t, replies: [...t.replies, reply] } : t,
          ),
        );
        void refreshStatus();
      } catch (err) {
        setError(describe(err));
      } finally {
        setReflecting((prev) => {
          const next = new Set(prev);
          next.delete(entryId);
          return next;
        });
      }
    },
    [refreshStatus],
  );

  const update = useCallback(async (entryId: string, body: string) => {
    const trimmed = body.trim();
    if (!trimmed) return;
    const previous = threads;
    setThreads((prev) =>
      prev.map((t) => (t.entry.id === entryId ? { ...t, entry: { ...t.entry, body: trimmed } } : t)),
    );
    try {
      const saved = await api.update(entryId, trimmed);
      setThreads((prev) => prev.map((t) => (t.entry.id === entryId ? { ...t, entry: saved } : t)));
    } catch (err) {
      setThreads(previous);
      setError(describe(err));
    }
    // `threads` is read only to build the rollback snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads]);

  const remove = useCallback(
    async (entryId: string) => {
      const previous = threads;
      setThreads((prev) => prev.filter((t) => t.entry.id !== entryId));
      try {
        await api.remove(entryId);
        void refreshStatus();
      } catch (err) {
        setThreads(previous);
        setError(describe(err));
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [threads, refreshStatus],
  );

  return {
    threads,
    status,
    loading,
    error,
    reflecting,
    create,
    reflect,
    update,
    remove,
    refresh,
    dismissError: () => setError(null),
  };
}
