import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

const KEY = "tilt.theme";

/**
 * Dark is the default, not the system preference.
 *
 * Tilt is a night-desk instrument and the palette is tuned for it; a light
 * system setting should not decide how the app looks the first time it opens.
 * Light is available and fully supported — it is just a choice you make rather
 * than one inherited from the OS.
 */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(KEY);
    return stored === "light" ? "light" : "dark";
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
