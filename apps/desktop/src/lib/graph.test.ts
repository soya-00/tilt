import { describe, expect, it } from "vitest";

import { hash, nodeAt, radius, relax, seed, settled, tick, viewport } from "./graph";
import type { Graph } from "./types";

function graph(
  nodes: { id: string; kind?: string; weight?: number }[],
  edges: { source: string; target: string; kind?: string }[] = [],
): Graph {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      label: n.id,
      kind: (n.kind ?? "note") as Graph["nodes"][number]["kind"],
      provenance: "self",
      created: null,
      weight: n.weight ?? 1,
    })),
    edges: edges.map((e) => ({
      source: e.source,
      target: e.target,
      kind: (e.kind ?? "echo") as Graph["edges"][number]["kind"],
      rationale: "",
    })),
    truncated: false,
    total: nodes.length,
  };
}

const distance = (sim: ReturnType<typeof seed>, a: string, b: string): number => {
  const x = sim.nodes.find((n) => n.id === a)!;
  const y = sim.nodes.find((n) => n.id === b)!;
  return Math.hypot(x.x - y.x, x.y - y.y);
};

describe("layout is deterministic", () => {
  it("places the same journal in the same shape every time", () => {
    // A layout that reshuffles on every open is a different graph each time and
    // cannot be learned. This is the property that makes the view navigable.
    const g = graph([{ id: "a" }, { id: "b" }, { id: "c" }], [{ source: "a", target: "b" }]);
    const first = relax(seed(g, 800, 600));
    const second = relax(seed(g, 800, 600));
    expect(first.nodes.map((n) => [n.x, n.y])).toEqual(second.nodes.map((n) => [n.x, n.y]));
  });

  it("hashes ids without collapsing them onto one point", () => {
    const seen = new Set([hash("a"), hash("b"), hash("c"), hash("d")]);
    expect(seen.size).toBe(4);
  });
});

describe("forces", () => {
  it("pulls two connected nodes toward the rest length", () => {
    const sim = relax(seed(graph([{ id: "a" }, { id: "b" }], [{ source: "a", target: "b" }]), 800, 600));
    expect(distance(sim, "a", "b")).toBeGreaterThan(60);
    expect(distance(sim, "a", "b")).toBeLessThan(170);
  });

  it("holds a folder closer to its members than a connection holds two thoughts", () => {
    // A folder should read as a cluster's centre, not as one more thought.
    const linked = relax(
      seed(graph([{ id: "a" }, { id: "b" }], [{ source: "a", target: "b", kind: "echo" }]), 800, 600),
    );
    const filed = relax(
      seed(
        graph(
          [{ id: "a" }, { id: "t", kind: "theme", weight: 1 }],
          [{ source: "a", target: "t", kind: "member" }],
        ),
        800,
        600,
      ),
    );
    expect(distance(filed, "a", "t")).toBeLessThan(distance(linked, "a", "b"));
  });

  it("settles connected thoughts closer together than unrelated ones", () => {
    // The one claim the picture makes. If proximity did not mean connection,
    // the layout would be decoration.
    const sim = relax(
      seed(graph([{ id: "a" }, { id: "b" }, { id: "c" }], [{ source: "a", target: "b" }]), 800, 600),
    );
    expect(distance(sim, "a", "b")).toBeLessThan(distance(sim, "a", "c"));
    expect(distance(sim, "a", "b")).toBeLessThan(distance(sim, "b", "c"));
  });

  it("separates two nodes that start exactly on top of each other", () => {
    // Coincident nodes have no direction to separate along; without the nudge
    // the distance stays zero and both vanish under one dot.
    const sim = seed(graph([{ id: "a" }, { id: "b" }]), 800, 600);
    sim.nodes[0]!.x = 400;
    sim.nodes[0]!.y = 300;
    sim.nodes[1]!.x = 400;
    sim.nodes[1]!.y = 300;
    relax(sim);
    expect(distance(sim, "a", "b")).toBeGreaterThan(1);
  });
});

describe("the simulation stops", () => {
  it("freezes rather than running forever", () => {
    // A force layout that never settles is a fan spinning for no reason.
    const sim = seed(graph([{ id: "a" }, { id: "b" }, { id: "c" }]), 800, 600);
    expect(settled(sim)).toBe(false);
    for (let i = 0; i < 600; i += 1) tick(sim);
    expect(settled(sim)).toBe(true);
  });
});

describe("what gets drawn", () => {
  it("drops an edge whose other end was filtered out", () => {
    // An edge to a node that is not there would be drawn to nowhere, or would
    // make the layout invent a phantom to hang it on.
    const sim = seed(graph([{ id: "a" }], [{ source: "a", target: "gone" }]), 800, 600);
    expect(sim.edges).toHaveLength(0);
  });

  it("counts the edges touching each node", () => {
    const sim = seed(
      graph([{ id: "a" }, { id: "b" }, { id: "c" }], [{ source: "a", target: "b" }]),
      800,
      600,
    );
    expect(sim.nodes.find((n) => n.id === "a")!.degree).toBe(1);
    expect(sim.nodes.find((n) => n.id === "c")!.degree).toBe(0);
  });

  it("sizes a dot by how connected it is, not by how much was written", () => {
    // A graph that sized nodes by body length would reward verbosity. What
    // earns a bigger dot is having met more of the rest of the journal.
    const note = { kind: "note", weight: 1 };
    expect(radius(note, 6)).toBeGreaterThan(radius(note, 1));
    expect(radius({ kind: "note", weight: 1 }, 3)).toBe(
      radius({ kind: "card", weight: 40 }, 3),
    );
  });

  it("sizes a folder by its members, which is its degree", () => {
    expect(radius({ kind: "theme", weight: 9 })).toBe(radius({ kind: "note", weight: 1 }, 9));
  });

  it("grows by area, so a busy node does not swallow the canvas", () => {
    const growth = (from: number, to: number) =>
      radius({ kind: "note", weight: 1 }, to) - radius({ kind: "note", weight: 1 }, from);
    expect(growth(1, 2)).toBeGreaterThan(growth(8, 9));
    expect(radius({ kind: "theme", weight: 400 })).toBeLessThanOrEqual(14);
  });
});

describe("hit testing", () => {
  it("finds the node under the cursor and nothing under empty space", () => {
    const sim = seed(graph([{ id: "a" }]), 800, 600);
    const node = sim.nodes[0]!;
    expect(nodeAt(sim, node.x, node.y)?.id).toBe("a");
    expect(nodeAt(sim, node.x + 400, node.y + 400)).toBeNull();
  });

  it("picks the nearest when two overlap", () => {
    const sim = seed(graph([{ id: "a" }, { id: "b" }]), 800, 600);
    sim.nodes[0]!.x = 100;
    sim.nodes[0]!.y = 100;
    sim.nodes[1]!.x = 104;
    sim.nodes[1]!.y = 100;
    expect(nodeAt(sim, 100, 100)?.id).toBe("a");
    expect(nodeAt(sim, 104, 100)?.id).toBe("b");
  });
});

describe("viewport", () => {
  it("fits a settled layout inside the canvas", () => {
    const sim = relax(seed(graph(Array.from({ length: 20 }, (_, i) => ({ id: `n${i}` }))), 800, 600));
    const { scale, dx, dy } = viewport(sim, 800, 600);
    for (const node of sim.nodes) {
      expect(node.x * scale + dx).toBeGreaterThanOrEqual(0);
      expect(node.x * scale + dx).toBeLessThanOrEqual(800);
      expect(node.y * scale + dy).toBeGreaterThanOrEqual(0);
      expect(node.y * scale + dy).toBeLessThanOrEqual(600);
    }
  });

  it("never magnifies a lone node into a balloon", () => {
    const sim = seed(graph([{ id: "a" }]), 800, 600);
    expect(viewport(sim, 800, 600).scale).toBeLessThanOrEqual(1.6);
  });

  it("survives an empty graph", () => {
    expect(viewport(seed(graph([]), 800, 600), 800, 600)).toEqual({ scale: 1, dx: 0, dy: 0 });
  });
});
