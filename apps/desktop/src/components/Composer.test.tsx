import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("submits on Cmd+Enter", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Write an entry"), "Attention is a filter.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    expect(onSubmit).toHaveBeenCalledWith("Attention is a filter.");
  });

  it("inserts a newline on plain Enter rather than submitting", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSubmit={onSubmit} />);

    const input = screen.getByLabelText("Write an entry");
    await user.type(input, "First line{Enter}second line");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(input).toHaveValue("First line\nsecond line");
  });

  it("clears after a successful submit", async () => {
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    const input = screen.getByLabelText("Write an entry");
    await user.type(input, "A thought.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    expect(input).toHaveValue("");
  });

  it("keeps the text when submission fails", async () => {
    // Losing what someone just wrote because a request failed is the single
    // worst thing this component could do.
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn().mockRejectedValue(new Error("offline"))} />);

    const input = screen.getByLabelText("Write an entry");
    await user.type(input, "Hard-won thought.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    expect(input).toHaveValue("Hard-won thought.");
  });

  it("ignores whitespace-only input", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Write an entry"), "   ");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables the send control until there is something to keep", async () => {
    const user = userEvent.setup();
    render(<Composer onSubmit={vi.fn().mockResolvedValue(undefined)} />);

    const send = screen.getByRole("button", { name: /keep/i });
    expect(send).toBeDisabled();

    await user.type(screen.getByLabelText("Write an entry"), "x");
    expect(send).toBeEnabled();
  });
});
