import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useTheme } from "./useTheme";

describe("useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("defaults to dark even when the system prefers light", () => {
    // Dark is a design decision, not an inherited OS setting.
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("restores an explicit light choice", () => {
    localStorage.setItem("tilt.theme", "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("light");
  });

  it("toggles and persists", () => {
    const { result } = renderHook(() => useTheme());

    act(() => result.current[1]());
    expect(result.current[0]).toBe("light");
    expect(localStorage.getItem("tilt.theme")).toBe("light");

    act(() => result.current[1]());
    expect(result.current[0]).toBe("dark");
  });

  it("ignores a corrupted stored value", () => {
    localStorage.setItem("tilt.theme", "chartreuse");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
  });
});
