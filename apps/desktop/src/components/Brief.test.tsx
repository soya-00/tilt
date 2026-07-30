/**
 * The brief, from the reader's side.
 *
 * The property under most of these is the same one the backend tests protect
 * from the other direction: this is a shelf and not a queue. It has no counts,
 * no completion, and it does not congratulate anyone for emptying it.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import * as shell from "../lib/shell";
import type { BriefItem } from "../lib/types";
import { Brief } from "./Brief";

function item(over: Partial<BriefItem> = {}): BriefItem {
  return {
    id: "b1",
    title: "Attention as a filter",
    url: "https://arxiv.org/abs/2401.00001",
    why: "argues against the filter model you settled on in June",
    origin: "scout",
    tags: ["attention", "memory"],
    created: new Date().toISOString(),
    dismissed: false,
    path: "/tmp/b1.md",
    ...over,
  };
}

const props = { open: true, onClose: vi.fn(), onRead: vi.fn(), onScope: vi.fn() };

beforeEach(() => {
  vi.restoreAllMocks();
  props.onClose = vi.fn();
  props.onRead = vi.fn();
  props.onScope = vi.fn();
});

describe("Brief", () => {
  it("shows why something is there, not just what it is", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);

    render(<Brief {...props} />);

    expect(await screen.findByText("Attention as a filter")).toBeInTheDocument();
    expect(
      screen.getByText(/argues against the filter model you settled on in June/),
    ).toBeInTheDocument();
  });

  it("gives each item the Stream's dot", async () => {
    /* A candidate is a thought you have not had yet, and it should look like
       one. Reusing the class rather than copying it is what keeps that true. */
    vi.spyOn(api, "brief").mockResolvedValue([item()]);

    const { container } = render(<Brief {...props} />);
    await screen.findByText("Attention as a filter");

    expect(container.querySelectorAll(".brief__item .row__dot")).toHaveLength(1);
    // No connector: that line claims two rows belong to one thread.
    expect(container.querySelector(".row__connector")).toBeNull();
  });

  it("tags go to what you have already written under them", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);

    render(<Brief {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "attention" }));

    expect(props.onScope).toHaveBeenCalledWith({ type: "tag", tag: "attention" });
    expect(props.onClose).toHaveBeenCalled();
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
      item({ url: null, title: "", why: "the second half of that book", tags: [] }),
    ]);

    render(<Brief {...props} />);

    await screen.findByText("the second half of that book");
    expect(screen.queryByRole("button", { name: "Read" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("takes one box and files a link, tags and a note", async () => {
    /* The whole point of the composer: you type the way you would tell someone
       about it, and the parts get sorted out here rather than by you. */
    vi.spyOn(api, "brief").mockResolvedValue([]);
    const add = vi.spyOn(api, "addToBrief").mockResolvedValue(item({ id: "mine", origin: "you" }));

    render(<Brief {...props} />);
    await screen.findByLabelText("Title");

    await userEvent.type(screen.getByLabelText("Title"), "Seeing Like a State");
    await userEvent.type(
      screen.getByLabelText("Why this is here"),
      "Kate says it argues the opposite https://example.com/essay #attention",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(add).toHaveBeenCalledWith({
      title: "Seeing Like a State",
      url: "https://example.com/essay",
      tags: ["attention"],
      why: "Kate says it argues the opposite",
    });
  });

  it("will not add an empty item", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([]);

    render(<Brief {...props} />);
    await screen.findByLabelText("Title");

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("opens a pasted link in the browser without shelving it", async () => {
    /* Checking it is the right thing before saving it is a different act from
       deciding to read it, and it costs nothing. */
    vi.spyOn(api, "brief").mockResolvedValue([]);
    const opened = vi.spyOn(shell, "openExternal").mockResolvedValue();
    const add = vi.spyOn(api, "addToBrief");

    render(<Brief {...props} />);
    await screen.findByLabelText("Title");

    expect(screen.getByRole("button", { name: "Open" })).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText("Why this is here"),
      "https://example.com/essay",
    );

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(opened).toHaveBeenCalledWith("https://example.com/essay");
    expect(add).not.toHaveBeenCalled();
  });

  it("a title opens in the browser rather than inside the app", async () => {
    /* A page that opened in the webview would be a browser nobody asked for,
       sitting on top of the journal with no way back. */
    vi.spyOn(api, "brief").mockResolvedValue([item()]);
    const opened = vi.spyOn(shell, "openExternal").mockResolvedValue();

    render(<Brief {...props} />);
    await userEvent.click(await screen.findByText("Attention as a filter"));

    expect(opened).toHaveBeenCalledWith("https://arxiv.org/abs/2401.00001");
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
    expect(screen.queryByText("Attention as a filter")).not.toBeInTheDocument();
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
    expect(screen.getByText("Attention as a filter")).toBeInTheDocument();
  });

  it("dismissing removes it from view", async () => {
    vi.spyOn(api, "brief").mockResolvedValue([item()]);
    const dismiss = vi
      .spyOn(api, "dismissBriefItem")
      .mockResolvedValue(item({ dismissed: true }));

    render(<Brief {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(dismiss).toHaveBeenCalledWith("b1"));
    expect(screen.queryByText("Attention as a filter")).not.toBeInTheDocument();
  });

  it("treats an empty brief as the resting state rather than an achievement", async () => {
    /* "All caught up" is inbox language, and it would make this the queue the
       whole design exists not to be. */
    vi.spyOn(api, "brief").mockResolvedValue([]);

    render(<Brief {...props} />);

    const note = await screen.findByText(/Nothing waiting/);
    expect(note.textContent).not.toMatch(/caught up|done|complete|inbox zero/i);
    // The assurance the removed footer used to carry, kept where someone
    // seeing the brief for the first time actually reads it.
    expect(note.textContent).toMatch(/nothing here is in your journal until you read it/i);
  });

  it("never shows a count of what is outstanding", async () => {
    /* A number beside a list is what turns a shelf into a backlog. */
    vi.spyOn(api, "brief").mockResolvedValue([
      item(),
      item({ id: "b2" }),
      item({ id: "b3" }),
    ]);

    const { container } = render(<Brief {...props} />);
    await screen.findAllByText("Attention as a filter");

    const head = within(container.querySelector(".sheet__head") as HTMLElement);
    expect(head.queryByText(/\d/)).not.toBeInTheDocument();
  });
});
