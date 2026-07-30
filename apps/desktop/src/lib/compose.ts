/** Turning one block of typed text into the parts an item is made of.
 *
 * The brief's composer is one box on purpose — a form with a URL field and a
 * tag field is a form, and nobody fills one in to save a link they meant to
 * read. So the box takes whatever you type and this pulls it apart: a link
 * wherever it landed, `#tags` wherever you put them, and what is left is the
 * note.
 *
 * Pure and separate from the component so the parsing can be tested on its own
 * — it is the part with rules, and the component is the part with pixels.
 */

const URL_PATTERN = /https?:\/\/[^\s<>"')\]]+/i;

/** Preceded by a space or the start of the line, so a `#` inside a URL or a
 *  C-major chord in the middle of a word is not a tag. */
const TAG_PATTERN = /(^|\s)#([\p{L}\p{N}][\p{L}\p{N}_-]{1,39})/gu;

export interface Composed {
  url: string;
  tags: string[];
  /** What is left once the link and the tags are lifted out. */
  why: string;
}

export function findUrl(text: string): string {
  const match = URL_PATTERN.exec(text);
  // Trailing punctuation belongs to your sentence, not to the address —
  // "see https://example.com/a, it argues the opposite" is not a link ending
  // in a comma.
  return match ? match[0].replace(/[.,;:!?]+$/, "") : "";
}

export function compose(text: string): Composed {
  const url = findUrl(text);
  const tags: string[] = [];

  let rest = text.replace(TAG_PATTERN, (_whole, lead: string, tag: string) => {
    const lowered = tag.toLowerCase();
    if (!tags.includes(lowered)) tags.push(lowered);
    // Keep the leading space: removing it would weld the two surrounding
    // words together.
    return lead;
  });

  if (url) rest = rest.replace(URL_PATTERN, "");

  return { url, tags, why: rest.replace(/\s+/g, " ").trim() };
}
