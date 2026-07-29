import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Scope, Theme } from "../lib/types";
import { Sidebar } from "./Sidebar";

function theme(label: string, count: number, id = label, status: Theme["status"] = "active"): Theme {
  const now = new Date().toISOString();
  return {
    id,
    label,
    description: "",
    created: now,
    updated: now,
    pinned_label: false,
    count,
    status,
    last_active: now,
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
  status: {
    ok: true,
    version: "0.2.0",
    provider: "echo",
    offline: true,
    model: "offline",
    entries: 6,
    spend_this_month_usd: 0,
    cost_ceiling_usd: 20,
    data_dir: "/tmp/journal",
  },
  persona: { name: "Tilt", personality: "Direct and unsentimental." },
  onScope: vi.fn(),
  onOpenGraph: vi.fn(),
  onRenameTheme: vi.fn(),
  onDeleteTheme: vi.fn(),
  onSavePersona: vi.fn(),
};

describe("Sidebar", () => {
  it("lists agent-created folders with their counts", () => {
    render(<Sidebar {...base} />);

    const row = screen.getByText("Attention").closest("button")!;
    expect(row).toHaveTextContent("Attention");
    expect(row.querySelector(".nav-row__count")).toHaveTextContent("4");
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

  it("scopes by tag", async () => {
    const user = userEvent.setup();
    const onScope = vi.fn();
    render(<Sidebar {...base} onScope={onScope} />);

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
    expect(screen.getByText(/appear here as Tilt finds themes/i)).toBeInTheDocument();
  });

  it("offers no way to create a folder by hand", () => {
    // Filing is what the app exists to take off you; a "new folder" control
    // would hand it straight back.
    render(<Sidebar {...base} />);
    const labels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(labels.some((l) => /new|add|\+/i.test(l))).toBe(false);
  });

  it("requires a second click to delete a folder", async () => {
    const user = userEvent.setup();
    const onDeleteTheme = vi.fn();
    render(<Sidebar {...base} onDeleteTheme={onDeleteTheme} />);

    await user.click(screen.getByRole("button", { name: "Delete Attention" }));
    expect(onDeleteTheme).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm deleting Attention" }));
    expect(onDeleteTheme).toHaveBeenCalledWith("Attention");
  });

  it("says that deleting a folder keeps the entries in it", () => {
    // The whole reason this control can exist. If it read as "delete these
    // thoughts" nobody should ever click it, and nobody would.
    render(<Sidebar {...base} />);
    expect(screen.getByRole("button", { name: "Delete Attention" })).toHaveAttribute(
      "title",
      expect.stringContaining("entries in it are kept"),
    );
  });

  it("deletes the folder it was armed on, not the next one clicked", async () => {
    const user = userEvent.setup();
    const onDeleteTheme = vi.fn();
    render(<Sidebar {...base} onDeleteTheme={onDeleteTheme} />);

    await user.click(screen.getByRole("button", { name: "Delete Attention" }));
    await user.click(screen.getByRole("button", { name: "Delete Memory" }));

    expect(onDeleteTheme).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete Attention" })).toBeInTheDocument();
  });

  it("marks the active scope", () => {
    render(<Sidebar {...base} scope={{ type: "theme", id: "Memory", label: "Memory" }} />);
    expect(screen.getByText("Memory").closest("button")).toHaveClass("nav-row--selected");
  });

  it("recedes a folder that has gone quiet without hiding it", () => {
    // Dormant is not deleted. A subject you set down is part of the record of
    // how your thinking moved, and removing it would flatten that.
    render(<Sidebar {...base} themes={[theme("Old Preoccupation", 9, "old", "dormant")]} />);

    const row = screen.getByText("Old Preoccupation");
    expect(row).toBeInTheDocument();
    expect(row.closest(".stagger")).toHaveClass("nav-dormant");
    expect(row.closest("button")).toHaveAttribute("title", expect.stringContaining("quiet"));
  });
});
