import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Scope, Theme } from "../lib/types";
import { Sidebar } from "./Sidebar";

function theme(label: string, count: number, id = label): Theme {
  const now = new Date().toISOString();
  return {
    id,
    label,
    description: "",
    created: now,
    updated: now,
    pinned_label: false,
    count,
  };
}

const base = {
  themes: [theme("Attention", 4), theme("Memory", 2)],
  tags: [
    { tag: "attention", count: 4 },
    { tag: "memory", count: 2 },
  ],
  scope: { type: "all" } as Scope,
  entryCount: 6,
  onScope: vi.fn(),
  onRenameTheme: vi.fn(),
};

describe("Sidebar", () => {
  it("lists agent-created folders with their counts", () => {
    render(<Sidebar {...base} />);

    expect(screen.getByText("Attention")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("scopes the stream to a folder", async () => {
    const user = userEvent.setup();
    const onScope = vi.fn();
    render(<Sidebar {...base} onScope={onScope} />);

    await user.click(screen.getByText("Attention"));
    expect(onScope).toHaveBeenCalledWith({
      type: "theme",
      id: "Attention",
      label: "Attention",
    });
  });

  it("switches to tags and scopes by tag", async () => {
    const user = userEvent.setup();
    const onScope = vi.fn();
    render(<Sidebar {...base} onScope={onScope} />);

    await user.click(screen.getByRole("tab", { name: "Tags" }));
    await user.click(screen.getByText("memory"));

    expect(onScope).toHaveBeenCalledWith({ type: "tag", tag: "memory" });
  });

  it("renames a folder on double click", async () => {
    const user = userEvent.setup();
    const onRenameTheme = vi.fn();
    render(<Sidebar {...base} onRenameTheme={onRenameTheme} />);

    await user.dblClick(screen.getByText("Attention"));
    const input = screen.getByLabelText("Rename Attention");
    await user.clear(input);
    await user.type(input, "How I Pay Attention{Enter}");

    expect(onRenameTheme).toHaveBeenCalledWith("Attention", "How I Pay Attention");
  });

  it("abandons a rename on Escape", async () => {
    const user = userEvent.setup();
    const onRenameTheme = vi.fn();
    render(<Sidebar {...base} onRenameTheme={onRenameTheme} />);

    await user.dblClick(screen.getByText("Memory"));
    await user.type(screen.getByLabelText("Rename Memory"), " changed{Escape}");

    expect(onRenameTheme).not.toHaveBeenCalled();
  });

  it("explains that folders are discovered, not created", () => {
    render(<Sidebar {...base} themes={[]} />);
    expect(screen.getByText(/appear as Tilt finds themes/i)).toBeInTheDocument();
  });

  it("offers no way to create a folder by hand", () => {
    // Filing is what the app exists to take off you; a "new folder" control
    // would hand it straight back.
    render(<Sidebar {...base} />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(labels.some((l) => /new|add|\+/i.test(l))).toBe(false);
  });

  it("marks the active scope", () => {
    render(<Sidebar {...base} scope={{ type: "theme", id: "Memory", label: "Memory" }} />);
    expect(screen.getByText("Memory").closest("button")).toHaveClass("sidebar__row--active");
  });
});
