import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LinkKind, LinkedEntry } from "../lib/types";
import { Connection } from "./Connection";

function linked(kind: LinkKind = "echo"): LinkedEntry {
  const now = new Date().toISOString();
  return {
    link: {
      id: "L1",
      src_id: "A",
      dst_id: "B",
      kind,
      rationale: "both turn on attention as a filter",
      created: now,
      dismissed: false,
    },
    entry: {
      id: "B",
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
      body: "An earlier thought about attention.",
    },
  };
}

describe("Connection", () => {
  it("shows the relationship in plain language", () => {
    render(<Connection linked={linked()} onOpen={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText("echoes")).toBeInTheDocument();
  });

  it("names contradictions distinctly", () => {
    const { container } = render(
      <Connection linked={linked("contradiction")} onOpen={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(screen.getByText("contradicts")).toBeInTheDocument();
    expect(container.querySelector(".connection--contradiction")).toBeInTheDocument();
  });

  it("shows the rationale so the link can be judged", () => {
    render(<Connection linked={linked()} onOpen={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText(/attention as a filter/)).toBeInTheDocument();
  });

  it("opens the linked entry", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<Connection linked={linked()} onOpen={onOpen} onDismiss={vi.fn()} />);

    await user.click(screen.getByText(/An earlier thought/));
    expect(onOpen).toHaveBeenCalledWith("B");
  });

  it("dismisses in a single click", async () => {
    // A connector you cannot correct is one you stop trusting.
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<Connection linked={linked()} onOpen={vi.fn()} onDismiss={onDismiss} />);

    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalledWith("L1");
  });
});
