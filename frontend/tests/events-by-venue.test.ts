import { describe, expect, it } from "vitest";
import { eventsByVenue, HOTSPOT_MIN } from "../src/utils/data";
import type { Category, Event, Venue } from "../src/types";

/**
 * Venue-first aggregation.
 *
 * The operations lead interviewed on 2026-10-15 runs a hotel in 太仓 and reasoned entirely in
 * venues - "场地", "场地大小", "音乐节在哪个场地" - and described the problem as
 * 官方渠道比较多，信息比较散，需要一年中的活动归纳好. This groups the same events that way.
 */
const venue = (id: string, name: string, coords = false): Venue =>
  ({
    id,
    name,
    address: null,
    districtId: null,
    coordinates: coords
      ? {
          lng: 120.6,
          lat: 31.3,
          system: "GCJ-02",
          status: "Verified",
          sourceUrl: "https://ditu.amap.com/place/TEST",
        }
      : null,
    districtDemo: false,
  }) as Venue;

const event = (
  id: string,
  venueId: string | null,
  startDate: string,
  category: Category = "culture",
): Event =>
  ({
    id,
    name: `活动 ${id}`,
    category,
    startDate,
    endDate: null,
    venueId,
    districtId: null,
    sourceUrl: "https://example.invalid/e",
    demo: false,
  }) as Event;

describe("eventsByVenue", () => {
  it("groups events by venue, busiest first", () => {
    const venues = [venue("a", "苏州文化艺术中心"), venue("b", "周庄古镇")];
    const events = [
      event("1", "a", "2026-11-01"),
      event("2", "a", "2026-11-05"),
      event("3", "a", "2026-11-09"),
      event("4", "b", "2026-11-02"),
    ];
    const rows = eventsByVenue(events, venues);
    expect(rows.map((r) => r.venue.name)).toEqual(["苏州文化艺术中心", "周庄古镇"]);
    expect(rows.map((r) => r.count)).toEqual([3, 1]);
  });

  it("omits a venue with no events rather than showing an empty row", () => {
    const venues = [venue("a", "有活动"), venue("b", "没活动")];
    const rows = eventsByVenue([event("1", "a", "2026-11-01")], venues);
    expect(rows).toHaveLength(1);
    expect(rows[0].venue.id).toBe("a");
  });

  it("ignores events with no venue instead of inventing one", () => {
    const rows = eventsByVenue([event("1", null, "2026-11-01")], [venue("a", "甲")]);
    expect(rows).toEqual([]);
  });

  it("ignores an event whose venue id is not in the venue set", () => {
    const rows = eventsByVenue([event("1", "ghost", "2026-11-01")], [venue("a", "甲")]);
    expect(rows).toEqual([]);
  });

  it("reports the most common category, not the first one seen", () => {
    const venues = [venue("a", "混合场馆")];
    const events = [
      event("1", "a", "2026-11-01", "culture"),
      event("2", "a", "2026-11-02", "business"),
      event("3", "a", "2026-11-03", "business"),
    ];
    expect(eventsByVenue(events, venues)[0].topCategory).toBe("business");
  });

  it("sorts a venue's own events by date and reports the earliest", () => {
    const venues = [venue("a", "甲")];
    const events = [
      event("late", "a", "2026-12-01"),
      event("early", "a", "2026-11-01"),
    ];
    const row = eventsByVenue(events, venues)[0];
    expect(row.events.map((e) => e.id)).toEqual(["early", "late"]);
    expect(row.firstDate).toBe("2026-11-01");
  });

  it("puts an undated event last inside its venue rather than first", () => {
    const venues = [venue("a", "甲")];
    const events = [
      event("none", "a", "" as unknown as string),
      event("dated", "a", "2026-11-01"),
    ];
    const row = eventsByVenue(events, venues)[0];
    expect(row.events[0].id).toBe("dated");
    expect(row.firstDate).toBe("2026-11-01");
  });

  it("reports whether the venue can be mapped, separately from its event count", () => {
    const venues = [venue("a", "有坐标", true), venue("b", "缺坐标", false)];
    const events = [event("1", "a", "2026-11-01"), event("2", "b", "2026-11-01")];
    const rows = eventsByVenue(events, venues);
    const byName = Object.fromEntries(rows.map((r) => [r.venue.name, r]));
    expect(byName["有坐标"].hasCoordinates).toBe(true);
    expect(byName["缺坐标"].hasCoordinates).toBe(false);
    // A venue with coordinates and one without carry the same kind of count: the flag is
    // about the geography, not about how well evidenced the events are.
    expect(byName["有坐标"].count).toBe(byName["缺坐标"].count);
  });

  it("breaks a count tie by name so the order is stable between renders", () => {
    const venues = [venue("b", "乙场馆"), venue("a", "甲场馆")];
    const events = [event("1", "a", "2026-11-01"), event("2", "b", "2026-11-01")];
    const first = eventsByVenue(events, venues).map((r) => r.venue.name);
    const second = eventsByVenue([...events].reverse(), venues).map((r) => r.venue.name);
    expect(first).toEqual(second);
    expect(first).toEqual(["甲场馆", "乙场馆"]);
  });

  it("uses the same hotspot threshold the rest of the workspace uses", () => {
    const venues = [venue("a", "甲")];
    const events = Array.from({ length: HOTSPOT_MIN }, (_, i) =>
      event(String(i), "a", "2026-11-01"),
    );
    expect(eventsByVenue(events, venues)[0].count).toBe(HOTSPOT_MIN);
  });

  it("returns nothing for no events rather than throwing", () => {
    expect(eventsByVenue([], [venue("a", "甲")])).toEqual([]);
  });
});
