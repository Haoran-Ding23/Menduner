import { describe, expect, it } from "vitest";
import {
  beijingToday,
  caliberCounts,
  eventsInWindow,
  phaseOf,
  windowFromParams,
  type TimeWindow,
} from "../src/utils/caliber";
import type { Event } from "../src/types";

/**
 * 口径函数的测试。
 *
 * 这些断言针对的是「同一批活动在不同页面上被算成不同数字」这个具体问题，所以重点在
 * 活动数与覆盖天数的区别、窗口边界上的归入/排除，以及北京时间跨零点。
 */

const event = (partial: Partial<Event> & { id: string }): Event =>
  ({
    name: partial.name ?? partial.id,
    category: "culture",
    startDate: partial.startDate ?? null,
    endDate: partial.endDate ?? null,
    venueId: null,
    districtId: partial.districtId ?? null,
    demo: partial.demo ?? false,
    organizer: null,
    attendance: null,
    sponsor: null,
    ...partial,
  }) as Event;

const window = (start: string, end: string): TimeWindow => ({
  kind: "custom",
  start,
  end,
  label: `${start} 至 ${end}`,
});

describe("beijingToday", () => {
  it("uses Asia/Shanghai, not UTC", () => {
    // 2026-10-23T16:30Z is already 2026-10-24 in Beijing (UTC+8).
    expect(beijingToday(new Date("2026-10-23T16:30:00Z"))).toBe("2026-10-24");
    // 2026-10-23T15:30Z is still 2026-10-23 in Beijing.
    expect(beijingToday(new Date("2026-10-23T15:30:00Z"))).toBe("2026-10-23");
  });
});

describe("windowFromParams", () => {
  it("defaults to the next 30 days from today", () => {
    const w = windowFromParams(new URLSearchParams(), "2026-10-23");
    expect(w.kind).toBe("next30");
    expect(w.start).toBe("2026-10-23");
    expect(w.end).toBe("2026-11-21"); // 30 calendar days inclusive
  });

  it("supports the next 7 days", () => {
    const w = windowFromParams(new URLSearchParams("window=next7"), "2026-10-23");
    expect(w.end).toBe("2026-10-29"); // 7 calendar days inclusive
  });

  it("honours an explicit custom range", () => {
    const w = windowFromParams(
      new URLSearchParams("from=2026-11-01&to=2026-11-30"),
      "2026-10-23",
    );
    expect(w.kind).toBe("custom");
    expect([w.start, w.end]).toEqual(["2026-11-01", "2026-11-30"]);
  });

  it("ignores an invalid or inverted range instead of producing an empty window", () => {
    const bad = windowFromParams(new URLSearchParams("from=2026-13-01&to=2026-12-01"), "2026-10-23");
    expect(bad.kind).toBe("next30");
    const inverted = windowFromParams(new URLSearchParams("from=2026-12-01&to=2026-11-01"), "2026-10-23");
    expect(inverted.kind).toBe("next30");
  });
});

describe("phaseOf", () => {
  const w = window("2026-10-23", "2026-11-21");

  it("classifies an event that starts before the window and ends inside it as ongoing", () => {
    expect(phaseOf(event({ id: "e1", startDate: "2026-10-01", endDate: "2026-11-29" }), w)).toBe(
      "ongoing",
    );
  });

  it("classifies an event entirely inside the window as upcoming", () => {
    expect(phaseOf(event({ id: "e2", startDate: "2026-10-25", endDate: "2026-10-27" }), w)).toBe(
      "upcoming",
    );
  });

  it("treats an event that ends before the window starts as ended", () => {
    expect(phaseOf(event({ id: "e3", startDate: "2026-09-01", endDate: "2026-09-30" }), w)).toBe(
      "ended",
    );
  });

  it("treats a single-day event on the last day of the window as inside", () => {
    expect(phaseOf(event({ id: "e4", startDate: "2026-11-21" }), w)).toBe("upcoming");
    expect(phaseOf(event({ id: "e5", startDate: "2026-11-22" }), w)).toBe("ended");
  });
});

describe("caliberCounts", () => {
  const w = window("2026-10-23", "2026-10-29");

  it("separates activity count from covered days", () => {
    const events = [
      event({ id: "a", startDate: "2026-10-24", endDate: "2026-10-26" }), // 24, 25, 26
      event({ id: "b", startDate: "2026-10-26", endDate: "2026-10-26" }), // 26, already counted
    ];
    const counts = caliberCounts(w, events, () => true);
    expect(counts.activities).toBe(2);
    // Two activities, but only three distinct calendar days: this is exactly the distinction the
    // caliber bar has to keep visible.
    expect(counts.coveredDays).toBe(3);
  });

  it("clamps a long-running event to the window instead of counting a whole year of days", () => {
    const events = [event({ id: "long", startDate: "2026-01-01", endDate: "2026-12-31" })];
    const counts = caliberCounts(w, events, () => true);
    expect(counts.activities).toBe(1);
    expect(counts.coveredDays).toBe(7); // 2026-10-23 .. 2026-10-29
  });

  it("reports events without verified coordinates separately", () => {
    const events = [
      event({ id: "with", startDate: "2026-10-24" }),
      event({ id: "without", startDate: "2026-10-24" }),
    ];
    const counts = caliberCounts(w, events, (e) => e.id === "with");
    expect(counts.activities).toBe(2);
    expect(counts.withoutCoordinates).toBe(1);
  });

  it("splits phases over the window", () => {
    const events = [
      event({ id: "ongoing", startDate: "2026-10-01", endDate: "2026-11-30" }),
      event({ id: "upcoming", startDate: "2026-10-25" }),
      event({ id: "ended", startDate: "2026-10-01", endDate: "2026-10-02" }),
    ];
    const counts = caliberCounts(w, events, () => true);
    expect(counts.phases.ongoing).toBe(1);
    expect(counts.phases.upcoming).toBe(1);
    expect(counts.phases.ended).toBe(1);
  });
});

describe("eventsInWindow", () => {
  const w = window("2026-10-23", "2026-10-29");

  it("keeps an ongoing event that started before the window", () => {
    const events = [event({ id: "ongoing", startDate: "2026-10-01", endDate: "2026-11-30" })];
    expect(eventsInWindow(events, { includeDemo: false }, w).map((e) => e.id)).toEqual(["ongoing"]);
  });

  it("excludes an event that ends the day before the window starts", () => {
    const events = [event({ id: "before", startDate: "2026-10-01", endDate: "2026-10-22" })];
    expect(eventsInWindow(events, { includeDemo: false }, w)).toEqual([]);
  });

  it("hides demo data unless explicitly included", () => {
    const events = [event({ id: "demo", startDate: "2026-10-24", demo: true })];
    expect(eventsInWindow(events, { includeDemo: false }, w)).toEqual([]);
    expect(eventsInWindow(events, { includeDemo: true }, w)).toHaveLength(1);
  });

  it("filters by district and category", () => {
    const events = [
      event({ id: "tc", startDate: "2026-10-24", districtId: "taicang", category: "culture" }),
      event({ id: "gs", startDate: "2026-10-24", districtId: "gusu", category: "culture" }),
    ];
    const scoped = eventsInWindow(events, { includeDemo: false, district: "taicang" }, w);
    expect(scoped.map((e) => e.id)).toEqual(["tc"]);
  });
});
