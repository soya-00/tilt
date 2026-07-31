import { describe, expect, it } from "vitest";

import { compose, findUrl } from "./compose";

describe("compose", () => {
  it("pulls a link, tags, and a note out of one line", () => {
    expect(
      compose("Kate says it argues the opposite https://example.com/essay #attention"),
    ).toEqual({
      url: "https://example.com/essay",
      tags: ["attention"],
      why: "Kate says it argues the opposite",
    });
  });

  it("takes the link wherever it landed", () => {
    const { url, why } = compose("https://arxiv.org/abs/2401.1 worth a look later");
    expect(url).toBe("https://arxiv.org/abs/2401.1");
    expect(why).toBe("worth a look later");
  });

  it("does not weld words together where a tag was", () => {
    expect(compose("read #memory before the talk").why).toBe("read before the talk");
  });

  it("keeps a note that is only a note", () => {
    expect(compose("the second half of Seeing Like a State")).toEqual({
      url: "",
      tags: [],
      why: "the second half of Seeing Like a State",
    });
  });

  it("lowercases and de-duplicates tags", () => {
    expect(compose("#Attention and #attention and #memory").tags).toEqual([
      "attention",
      "memory",
    ]);
  });

  it("does not mistake a fragment for a tag", () => {
    // The `#` in a URL is part of the address, and `C#` is not a tag either.
    const { url, tags } = compose("https://example.com/a#section on C# and #music");
    expect(url).toBe("https://example.com/a#section");
    expect(tags).toEqual(["music"]);
  });

  it("drops trailing punctuation from a link", () => {
    expect(findUrl("see https://example.com/a, it argues the opposite")).toBe(
      "https://example.com/a",
    );
  });

  it("has nothing to say about an empty box", () => {
    expect(compose("   ")).toEqual({ url: "", tags: [], why: "" });
  });
});
