import { describe, expect, it } from "vitest";

import { dayHeading, dayKey, daysApart, stamp } from "./time";

const iso = (y: number, m: number, d: number, h = 12, min = 0) =>
  new Date(y, m - 1, d, h, min).toISOString();

describe("daysApart", () => {
  it("counts calendar days, not elapsed hours", () => {
    // 23:30 to 00:30 is one hour but a different day, and the Stream groups by
    // day, so this must read as 1.
    const late = new Date(2026, 6, 27, 23, 30);
    const early = new Date(2026, 6, 28, 0, 30);
    expect(daysApart(early, late)).toBe(1);
  });

  it("is zero within the same day", () => {
    expect(daysApart(new Date(2026, 6, 28, 23, 0), new Date(2026, 6, 28, 1, 0))).toBe(0);
  });
});

describe("stamp", () => {
  it("shows a time for entries from today", () => {
    const now = new Date(2026, 6, 28, 18, 0);
    expect(stamp(iso(2026, 7, 28, 9, 5), now)).toMatch(/09.05/);
  });

  it("shows a date without a year within the current year", () => {
    const now = new Date(2026, 6, 28);
    const result = stamp(iso(2026, 3, 14), now);
    expect(result).not.toMatch(/2026/);
    expect(result).toMatch(/14/);
  });

  it("includes the year for older entries", () => {
    expect(stamp(iso(2024, 3, 14), new Date(2026, 6, 28))).toMatch(/2024/);
  });
});

describe("dayHeading", () => {
  const now = new Date(2026, 6, 28, 12, 0);

  it("names today and yesterday", () => {
    expect(dayHeading(iso(2026, 7, 28, 8), now)).toBe("Today");
    expect(dayHeading(iso(2026, 7, 27, 8), now)).toBe("Yesterday");
  });

  it("uses a full weekday heading further back", () => {
    expect(dayHeading(iso(2026, 7, 20, 8), now)).toMatch(/day/i);
  });
});

describe("dayKey", () => {
  it("matches for two times on the same day", () => {
    expect(dayKey(iso(2026, 7, 28, 1))).toBe(dayKey(iso(2026, 7, 28, 23)));
  });

  it("differs across a midnight boundary", () => {
    expect(dayKey(iso(2026, 7, 28, 23))).not.toBe(dayKey(iso(2026, 7, 29, 0, 1)));
  });
});
