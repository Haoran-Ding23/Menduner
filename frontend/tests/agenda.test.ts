import { describe, expect, it } from "vitest";
import dayjs from "dayjs";
import {
  overlapsRange,
  startsInRange,
  partitionByStart,
  rangeFor,
  todayKey,
} from "../src/pages/EventAgenda";
import type { Event } from "../src/types";

/**
 * The agenda page exists to answer "what starts today?" — and the distinction that makes it
 * useful is STARTING versus RUNNING.
 *
 * An exhibition that opened in August and closes in October overlaps today, but it is not news:
 * it has been generating demand for weeks. An event that starts today is the new signal. If
 * those two are not separated the list reads as one undifferentiated block and the page adds
 * nothing over the calendar grid.
 */
const event = (name: string, startDate: string, endDate: string | null = null): Event =>
  ({
    id: name,
    name,
    category: "culture",
    startDate,
    endDate,
    venueId: null,
    districtId: null,
    sourceUrl: "https://example.invalid/e",
    demo: false,
  }) as Event;

describe("rangeFor", () => {
  it("gives a single day for 本日", () => {
    const { start, end } = rangeFor("day");
    expect(start).toBe(end);
    expect(start).toBe(todayKey());
  });

  it("starts 本周 on Monday, matching the calendar page", () => {
    const { start, end } = rangeFor("week");
    expect(dayjs(start).day()).toBe(1); // Monday
    expect(dayjs(end).diff(dayjs(start), "day")).toBe(6);
  });

  it("covers the whole of 本月", () => {
    const { start, end } = rangeFor("month");
    expect(dayjs(start).date()).toBe(1);
    expect(dayjs(start).format("YYYY-MM")).toBe(dayjs(end).format("YYYY-MM"));
    expect(dayjs(end).date()).toBe(dayjs(end).daysInMonth());
  });
});

describe("overlapsRange and startsInRange", () => {
  const range = { start: "2026-10-12", end: "2026-10-18" };

  it("treats a long exhibition that spans the range as overlapping but not starting", () => {
    const exhibition = event("长期展览", "2026-08-30", "2026-10-30");
    expect(overlapsRange(exhibition, range.start, range.end)).toBe(true);
    expect(startsInRange(exhibition, range.start, range.end)).toBe(false);
  });

  it("treats an event beginning inside the range as starting", () => {
    const opening = event("今日开幕", "2026-10-15", "2026-10-20");
    expect(overlapsRange(opening, range.start, range.end)).toBe(true);
    expect(startsInRange(opening, range.start, range.end)).toBe(true);
  });

  it("includes boundary days on both ends", () => {
    expect(overlapsRange(event("首日", "2026-10-12"), range.start, range.end)).toBe(true);
    expect(overlapsRange(event("末日", "2026-10-18"), range.start, range.end)).toBe(true);
  });

  it("excludes an event on an adjacent day", () => {
    expect(overlapsRange(event("前一天", "2026-10-11"), range.start, range.end)).toBe(false);
    expect(overlapsRange(event("后一天", "2026-10-19"), range.start, range.end)).toBe(false);
  });

  it("ignores an event with no usable dates rather than guessing", () => {
    const undated = event("日期待定", "" as unknown as string);
    expect(overlapsRange(undated, range.start, range.end)).toBe(false);
    expect(startsInRange(undated, range.start, range.end)).toBe(false);
  });

  it("treats a single-day event as starting and overlapping on that day", () => {
    const oneDay = event("单日活动", "2026-10-15");
    expect(overlapsRange(oneDay, "2026-10-15", "2026-10-15")).toBe(true);
    expect(startsInRange(oneDay, "2026-10-15", "2026-10-15")).toBe(true);
  });
});

describe("partitionByStart", () => {
  it("separates the new signal from the already-running background", () => {
    const events = [
      event("八月开始的长展", "2026-08-30", "2026-10-30"),
      event("今日开幕", "2026-10-15", "2026-10-20"),
      event("今日单场", "2026-10-15"),
    ];
    const { starting, running } = partitionByStart(events, "2026-10-15", "2026-10-15");
    expect(starting.map((e) => e.name)).toEqual(["今日单场", "今日开幕"]);
    expect(running.map((e) => e.name)).toEqual(["八月开始的长展"]);
  });

  it("keeps every in-range event in exactly one bucket", () => {
    const events = [
      event("甲", "2026-10-01", "2026-12-31"),
      event("乙", "2026-10-13", "2026-10-14"),
      event("丙", "2026-10-16"),
      event("丁", "2026-11-20"),
    ];
    const { starting, running } = partitionByStart(events, "2026-10-12", "2026-10-18");
    expect([...starting, ...running]).toHaveLength(3);
    const overlap = starting.filter((s) => running.some((r) => r.id === s.id));
    expect(overlap).toEqual([]);
  });

  it("sorts by start date so the order is stable and readable", () => {
    const events = [
      event("丙", "2026-10-17"),
      event("甲", "2026-10-13"),
      event("乙", "2026-10-15"),
    ];
    const { starting } = partitionByStart(events, "2026-10-12", "2026-10-18");
    expect(starting.map((e) => e.name)).toEqual(["甲", "乙", "丙"]);
  });

  it("returns empty buckets for an empty input rather than throwing", () => {
    expect(partitionByStart([], "2026-10-12", "2026-10-18")).toEqual({
      starting: [],
      running: [],
    });
  });
});
