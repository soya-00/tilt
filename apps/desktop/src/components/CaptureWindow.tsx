import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { announceCapture, dismiss } from "../lib/shell";
import { Composer } from "./Composer";

/**
 * The whole content of the always-on-top panel.
 *
 * Not the journal in a smaller window — deliberately. It holds one composer and
 * no state to speak of, because the point of ⌥Space is to take a thought and
 * disappear before you have time to start organising. Everything the entry
 * needs afterwards, the agent does on its own.
 *
 * The window itself is transparent and sits on real system vibrancy, so this
 * draws only the panel's edge and lets macOS supply the material.
 */
export function CaptureWindow() {
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void dismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="capture-window glass">
      <Composer
        autoFocus
        compact
        placeholder="Capture a thought"
        onSubmit={async (body) => {
          try {
            await api.create(body);
          } catch {
            // Keep the window open with the text intact. Losing a thought to a
            // dead sidecar is the one failure this window must not have.
            setFailed("Could not save that. Tilt is not answering.");
            throw new Error("save failed");
          }
          setFailed(null);
          await announceCapture();
          await dismiss();
        }}
      />
      {failed && (
        <p className="capture-window__error" role="alert">
          {failed}
        </p>
      )}
    </div>
  );
}
