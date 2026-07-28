import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import { CaptureWindow } from "./CaptureWindow";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the quick capture panel", () => {
  it("saves a thought and clears itself", async () => {
    const create = vi.spyOn(api, "create").mockResolvedValue({} as never);
    render(<CaptureWindow />);

    const box = screen.getByRole("textbox");
    await userEvent.type(box, "attention is a filter{Enter}");

    await waitFor(() => expect(create).toHaveBeenCalledWith("attention is a filter"));
    await waitFor(() => expect(box).toHaveValue(""));
  });

  it("keeps the thought in the box when saving fails", async () => {
    // The one failure this window must not have: a thought typed, the panel
    // vanishing, and nothing written anywhere.
    vi.spyOn(api, "create").mockRejectedValue(new Error("no service"));
    render(<CaptureWindow />);

    const box = screen.getByRole("textbox");
    await userEvent.type(box, "a fragile thought{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Tilt is not answering");
    expect(box).toHaveValue("a fragile thought");
  });

  it("offers nothing to organise with", () => {
    // Deliberate: the panel takes one thought and goes away. Filing is the
    // agent's job, and anything to click here would invite staying.
    render(<CaptureWindow />);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });
});
