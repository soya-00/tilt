import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ICON_NAMES, Icon } from "./Icon";

describe("Icon", () => {
  it("uses a 24 viewBox for every glyph, without exception", () => {
    // Scaling happens via the size prop; the viewBox is never edited, which is
    // what keeps optical weight consistent across the set.
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />);
      expect(container.querySelector("svg")).toHaveAttribute("viewBox", "0 0 24 24");
    }
  });

  it("never names a colour — it always inherits", () => {
    for (const name of ICON_NAMES) {
      const { container } = render(<Icon name={name} />);
      const svg = container.querySelector("svg")!;
      expect(svg).toHaveAttribute("stroke", "currentColor");
      expect(svg).toHaveAttribute("fill", "none");
      expect(svg.outerHTML).not.toMatch(/#[0-9a-f]{3,6}/i);
    }
  });

  it("keeps one stroke weight across the set", () => {
    // Optical weight is corrected by simplifying paths, never by adjusting
    // stroke-width on an individual icon.
    const widths = ICON_NAMES.map((name) => {
      const { container } = render(<Icon name={name} />);
      return container.querySelector("svg")!.getAttribute("stroke-width");
    });
    expect(new Set(widths)).toEqual(new Set(["1.75"]));
  });

  it("is hidden from assistive tech by default", () => {
    const { container } = render(<Icon name="home" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
  });

  it("scales through the size prop", () => {
    const { container } = render(<Icon name="home" size={32} />);
    expect(container.querySelector("svg")).toHaveAttribute("width", "32");
  });
});
