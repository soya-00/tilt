import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DiagramButton } from "./DiagramButton";

describe("DiagramButton", () => {
  it("is absent when nothing is scoped", () => {
    // Not disabled — absent. A diagram of everything is not a diagram of
    // anything, and there is nothing to explain.
    const { container } = render(
      <DiagramButton scope={{ type: "all" }} onOpen={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("names the folder it would draw", () => {
    render(
      <DiagramButton
        scope={{ type: "theme", id: "t", label: "Attention" }}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /diagram attention/i })).toBeInTheDocument();
  });

  it("appears for a search too, not only a folder", () => {
    // The palette entry enables on any scope but "all", and the button has to
    // agree with it or one of them is lying about what can be drawn.
    render(<DiagramButton scope={{ type: "search", q: "attention" }} onOpen={vi.fn()} />);

    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("opens the sheet", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<DiagramButton scope={{ type: "tag", tag: "focus" }} onOpen={onOpen} />);

    await user.click(screen.getByRole("button"));

    expect(onOpen).toHaveBeenCalled();
  });
});
