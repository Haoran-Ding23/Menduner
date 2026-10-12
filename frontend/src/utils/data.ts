import type {
  Category,
  Coordinates,
  Event,
  Evidence,
  Filters,
  Status,
} from "../types";
export const categories: Record<
  Category,
  {
    label: string;
    color: string;
  }
> = {
  government: { label: "政府 / 公共管理", color: "#5579d6" },
  business: { label: "商业 / 经济", color: "#1677ff" },
  culture: { label: "文化 / 娱乐", color: "#a56be2" },
  education: { label: "教育 / 学术", color: "#13aaba" },
  sports: { label: "体育", color: "#31a56b" },
  folk: { label: "宗教 / 民俗", color: "#d39725" },
  others: { label: "其他", color: "#8794a8" },
};
export const statusColors: Record<Status, string> = {
  Verified: "green",
  Unverified: "orange",
  Missing: "default",
  Conflicting: "red",
  "Needs Review": "gold",
};
export const statusLabels: Record<Status, string> = {
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
export function eventStatus(items: Evidence[]): Status {
  const s = items.map(effectiveStatus);
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
