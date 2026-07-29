/**
 * Shared presentational primitives.
 *
 * Every interactive row implements the same five states — rest, hover, active,
 * selected, focus-visible — defined once in CSS. A component missing one of
 * them is incomplete.
 */

import type { ReactNode } from "react";

import { Icon, type IconName } from "./Icon";

/* ---------------------------------------------------------------- IconButton */

interface IconButtonProps {
  name: IconName;
  label: string;
  onClick?: () => void;
  /** Outlined pill instead of a bare glyph. */
  outlined?: boolean;
  /** The send affordance: border and glyph strengthen when there is input. */
  ready?: boolean;
  disabled?: boolean;
  size?: number;
}

export function IconButton({
  name,
  label,
  onClick,
  outlined,
  ready,
  disabled,
  size = 20,
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={
        "icon-btn" + (outlined ? " icon-btn--outlined" : "") + (ready ? " icon-btn--ready" : "")
      }
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon name={name} size={size} />
    </button>
  );
}

/* -------------------------------------------------------------- GlassButton */

interface GlassButtonProps {
  name: IconName;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  size?: number;
}

/**
 * A control cut from the same glass as the panels.
 *
 * Reserved for the composer's row, where the three controls you act with live.
 * Everything else in the app is a bare glyph: applied everywhere this stops
 * being a material and becomes a texture, and the row that matters stops
 * standing out at all.
 */
export function GlassButton({ name, label, onClick, disabled, size = 20 }: GlassButtonProps) {
  return (
    <button
      type="button"
      className="glass-btn glass-btn--icon"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon name={name} size={size} />
    </button>
  );
}

/* --------------------------------------------------------------- SectionLabel */

export function SectionLabel({ children }: { children: ReactNode }) {
  return <h2 className="section-label">{children}</h2>;
}

/* -------------------------------------------------------------------- NavRow */

interface NavRowProps {
  icon: IconName;
  label: string;
  count?: number;
  selected?: boolean;
  onClick: () => void;
  onDoubleClick?: () => void;
  title?: string;
  /** Trailing control, revealed on hover. Rendered as a sibling of the row
   *  rather than inside it — a button cannot contain another button. */
  action?: ReactNode;
}

export function NavRow({
  icon,
  label,
  count,
  selected,
  onClick,
  onDoubleClick,
  title,
  action,
}: NavRowProps) {
  const row = (
    <button
      type="button"
      className={"nav-row" + (selected ? " nav-row--selected" : "")}
      aria-current={selected ? "page" : undefined}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      title={title}
    >
      <Icon name={icon} size={20} />
      <span className="nav-row__label">{label}</span>
      {count !== undefined && <span className="nav-row__count">{count}</span>}
    </button>
  );

  if (!action) return row;
  return (
    <div className="nav-slot">
      {row}
      {action}
    </div>
  );
}

/* -------------------------------------------------------------------- Avatar */

/** Enclosed treatment — only ever for entities, never for actions. */
export function Avatar({ icon, size = 28 }: { icon: IconName; size?: number }) {
  return (
    <span className="avatar" style={{ width: size, height: size }}>
      <Icon name={icon} size={Math.round(size * 0.57)} />
    </span>
  );
}

/* ------------------------------------------------------------------ AgentRow */

interface AgentRowProps {
  name: string;
  status: string;
  icon?: IconName;
  trailing?: IconName;
}

export function AgentRow({ name, status, icon = "spark", trailing }: AgentRowProps) {
  return (
    <div className="agent-row">
      <Avatar icon={icon} />
      <span className="agent-row__text">
        <span className="agent-row__name">{name}</span>
        <span className="agent-row__status">{status}</span>
      </span>
      {trailing && <Icon name={trailing} size={18} className="agent-row__trailing" />}
    </div>
  );
}
