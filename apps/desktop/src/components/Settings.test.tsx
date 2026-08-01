import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PublicSettings, Status } from "../lib/types";
import { Settings } from "./Settings";

vi.mock("../lib/api", () => ({
  api: {
    runs: vi.fn().mockResolvedValue([]),
    runJob: vi.fn(),
    rebuildIndex: vi.fn(),
    erase: vi.fn(),
  },
}));

const settings = {
  has_key: true,
  key_hint: "…9f2a",
  gemini_model: "gemini-3.6-flash",
  monthly_cost_ceiling_usd: 20,
  feeds: ["https://example.com/feed.xml"],
} as PublicSettings;

const status = {
  version: "0.3.0",
  data_dir: "/Users/me/Tilt",
  key_storage: "keychain",
  dormant: [],
  conflicts: [],
} as unknown as Status;

function open(overrides = {}) {
  return render(
    <Settings
      open
      settings={settings}
      status={status}
      theme="light"
      onClose={vi.fn()}
      onSave={vi.fn().mockResolvedValue(undefined)}
      onToggleTheme={vi.fn()}
      {...overrides}
    />,
  );
}

describe("Settings", () => {
  it("opens on Agent, not on whatever was last looked at", () => {
    // A settings sheet that reopens on Danger is a settings sheet that reopens
    // on a delete button.
    open();

    expect(screen.getByLabelText("Gemini API key")).toBeInTheDocument();
    expect(screen.queryByText(/delete everything/i)).not.toBeInTheDocument();
  });

  it("shows one panel at a time", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("button", { name: /^Reading/ }));

    expect(screen.getByLabelText(/feed urls/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Gemini API key")).not.toBeInTheDocument();
  });

  it("keeps danger reachable but never on the way to anything", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("button", { name: /^Danger/ }));

    expect(screen.getByRole("button", { name: /delete everything/i })).toBeDisabled();
  });

  it("saves the key and model without touching the feeds", async () => {
    // The old single Save wrote all three in one request, which is why they had
    // to be adjacent. They are not any more, so a panel must send only its own.
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    open({ onSave });

    await user.type(screen.getByLabelText("Gemini API key"), "AIzaNew");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledWith({
      gemini_api_key: "AIzaNew",
      gemini_model: "gemini-3.6-flash",
    });
  });

  it("saves the feeds without touching the key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    open({ onSave });

    await user.click(screen.getByRole("button", { name: /^Reading/ }));
    await user.clear(screen.getByLabelText(/feed urls/i));
    await user.type(screen.getByLabelText(/feed urls/i), "https://a.example/rss");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledWith({ feeds: ["https://a.example/rss"] });
  });

  it("never sends an empty key by accident", async () => {
    // An empty field means "leave it alone". Clearing is a deliberate act and
    // lives one panel away, behind a typed word.
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    open({ onSave });

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledWith({ gemini_model: "gemini-3.6-flash" });
  });

  it("says where the journal is", async () => {
    // The app's strongest claim is that your writing is a folder you own, and
    // until now nothing in the interface said which folder.
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("button", { name: /^Journal/ }));

    expect(screen.getByText("/Users/me/Tilt")).toBeInTheDocument();
  });
});
