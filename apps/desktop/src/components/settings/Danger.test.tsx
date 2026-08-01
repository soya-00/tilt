import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../lib/api";
import type { Status } from "../../lib/types";
import { Danger } from "./Danger";

vi.mock("../../lib/api", () => ({
  api: { rebuildIndex: vi.fn(), erase: vi.fn() },
}));

// `restoreMocks` clears implementations between tests, so they are set per test
// rather than once at the mock — a resolved value declared above would silently
// become `undefined` by the third case.
beforeEach(() => {
  vi.mocked(api.rebuildIndex).mockResolvedValue({ indexed: 42 });
  vi.mocked(api.erase).mockResolvedValue({ removed: ["/journal", "/support"] });
});

const status = {
  data_dir: "/Users/me/Tilt",
  key_storage: "keychain",
} as Status;

describe("Danger", () => {
  it("will not delete anything until the word is typed", async () => {
    // A second click is reachable by a double-fire, a replayed request, or a
    // handler wired to the wrong element. Typing DELETE is reachable only on
    // purpose, which is the whole reason it is a word and not a confirm dialog.
    const user = userEvent.setup();
    render(<Danger status={status} onForgetKey={vi.fn()} />);

    const button = screen.getByRole("button", { name: /delete everything/i });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText(/type delete to confirm/i), "delete");
    expect(button).toBeDisabled();

    await user.clear(screen.getByLabelText(/type delete to confirm/i));
    await user.type(screen.getByLabelText(/type delete to confirm/i), "DELETE");
    expect(button).toBeEnabled();
  });

  it("names the folder it is about to remove", () => {
    // The journal may be in Dropbox, iCloud or a git repository, in which case
    // this deletes it there too — and the only way to know is to be shown which
    // folder it is.
    render(<Danger status={status} onForgetKey={vi.fn()} />);

    expect(screen.getByText("/Users/me/Tilt")).toBeInTheDocument();
  });

  it("says it is over once it is", async () => {
    const user = userEvent.setup();
    render(<Danger status={status} onForgetKey={vi.fn()} />);

    await user.type(screen.getByLabelText(/type delete to confirm/i), "DELETE");
    await user.click(screen.getByRole("button", { name: /delete everything/i }));

    expect(api.erase).toHaveBeenCalledWith("DELETE");
    expect(await screen.findByText(/quit and reopen/i)).toBeInTheDocument();
  });

  it("offers the harmless rebuild above the line, and reports it", async () => {
    const user = userEvent.setup();
    render(<Danger status={status} onForgetKey={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^rebuild$/i }));

    expect(await screen.findByText(/42 entries read back/i)).toBeInTheDocument();
  });

  it("names where the key is kept when offering to forget it", () => {
    // Saying "the settings file" to someone whose key is in the keychain would
    // be a straight untruth, and this is the panel where being wrong matters.
    const { rerender } = render(<Danger status={status} onForgetKey={vi.fn()} />);
    expect(screen.getByText(/login keychain/i)).toBeInTheDocument();

    rerender(
      <Danger status={{ ...status, key_storage: "file" } as Status} onForgetKey={vi.fn()} />,
    );
    expect(screen.getByText(/settings file/i)).toBeInTheDocument();
  });

  it("forgets the key without any typing", async () => {
    // Reversible by pasting it back, so it does not deserve the same gate.
    const user = userEvent.setup();
    const onForgetKey = vi.fn().mockResolvedValue(undefined);
    render(<Danger status={status} onForgetKey={onForgetKey} />);

    await user.click(screen.getByRole("button", { name: /forget it/i }));

    expect(onForgetKey).toHaveBeenCalled();
  });
});
