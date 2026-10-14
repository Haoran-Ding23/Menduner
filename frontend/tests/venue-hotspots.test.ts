import { describe, expect, it } from "vitest";
import { categories, venueHotspots, HOTSPOT_MIN } from "../src/utils/data";
import type { Category, Event, Venue } from "../src/types";

/**
 * Demand clustered by venue.
 *
 * The product decision under test: a hotel acts on "this theatre has 8 events", so clustering is
 * by VENUE — a fact taken from the source page — rather than by an inferred business district.
 * A venue at or above HOTSPOT_MIN is what the map marks as a hotspot.
 */
const venue = (id: string, name: string): Venue => ({
  id,
  name,
  address: null,
  districtId: null,
  coordinates: null,
  districtDemo: false,
});

const event = (id: string, venueId: string | null, category: Category): Event =>
  ({
    id,
    name: `event ${id}`,
    category,
    startDate: "2026-11-01",
    endDate: null,
    venueId,
    districtId: null,
    sourceUrl: "https://example.invalid/e",
    demo: false,
  }) as Event;

describe("venueHotspots", () => {
  it("clusters by venue and flags venues at the hotspot threshold", () => {
    const venues = [venue("a", "苏州保利大剧院"), venue("b", "小众剧场")];
    const events = [
      event("1", "a", "culture"),
      event("2", "a", "culture"),
      event("3", "a", "sports"),
      event("4", "b", "culture"),
    ];
    const rows = venueHotspots(events, venues);

    expect(rows.map((r) => r.venue.id)).toEqual(["a", "b"]);
    expect(rows[0].count).toBe(3);
    expect(rows[0].isHotspot).toBe(true);
    expect(rows[1].count).toBe(1);
    expect(rows[1].isHotspot).toBe(false);
    expect(rows[0].count >= HOTSPOT_MIN).toBe(rows[0].isHotspot);
  });

  it("reports the dominant category so a cluster's colour is explainable", () => {
    const venues = [venue("a", "剧院")];
    const events = [
      event("1", "a", "culture"),
      event("2", "a", "culture"),
      event("3", "a", "sports"),
    ];
    const [row] = venueHotspots(events, venues);
    // Depending on the rest of the record this event may also be absent, so the split is
    // computed from the events that are actually there.
    expect(row.topCategory).toBe("culture");
    expect(row.events.filter((e) => e.category === "culture")).toHaveLength(2);
  });

  it("sorts by activity, then by name so the order is stable", () => {
    const venues = [venue("a", "乙场馆"), venue("b", "甲场馆"), venue("c", "丙场馆")];
    const events = [
      event("1", "a", "culture"),
      event("2", "b", "culture"),
      event("3", "c", "culture"),
      event("4", "c", "culture"),
    ];
    const rows = venueHotspots(events, venues);
    expect(rows.map((r) => r.venue.name)).toEqual(["丙场馆", "甲场馆", "乙场馆"]);
  });

  it("ignores events without a venue and venues it does not know", () => {
    const venues = [venue("a", "剧院")];
    const events = [
      event("1", null, "culture"),
      event("2", "missing", "culture"),
      event("3", "a", "culture"),
    ];
    const rows = venueHotspots(events, venues);
    expect(rows).toHaveLength(1);
    expect(rows[0].count).toBe(1);
  });

  it("returns nothing for no events rather than throwing", () => {
    expect(venueHotspots([], [venue("a", "剧院")])).toEqual([]);
  });
});

describe("category colours", () => {
  it("gives every category a distinct colour, including a red and a purple", () => {
    const colours = Object.values(categories).map((c) => c.color.toLowerCase());
    expect(new Set(colours).size).toBe(colours.length);

    // Both were explicitly required, and they must not be the same category.
    const reds = colours.filter((c) => /^#e[0-9a-f]{5}$/.test(c));
    expect(reds.length).toBeGreaterThan(0);
    const purple = Object.entries(categories).find(([, c]) => c.color === "#8b5cf6");
    expect(purple?.[0]).toBe("sports");
    expect(categories.culture.color).toBe("#e5484d");
  });

  it("labels every category in Chinese only", () => {
    for (const [key, meta] of Object.entries(categories)) {
      expect(meta.label.length).toBeGreaterThan(0);
      // No Latin letters in a user-visible label.
      expect(meta.label).not.toMatch(/[A-Za-z]/);
      expect(key).toMatch(/^[a-z]+$/);
    }
  });
});
