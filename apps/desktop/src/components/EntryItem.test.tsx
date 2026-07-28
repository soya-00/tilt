import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Entry, Thread } from "../lib/types";
import { EntryItem } from "./EntryItem";

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
  return { entry: entry(), replies: [], ...overrides };
}

const noop = { onReflect: vi.fn(), onUpdate: vi.fn(), onDelete: vi.fn() };

describe("EntryItem", () => {
  it("renders the entry body", () => {
    render(<EntryItem thread={thread()} reflecting={false} {...noop} />);
    expect(screen.getByText(/Attention is a filter/)).toBeInTheDocument();
  });

  it("splits blank-line-separated paragraphs", () => {
    const t = thread({ entry: entry({ body: "First para.\n\nSecond para." }) });
    render(<EntryItem thread={t} reflecting={false} {...noop} />);

    expect(screen.getByText("First para.")).toBeInTheDocument();
    expect(screen.getByText("Second para.")).toBeInTheDocument();
  });

  it("requires a second click to delete", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    render(<EntryItem thread={thread()} reflecting={false} {...noop} onDelete={onDelete} />);

    await user.click(screen.getByRole("button", { name: "delete" }));
    expect(onDelete).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "confirm" }));
    expect(onDelete).toHaveBeenCalledWith("01ABC");
  });

  it("triggers a reflection", async () => {
    const user = userEvent.setup();
    const onReflect = vi.fn();
    render(<EntryItem thread={thread()} reflecting={false} {...noop} onReflect={onReflect} />);

    await user.click(screen.getByRole("button", { name: "reflect" }));
    expect(onReflect).toHaveBeenCalledWith("01ABC");
  });

  it("shows a pending reply while reflecting", () => {
    render(<EntryItem thread={thread()} reflecting={true} {...noop} />);
    expect(screen.getByText("reflecting", { selector: ".reply__label" })).toBeInTheDocument();
  });

  it("saves an edit on Cmd+Enter", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(<EntryItem thread={thread()} reflecting={false} {...noop} onUpdate={onUpdate} />);

    await user.click(screen.getByRole("button", { name: "edit" }));
    const editor = screen.getByLabelText("Edit entry");
    await user.clear(editor);
    await user.type(editor, "Revised wording.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    expect(onUpdate).toHaveBeenCalledWith("01ABC", "Revised wording.");
  });

  it("discards an edit on Escape", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(<EntryItem thread={thread()} reflecting={false} {...noop} onUpdate={onUpdate} />);

    await user.click(screen.getByRole("button", { name: "edit" }));
    await user.type(screen.getByLabelText("Edit entry"), " and more");
    await user.keyboard("{Escape}");

    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("hides actions on an optimistic entry that has no server id yet", () => {
    const t = thread({ entry: entry({ id: "pending-xyz" }) });
    render(<EntryItem thread={t} reflecting={false} {...noop} />);

    expect(screen.queryByRole("button", { name: "reflect" })).not.toBeInTheDocument();
  });

  it("renders machine replies in the machine's voice", () => {
    const t = thread({
      replies: [
        entry({ id: "r1", kind: "reply", reply_kind: "reflection", body: "A reflection." }),
      ],
    });
    render(<EntryItem thread={t} reflecting={false} {...noop} />);

    const reply = screen.getByText("A reflection.");
    expect(reply.closest(".reply__body")).toHaveClass("mono");
  });
});
