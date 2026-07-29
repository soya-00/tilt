/**
 * The whole icon system.
 *
 * No library, no external fetch. Every glyph is a 24×24 viewBox stroked in
 * `currentColor` at 1.75 — colour is always inherited, never named here. Scale
 * with the `size` prop; the viewBox is never edited.
 *
 * Optical weight is matched by simplifying paths, not by changing stroke width.
 */

export type IconName =
  | "home"
  | "folder"
  | "hash"
  | "spark"
  | "settings"
  | "search"
  | "camera"
  | "paperclip"
  | "waveform"
  | "arrow-up"
  | "link"
  | "close"
  | "plus"
  | "sun"
  | "moon"
  | "refresh"
  | "pencil"
  | "trash"
  | "eye-off"
  | "constellation";

const PATHS: Record<IconName, string> = {
  home: "M4 10.2 12 4l8 6.2V19a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z",
  folder: "M3 7a2 2 0 0 1 2-2h3.6a1 1 0 0 1 .7.3L11 7h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  hash: "M9 4 7 20M17 4l-2 16M4 9h16M3 15h16",
  spark: "M12 4v6M12 14v6M4.9 8.1l4.3 2.5M14.8 13.4l4.3 2.5M19.1 8.1l-4.3 2.5M9.2 13.4l-4.3 2.5",
  settings: "M5 7h14M5 12h14M5 17h14M9 5v4M16 10v4M11 15v4",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  camera: "M4 8a2 2 0 0 1 2-2h1.5l1-2h7l1 2H18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM12 16a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
  paperclip: "M20 11.5 12.4 19a4.5 4.5 0 0 1-6.4-6.4l7.8-7.7a3 3 0 0 1 4.2 4.2l-7.7 7.7a1.5 1.5 0 0 1-2.1-2.1L15.5 7",
  // The one place the grammar bends: five bars, because it signals audio.
  waveform: "M5 10v4M9 7v10M12 5v14M16 8v8M20 11v2",
  "arrow-up": "M12 19V5M6 11l6-6 6 6",
  link: "M10 13a4 4 0 0 0 5.7.4l2.8-2.8a4 4 0 0 0-5.7-5.7L11.4 6.3M14 11a4 4 0 0 0-5.7-.4l-2.8 2.8a4 4 0 0 0 5.7 5.7l1.4-1.4",
  close: "M6 6l12 12M18 6 6 18",
  plus: "M12 5v14M5 12h14",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  // A crescent, not a circle with a bite: the terminator is the whole glyph.
  moon: "M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z",
  refresh: "M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5",
  pencil: "M4 20h4l10-10a2.8 2.8 0 0 0-4-4L4 16z",
  trash: "M4 7h16M10 7V5h4v2M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12",
  // Three points and the lines between them — the graph itself, not a star.
  constellation: "M7 8.5 16 6M8 10.5 15.5 16M17.5 8 16.5 14M6 7.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zM17.5 4.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zM16 14.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z",
  "eye-off": "M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M6.7 6.8C4.6 8.1 3 10 2 12c2 3.6 5.6 6 10 6 1.7 0 3.3-.4 4.7-1M9.9 6.2A9.9 9.9 0 0 1 12 6c4.4 0 8 2.4 10 6a14 14 0 0 1-2.8 3.5",
};

interface Props {
  name: IconName;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 20, className }: Props) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

export const ICON_NAMES = Object.keys(PATHS) as IconName[];
