/** Time formatting for the Stream.
 *
 * Timestamps are the machine's voice, so they are terse and absolute. Relative
 * labels ("2 hours ago") are used only inside today, where they carry real
 * meaning; beyond that they cost precision without buying legibility.
 */

const TIME = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const DATE_WITH_YEAR = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const DAY_HEADING = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  month: "long",
  day: "numeric",
});

export function parse(iso: string): Date {
  return new Date(iso);
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function daysApart(a: Date, b: Date): number {
  return Math.round((startOfDay(a) - startOfDay(b)) / 86_400_000);
}

/** Short stamp shown in the entry gutter. */
export function stamp(iso: string, now = new Date()): string {
  const date = parse(iso);
  const delta = daysApart(now, date);
  if (delta === 0) return TIME.format(date);
  if (now.getFullYear() === date.getFullYear()) return DATE.format(date);
  return DATE_WITH_YEAR.format(date);
}

/** Full stamp for tooltips — never ambiguous. */
export function precise(iso: string): string {
  return parse(iso).toLocaleString(undefined, {
    dateStyle: "full",
    timeStyle: "short",
  });
}

/** Heading for a day separator in the Stream. */
export function dayHeading(iso: string, now = new Date()): string {
  const date = parse(iso);
  const delta = daysApart(now, date);
  if (delta === 0) return "Today";
  if (delta === 1) return "Yesterday";
  return DAY_HEADING.format(date);
}

/** Stable key for grouping entries into days. */
export function dayKey(iso: string): string {
  const date = parse(iso);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}
