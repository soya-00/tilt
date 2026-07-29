import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import type { Graph } from "../lib/types";
import { Constellation } from "./Constellation";

function graph(over: Partial<Graph> = {}): Graph {
  return {
    nodes: [
      {
        id: "a",
        label: "Attention is a budget",
        kind: "note",
        provenance: "self",
        created: null,
        weight: 1,
      },
      {
        id: "b",
        label: "Distraction is the interest",
        kind: "note",
        provenance: "self",
        created: null,
        weight: 1,
      },
      {
        id: "t",
        label: "Attention",
        kind: "theme",
        provenance: "self",
        created: null,
        weight: 2,
      },
    ],
    edges: [
      { source: "a", target: "b", kind: "echo", rationale: "both turn on cost" },
      { source: "a", target: "t", kind: "member", rationale: "" },
      { source: "b", target: "t", kind: "member", rationale: "" },
    ],
    truncated: false,
    total: 2,
    ...over,
  };
}

const props = {
  open: true,
  scope: { type: "all" } as const,
  onClose: vi.fn(),
  onOpenEntry: vi.fn(),
  onScope: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(api, "graph").mockResolvedValue(graph());
});

describe("Constellation", () => {
  it("takes you to the entry you clicked, and stays open while it does", async () => {
    // The whole feature is gated on this. A graph that does not open old
    // entries is a screensaver — and a graph that has to close itself to show
    // you one makes following a chain of connections cost a reopen each time.
    render(<Constellation {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Open Attention is a budget" }));

    expect(props.onOpenEntry).toHaveBeenCalledWith("a", "Attention is a budget");
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("browses a folder rather than trying to open it as an entry", async () => {
    render(<Constellation {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Browse Attention" }));

    expect(props.onScope).toHaveBeenCalledWith({ type: "theme", id: "t", label: "Attention" });
    expect(props.onOpenEntry).not.toHaveBeenCalled();
  });

  it("collapses from its own header, not only from the keyboard", async () => {
    render(<Constellation {...props} />);
    await userEvent.click(screen.getByRole("button", { name: "Collapse the constellation" }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("reaches every node from the keyboard", async () => {
    // The canvas cannot be tabbed to or read aloud, so the list beside it is
    // not a fallback — it is the accessible version of the same graph.
    render(<Constellation {...props} />);
    const buttons = await screen.findAllByRole("button", { name: /^(Open|Browse) / });
    expect(buttons).toHaveLength(3);
  });

  it("says how many entries are on their own instead of drawing them as dust", async () => {
    vi.spyOn(api, "graph").mockResolvedValue(
      graph({
        nodes: [
          ...graph().nodes,
          {
            id: "lonely",
            label: "Nothing has met this yet",
            kind: "note",
            provenance: "self",
            created: null,
            weight: 1,
          },
        ],
      }),
    );
    render(<Constellation {...props} />);
    await screen.findByText(/3 connected · 1 on their own/);
    expect(
      screen.queryByRole("button", { name: "Open Nothing has met this yet" }),
    ).not.toBeInTheDocument();
  });

  it("names the number it is not showing when the cap bites", async () => {
    vi.spyOn(api, "graph").mockResolvedValue(graph({ truncated: true, total: 412 }));
    render(<Constellation {...props} />);
    // Two of the three nodes are entries; the folder is not part of the count,
    // because `total` counts entries and the sentence has to compare like with
    // like.
    await screen.findByText(/newest 2 of 412/);
  });

  it("opens on the folder you were already browsing", async () => {
    // Opening the graph should not lose your place.
    render(
      <Constellation {...props} scope={{ type: "theme", id: "t", label: "Attention" }} />,
    );
    await waitFor(() =>
      expect(api.graph).toHaveBeenCalledWith(expect.objectContaining({ theme_id: "t" })),
    );
  });

  it("asks for what you have read only when you ask for it", async () => {
    render(<Constellation {...props} />);
    await waitFor(() =>
      expect(api.graph).toHaveBeenCalledWith(expect.objectContaining({ include_sources: false })),
    );

    await userEvent.click(screen.getByRole("button", { name: /What I/ }));
    await waitFor(() =>
      expect(api.graph).toHaveBeenCalledWith(expect.objectContaining({ include_sources: true })),
    );
  });

  it("narrows to a time window without touching the other filters", async () => {
    render(<Constellation {...props} />);
    await userEvent.click(screen.getByRole("button", { name: "30 days" }));

    await waitFor(() => {
      const last = vi.mocked(api.graph).mock.calls.at(-1)![0]!;
      expect(last.since).toEqual(expect.any(String));
      expect(last.include_themes).toBe(true);
    });
  });

  it("says why it is empty rather than showing a blank rectangle", async () => {
    vi.spyOn(api, "graph").mockResolvedValue(graph({ nodes: [], edges: [], total: 0 }));
    render(<Constellation {...props} />);
    await screen.findByText(/Nothing has connected yet/);
  });

  it("surfaces a failure instead of pretending the journal is empty", async () => {
    vi.spyOn(api, "graph").mockRejectedValue(new Error("Cannot reach the Tilt service."));
    render(<Constellation {...props} />);
    await screen.findByText("Cannot reach the Tilt service.");
  });

  it("closes on Escape", async () => {
    render(<Constellation {...props} />);
    await userEvent.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalled();
  });

  it("asks for nothing while it is closed", () => {
    render(<Constellation {...props} open={false} />);
    expect(api.graph).not.toHaveBeenCalled();
  });
});
