import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

const KEY = "tilt.theme";

/**
 * Follows the system appearance until the user chooses otherwise, which is how
 * a Mac app is expected to behave. Both themes are first-class: light is a
 * bright neutral white, dark is true black with lifted surfaces.
 *
 * An explicit choice is sticky and always wins over the system setting.
 */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(KEY);
    if (stored === "dark" || stored === "light") return stored;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  return [theme, toggle];
}

/** Read-only view of the active theme, for code that must pick a palette. */
export function useIsDark(): boolean {
  const [dark, setDark] = useState(
    () => document.documentElement.dataset.theme !== "light",
  );

  useEffect(() => {
    const observer = new MutationObserver(() =>
      setDark(document.documentElement.dataset.theme !== "light"),
    );
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  return dark;
}
