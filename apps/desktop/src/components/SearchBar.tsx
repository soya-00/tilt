import { useEffect, useRef, useState } from "react";

import type { Scope } from "../lib/types";
import { Icon } from "./Icon";

interface Props {
  scope: Scope;
  onScope: (scope: Scope) => void;
}

/**
 * Search across the journal.
 *
 * Debounced so a query fires once you pause rather than on every keystroke,
 * and it sets the scope rather than opening a separate results view — searching
 * is just another way of narrowing the same thread.
 *
 * It is the one piece of glass floating in open space rather than anchored to a
 * window edge, so it takes the full rim: a closed pill lit all the way round,
 * hottest on the edge facing the light.
 */
export function SearchBar({ scope, onScope }: Props) {
  const [value, setValue] = useState(scope.type === "search" ? scope.q : "");
  const input = useRef<HTMLInputElement>(null);
  const applied = useRef(value);

  // Clearing the scope elsewhere (a folder click, "show everything") must empty
  // the field too, or it would claim to be filtering when it is not.
  useEffect(() => {
    if (scope.type !== "search" && applied.current !== "") {
      applied.current = "";
      setValue("");
    }
  }, [scope]);

  useEffect(() => {
    const term = value.trim();
    if (term === applied.current) return;
    const timer = setTimeout(() => {
      applied.current = term;
      onScope(term ? { type: "search", q: term } : { type: "all" });
    }, 220);
    return () => clearTimeout(timer);
  }, [value, onScope]);

  return (
    <div className={"search glass" + (value ? " search--active" : "")}>
      <Icon name="search" size={17} className="search__glyph" />
      <input
        ref={input}
        className="search__input"
        value={value}
        placeholder="Search your thinking"
        aria-label="Search your thinking"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setValue("");
            input.current?.blur();
          }
        }}
      />
      {value && (
        <button
          className="search__clear"
          aria-label="Clear search"
          onClick={() => {
            setValue("");
            input.current?.focus();
          }}
        >
          <Icon name="close" size={15} />
        </button>
      )}
    </div>
  );
}
