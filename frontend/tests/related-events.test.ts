import { describe, expect, it } from "vitest";
import { relatedEvents, RELATED_LIMIT } from "../src/utils/data";
import type { Dataset, Event, Venue } from "../src/types";

/**
 * Related events in the knowledge graph.
 *
 * The graph used to show one event and its venue, never what else is on. The relation that
 * the data actually supports is the shared venue: measured over the 345 live events, same-venue
 * pairs are 248 across 30 venues, same-district pairs are 506 but only 5 events carry a district
 * at all, and date-overlap pairs are 14,895 — a number that relates everything to everything and
 * therefore relates nothing.
 */
const venue = (id: string, name: string): Venue => ({
  id,
  name,
  address: null,
  districtId: null,
  coordinates: null,
  districtDemo: false,
});

const event = (
  id: string,
  venueId: string | null,
  startDate: string,
  endDate: string | null = null,
): Event =>
  ({
    id,
    name: `活动 ${id}`,
    category: "culture",
    startDate,
    endDate,
    venueId,
    districtId: null,
    sourceUrl: "https://example.invalid/e",
    demo: false,
  }) as Event;

const dataset = (events: Event[], venues: Venue[]): Dataset =>
  ({
    events,
    venues,
    hotels: [],
    districts: [],
    evidence: [],
  }) as unknown as Dataset;

const V = [venue("v1", "苏州保利大剧院"), venue("v2", "独墅湖影剧院")];

describe("relatedEvents", () => {
  it("relates events that share a venue, and only those", () => {
    const events = [
      event("a", "v1", "2026-11-01"),
      event("b", "v1", "2026-11-20"),
      event("c", "v2", "2026-11-05"),
    ];
    const found = relatedEvents(events[0], dataset(events, V));
    expect(found.map((r) => r.event.id)).toEqual(["b"]);
    expect(found[0].kind).toBe("SAME_VENUE");
    expect(found[0].venueName).toBe("苏州保利大剧院");
  });

  it("ranks an overlapping event above a merely co-located one", () => {
    const events = [
      event("a", "v1", "2026-11-10", "2026-11-12"),
      event("later", "v1", "2026-12-01"),
      event("overlap", "v1", "2026-11-11", "2026-11-14"),
    ];
    const found = relatedEvents(events[0], dataset(events, V));
    expect(found.map((r) => r.event.id)).toEqual(["overlap", "later"]);
    expect(found[0].kind).toBe("SAME_VENUE_OVERLAPPING");
    expect(found[0].overlapDays).toBe(2); // 11th and 12th
    expect(found[1].kind).toBe("SAME_VENUE");
    expect(found[1].overlapDays).toBe(0);
  });

  it("counts a shared single day as an overlap", () => {
    const events = [
      event("a", "v1", "2026-11-10"),
      event("b", "v1", "2026-11-10"),
    ];
    const found = relatedEvents(events[0], dataset(events, V));
    expect(found[0].kind).toBe("SAME_VENUE_OVERLAPPING");
    expect(found[0].overlapDays).toBe(1);
  });

  it("treats touching ranges as overlapping", () => {
    const events = [
      event("a", "v1", "2026-11-01", "2026-11-10"),
      event("b", "v1", "2026-11-10", "2026-11-20"),
    ];
    expect(relatedEvents(events[0], dataset(events, V))[0].overlapDays).toBe(1);
  });

  it("returns nothing for an event with no venue rather than guessing one", () => {
    const events = [event("a", null, "2026-11-01"), event("b", "v1", "2026-11-01")];
    expect(relatedEvents(events[0], dataset(events, V))).toEqual([]);
  });

  it("returns nothing for an undated event rather than relating it to everything", () => {
    const events = [
      event("a", "v1", "" as unknown as string),
      event("b", "v1", "2026-11-01"),
    ];
    expect(relatedEvents(events[0], dataset(events, V))).toEqual([]);
  });

  it("caps the neighbourhood, because one venue programmes a hundred events", () => {
    const events = [event("a", "v1", "2026-11-01")];
    for (let i = 0; i < 40; i += 1) {
      events.push(event(`e${i}`, "v1", `2026-12-${String((i % 28) + 1).padStart(2, "0")}`));
    }
    const found = relatedEvents(events[0], dataset(events, V));
    expect(found).toHaveLength(RELATED_LIMIT);
    // The cap must not be filled arbitrarily: the order has to be deterministic.
    const again = relatedEvents(events[0], dataset(events, V));
    expect(again.map((r) => r.event.id)).toEqual(found.map((r) => r.event.id));
  });

  it("never relates an event to itself", () => {
    const events = [event("a", "v1", "2026-11-01"), event("b", "v1", "2026-11-01")];
    const found = relatedEvents(events[0], dataset(events, V));
    expect(found.some((r) => r.event.id === "a")).toBe(false);
  });

  it("returns nothing when the venue programmes only this one event", () => {
    const events = [event("a", "v1", "2026-11-01"), event("b", "v2", "2026-11-01")];
    expect(relatedEvents(events[0], dataset(events, V))).toEqual([]);
  });
});
