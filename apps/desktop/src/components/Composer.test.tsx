import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("opens a text file in the sheet rather than sending it straight off", async () => {
    // Readable here, so it can be checked and titled before anything is spent
    // on distilling it.
    const user = userEvent.setup();
    const onAddSource = vi.fn();
    const onUploadSource = vi.fn().mockResolvedValue(undefined);
    render(
      <Composer onSubmit={vi.fn()} onAddSource={onAddSource} onUploadSource={onUploadSource} />,
    );

    const file = new File(["Attention is a filter."], "talk.txt", { type: "text/plain" });
    await user.upload(screen.getByLabelText("Choose a file"), file);

    // Reading the file is async, so the sheet opens a tick after the pick.
    await waitFor(() =>
      expect(onAddSource).toHaveBeenCalledWith({
        title: "talk",
        text: "Attention is a filter.",
      }),
    );
    expect(onUploadSource).not.toHaveBeenCalled();
  });

  it("hands a PDF to the service, which can read it", async () => {
    // Nothing in the browser can open a PDF. Refusing it would be a chore the
    // app exists to remove.
    const user = userEvent.setup();
    const onAddSource = vi.fn();
    const onUploadSource = vi.fn().mockResolvedValue(undefined);
    render(
      <Composer onSubmit={vi.fn()} onAddSource={onAddSource} onUploadSource={onUploadSource} />,
    );

    const file = new File([new Uint8Array([37, 80, 68, 70])], "paper.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText("Choose a file"), file);

    expect(onUploadSource).toHaveBeenCalledWith(file);
    expect(onAddSource).not.toHaveBeenCalled();
  });

  it("says why a dropped file it cannot read was refused", async () => {
    // Dropping is the way an unreadable file actually arrives: the picker's
    // accept list already filters these out, but nothing filters a drag.
    const { container } = render(<Composer onSubmit={vi.fn()} onAddSource={vi.fn()} />);

    const file = new File([new Uint8Array([0, 1])], "lecture.mp3", { type: "audio/mpeg" });
    fireEvent.drop(container.querySelector(".composer")!, { dataTransfer: { files: [file] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot read lecture\.mp3/i);
  });

  it("surfaces an upload failure beside the file that caused it", async () => {
    const user = userEvent.setup();
    const onUploadSource = vi.fn().mockRejectedValue(new Error("That PDF is a scan."));
    render(<Composer onSubmit={vi.fn()} onUploadSource={onUploadSource} />);

    const file = new File([new Uint8Array([37])], "scan.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Choose a file"), file);

    expect(await screen.findByRole("alert")).toHaveTextContent("That PDF is a scan.");
  });
});
