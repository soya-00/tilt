import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Entry, LinkKind, LinkedEntry } from "../lib/types";
import { ConnectionRow, EntryRow, ReplyRow } from "./Thread";

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

const handlers = {
  themes: [],
  connected: false,
  onScope: vi.fn(),
  onReflect: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
};

describe("EntryRow", () => {
  it("renders your words as plain text, never in a bubble", () => {
    // The bubble is reserved for the agent; containment is the only signal
    // separating the two voices.
    const { container } = render(<EntryRow entry={entry()} {...handlers} />);

    expect(screen.getByText(/Attention is a filter/)).toBeInTheDocument();
    expect(container.querySelector(".bubble")).toBeNull();
  });

  it("splits blank-line-separated paragraphs", () => {
    render(<EntryRow entry={entry({ body: "First.\n\nSecond." })} {...handlers} />);
    expect(screen.getByText("First.")).toBeInTheDocument();
    expect(screen.getByText("Second.")).toBeInTheDocument();
  });

  it("requires a second click to delete", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    render(<EntryRow entry={entry()} {...handlers} onDelete={onDelete} />);

    await user.click(screen.getByRole("button", { name: "delete" }));
    expect(onDelete).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "confirm" }));
    expect(onDelete).toHaveBeenCalledWith("01ABC");
  });

  it("saves an edit on Cmd+Enter and discards on Escape", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    render(<EntryRow entry={entry()} {...handlers} onEdit={onEdit} />);

    await user.click(screen.getByRole("button", { name: "edit" }));
    const editor = screen.getByLabelText("Edit entry");
    await user.clear(editor);
    await user.type(editor, "Revised.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(onEdit).toHaveBeenCalledWith("01ABC", "Revised.");
  });

  it("hides actions on an optimistic entry with no server id", () => {
    render(<EntryRow entry={entry({ id: "pending-x" })} {...handlers} />);
    expect(screen.queryByRole("button", { name: "reflect" })).not.toBeInTheDocument();
  });

  it("draws a connector only when something follows", () => {
    const { container, rerender } = render(<EntryRow entry={entry()} {...handlers} />);
    expect(container.querySelector(".row__connector")).toBeNull();

    rerender(<EntryRow entry={entry()} {...handlers} connected />);
    expect(container.querySelector(".row__connector")).toBeInTheDocument();
  });
});

describe("ReplyRow", () => {
  const reply = entry({ id: "r1", kind: "reply", reply_kind: "reflection", body: "One two three" });

  it("renders settled text when the reply is not fresh", () => {
    const { container } = render(<ReplyRow entry={reply} fresh={false} connected={false} />);
    expect(container.querySelectorAll(".word--pending")).toHaveLength(0);
  });

  it("starts a fresh reply unsettled so it lands word by word", () => {
    const { container } = render(<ReplyRow entry={reply} fresh connected={false} />);
    expect(container.querySelectorAll(".word--pending").length).toBeGreaterThan(0);
  });

  it("puts the agent's voice in an outlined bubble", () => {
    const { container } = render(<ReplyRow entry={reply} fresh={false} connected={false} />);
    expect(container.querySelector(".bubble")).toBeInTheDocument();
  });
});

describe("ConnectionRow", () => {
  function linked(kind: LinkKind = "echo"): LinkedEntry {
    return {
      link: {
        id: "L1",
        src_id: "A",
        dst_id: "B",
        kind,
        rationale: "both turn on attention",
        created: new Date().toISOString(),
        dismissed: false,
      },
      entry: entry({ id: "B", body: "An earlier thought about attention." }),
    };
  }

  it("names the relationship in plain language", () => {
    render(
      <ConnectionRow linked={linked()} connected={false} onOpen={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(screen.getByText("echoes")).toBeInTheDocument();
  });

  it("distinguishes a contradiction", () => {
    render(
      <ConnectionRow
        linked={linked("contradiction")}
        connected={false}
        onOpen={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("contradicts")).toBeInTheDocument();
  });

  it("opens the linked entry and dismisses in one click", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onDismiss = vi.fn();
    render(
      <ConnectionRow linked={linked()} connected={false} onOpen={onOpen} onDismiss={onDismiss} />,
    );

    await user.click(screen.getByText(/An earlier thought/));
    expect(onOpen).toHaveBeenCalledWith("B");

    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalledWith("L1");
  });
});
