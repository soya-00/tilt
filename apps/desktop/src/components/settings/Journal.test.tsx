import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../lib/api";
import type { Status } from "../../lib/types";
import { Journal } from "./Journal";

vi.mock("../../lib/api", () => ({
  api: {
    folderDecisions: vi.fn(),
    unpinFolder: vi.fn(),
    askAgainAbout: vi.fn(),
    exportArchive: vi.fn(),
    importArchive: vi.fn(),
  },
}));

const status = { data_dir: "/Users/me/Tilt", key_storage: "keychain" } as Status;

beforeEach(() => {
  vi.mocked(api.folderDecisions).mockResolvedValue({ pinned: [], declined: [] });
  vi.mocked(api.unpinFolder).mockResolvedValue(undefined);
  vi.mocked(api.askAgainAbout).mockResolvedValue(undefined);
  vi.mocked(api.exportArchive).mockResolvedValue({
    path: "/support/tilt-2026-08-01-1130.zip",
    entries: 12,
  });
  vi.mocked(api.importArchive).mockResolvedValue({
    path: "/x.zip",
    entries: 12,
    written_by: "0.3.0",
  });
});

describe("Journal", () => {
  it("says where the journal is", () => {
    render(<Journal status={status} />);

    expect(screen.getByText("/Users/me/Tilt")).toBeInTheDocument();
  });

  it("shows where the archive went, since nothing else will", async () => {
    // No file picker, so the path on screen is the only way to find it.
    const user = userEvent.setup();
    render(<Journal status={status} />);

    await user.click(screen.getByRole("button", { name: /^export$/i }));

    expect(await screen.findByText("/support/tilt-2026-08-01-1130.zip")).toBeInTheDocument();
  });

  it("will not replace a journal without a path and the word", async () => {
    const user = userEvent.setup();
    render(<Journal status={status} />);

    const button = screen.getByRole("button", { name: /replace this journal/i });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/path to an archive/i), "/x.zip");
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/type replace to confirm/i), "REPLACE");
    expect(button).toBeEnabled();
  });

  it("says it is over once it is, because the service has stopped", async () => {
    const user = userEvent.setup();
    render(<Journal status={status} />);

    await user.type(screen.getByLabelText(/path to an archive/i), "/x.zip");
    await user.type(screen.getByLabelText(/type replace to confirm/i), "REPLACE");
    await user.click(screen.getByRole("button", { name: /replace this journal/i }));

    expect(await screen.findByText(/quit and reopen/i)).toBeInTheDocument();
  });

  it("lists what you have told the keeper, and lets you take it back", async () => {
    // These accumulate silently. Without this panel you could pin a dozen
    // folder names over months with no way to see or undo any of them.
    vi.mocked(api.folderDecisions).mockResolvedValue({
      pinned: ["Attention"],
      declined: [{ folder: "Reading", at: 24 }],
    });
    const user = userEvent.setup();
    render(<Journal status={status} />);

    expect(await screen.findByText("Attention")).toBeInTheDocument();
    expect(screen.getByText(/at 24 entries/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /let the agent rename it/i }));
    await waitFor(() => expect(api.unpinFolder).toHaveBeenCalledWith("Attention"));

    await user.click(screen.getByRole("button", { name: /ask me again/i }));
    await waitFor(() => expect(api.askAgainAbout).toHaveBeenCalledWith("Reading"));
  });

  it("says an empty list is normal rather than showing nothing", async () => {
    render(<Journal status={status} />);

    expect(await screen.findByText(/which is the normal state/i)).toBeInTheDocument();
  });
});
