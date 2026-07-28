import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "./useTheme";

/** jsdom always reports "no match"; this lets a test assert the dark branch. */
function systemPrefersDark(dark: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: dark && query.includes("dark"),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as MediaQueryList,
  );
}

describe("useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("follows a light system appearance", () => {
    systemPrefersDark(false);
    const { result } = renderHook(() => useTheme());

    expect(result.current[0]).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("follows a dark system appearance", () => {
    systemPrefersDark(true);
    expect(renderHook(() => useTheme()).result.current[0]).toBe("dark");
  });

  it("lets an explicit choice override the system", () => {
    systemPrefersDark(true);
    localStorage.setItem("tilt.theme", "light");

    expect(renderHook(() => useTheme()).result.current[0]).toBe("light");
  });

  it("toggles and persists", () => {
    systemPrefersDark(false);
    const { result } = renderHook(() => useTheme());

    act(() => result.current[1]());
    expect(result.current[0]).toBe("dark");
    expect(localStorage.getItem("tilt.theme")).toBe("dark");

    act(() => result.current[1]());
    expect(result.current[0]).toBe("light");
  });

  it("ignores a corrupted stored value and falls back to the system", () => {
    systemPrefersDark(true);
    localStorage.setItem("tilt.theme", "chartreuse");

    expect(renderHook(() => useTheme()).result.current[0]).toBe("dark");
  });
});
