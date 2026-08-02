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
import type {
  Entry,
  Persona,
  PublicSettings,
  Misfiled,
  Notice,
  Scope,
  Status,
  TagCount,
  Theme,
  ThemeSplit,
  Thread,
} from "./types";

const PAGE = 50;

export interface JournalState {
  threads: Thread[];
  themes: Theme[];
  /** Folders the keeper thinks have become two. Almost always empty — the
   *  nightly pass proposes at most one and only when it is sure enough to
   *  spend a model call being told no. */
  splits: ThemeSplit[];
  /** What the weekly pass noticed. Empty most weeks, deliberately. */
  notices: Notice[];
  /** Entries the filing pass thinks are in the wrong folder. Usually empty. */
  moves: Misfiled[];
  /** Move ids being carried out. */
  moving: Set<string>;
  tags: TagCount[];
  status: Status | null;
  persona: Persona | null;
  settings: PublicSettings | null;
  scope: Scope;
  loading: boolean;
  error: string | null;
  /** Entry ids with a reflection in flight. */
  reflecting: Set<string>;
  /** Entry ids being categorised or connected. */
  processing: Set<string>;
  /** Notice ids with a synthesis in flight — the one weekly cost. */
  synthesising: Set<string>;
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
  deleteTheme: (themeId: string) => Promise<void>;
  acceptSplit: (splitId: string) => Promise<void>;
  dismissSplit: (splitId: string) => Promise<void>;
  dismissNotice: (noticeId: string) => Promise<void>;
  acceptMove: (moveId: string) => Promise<void>;
  dismissMove: (moveId: string) => Promise<void>;
  reflectOnNotice: (noticeId: string) => Promise<void>;
  savePersona: (payload: Partial<Persona>) => Promise<void>;
  saveSettings: (payload: {
    gemini_api_key?: string;
    gemini_model?: string;
    feeds?: string[];
  }) => Promise<void>;
  ingest: (payload: { title: string; text: string; url?: string }) => Promise<void>;
  ingestFile: (file: File) => Promise<void>;
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
  const [splits, setSplits] = useState<ThemeSplit[]>([]);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [moves, setMoves] = useState<Misfiled[]>([]);
  const [moving, setMoving] = useState<Set<string>>(new Set());
  const [tags, setTags] = useState<TagCount[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [scope, setScope] = useState<Scope>({ type: "all" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reflecting, setReflecting] = useState<Set<string>>(new Set());
  const [processing, setProcessing] = useState<Set<string>>(new Set());
  const [freshReplies, setFresh] = useState<Set<string>>(new Set());
  const [synthesising, setSynthesising] = useState<Set<string>>(new Set());

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
      const [
        nextThemes,
        nextTags,
        nextStatus,
        nextPersona,
        nextSettings,
        nextSplits,
        nextNotices,
        nextMoves,
      ] = await Promise.all([
        api.themes(),
        api.tags(),
        api.status(),
        api.persona(),
        api.settings(),
        api.splits(),
        api.notices(),
        api.moves(),
      ]);
      if (!mounted.current) return;
      setThemes(nextThemes);
      setSplits(nextSplits);
      setNotices(nextNotices);
      setMoves(nextMoves);
      setTags(nextTags);
      setStatus(nextStatus);
      setPersona(nextPersona);
      setSettings(nextSettings);
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
        { entry: pending, replies: [], themes: [], links: [], quiet: 0 },
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

  const deleteTheme = useCallback(
    async (themeId: string) => {
      // Drop it from the sidebar first: the request has to reach disk to
      // rewrite every affected entry's frontmatter, and a folder that lingers
      // for that long after you deleted it reads as a failure.
      const snapshot = themes;
      const threadSnapshot = threadsRef.current;
      setThemes((prev) => prev.filter((t) => t.id !== themeId));
      // Entries on screen are still wearing the folder as a chip.
      setThreads((prev) =>
        prev.map((t) => ({ ...t, themes: t.themes.filter((th) => th.id !== themeId) })),
      );
      // And the stream may be scoped to a folder that no longer exists.
      setScope((current) =>
        current.type === "theme" && current.id === themeId ? { type: "all" } : current,
      );
      try {
        await api.deleteTheme(themeId);
        await refreshLibrary();
      } catch (err) {
        setThemes(snapshot);
        setThreads(threadSnapshot);
        setError(describe(err));
      }
    },
    [refreshLibrary, themes],
  );

  const acceptSplit = useCallback(
    async (splitId: string) => {
      // Cleared from the sidebar first. Accepting rewrites the frontmatter of
      // every entry that moves, which takes long enough that a proposal still
      // sitting there reads as a click that did not land.
      setSplits((prev) => prev.filter((s) => s.id !== splitId));
      try {
        setThemes(await api.acceptSplit(splitId));
        await refreshLibrary();
      } catch (err) {
        setError(describe(err));
        await refreshLibrary();
      }
    },
    [refreshLibrary],
  );

  const dismissSplit = useCallback(
    async (splitId: string) => {
      setSplits((prev) => prev.filter((s) => s.id !== splitId));
      try {
        await api.dismissSplit(splitId);
      } catch (err) {
        setError(describe(err));
        await refreshLibrary();
      }
    },
    [refreshLibrary],
  );

  const dismissNotice = useCallback(
    async (noticeId: string) => {
      setNotices((prev) => prev.filter((n) => n.id !== noticeId));
      try {
        await api.dismissNotice(noticeId);
      } catch (err) {
        setError(describe(err));
        await refreshLibrary();
      }
    },
    [refreshLibrary],
  );

  const reflectOnNotice = useCallback(
    async (noticeId: string) => {
      // The only part of the weekly pass that spends anything, and it happens
      // because somebody pressed this. The row stays put while it runs, saying
      // so — a notice that vanished the moment you clicked would leave nothing
      // on screen for however long the model takes.
      setSynthesising((prev) => new Set(prev).add(noticeId));
      try {
        await api.reflectOnNotice(noticeId);
        setNotices((prev) => prev.filter((n) => n.id !== noticeId));
        // The answer is threaded under an entry, so it is the stream that has
        // to come back rather than the sidebar.
        await refresh();
      } catch (err) {
        setError(describe(err));
        await refreshLibrary();
      } finally {
        setSynthesising((prev) => {
          const next = new Set(prev);
          next.delete(noticeId);
          return next;
        });
      }
    },
    [refresh, refreshLibrary],
  );

  const acceptMove = useCallback(
    async (moveId: string) => {
      // The row stays put while it runs, saying so. Refiling rewrites the
      // entry's frontmatter, which takes long enough that a row vanishing on
      // click would look like nothing happened.
      setMoving((prev) => new Set(prev).add(moveId));
      try {
        const thread = await api.acceptMove(moveId);
        setMoves((prev) => prev.filter((m) => m.id !== moveId));
        // The entry's folder chips changed, so fold the fresh thread in rather
        // than refetching the whole stream for one row.
        setThreads((prev) => prev.map((t) => (t.entry.id === thread.entry.id ? thread : t)));
        await refreshLibrary();
      } catch (err) {
        setError(describe(err));
        await refreshLibrary();
      } finally {
        setMoving((prev) => {
          const next = new Set(prev);
          next.delete(moveId);
          return next;
        });
      }
    },
    [refreshLibrary],
  );

  const dismissMove = useCallback(
    async (moveId: string) => {
      setMoves((prev) => prev.filter((m) => m.id !== moveId));
      try {
        await api.dismissMove(moveId);
      } catch (err) {
        setError(describe(err));
        await refreshLibrary();
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

  const saveSettings = useCallback(
    async (payload: { gemini_api_key?: string; gemini_model?: string; feeds?: string[] }) => {
      try {
        setSettings(await api.saveSettings(payload));
        await refreshLibrary();
      } catch (err) {
        setError(describe(err));
      }
    },
    [refreshLibrary],
  );

  const ingest = useCallback(
    async (payload: { title: string; text: string; url?: string }) => {
      try {
        const source = await api.ingest(payload);
        setThreads((prev) => [source, ...prev]);
        await refreshLibrary();
      } catch (err) {
        setError(describe(err));
        throw err;
      }
    },
    [refreshLibrary],
  );

  const ingestFile = useCallback(
    async (file: File) => {
      try {
        const source = await api.ingestFile(file, file.name.replace(/\.[^.]+$/, ""));
        setThreads((prev) => [source, ...prev]);
        await refreshLibrary();
      } catch (err) {
        // Rethrown as well as recorded: the composer shows the reason inline,
        // beside the file that caused it, which is where it means something.
        setError(describe(err));
        throw err;
      }
    },
    [refreshLibrary],
  );

  return {
    threads,
    themes,
    splits,
    notices,
    moves,
    moving,
    tags,
    status,
    persona,
    settings,
    scope,
    loading,
    error,
    reflecting,
    processing,
    synthesising,
    freshReplies,
    setScope,
    create,
    reflect,
    connect,
    update,
    remove,
    dismissLink,
    renameTheme,
    deleteTheme,
    acceptSplit,
    dismissSplit,
    dismissNotice,
    reflectOnNotice,
    acceptMove,
    dismissMove,
    savePersona,
    saveSettings,
    ingest,
    ingestFile,
    refresh,
    dismissError: () => setError(null),
  };
}
