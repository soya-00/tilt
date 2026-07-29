/** The constellation's physics.
 *
 * A small force simulation rather than a graph library. With the server's
 * 300-node cap, naive all-pairs repulsion is under 90k operations a tick —
 * nothing — so Barnes-Hut buys us no frame budget we need, and a library would
 * arrive with a default paint that looks nothing like the rest of the app.
 *
 * Layout is *deterministic*: starting positions come from a hash of the entry
 * id, never from `Math.random`. Reopening the constellation therefore redraws
 * the same picture, and a journal you visit often becomes a place you can
 * remember your way around. A layout that reshuffles on every open is a
 * different graph each time and cannot be learned.
 *
 * Everything here is pure arithmetic over plain objects — no canvas, no DOM —
 * so it is testable directly.
 */

import type { Graph, GraphEdge } from "./types";

export interface SimNode {
  id: string;
  label: string;
  kind: string;
  provenance: string;
  /** Members, for a folder. Drives radius. */
  weight: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  /** Edges touching this node. Zero means it is drawn only when asked for. */
  degree: number;
}

export interface SimEdge extends GraphEdge {
  /** Resolved once at seed time so the tick loop never does a map lookup. */
  a: SimNode;
  b: SimNode;
}

export interface Sim {
  nodes: SimNode[];
  edges: SimEdge[];
  /** Simulation temperature. Decays each tick; at zero the layout is settled. */
  alpha: number;
  width: number;
  height: number;
}

const REPULSION = 5200;
const SPRING = 0.035;
/** Rest length. Long enough that labels beside two joined nodes do not collide. */
const REST = 110;
const MEMBER_REST = 78;
/** Folders sit closer to their members than two connected thoughts do, so a
 *  theme reads as a cluster's centre rather than as another thought. */
const CENTERING = 0.004;
const DAMPING = 0.82;
const ALPHA_DECAY = 0.985;
/** Below this the picture is not visibly moving and the loop should stop. A
 *  simulation that never freezes is a battery drain with a fan attached. */
const ALPHA_MIN = 0.02;

/** Deterministic 32-bit hash. Only ever used to place a node, never for ids. */
export function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Every node is a dot. Its size is how connected it is, nothing else.
 *
 *  Not how much was written — a graph that sizes nodes by body length rewards
 *  verbosity. What earns a bigger dot is having met more of the rest of the
 *  journal, which is the one thing the picture is actually about. A folder is
 *  sized by its members for the same reason: that is its degree. */
export function radius(node: { kind: string; weight: number }, degree = 0): number {
  const links = node.kind === "theme" ? node.weight : degree;
  // Area, not radius, tracks the count: doubling the connections should look
  // twice as big, and scaling the radius would make it look four times.
  return Math.min(14, 3.2 + Math.sqrt(links) * 2.1);
}

export function seed(graph: Graph, width: number, height: number): Sim {
  const degree = new Map<string, number>();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  const nodes: SimNode[] = graph.nodes.map((n) => {
    const h = hash(n.id);
    const deg = degree.get(n.id) ?? 0;
    // Golden-angle spiral: an even fill with no clumping, from one number.
    const angle = (h % 1000) * 2.399963;
    const spread = Math.min(width, height) * 0.36;
    const distance = Math.sqrt(((h >>> 10) % 1000) / 1000) * spread;
    return {
      id: n.id,
      label: n.label,
      kind: n.kind,
      provenance: n.provenance,
      weight: n.weight,
      x: width / 2 + Math.cos(angle) * distance,
      y: height / 2 + Math.sin(angle) * distance,
      vx: 0,
      vy: 0,
      r: radius(n, deg),
      degree: deg,
    };
  });

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: SimEdge[] = [];
  for (const edge of graph.edges) {
    const a = byId.get(edge.source);
    const b = byId.get(edge.target);
    // An edge missing an end is dropped rather than drawn to nowhere. The
    // server already guarantees this; the client refuses to assume it.
    if (a && b) edges.push({ ...edge, a, b });
  }

  return { nodes, edges, alpha: 1, width, height };
}

/** Advance the simulation one step. Mutates in place and returns the new alpha. */
export function tick(sim: Sim): number {
  const { nodes, edges, alpha } = sim;

  for (let i = 0; i < nodes.length; i += 1) {
    const a = nodes[i]!;
    for (let j = i + 1; j < nodes.length; j += 1) {
      const b = nodes[j]!;
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) {
        // Two nodes exactly on top of each other have no direction to separate
        // along. Nudge them apart deterministically rather than at random.
        dx = (hash(a.id) % 7) - 3 || 1;
        dy = (hash(b.id) % 7) - 3 || 1;
        d2 = dx * dx + dy * dy;
      }
      const force = REPULSION / d2;
      const d = Math.sqrt(d2);
      const fx = (dx / d) * force;
      const fy = (dy / d) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  for (const edge of edges) {
    const { a, b } = edge;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 1;
    const rest = edge.kind === "member" ? MEMBER_REST : REST;
    const force = (d - rest) * SPRING;
    const fx = (dx / d) * force;
    const fy = (dy / d) * force;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }

  const cx = sim.width / 2;
  const cy = sim.height / 2;
  // Centering is stronger along the short axis, which lets the cloud take the
  // shape of the space it is in. Repulsion is isotropic and would otherwise
  // settle into a disc — in a tall, narrow rail that means a small circle with
  // empty bands above and below it.
  const aspect = sim.height / Math.max(sim.width, 1);
  const kx = CENTERING * Math.max(1, aspect);
  const ky = CENTERING * Math.max(1, 1 / aspect);
  for (const node of nodes) {
    // Deliberately not scaled by node count. Doing so made centering overwhelm
    // repulsion on a small graph and pull two unrelated thoughts together — and
    // it bought nothing, because `viewport` refits whatever spread results.
    node.vx += (cx - node.x) * kx;
    node.vy += (cy - node.y) * ky;
    node.vx *= DAMPING;
    node.vy *= DAMPING;
    node.x += node.vx * alpha;
    node.y += node.vy * alpha;
  }

  sim.alpha = alpha * ALPHA_DECAY;
  return sim.alpha;
}

export function settled(sim: Sim): boolean {
  return sim.alpha <= ALPHA_MIN;
}

/** Run to a stable layout without painting. Used by tests and the first frame. */
export function relax(sim: Sim, steps = 260): Sim {
  for (let i = 0; i < steps && !settled(sim); i += 1) tick(sim);
  return sim;
}

/** The node under a point, or null. Nearest-first so overlaps pick the top one. */
export function nodeAt(sim: Sim, x: number, y: number, slack = 8): SimNode | null {
  let best: SimNode | null = null;
  let bestD = Infinity;
  for (const node of sim.nodes) {
    const d = Math.hypot(node.x - x, node.y - y);
    if (d <= node.r + slack && d < bestD) {
      best = node;
      bestD = d;
    }
  }
  return best;
}

/** Fit the drawn layout to the viewport, so a settled graph is never off-screen. */
export function viewport(
  sim: Sim,
  width: number,
  height: number,
  pad = 56,
): { scale: number; dx: number; dy: number } {
  if (!sim.nodes.length) return { scale: 1, dx: 0, dy: 0 };
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of sim.nodes) {
    minX = Math.min(minX, n.x - n.r);
    minY = Math.min(minY, n.y - n.r);
    maxX = Math.max(maxX, n.x + n.r);
    maxY = Math.max(maxY, n.y + n.r);
  }
  const scale = Math.min(
    (width - pad * 2) / Math.max(maxX - minX, 1),
    (height - pad * 2) / Math.max(maxY - minY, 1),
    1.6,
  );
  return {
    scale,
    dx: width / 2 - ((minX + maxX) / 2) * scale,
    dy: height / 2 - ((minY + maxY) / 2) * scale,
  };
}
