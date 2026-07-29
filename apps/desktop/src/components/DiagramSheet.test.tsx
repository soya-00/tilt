import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import type { Artifact } from "../lib/types";
import { DiagramSheet } from "./DiagramSheet";

const parse = vi.fn();
const renderMermaid = vi.fn();

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    parse: (...args: unknown[]) => parse(...args),
    render: (...args: unknown[]) => renderMermaid(...args),
  },
}));

function artifact(over: Partial<Artifact> = {}): Artifact {
  return {
    id: "D1",
    kind: "mindmap",
    path: "/tmp/D1.md",
    title: "Attention",
    body: "mindmap\n  root((Attention))",
    note: "Grouped around what attention discards.",
    subject_ids: ["a", "b"],
    created: new Date().toISOString(),
    ...over,
  };
}

const props = {
  open: true,
  scope: { type: "theme", id: "t", label: "Attention" } as const,
  onClose: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  parse.mockResolvedValue(true);
  renderMermaid.mockResolvedValue({ svg: "<svg><title>drawn</title></svg>" });
  vi.spyOn(api, "diagram").mockResolvedValue(artifact());
  vi.spyOn(api, "repairDiagram").mockResolvedValue(artifact({ body: "mindmap\n  root((Fixed))" }));
});

describe("DiagramSheet", () => {
  it("draws the scope it was opened on and shows the agent's reading of it", async () => {
    render(<DiagramSheet {...props} />);

    await waitFor(() => expect(api.diagram).toHaveBeenCalledWith({ theme_id: "t" }));
    await screen.findByText("Grouped around what attention discards.");
    expect(renderMermaid).toHaveBeenCalled();
    expect(api.repairDiagram).not.toHaveBeenCalled();
  });

  it("sends a tag or a search rather than always a folder", async () => {
    render(<DiagramSheet {...props} scope={{ type: "search", q: "attention" }} />);
    await waitFor(() => expect(api.diagram).toHaveBeenCalledWith({ q: "attention" }));
  });

  it("repairs once, with the parser's own words", async () => {
    // A paraphrase of a parse error is worth nothing to the model fixing it.
    parse.mockRejectedValueOnce(new Error("Parse error on line 2: expected NODE"));
    render(<DiagramSheet {...props} />);

    await waitFor(() =>
      expect(api.repairDiagram).toHaveBeenCalledWith(
        "D1",
        "Parse error on line 2: expected NODE",
      ),
    );
    await screen.findByText("Grouped around what attention discards.");
  });

  it("stops after the second failure instead of looping", async () => {
    // Two failures is enough evidence that the model cannot draw this one, and
    // a third paid attempt converges on nothing.
    parse.mockRejectedValue(new Error("Parse error on line 2"));
    render(<DiagramSheet {...props} />);

    await screen.findByText("The diagram could not be drawn.");
    expect(api.repairDiagram).toHaveBeenCalledTimes(1);
  });

  it("shows both what broke and what it produced", async () => {
    // The writer paid for two attempts and is owed the evidence. A diagram that
    // silently never appears is indistinguishable from a hung app.
    parse.mockRejectedValue(new Error("Parse error on line 2"));
    render(<DiagramSheet {...props} />);

    await screen.findByText("Parse error on line 2");
    await screen.findByText(/root\(\(Fixed\)\)/);
  });

  it("says what to do rather than drawing everything", async () => {
    render(<DiagramSheet {...props} scope={{ type: "all" }} />);
    await screen.findByText(/no shape to find/);
    expect(api.diagram).not.toHaveBeenCalled();
  });

  it("surfaces a refusal from the service", async () => {
    vi.spyOn(api, "diagram").mockRejectedValue(new Error("There is nothing here to draw yet."));
    render(<DiagramSheet {...props} />);
    await screen.findByText("There is nothing here to draw yet.");
  });

  it("closes on Escape", async () => {
    render(<DiagramSheet {...props} />);
    await userEvent.keyboard("{Escape}");
    expect(props.onClose).toHaveBeenCalled();
  });

  it("costs nothing while it is closed", () => {
    render(<DiagramSheet {...props} open={false} />);
    expect(api.diagram).not.toHaveBeenCalled();
  });
});
