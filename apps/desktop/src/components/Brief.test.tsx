/**
 * The brief, from the reader's side.
 *
 * The property under most of these is the same one the backend tests protect
 * from the other direction: this is a shelf and not a queue. It has no counts,
 * no completion, and it does not congratulate anyone for emptying it.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import type { BriefItem } from "../lib/types";
import { Brief } from "./Brief";

function item(over: Partial<BriefItem> = {}): BriefItem {
  return {
    id: "b1",
    title: "Attention is not a spotlight",
    url: "https://arxiv.org/abs/2401.00001",
    why: "argues against the filter model you settled on in June",
    origin: "scout",
    created: new Date().toISOString(),
    dismissed: false,
    path: "/tmp/b1.md",
    ...over,
  };
}

const props = { open: true, onClose: vi.fn(), onRead: vi.fn() };

beforeEach(() => {
  vi.restoreAllMocks();
  props.onClose = vi.fn();
  props.onRead = vi.fn();
});

describe("Brief", () => {
  it("shows why something is there, not just what it is", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);

    render(<Brief {...props} />);

    expect(await screen.findByText("Attention is not a spotlight")).toBeInTheDocument();
    expect(
      screen.getByText(/argues against the filter model you settled on in June/),
    ).toBeInTheDocument();
  });

  it("says who put each item there", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([
      item(),
      item({ id: "b2", title: "A book chapter", origin: "you", url: null, why: "finish it" }),
    ]);

    render(<Brief {...props} />);

    expect(await screen.findByText(/found for you/)).toBeInTheDocument();
    expect(screen.getByText(/yours/)).toBeInTheDocument();
  });

  it("offers no way to read a note that has no link", async () => {
    /* There is no page to open, and a Read button that always failed would be
       a promise the app cannot keep. */
    vi.spyOn(api, "brief").mockResolvedValue([
      item({ url: null, title: "", why: "the second half of that book" }),
    ]);

    render(<Brief {...props} />);

    await screen.findByText("the second half of that book");
    expect(screen.queryByRole("button", { name: "Read" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("lets you put something there yourself", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([]);
    const add = vi
      .spyOn(api, "addToBrief")
      .mockResolvedValue(item({ id: "mine", origin: "you", title: "" }));

    render(<Brief {...props} />);
    await screen.findByPlaceholderText(/A link you have been meaning to read/);

    await userEvent.type(
      screen.getByLabelText("Link to add"),
      "https://example.com/essay",
    );
    await userEvent.type(screen.getByLabelText("Why this is here"), "been meaning to");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(add).toHaveBeenCalledWith({
      url: "https://example.com/essay",
      why: "been meaning to",
    });
  });

  it("will not add an empty item", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([]);

    render(<Brief {...props} />);
    await screen.findByLabelText("Link to add");

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("reading one takes it off the list and reloads the journal", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);
    const read = vi.spyOn(api, "readBriefItem").mockResolvedValue({
      entry: {} as never,
      replies: [],
      links: [],
      cards: [],
    } as never);

    render(<Brief {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Read" }));

    await waitFor(() => expect(read).toHaveBeenCalledWith("b1"));
    expect(screen.queryByText("Attention is not a spotlight")).not.toBeInTheDocument();
    expect(props.onRead).toHaveBeenCalled();
  });

  it("keeps the item when reading fails", async () => {
    /* A budget stop or a missing key must not quietly consume the thing you
       asked to read. */
    vi.spyOn(api, "brief").mockResolvedValue([item()]);
    vi.spyOn(api, "readBriefItem").mockRejectedValue(
      new Error("Reading a link needs a Gemini key."),
    );

    render(<Brief {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Read" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("needs a Gemini key");
    expect(screen.getByText("Attention is not a spotlight")).toBeInTheDocument();
  });

  it("dismissing removes it from view", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);
    const dismiss = vi.spyOn(api, "dismissBriefItem").mockResolvedValue(item({ dismissed: true }));

    render(<Brief {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(dismiss).toHaveBeenCalledWith("b1"));
    expect(screen.queryByText("Attention is not a spotlight")).not.toBeInTheDocument();
  });

  it("treats an empty brief as the resting state rather than an achievement", async () => {
    /* "All caught up" is inbox language, and it would make this the queue the
       whole design exists not to be. */
    vi.spyOn(api, "brief").mockResolvedValue([]);

    render(<Brief {...props} />);

    const note = await screen.findByText(/Nothing waiting/);
    expect(note.textContent).not.toMatch(/caught up|done|complete|inbox zero/i);
  });

  it("says plainly that none of this is in the journal yet", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);

    render(<Brief {...props} />);

    expect(
      await screen.findByText(/Nothing here is in your journal/),
    ).toBeInTheDocument();
  });

  it("never shows a count of what is outstanding", async () => {
    /* A number beside a list is what turns a shelf into a backlog. */
    vi.spyOn(api, "brief").mockResolvedValue([item(), item({ id: "b2" }), item({ id: "b3" })]);

    render(<Brief {...props} />);
    await screen.findAllByText("Attention is not a spotlight");

    expect(screen.queryByText(/\b3\b/)).not.toBeInTheDocument();
  });
});
