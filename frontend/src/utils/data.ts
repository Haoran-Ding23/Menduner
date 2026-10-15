import type {
  Category,
  Coordinates,
  Event,
  Evidence,
  Filters,
  Status,
  Venue,
} from "../types";

/**
 * Clustered demand by VENUE, not by business district.
 *
 * A hotel reacts to "苏州保利大剧院 has 8 events this month", not to "吴中区 has 92". A venue is
 * also a fact in the data, whereas a business district is an inference from reverse geocoding.
 * Venues holding at least HOTSPOT_MIN events are flagged so the map can show where the city is
 * heating up, and each row keeps its per-category split so a cluster's colour is explainable.
 */
export const HOTSPOT_MIN = 3;

export function venueHotspots(
  events: Event[],
  venues: Venue[],
): {
  venue: Venue;
  events: Event[];
  count: number;
  isHotspot: boolean;
  topCategory: Category | null;
}[] {
  const byVenue = new Map<string, Event[]>();
  for (const event of events) {
    const id = event.venueId;
    if (!id) continue;
    const list = byVenue.get(id);
    if (list) list.push(event);
    else byVenue.set(id, [event]);
  }
  const lookup = new Map(venues.map((v) => [v.id, v]));
  const rows = [];
  for (const [venueId, list] of byVenue) {
    const venue = lookup.get(venueId);
    if (!venue) continue;
    const counts = new Map<Category, number>();
    for (const event of list) {
      counts.set(event.category, (counts.get(event.category) ?? 0) + 1);
    }
    const topCategory =
      [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
    rows.push({
      venue,
      events: list,
      count: list.length,
      isHotspot: list.length >= HOTSPOT_MIN,
      topCategory,
    });
  }
  // Most active first, then by name so the order is stable between renders.
  return rows.sort(
    (a, b) => b.count - a.count || a.venue.name.localeCompare(b.venue.name),
  );
}

// Every kind gets its own colour so a glance at the map separates the demand types a hotel
// reacts to. Chosen for contrast at marker size rather than for any palette convention:
//   blue    trade fairs and exhibitions — the Expo volume driver, most neutral strong colour
//   red     concerts and stage shows — the loudest marker, and the loudest demand
//   purple  sport
//   amber   culture-and-tourism and folk festivals
//   teal    government and public administration, to read as official
//   green   education and academia
//   grey    everything else, so it does not compete for attention
export const categories: Record<
  Category,
  {
    label: string;
    color: string;
  }
> = {
  government: { label: "政府 / 公共管理", color: "#13aaba" },
  business: { label: "商业 / 经济", color: "#1677ff" },
  culture: { label: "文化 / 娱乐", color: "#e5484d" },
  education: { label: "教育 / 学术", color: "#2fa84f" },
  sports: { label: "体育", color: "#8b5cf6" },
  folk: { label: "宗教 / 民俗", color: "#e8a317" },
  others: { label: "其他", color: "#8794a8" },
};
export const statusColors: Record<Status, string> = {
  Verified: "green",
  Unverified: "orange",
  Missing: "default",
  Conflicting: "red",
  "Needs Review": "gold",
};export const statusLabels: Record<Status, string> = {
  Verified: "已核验",
  Unverified: "未核验",
  Missing: "缺失",
  Conflicting: "冲突",
  "Needs Review": "待复核",
};
export function safeUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const u = new URL(value);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
export function validDate(x: unknown): x is string {
  if (typeof x !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(x)) return false;
  const d = new Date(x + "T00:00:00Z");
  return !isNaN(d.getTime()) && d.toISOString().slice(0, 10) === x;
}
export function dates(e: Event): [string, string] | null {
  if (!validDate(e.startDate)) return null;
  const end = validDate(e.endDate) ? e.endDate : e.startDate;
  return end < e.startDate ? null : [e.startDate, end];
}
export function overlaps(e: Event, start: string, end: string) {
  const d = dates(e);
  return !!d && d[0] <= end && d[1] >= start;
}
export function monthRange(year: number, month: number): [string, string] {
  return [
    `${year}-${String(month).padStart(2, "0")}-01`,
    new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10),
  ];
}
export function filterEvents(events: Event[], f: Filters) {
  const [start, end] = monthRange(f.year, f.month);
  return events.filter(
    (e) =>
      (f.includeDemo || !e.demo) &&
      (!f.district || e.districtId === f.district) &&
      (!f.category || e.category === f.category) &&
      overlaps(e, start, end),
  );
}
export function verifiedCoords(
  c: Coordinates | null | undefined,
): c is Coordinates {
  return (
    !!c &&
    c.status === "Verified" &&
    c.system === "GCJ-02" &&
    !!safeUrl(c.sourceUrl) &&
    Number.isFinite(c.lng) &&
    Number.isFinite(c.lat) &&
    Math.abs(c.lng) <= 180 &&
    Math.abs(c.lat) <= 90
  );
}
export function distanceKm(a: Coordinates, b: Coordinates): number | null {
  if (!verifiedCoords(a) || !verifiedCoords(b)) return null;
  const rad = (x: number) => (x * Math.PI) / 180;
  const dl = rad(b.lat - a.lat),
    dn = rad(b.lng - a.lng);
  const h =
    Math.sin(dl / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dn / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}
export function effectiveStatus(e: Evidence): Status {
  if (e.value === null || e.value === undefined || e.value === "")
    return "Missing";
  if (e.status === "Verified" && !safeUrl(e.sourceUrl)) return "Needs Review";
  return e.status;
}
/**
 * Fields a human can actually verify by reading the source.
 *
 * A reference id, a classification rule's output and the response URL are derived, not
 * claimed by the page, so no reviewer can confirm them. Counting them towards an event's
 * status made an event impossible to finish: it could never reach 已核验 however carefully
 * every factual field was checked. They are still displayed with their own status, so the
 * 已核验 badge is scoped to what it can honestly mean.
 */
export const DERIVED_FIELDS = new Set([
  "venueId",
  "districtId",
  "category",
  "sourceUrl",
  "city",
]);

export function eventStatus(items: Evidence[]): Status {
  const verifiable = items.filter((e) => !DERIVED_FIELDS.has(e.field));
  const s = (verifiable.length ? verifiable : items).map(effectiveStatus);
  if (s.includes("Conflicting")) return "Conflicting";
  if (s.includes("Needs Review")) return "Needs Review";
  if (s.includes("Unverified")) return "Unverified";
  if (s.includes("Missing") || !s.length) return "Missing";
  return "Verified";
}
export function valueText(x: unknown): string {
  return x === null || x === undefined || x === ""
    ? "—"
    : typeof x === "object"
      ? JSON.stringify(x)
      : String(x);
}
// A verified venue position alone does not verify that a real event takes place there.
export function eventCoordinates(
  event: Event,
  data: import("../types").Dataset,
): Coordinates | null {
  const venue = data.venues.find((v) => v.id === event.venueId);
  if (!verifiedCoords(venue?.coordinates)) return null;
  if (
    !event.demo &&
    (data.evidence.some(
      (e) =>
        e.entityId === event.id &&
        e.field === "venueId" &&
        ["Conflicting", "Needs Review"].includes(effectiveStatus(e)),
    ) ||
      !data.evidence.some(
        (e) =>
          e.entityId === event.id &&
          e.field === "venueId" &&
          e.value === event.venueId &&
          effectiveStatus(e) === "Verified",
      ))
  )
    return null;
  return venue.coordinates;
}

/** Every venue that has at least one event in the given list, busiest first.
 *
 * This is the venue-first view of the same data the map shows spatially. The interviewed
 * operations lead at a hotel in 太仓 described the problem as "官方渠道比较多，信息比较散，
 * 需要一年中的活动归纳好" and reasoned entirely in venues ("场地", "场地大小"), so grouping
 * by venue is the aggregation that matches how the demand side already thinks.
 *
 * Venues with no events in the current selection are omitted rather than shown as empty rows:
 * a list of 93 venues where 40 are blank would defeat the purpose of aggregating.
 */
export function eventsByVenue(
  events: Event[],
  venues: Venue[],
): {
  venue: Venue;
  events: Event[];
  count: number;
  topCategory: Category | null;
  firstDate: string | null;
  hasCoordinates: boolean;
}[] {
  const byVenue = new Map<string, Event[]>();
  for (const event of events) {
    const id = event.venueId;
    if (!id) continue;
    const list = byVenue.get(id);
    if (list) list.push(event);
    else byVenue.set(id, [event]);
  }
  const lookup = new Map(venues.map((v) => [v.id, v]));
  const rows = [];
  for (const [venueId, list] of byVenue) {
    const venue = lookup.get(venueId);
    if (!venue) continue;
    const counts = new Map<Category, number>();
    for (const event of list) {
      counts.set(event.category, (counts.get(event.category) ?? 0) + 1);
    }
    // Dated events in date order, undated ones last. A record with no date cannot be placed
    // in a programme, so it belongs at the end rather than in front of the dated ones - which
    // is where an empty string sorts by default, and where the first version of this put it.
    list.sort((a, b) =>
      (dates(a)?.[0] ?? "9999-99-99").localeCompare(dates(b)?.[0] ?? "9999-99-99"),
    );
    rows.push({
      venue,
      events: list,
      count: list.length,
      topCategory: [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null,
      firstDate: dates(list[0])?.[0] ?? null,
      hasCoordinates: !!verifiedCoords(venue.coordinates),
    });
  }
  // Busiest first, then by name so the order is stable between renders.
  return rows.sort((a, b) => b.count - a.count || a.venue.name.localeCompare(b.venue.name));
}

/** How many related events the graph will draw around the selected one.
 *
 * Measured on the live database: 30 venues program two or more events, and the same-venue
 * relation alone accounts for 248 pairs. 苏州文化艺术中心·金鸡湖音乐厅 programs 100 events, so
 * drawing every neighbour of the busiest venue would be unreadable and useless. The cap keeps
 * the graph a neighbourhood, and the sidebar reports how many were left out.
 */
export const RELATED_LIMIT = 4;

export type RelatedKind =
  /** Same venue, and the two events overlap in time. The stronger signal: the venue is
   *  already hosting demand while this event runs. */
  | "SAME_VENUE_OVERLAPPING"
  /** Same venue, different dates. The venue is the shared fact; the dates are not. */
  | "SAME_VENUE";

export interface RelatedEvent {
  event: Event;
  kind: RelatedKind;
  /** Shared days between the two events, or 0 when they do not overlap. */
  overlapDays: number;
  /** Shared venue name, for the edge label. */
  venueName: string;
}

function dayCount(from: string, to: string): number {
  const a = Date.parse(from + "T00:00:00Z");
  const b = Date.parse(to + "T00:00:00Z");
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return 0;
  return Math.round((b - a) / 86400000) + 1;
}

/** Events that share the selected event's venue, strongest relation first.
 *
 * Only the venue relation is offered, because it is the only one the data supports as a
 * relation rather than as a coincidence. Measured over the 345 live events: same-venue
 * pairs are 248, same-district pairs are 506 but only 5 events carry a district at all, and
 * date-overlap pairs are 14,895 — a number that relates everything to everything and
 * therefore says nothing. Overlap is used only to rank events that already share a venue.
 */
export function relatedEvents(
  event: Event,
  data: import("../types").Dataset,
  limit = RELATED_LIMIT,
): RelatedEvent[] {
  if (!event.venueId) return [];
  const venue = data.venues.find((v) => v.id === event.venueId);
  const own = dates(event);
  if (!own) return [];
  const rows: RelatedEvent[] = [];
  for (const other of data.events) {
    if (other.id === event.id) continue;
    if (other.venueId !== event.venueId) continue;
    const span = dates(other);
    if (!span) continue;
    const from = span[0] > own[0] ? span[0] : own[0];
    const to = span[1] < own[1] ? span[1] : own[1];
    const overlapDays = from <= to ? dayCount(from, to) : 0;
    rows.push({
      event: other,
      kind: overlapDays ? "SAME_VENUE_OVERLAPPING" : "SAME_VENUE",
      overlapDays,
      venueName: venue?.name ?? event.venueId,
    });
  }
  rows.sort((a, b) => {
    if (a.overlapDays !== b.overlapDays) return b.overlapDays - a.overlapDays;
    const sa = dates(a.event)?.[0] ?? "";
    const sb = dates(b.event)?.[0] ?? "";
    return sa.localeCompare(sb) || a.event.name.localeCompare(b.event.name);
  });
  return rows.slice(0, limit);
}
