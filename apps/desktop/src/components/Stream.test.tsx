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
  notices: [],
  synthesising: new Set<string>(),
  freshReplies: new Set<string>(),
  onReflect: vi.fn(),
  onUpdate: vi.fn(),
  onDelete: vi.fn(),
  onDismissLink: vi.fn(),
  onOpenEntry: vi.fn(),
  onScope: vi.fn(),
  onSynthesise: vi.fn(),
  onDismissNotice: vi.fn(),
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

describe("the weekly notice", () => {
  const notice = {
    id: "n1",
    kind: "contradiction" as const,
    body: "You wrote two things this week that pull against each other.",
    entry_ids: ["a", "b"],
    subject: "link:1",
    created: "2026-08-01T18:53:00Z",
    dismissed: false,
  };

  it("says what it found, in one sentence", () => {
    render(<Stream {...handlers} threads={[thread()]} notices={[notice]} />);

    expect(screen.getByText(/pull against each other/i)).toBeInTheDocument();
  });

  it("costs nothing until it is asked to", async () => {
    // The point of the whole design. Noticing runs on a schedule and is free;
    // the synthesis is a button, so a week nobody looks at is a week nobody
    // pays for.
    const user = userEvent.setup();
    const onSynthesise = vi.fn();
    render(
      <Stream {...handlers} threads={[thread()]} notices={[notice]} onSynthesise={onSynthesise} />,
    );

    expect(onSynthesise).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /look at this/i }));
    expect(onSynthesise).toHaveBeenCalledWith("n1");
  });

  it("can be waved away", async () => {
    const user = userEvent.setup();
    const onDismissNotice = vi.fn();
    render(
      <Stream
        {...handlers}
        threads={[thread()]}
        notices={[notice]}
        onDismissNotice={onDismissNotice}
      />,
    );

    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismissNotice).toHaveBeenCalledWith("n1");
  });

  it("stays put while the synthesis runs, and says so", () => {
    // A row that vanished the moment you clicked would leave nothing on screen
    // for however long the model takes.
    render(
      <Stream
        {...handlers}
        threads={[thread()]}
        notices={[notice]}
        synthesising={new Set(["n1"])}
      />,
    );

    expect(screen.getByRole("button", { name: /reading it back/i })).toBeDisabled();
  });

  it("shows nothing on a quiet week", () => {
    render(<Stream {...handlers} threads={[thread()]} />);

    expect(screen.queryByRole("button", { name: /look at this/i })).not.toBeInTheDocument();
  });

  it("stays out of a folder view", () => {
    // It is an observation about the journal, not about the folder you happen
    // to be looking at.
    render(
      <Stream
        {...handlers}
        threads={[thread()]}
        notices={[notice]}
        scope={{ type: "theme", id: "t", label: "Attention" }}
      />,
    );

    expect(screen.queryByText(/pull against each other/i)).not.toBeInTheDocument();
  });
});
