/**
 * Diagram this.
 *
 * The agent draws the structure it sees in a folder, a tag, or a search — and
 * picks the form, because the form is most of the claim: a mindmap says these
 * are facets of one thing, a flowchart says one leads to another, a state
 * diagram says a position moved.
 *
 * Mermaid's parser is JavaScript, so this is the only place the diagram can be
 * checked. The loop is: parse; on failure send the parser's own words back for
 * one repair; on a second failure show the error and the source and stop. Two
 * failures means the model cannot draw this one, and a third paid attempt is a
 * loop rather than a fix.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { Artifact, DiagramScope, Scope } from "../lib/types";
import { useIsDark } from "../lib/useTheme";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  /** What the Stream is showing. A diagram is always of something in particular. */
  scope: Scope;
  onClose: () => void;
}

type Phase = "drawing" | "repairing" | "ready" | "failed";

/** Mermaid is ~3MB and almost nobody opens this on any given day, so it is
 *  loaded on first use. Vite splits it into its own chunk; the Stream never
 *  pays for a library it does not draw with. */
let mermaidReady: Promise<typeof import("mermaid").default> | null = null;

/** Mermaid's own dark theme paints maroon boxes, which belong to a different
 *  application. Every colour is named from the app's palette instead, so a
 *  diagram looks like part of Tilt rather than something pasted into it. */
function palette(dark: boolean) {
  return dark
    ? {
        background: "#0d0d0e",
        primaryColor: "#1e1e21",
        primaryTextColor: "#f2f2f4",
        primaryBorderColor: "#3a3a40",
        secondaryColor: "#232326",
        tertiaryColor: "#1a1a1d",
        lineColor: "#6b6b73",
        textColor: "#f2f2f4",
      }
    : {
        background: "#f4f4f5",
        primaryColor: "#ffffff",
        primaryTextColor: "#16181c",
        primaryBorderColor: "#d6d6da",
        secondaryColor: "#eaeaec",
        tertiaryColor: "#f7f7f8",
        lineColor: "#9aa0a8",
        textColor: "#16181c",
      };
}

/** The import is cached; the configuration is not.
 *
 *  Initialising once at import time would freeze the diagram in whichever
 *  appearance happened to be active the first time anyone opened this — toggle
 *  the theme afterwards and every diagram keeps the old one. */
async function loadMermaid(dark: boolean) {
  mermaidReady ??= import("mermaid").then((m) => m.default);
  const mermaid = await mermaidReady;
  mermaid.initialize({
    startOnLoad: false,
    // The diagram is model output being handed to a parser. Strict is what
    // stops a `click` directive from doing anything even if one slipped past
    // the sanitiser on the way in.
    securityLevel: "strict",
    theme: "base",
    themeVariables: {
      ...palette(dark),
      fontFamily: "-apple-system, system-ui, sans-serif",
      fontSize: "15px",
    },
  });
  return mermaid;
}

function toScope(scope: Scope): DiagramScope | null {
  if (scope.type === "theme") return { theme_id: scope.id };
  if (scope.type === "tag") return { tag: scope.tag };
  if (scope.type === "search") return { q: scope.q };
  return null;
}

export function label(scope: Scope): string {
  if (scope.type === "theme") return scope.label;
  if (scope.type === "tag") return `#${scope.tag}`;
  if (scope.type === "search") return `“${scope.q}”`;
  return "everything";
}

export function DiagramSheet({ open, scope, onClose }: Props) {
  const dark = useIsDark();
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [phase, setPhase] = useState<Phase>("drawing");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  /** Parse, then render. `parse` is the check; `render` is what draws. */
  const attempt = useCallback(
    async (source: string, id: string): Promise<string | null> => {
      const mermaid = await loadMermaid(dark);
      try {
        await mermaid.parse(source);
        const { svg: drawn } = await mermaid.render(`d-${id}-${seq.current++}`, source);
        setSvg(drawn);
        return null;
      } catch (err) {
        return err instanceof Error ? err.message : String(err);
      }
    },
    [dark],
  );

  useEffect(() => {
    if (!open) return;
    const target = toScope(scope);
    if (!target) {
      setPhase("failed");
      setError("Choose a folder, a tag, or a search first. A diagram of everything has no shape to find.");
      return;
    }

    let cancelled = false;
    setPhase("drawing");
    setSvg("");
    setError("");

    void (async () => {
      try {
        const drawn = await api.diagram(target);
        if (cancelled) return;
        setArtifact(drawn);

        const complaint = await attempt(drawn.body, drawn.id);
        if (cancelled || !complaint) {
          if (!cancelled) setPhase("ready");
          return;
        }

        // One repair, with the renderer's own words. A paraphrase of a parser
        // error is worth nothing to the model trying to fix it.
        setPhase("repairing");
        const fixed = await api.repairDiagram(drawn.id, complaint);
        if (cancelled) return;
        setArtifact(fixed);

        const second = await attempt(fixed.body, fixed.id);
        if (cancelled) return;
        if (second) {
          setError(second);
          setPhase("failed");
        } else {
          setPhase("ready");
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Something went wrong.");
        setPhase("failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, scope, attempt]);

  if (!open) return null;

  return (
    <div className="sheet-scrim fade" onMouseDown={onClose} role="presentation">
      <div
        className="sheet sheet--wide glass glass--heavy"
        role="dialog"
        aria-modal="true"
        aria-label="Diagram"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="sheet__head">
          <h2 className="sheet__title">{artifact?.title || label(scope)}</h2>
          <p className="sheet__version">
            {phase === "drawing"
              ? "drawing…"
              : phase === "repairing"
                ? "that did not parse — trying once more…"
                : artifact?.kind}
          </p>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            <Icon name="close" size={18} />
          </button>
        </header>

        <div className="sheet__body sheet__body--grow scroll">
          {phase === "failed" ? (
            /* Shown rather than swallowed. The writer paid for two attempts and
               is owed both what broke and what was produced — a diagram that
               silently never appears is indistinguishable from a hung app. */
            <section className="sheet__section">
              <p className="sheet__note">The diagram could not be drawn.</p>
              <pre className="diagram__error">{error}</pre>
              {artifact?.body && <pre className="diagram__source">{artifact.body}</pre>}
            </section>
          ) : (
            <div
              className="diagram__stage"
              aria-label={artifact?.title || "Diagram"}
              // The source is sanitised server-side and rendered by Mermaid in
              // strict mode, which escapes every label it draws.
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          )}
        </div>

        {artifact?.note && phase === "ready" && (
          <footer className="sheet__foot sheet__foot--note">
            <p className="sheet__note sheet__note--quiet">{artifact.note}</p>
          </footer>
        )}
      </div>
    </div>
  );
}
