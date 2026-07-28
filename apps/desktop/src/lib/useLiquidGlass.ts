import { useCallback, useRef } from "react";

/**
 * Dynamic liquid glass.
 *
 * Tracks the pointer inside an element and writes its position to CSS custom
 * properties, so a specular highlight can follow the cursor across the surface
 * — the thing that makes glass read as a lit material rather than a flat
 * translucent fill.
 *
 * Position goes straight to the node with rAF coalescing rather than through
 * React state: a mousemove handler that re-renders on every event would drop
 * frames on any non-trivial tree.
 */
export function useLiquidGlass<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const frame = useRef(0);

  const onPointerMove = useCallback((event: React.PointerEvent<T>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;

    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      el.style.setProperty("--mx", `${x.toFixed(2)}%`);
      el.style.setProperty("--my", `${y.toFixed(2)}%`);
      el.style.setProperty("--lit", "1");
    });
  }, []);

  const onPointerLeave = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    cancelAnimationFrame(frame.current);
    // Settle back to centre so the highlight glides off rather than snapping.
    el.style.setProperty("--mx", "50%");
    el.style.setProperty("--my", "50%");
    el.style.setProperty("--lit", "0");
  }, []);

  return { ref, onPointerMove, onPointerLeave };
}
