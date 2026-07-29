/**
 * The constellation — the journal as a shape rather than a sequence.
 *
 * This is a navigation surface, not a picture. The whole feature is gated on
 * one question: does it ever actually make you open an old entry? Everything
 * here bends toward yes — it is a rail beside the Stream rather than a panel
 * over it, so clicking a node scrolls that entry into view without the graph
 * going anywhere; every dot carries its own label; hovering one shows the
 * agent's own sentence about why it drew the line; and the folder filter can be
 * cleared from in here, because a graph locked to where you already are can
 * never take you somewhere new.
 *
 * Drawn in greyscale, deliberately. Colour in a graph claims the categories it
 * encodes are worth learning, and here they are not — what a dot's size means
 * is how connected it is, and that is the whole legend.
 *
 * Only connected nodes are drawn by default. An entry nothing has met yet is
 * reported as a count rather than added to a cloud of dust: the graph is about
 * what has connected, and inventory belongs in the sidebar.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { relax, nodeAt, seed, settled, tick, viewport } from "../lib/graph";
import type { Sim, SimNode } from "../lib/graph";
import type { Graph, Scope } from "../lib/types";
import { useIsDark } from "../lib/useTheme";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  /** What the Stream is showing. Opening the graph should not lose your place. */
  scope: Scope;
  onClose: () => void;
  /** The label is a fallback route: an entry older than the Stream's page is
   *  only reachable by searching for its own opening words. */
  onOpenEntry: (entryId: string, hint?: string) => void;
  onScope: (scope: Scope) => void;
}

type Window = "all" | "90d" | "30d";

/* How many dots are named at rest, regardless of how many there are.
 *
 * Two budgets rather than one, because folders and thoughts scale in opposite
 * directions. A folder's degree is its membership, so on a large journal
 * folders would win every place in a shared budget and no thought would ever
 * be named; on a small one each folder has a single member and they lose every
 * place instead, taking the labels that orient you with them. Separate
 * allowances make the map legible at twenty nodes and at three thousand.
 *
 * Everything outside the budget answers to hover, which is the point of
 * rationing: a picture readable at a glance, and a way to interrogate the rest. */
const FOLDER_LABELS = 6;
const THOUGHT_LABELS = 8;

/** Below this a dot is not a hub, it is a thing with a neighbour. Naming those
 *  is what turns the graph into a wall of text. */
const HUB_DEGREE = 2;

const WINDOWS: { id: Window; label: string }[] = [
  { id: "all", label: "All time" },
  { id: "90d", label: "90 days" },
  { id: "30d", label: "30 days" },
];

/** Shorten a label until it fits, measured rather than counted.
 *
 *  Character counts lie: "Will it" and "MMMMMMM" are the same length and not
 *  remotely the same width, and a label that overruns the rail is worse than
 *  one cut short. */
function clip(ctx: CanvasRenderingContext2D, text: string, room: number): string {
  if (ctx.measureText(text).width <= room) return text;
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (ctx.measureText(`${text.slice(0, mid).trimEnd()}…`).width <= room) lo = mid;
    else hi = mid - 1;
  }
  return `${text.slice(0, lo).trimEnd()}…`;
}

function since(window: Window): string | undefined {
  if (window === "all") return undefined;
  const days = window === "90d" ? 90 : 30;
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

export function Constellation({ open, scope, onClose, onOpenEntry, onScope }: Props) {
  const dark = useIsDark();
  const canvas = useRef<HTMLCanvasElement>(null);
  const frame = useRef(0);
  const simRef = useRef<Sim | null>(null);

  const [graph, setGraph] = useState<Graph | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [window_, setWindow] = useState<Window>("all");
  const [sources, setSources] = useState(false);
  const [folders, setFolders] = useState(true);
  const [hover, setHover] = useState<SimNode | null>(null);
  const [folder, setFolder] = useState<{ id: string; label: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  // The graph opens on the folder you were browsing — that is the graph you
  // meant — but keeps its own copy of that filter so it can be widened from in
  // here. Locked to the Stream's scope it could only ever show you where you
  // already are, which is the one thing that would make it useless.
  useEffect(() => {
    if (!open) return;
    setFolder(scope.type === "theme" ? { id: scope.id, label: scope.label } : null);
  }, [open, scope]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    api
      .graph({
        since: since(window_),
        theme_id: folder?.id,
        include_sources: sources,
        include_themes: folders,
      })
      .then((next) => {
        if (cancelled) return;
        setGraph(next);
        setError(null);
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open, window_, sources, folders, folder]);

  /** Connected nodes only, filtered here so the toggle never refetches. */
  const drawn = useMemo(() => {
    if (!graph) return null;
    const touched = new Set<string>();
    for (const edge of graph.edges) {
      touched.add(edge.source);
      touched.add(edge.target);
    }
    return {
      ...graph,
      nodes: graph.nodes.filter((n) => touched.has(n.id)),
    };
  }, [graph]);

  const isolated = (graph?.nodes.length ?? 0) - (drawn?.nodes.length ?? 0);

  const paint = useCallback(() => {
    const el = canvas.current;
    const sim = simRef.current;
    if (!el || !sim) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;

    const dpr = globalThis.devicePixelRatio || 1;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (el.width !== w * dpr || el.height !== h * dpr) {
      el.width = w * dpr;
      el.height = h * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const { scale, dx, dy } = viewport(sim, w, h);

    // Greyscale throughout. Colour in a graph is a claim that the categories it
    // encodes are worth learning, and here they are not: the writer already
    // knows a folder from a thought, and tinting link kinds would make a
    // three-line diagram look like a subway map. What varies is weight.
    const dot = dark ? "255,255,255" : "22,24,28";
    const near = hover
      ? new Set(
          sim.edges
            .filter((e) => e.a === hover || e.b === hover)
            .flatMap((e) => [e.a.id, e.b.id]),
        )
      : null;
    const lit = (id: string) => (near ? (near.has(id) ? 1 : 0.18) : 1);

    ctx.save();
    ctx.translate(dx, dy);
    ctx.scale(scale, scale);
    ctx.lineCap = "round";
    for (const edge of sim.edges) {
      // Membership is scaffolding, not a finding, so it is drawn fainter — the
      // agent's actual connections stay the loud thing.
      const member = edge.kind === "member";
      const strength = (member ? 0.14 : 0.32) * lit(edge.a.id);
      ctx.strokeStyle = `rgba(${dot},${strength})`;
      ctx.lineWidth = (member ? 0.7 : 1.1) / scale;
      ctx.beginPath();
      ctx.moveTo(edge.a.x, edge.a.y);
      ctx.lineTo(edge.b.x, edge.b.y);
      ctx.stroke();
    }
    ctx.restore();

    // Nodes and labels are painted in screen space, with the layout transform
    // undone. Under the transform a dot's size and its label's type both track
    // the zoom, and the text runs past the panel edge — in a rail that is
    // narrow by design, that is most labels.
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.font = "11px -apple-system, system-ui, sans-serif";
    const room = Math.min(w - 16, 118);

    for (const node of sim.nodes) {
      const x = node.x * scale + dx;
      const y = node.y * scale + dy;
      // Borrowed material sits back a little. Provenance is the one distinction
      // worth keeping in a greyscale picture, and opacity can carry it without
      // introducing a second shape to learn.
      const strength = lit(node.id) * (node.provenance === "source" ? 0.6 : 1);
      ctx.fillStyle = `rgba(${dot},${node === hover ? 1 : strength * 0.82})`;
      ctx.beginPath();
      ctx.arc(x, y, node.r + (node === hover ? 1.5 : 0), 0, Math.PI * 2);
      ctx.fill();
    }

    // Labels are rationed, and the ration is a count rather than a threshold.
    //
    // A fixed size threshold does not survive scale: pick one that leaves a
    // 20-thought journal readable and a 3,000-thought one is a solid mat of
    // text; pick one for 3,000 and a new journal is unlabelled dots. A budget
    // self-scales — the busiest dozen are named at any size, which at twenty
    // nodes is most of them and at three thousand is the handful of hubs you
    // could actually have been looking for. Everything else answers to hover.
    const rank = (kind: "theme" | "entry", take: number, floor: number) =>
      sim.nodes
        .filter((n) => (n.kind === "theme") === (kind === "theme") && n.degree >= floor)
        .sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id))
        .slice(0, take)
        .map((n) => n.id);

    const budget = new Set([
      // A folder with one member is still the name of a cluster, so folders
      // have no hub floor — there is nothing else on the canvas that says what
      // you are looking at.
      ...rank("theme", FOLDER_LABELS, 1),
      ...rank("entry", THOUGHT_LABELS, HUB_DEGREE),
    ]);

    // Biggest first, and a label is skipped when its box would land on one
    // already drawn. Overlapping text is worse than absent text: two labels on
    // top of each other cost you both, and the node is still there to hover.
    const taken: { x: number; y: number; w: number }[] = [];
    for (const node of [...sim.nodes].sort((a, b) => b.r - a.r)) {
      const focused = node === hover || near?.has(node.id);
      if (!focused && !budget.has(node.id)) continue;

      const x = Math.min(Math.max(node.x * scale + dx, room / 2 + 8), w - room / 2 - 8);
      const y = node.y * scale + dy + node.r + 5;
      const text = clip(ctx, node.label, room);
      const width = ctx.measureText(text).width;
      const clash = taken.some(
        (box) => Math.abs(box.y - y) < 13 && Math.abs(box.x - x) < (box.w + width) / 2 + 6,
      );
      // A hovered node's label is never dropped. It is the answer to a question
      // the user just asked, and losing it to a collision would make hovering
      // feel broken rather than crowded.
      if (clash && !focused) continue;
      taken.push({ x, y, w: width });

      const strength = lit(node.id) * (node.provenance === "source" ? 0.6 : 1);
      ctx.fillStyle = `rgba(${dot},${strength * (focused ? 0.95 : 0.62)})`;
      ctx.fillText(text, x, y);
    }
  }, [dark, hover]);

  // Seed and run the simulation. It settles and then stops — a force layout
  // that never freezes is a fan spinning for no reason.
  useEffect(() => {
    const el = canvas.current;
    if (!open || !drawn || !el) return;
    const sim = seed(drawn, el.clientWidth || 900, el.clientHeight || 600);
    // Most of the untangling happens before the first frame, so the graph
    // arrives roughly in shape and then settles, rather than exploding outward.
    relax(sim, 120);
    simRef.current = sim;

    // A flag as well as the cancel: the loop must stop even where the host's
    // cancelAnimationFrame is a no-op, or a closed overlay keeps painting.
    let running = true;
    const step = () => {
      if (!running) return;
      if (!settled(sim)) tick(sim);
      paint();
      if (!settled(sim)) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => {
      running = false;
      cancelAnimationFrame(frame.current);
    };
  }, [open, drawn, paint]);

  // A hover changes only what is lit, so it repaints without re-simulating.
  useEffect(() => {
    if (simRef.current && settled(simRef.current)) paint();
  }, [hover, paint]);

  const locate = (e: React.MouseEvent<HTMLCanvasElement>): SimNode | null => {
    const el = canvas.current;
    const sim = simRef.current;
    if (!el || !sim) return null;
    const box = el.getBoundingClientRect();
    const { scale, dx, dy } = viewport(sim, el.clientWidth, el.clientHeight);
    return nodeAt(
      sim,
      (e.clientX - box.left - dx) / scale,
      (e.clientY - box.top - dy) / scale,
    );
  };

  /** Takes only what it needs, so the keyboard list can call it without a
   *  simulation node to hand.
   *
   *  Note what it does *not* do: close the panel. As a rail the graph sits
   *  beside the Stream rather than over it, so clicking a node scrolls the
   *  entry into view with the constellation still on screen — you can follow a
   *  thread of connections without reopening the picture between each one. */
  const activate = (node: { id: string; label: string; kind: string }) => {
    if (node.kind === "theme") onScope({ type: "theme", id: node.id, label: node.label });
    else onOpenEntry(node.id, node.label);
  };

  const summary = loading
    ? "reading…"
    : error
      ? error
      : graph
        ? `${drawn?.nodes.length ?? 0} connected` +
          (isolated > 0 ? ` · ${isolated} on their own` : "") +
          // Entries, not nodes: `total` counts entries, and folders in the
          // numerator would make the sentence compare two different things.
          (graph.truncated
            ? ` · newest ${graph.nodes.filter((n) => n.kind !== "theme").length}` +
              ` of ${graph.total}`
            : "")
        : "";

  return (
    /* Always mounted, so collapsing is a width the browser can animate rather
       than a panel that vanishes. Nothing is fetched or drawn while closed. */
    <aside
      className={"rail glass glass--edge-left" + (open ? "" : " rail--closed")}
      aria-label="Constellation"
      aria-hidden={!open}
    >
      <div className="rail__inner">
        <header className="rail__head">
          <h2 className="sheet__title">Constellation</h2>
          <button
            className="icon-btn"
            aria-label="Collapse the constellation"
            title="Collapse (⌘G)"
            onClick={onClose}
          >
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="constellation__strip">
          {WINDOWS.map((w) => (
            <button
              key={w.id}
              className={"chip-btn" + (window_ === w.id ? " chip-btn--on" : "")}
              aria-pressed={window_ === w.id}
              onClick={() => setWindow(w.id)}
            >
              {w.label}
            </button>
          ))}
          <button
            className={"chip-btn" + (sources ? " chip-btn--on" : "")}
            aria-pressed={sources}
            onClick={() => setSources((v) => !v)}
          >
            What I&rsquo;ve read
          </button>
          <button
            className={"chip-btn" + (folders ? " chip-btn--on" : "")}
            aria-pressed={folders}
            onClick={() => setFolders((v) => !v)}
          >
            Folders
          </button>
          {folder && (
            /* The way back out. Clearing this widens the graph without moving
               the Stream — you can look somewhere else without leaving where
               you are. */
            <button
              className="chip-btn chip-btn--on"
              aria-label={`Show the whole journal instead of ${folder.label}`}
              onClick={() => setFolder(null)}
            >
              {folder.label}
              <span className="chip-btn__clear">×</span>
            </button>
          )}
        </div>

        <div className="constellation__stage">
          <canvas
            ref={canvas}
            className="constellation__canvas"
            aria-label="Entries and folders as a graph"
            onMouseMove={(e) => {
              const node = locate(e);
              setHover(node);
              e.currentTarget.style.cursor = node ? "pointer" : "default";
            }}
            onMouseLeave={() => setHover(null)}
            onClick={(e) => {
              const node = locate(e);
              if (node) activate(node);
            }}
          />
          {/* The same graph as a list. A canvas is unreachable by keyboard and
              invisible to a screen reader, and "click a node" cannot be the
              only way in — so every drawn node is also a real button. */}
          <ul className="visually-hidden">
            {(drawn?.nodes ?? []).map((node) => (
              <li key={node.id}>
                <button onClick={() => activate(node)}>
                  {node.kind === "theme" ? `Browse ${node.label}` : `Open ${node.label}`}
                </button>
              </li>
            ))}
          </ul>

          {drawn && drawn.nodes.length === 0 && !loading && (
            <p className="constellation__empty">
              Nothing has connected yet. Keep writing — the agent draws these
              lines on its own, and they take a few entries to appear.
            </p>
          )}
          {hover && <Readout node={hover} sim={simRef.current} />}
        </div>

        <footer className="rail__foot">
          <p className="sheet__note sheet__note--quiet">{summary}</p>
          <p className="sheet__note sheet__note--quiet">
            Click a thought to find it in the stream. Click a folder to browse it.
          </p>
        </footer>
      </div>
    </aside>
  );
}

/** What the agent said about the connections touching the node under the cursor.
 *
 *  Without the sentence, an edge is a claim with no argument behind it — and
 *  the reason to click through is usually in the rationale, not the label. */
function Readout({ node, sim }: { node: SimNode; sim: Sim | null }) {
  const reasons = (sim?.edges ?? [])
    .filter((e) => (e.a === node || e.b === node) && e.kind !== "member" && e.rationale)
    .slice(0, 3);

  return (
    <div className="constellation__readout glass">
      <p className="constellation__label">{node.label}</p>
      {node.kind === "theme" ? (
        <p className="sheet__note sheet__note--quiet">
          {node.weight} {node.weight === 1 ? "entry" : "entries"} here
        </p>
      ) : (
        reasons.map((edge, i) => (
          <p key={i} className="sheet__note sheet__note--quiet">
            {edge.kind} — {edge.rationale}
          </p>
        ))
      )}
    </div>
  );
}
