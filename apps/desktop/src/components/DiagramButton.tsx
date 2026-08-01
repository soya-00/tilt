import type { Scope } from "../lib/types";
import { label as scopeName } from "./DiagramSheet";
import { Icon } from "./Icon";

interface Props {
  scope: Scope;
  onOpen: () => void;
}

/**
 * The one entrance to "Diagram this" that does not require knowing it exists.
 *
 * It had none. The command palette carried it, enabled only while a folder or a
 * search was open, which made a feature that spends a model call discoverable
 * by accident or not at all.
 *
 * Absent rather than disabled when nothing is scoped — the same rule the palette
 * entry already encodes, and there is nothing to explain: a diagram of
 * everything is not a diagram of anything.
 */
export function DiagramButton({ scope, onOpen }: Props) {
  if (scope.type === "all") return null;

  return (
    <button
      className="strip-btn"
      aria-label={`Diagram ${scopeName(scope)}`}
      title={`Diagram ${scopeName(scope)}`}
      onClick={onOpen}
    >
      <Icon name="diagram" size={18} />
    </button>
  );
}
