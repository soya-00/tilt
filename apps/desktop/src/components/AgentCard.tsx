import { useEffect, useRef, useState } from "react";

import type { Persona, Status } from "../lib/types";
import { useLiquidGlass } from "../lib/useLiquidGlass";
import { Icon } from "./Icon";
import { Avatar } from "./primitives";

interface Props {
  persona: Persona | null;
  status: Status | null;
  onSave: (payload: Partial<Persona>) => void;
}

/**
 * The agent.
 *
 * Singular by design — Tilt has one voice, not a roster you assemble. What is
 * configurable is who that voice *is*: its name, and the manner it reflects in.
 * Both feed straight into the reflection prompt.
 */
export function AgentCard({ persona, status, onSave }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(persona?.name ?? "Tilt");
  const [personality, setPersonality] = useState(persona?.personality ?? "");
  const area = useRef<HTMLTextAreaElement>(null);
  const glass = useLiquidGlass<HTMLDivElement>();

  useEffect(() => {
    if (open) return;
    setName(persona?.name ?? "Tilt");
    setPersonality(persona?.personality ?? "");
  }, [persona, open]);

  const commit = () => {
    const trimmed = name.trim();
    onSave({ name: trimmed || "Tilt", personality: personality.trim() });
    setOpen(false);
  };

  const subtitle = status?.offline ? "Offline — no model" : (status?.model ?? "Ready");

  return (
    <div
      ref={glass.ref}
      className={"agent glass-live" + (open ? " agent--open" : "")}
      onPointerMove={glass.onPointerMove}
      onPointerLeave={glass.onPointerLeave}
    >
      <button
        className="agent__head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Avatar icon="spark" size={32} />
        <span className="agent__text">
          <span className="agent__name">{persona?.name ?? "Tilt"}</span>
          <span className="agent__status">{subtitle}</span>
        </span>
        <Icon name="pencil" size={16} className="agent__edit" />
      </button>

      {open && (
        <div className="agent__editor">
          <label className="field">
            <span className="field__label">Name</span>
            <input
              className="field__input"
              value={name}
              maxLength={32}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") area.current?.focus();
                if (e.key === "Escape") setOpen(false);
              }}
            />
          </label>

          <label className="field">
            <span className="field__label">Personality</span>
            <textarea
              ref={area}
              className="field__input field__input--area"
              value={personality}
              rows={4}
              maxLength={600}
              placeholder="How should it speak to you?"
              onChange={(e) => setPersonality(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) commit();
                if (e.key === "Escape") setOpen(false);
              }}
            />
          </label>

          <div className="agent__actions">
            <button className="ghost-btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button className="ghost-btn ghost-btn--primary" onClick={commit}>
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
