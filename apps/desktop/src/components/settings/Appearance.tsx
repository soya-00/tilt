import { Icon } from "../Icon";

interface Props {
  theme: "light" | "dark";
  onToggle: () => void;
}

export function Appearance({ theme, onToggle }: Props) {
  return (
    <section className="sheet__section">
      <h3 className="sheet__label">Appearance</h3>
      {/* The thumb is the same glass as the panels, and it carries both glyphs
          at once — the sun and the moon cross-fade under it as it travels, so
          the control shows what it is moving toward rather than only what it
          currently is. */}
      <button
        className={"switch" + (theme === "dark" ? " switch--on" : "")}
        role="switch"
        aria-checked={theme === "dark"}
        onClick={onToggle}
      >
        <span className="switch__track">
          <span className="switch__glyphs" aria-hidden="true">
            <Icon name="sun" size={14} className="switch__sun" />
            <Icon name="moon" size={14} className="switch__moon" />
          </span>
          <span className="switch__thumb glass" />
        </span>
        <span className="switch__label">{theme === "dark" ? "Dark" : "Light"}</span>
      </button>
    </section>
  );
}
