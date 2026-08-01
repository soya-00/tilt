import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Conflicts } from "./Conflicts";

const conflict = {
  entry_id: "01KYVPF3VB2WV8J0PDGTQBKD5M",
  kept: "/journal/entries/2026/07/a.md",
  ignored: "/journal/entries/2026/07/a (conflicted copy).md",
};

describe("Conflicts", () => {
  it("says when two files claim one entry", () => {
    // The index has reported this for a while and nothing rendered it, which
    // is the same as not noticing: both files sit there looking fine.
    render(<Conflicts conflicts={[conflict]} onDismiss={vi.fn()} />);

    expect(screen.getByText(/2 files claim the same entry/i)).toBeInTheDocument();
  });

  it("names both paths, because a file manager is where this gets settled", () => {
    render(<Conflicts conflicts={[conflict]} onDismiss={vi.fn()} />);

    const item = screen.getByRole("button");
    expect(item.title).toContain("a (conflicted copy).md");
    expect(item.title).toContain("reading /journal/entries/2026/07/a.md");
  });

  it("counts entries rather than files when there are several", () => {
    render(
      <Conflicts
        conflicts={[conflict, { ...conflict, entry_id: "other" }]}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText(/2 entries are claimed by two files each/i)).toBeInTheDocument();
  });

  it("renders nothing at all on a healthy journal", () => {
    const { container } = render(<Conflicts conflicts={[]} onDismiss={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("can be waved away once you have seen it", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<Conflicts conflicts={[conflict]} onDismiss={onDismiss} />);

    await user.click(screen.getByRole("button"));
    expect(onDismiss).toHaveBeenCalled();
  });
});
