/**
 * Per-tag colour.
 *
 * Each tag gets its own hue from a muted, aesthetic palette — assigned by
 * hashing the tag name, so the same word is always the same colour, on every
 * machine, forever. Random-at-render would make the journal flicker.
 *
 * The colour stays hidden until you hover the tag or are actively scoped to it.
 * Colour here is a response to attention, not decoration: a wall of permanently
 * coloured tags would shout over the writing.
 */

export interface TagHue {
  /** Saturated enough to read as colour when it appears. */
  fg: string;
  /** A wash for the pill behind it. */
  bg: string;
}

/** Muted, desaturated, and deliberately non-primary. */
const PALETTE: TagHue[] = [
  { fg: "#c2643f", bg: "rgba(194, 100, 63, 0.14)" }, // terracotta
  { fg: "#b8873a", bg: "rgba(184, 135, 58, 0.14)" }, // ochre
  { fg: "#8a9a4b", bg: "rgba(138, 154, 75, 0.15)" }, // moss
  { fg: "#4e9080", bg: "rgba(78, 144, 128, 0.15)" }, // sage
  { fg: "#4a8ba6", bg: "rgba(74, 139, 166, 0.15)" }, // slate blue
  { fg: "#6f7fbc", bg: "rgba(111, 127, 188, 0.16)" }, // periwinkle
  { fg: "#9070b5", bg: "rgba(144, 112, 181, 0.16)" }, // muted violet
  { fg: "#b66391", bg: "rgba(182, 99, 145, 0.15)" }, // dusty rose
  { fg: "#a8635f", bg: "rgba(168, 99, 95, 0.15)" }, // clay
  { fg: "#5f8f6a", bg: "rgba(95, 143, 106, 0.15)" }, // fern
  { fg: "#c08a5e", bg: "rgba(192, 138, 94, 0.14)" }, // sand
  { fg: "#6d8fa0", bg: "rgba(109, 143, 160, 0.16)" }, // stone blue
];

/** Lifted variants so the same hue holds up on a near-black background. */
const PALETTE_DARK: TagHue[] = [
  { fg: "#e79268", bg: "rgba(231, 146, 104, 0.16)" },
  { fg: "#dcae5f", bg: "rgba(220, 174, 95, 0.16)" },
  { fg: "#b3c471", bg: "rgba(179, 196, 113, 0.16)" },
  { fg: "#6fbfab", bg: "rgba(111, 191, 171, 0.16)" },
  { fg: "#6fb6d6", bg: "rgba(111, 182, 214, 0.16)" },
  { fg: "#95a6e8", bg: "rgba(149, 166, 232, 0.18)" },
  { fg: "#b795e0", bg: "rgba(183, 149, 224, 0.18)" },
  { fg: "#e08bb8", bg: "rgba(224, 139, 184, 0.17)" },
  { fg: "#d08a85", bg: "rgba(208, 138, 133, 0.17)" },
  { fg: "#84bd92", bg: "rgba(132, 189, 146, 0.17)" },
  { fg: "#e0ae83", bg: "rgba(224, 174, 131, 0.16)" },
  { fg: "#93b5c7", bg: "rgba(147, 181, 199, 0.17)" },
];

/** FNV-1a — small, fast, and well spread for short strings. */
function hash(value: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function tagHue(tag: string, dark = false): TagHue {
  const table = dark ? PALETTE_DARK : PALETTE;
  return table[hash(tag.toLowerCase()) % table.length]!;
}

/** Inline custom properties the CSS reveals on hover or when selected. */
export function tagStyle(tag: string, dark = false): React.CSSProperties {
  const hue = tagHue(tag, dark);
  return { "--tag-fg": hue.fg, "--tag-bg": hue.bg } as React.CSSProperties;
}

export const PALETTE_SIZE = PALETTE.length;
