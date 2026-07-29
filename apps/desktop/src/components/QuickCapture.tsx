import { useEffect } from "react";

import { Composer } from "./Composer";

interface Props {
  open: boolean;
  onSubmit: (body: string) => Promise<void>;
  onClose: () => void;
}

/**
 * The two-second path.
 *
 * In the desktop shell this is a separate always-on-top window bound to a
 * global hotkey; in the browser it is a modal. Either way the contract is the
 * same: appear instantly, take one thought, disappear. It closes on submit
 * because anything else invites you to stay and start organising.
 */
export function QuickCapture({ open, onSubmit, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="capture-scrim fade" onMouseDown={onClose} role="presentation">
      <div
        className="capture rise glass glass--heavy"
        role="dialog"
        aria-modal="true"
        aria-label="Quick capture"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <Composer
          autoFocus
          compact
          placeholder="Capture a thought"
          onSubmit={async (body) => {
            await onSubmit(body);
            onClose();
          }}
        />
      </div>
    </div>
  );
}
