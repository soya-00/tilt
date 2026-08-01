import type { Conflict } from "../lib/types";

interface Props {
  conflicts: Conflict[];
  onDismiss: () => void;
}

/**
 * Two files on disk claiming the same entry.
 *
 * A sync client's "(conflicted copy)" carries the id of the file it copied, so
 * both are the same entry as far as the index is concerned and only one of them
 * is read. The index has reported this since it learned to notice it, and
 * nothing rendered it — which is the same as not noticing, because both files
 * sit in the folder looking perfectly fine.
 *
 * Said in the strip beside the other notices about the app rather than about
 * your writing, and not styled as an error: nothing is broken and nothing was
 * lost. One file is simply not being read, and the paths are in the tooltip so
 * it can be settled in a file manager, which is the only place it can be.
 */
export function Conflicts({ conflicts, onDismiss }: Props) {
  if (conflicts.length === 0) return null;

  return (
    <button
      className="pane__conflict"
      onClick={onDismiss}
      title={conflicts.map((c) => `reading ${c.kept}\nignoring ${c.ignored}`).join("\n\n")}
    >
      {conflicts.length === 1
        ? "2 files claim the same entry"
        : `${conflicts.length} entries are claimed by two files each`}
    </button>
  );
}
