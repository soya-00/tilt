import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends on Enter", async () => {
    // The layout is chat-shaped and bottom-anchored, so Enter carries the
    // frequent action and Shift+Enter carries the rare one.
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Write an entry"), "Attention is a filter.");
    await user.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("Attention is a filter.");
  });

  it("inserts a newline on Shift+Enter", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSubmit={onSubmit} />);

    const input = screen.getByLabelText("Write an entry");
    await user.type(input, "First line{Shift>}{Enter}{/Shift}second line");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(input).toHaveValue("First line\nsecond line");
  });

  it("clears after a successful submit", async () => {
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    const input = screen.getByLabelText("Write an entry");
    await user.type(input, "A thought.{Enter}");

    expect(input).toHaveValue("");
  });

  it("keeps the text when submission fails", async () => {
    // Losing what someone just wrote because a request failed is the single
    // worst thing this component could do.
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn().mockRejectedValue(new Error("offline"))} />);

    const input = screen.getByLabelText("Write an entry");
    await user.type(input, "Hard-won thought.{Enter}");

    expect(input).toHaveValue("Hard-won thought.");
  });

  it("ignores whitespace-only input", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Write an entry"), "   {Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("strengthens the send control only when there is something to keep", async () => {
    // The whole affordance: border and glyph gain weight. Never a colour fill.
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    const send = screen.getByRole("button", { name: /keep this entry/i });
    expect(send).toBeDisabled();
    expect(send).not.toHaveClass("icon-btn--ready");

    await user.type(screen.getByLabelText("Write an entry"), "x");
    expect(send).toBeEnabled();
    expect(send).toHaveClass("icon-btn--ready");
  });

  it("blurs on Escape", async () => {
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn()} autoFocus />);

    const input = screen.getByLabelText("Write an entry");
    expect(input).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(input).not.toHaveFocus();
  });
});
