import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Entry, Thread } from "../lib/types";
import { Stream } from "./Stream";

function entry(overrides: Partial<Entry> = {}): Entry {
  const now = new Date().toISOString();
  return {
    id: "01ABC",
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
    body: "Attention is a filter, not a spotlight.",
    ...overrides,
  };
}

function thread(overrides: Partial<Thread> = {}): Thread {
  return { entry: entry(), replies: [], themes: [], links: [], quiet: 0, ...overrides };
}

const handlers = {
  loading: false,
  scope: { type: "all" } as const,
  freshReplies: new Set<string>(),
  onReflect: vi.fn(),
  onUpdate: vi.fn(),
  onDelete: vi.fn(),
  onDismissLink: vi.fn(),
  onOpenEntry: vi.fn(),
  onScope: vi.fn(),
};

describe("Stream", () => {
  it("says how much of a source it held back", () => {
    // Filtering silently would be indistinguishable from losing the material.
    // The count is the app admitting it made a judgement.
    render(<Stream {...handlers} threads={[thread({ quiet: 7 })]} />);

    expect(screen.getByText(/7 more ideas from this source/i)).toBeInTheDocument();
  });

  it("says nothing when nothing was held back", () => {
    render(<Stream {...handlers} threads={[thread()]} />);
    expect(screen.queryByText(/kept quiet/i)).toBeNull();
  });

  it("counts one held-back idea in the singular", () => {
    render(<Stream {...handlers} threads={[thread({ quiet: 1 })]} />);
    expect(screen.getByText(/1 more idea from/i)).toBeInTheDocument();
  });

  it("offers a way to go and find them", () => {
    // Quiet is not deleted, so there has to be a route back to the rest.
    const onScope = vi.fn();
    render(
      <Stream
        {...handlers}
        onScope={onScope}
        threads={[thread({ entry: entry({ body: "A talk on memory\n\nSummary." }), quiet: 3 })]}
      />,
    );

    return userEvent.click(screen.getByText(/3 more ideas/i)).then(() => {
      expect(onScope).toHaveBeenCalledWith({ type: "search", q: "A talk on memory" });
    });
  });
});
