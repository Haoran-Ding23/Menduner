import type { Category, Dataset, Event, Hotel } from "../types";
import {
  dates,
  distanceKm,
  effectiveStatus,
  eventCoordinates,
  safeUrl,
  verifiedCoords,
  overlaps,
  monthRange,
  categories,
} from "../utils/data";

export type ImpactLevel = "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
export interface DemandAssessment {
  level: ImpactLevel;
  score: number | null;
  basis: "DEMO" | "RULE_BASED" | "INSUFFICIENT";
  reasons: string[];
  nearbyHotels: { hotel: Hotel; distance: number }[];
  radiusKm: number;
  nearestDistance: number | null;
}
export const impactColors = {
  HIGH: "red",
  MEDIUM: "gold",
  LOW: "blue",
  UNKNOWN: "default",
};
export const categoryWeights: Record<Category, number> = {
  business: 45,
  culture: 30,
  education: 30,
  sports: 25,
  folk: 20,
  government: 15,
  others: 10,
};
export function verifiedField(event: Event, data: Dataset, field: keyof Event) {
  const evidence = data.evidence.filter(
    (e) => e.entityId === event.id && e.field === field,
  );
  // An unresolved competing value suppresses assessment, even alongside a verified source.
  return (
    !evidence.some((e) =>
      ["Conflicting", "Needs Review"].includes(effectiveStatus(e)),
    ) &&
    evidence.some(
      (e) => effectiveStatus(e) === "Verified" && e.value === event[field],
    )
  );
}
export function nearbyHotels(event: Event, data: Dataset, radiusKm = 10) {
  const coordinate = eventCoordinates(event, data);
  if (!coordinate) return [];
  return data.hotels
    .flatMap((hotel) => {
      if (!verifiedCoords(hotel.coordinates)) return [];
      const distance = distanceKm(coordinate, hotel.coordinates);
      return distance !== null && distance <= radiusKm
        ? [{ hotel, distance }]
        : [];
    })
    .sort((a, b) => a.distance - b.distance);
}
/** A transparent review-priority heuristic, NEVER a forecast or likelihood of demand. */
export function assessDemand(
  event: Event,
  data: Dataset,
  radiusKm = 10,
): DemandAssessment {
  const hotels = nearbyHotels(event, data, radiusKm);
  const result: DemandAssessment = {
    level: "UNKNOWN",
    score: null,
    basis: "INSUFFICIENT",
    reasons: [],
    nearbyHotels: hotels,
    radiusKm,
    nearestDistance: hotels[0]?.distance ?? null,
  };
  const interval = dates(event);
  if (!interval) {
    result.reasons.push("日期缺失或范围无效，无法判断复核时间。");
    return result;
  }
  if (!eventCoordinates(event, data)) {
    result.reasons.push("活动场馆关系或坐标未核验，无法判断空间关联。");
    return result;
  }
  if (
    !event.demo &&
    (!verifiedField(event, data, "startDate") ||
      !verifiedField(event, data, "category") ||
      (event.endDate !== null && !verifiedField(event, data, "endDate")))
  ) {
    result.reasons.push("真实活动日期或类别缺少一致的字段证据，暂不分级。");
    return result;
  }
  const duration =
    Math.floor((Date.parse(interval[1]) - Date.parse(interval[0])) / 86400000) +
    1;
  const categoryScore = categoryWeights[event.category],
    durationScore = duration >= 2 ? 15 : 0,
    proximityScore = hotels.length ? 15 : 0;
  const score = categoryScore + durationScore + proximityScore;
  return {
    ...result,
    score,
    level: score >= 70 ? "HIGH" : score >= 40 ? "MEDIUM" : "LOW",
    basis: event.demo ? "DEMO" : "RULE_BASED",
    reasons: [
      `活动类别：${categories[event.category].label}${event.category === "business" ? "，与商务活动场景相关" : ""}`,
      event.endDate === null
        ? "结束日期未知，持续时间待核验"
        : `持续 ${duration} 天${duration > 1 ? "，跨多个日历日" : ""}`,
      `${radiusKm} km 内有 ${hotels.length} 家已配置且坐标核验的酒店，范围限于当前样本`,
      "场馆位置有可追溯坐标来源；场馆规模与行业重要性尚无已核验资料",
    ],
  };
}
export function shiftDate(date: string, delta: number) {
  return new Date(Date.parse(date + "T00:00:00Z") + delta * 86400000)
    .toISOString()
    .slice(0, 10);
}
export function businessToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  return ["year", "month", "day"]
    .map((type) => parts.find((p) => p.type === type)!.value)
    .join("-");
}
export function evidenceSummary(event: Event, data: Dataset) {
  const eventEvidence = data.evidence.filter((e) => e.entityId === event.id),
    venueEvidence = data.evidence.filter((e) => e.entityId === event.venueId);
  const urls = (items: typeof eventEvidence) => [
    ...new Set(
      items
        .filter((e) => effectiveStatus(e) === "Verified")
        .map((e) => safeUrl(e.sourceUrl))
        .filter((u): u is string => !!u),
    ),
  ];
  return {
    eventUrls: urls(eventEvidence),
    venueUrls: urls(venueEvidence),
    updatedAt:
      [...eventEvidence, ...venueEvidence]
        .map((e) => e.updatedAt)
        .filter((x) => !isNaN(Date.parse(x)))
        .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null,
  };
}
export interface ImportantPeriod {
  start: string;
  end: string;
  reasons: string[];
  eventIds: string[];
  demo: boolean;
}
/** Observed calendar activity only. Reasons apply to every day in each period. */
export function importantEventPeriods(
  events: Event[],
  year: number,
  month: number,
): ImportantPeriod[] {
  const [start, end] = monthRange(year, month);
  const periods: ImportantPeriod[] = [];
  for (let date = start; date <= end; date = shiftDate(date, 1)) {
    const active = events.filter((e) => overlaps(e, date, date));
    const reasons: string[] = [];
    if (active.length >= 2) reasons.push("多个活动重叠");
    if (active.filter((e) => e.category === "business").length >= 2)
      reasons.push("商务活动集中");
    if (
      active.some(
        (e) =>
          e.endDate &&
          dates(e) &&
          Date.parse(e.endDate) - Date.parse(e.startDate!) >= 2 * 86400000,
      )
    )
      reasons.push("包含持续三天及以上的活动");
    if (!reasons.length) continue;
    const previous = periods.at(-1);
    if (
      previous &&
      shiftDate(previous.end, 1) === date &&
      previous.reasons.join() === reasons.join()
    ) {
      previous.end = date;
      previous.eventIds = [
        ...new Set([...previous.eventIds, ...active.map((e) => e.id)]),
      ];
      previous.demo ||= active.some((e) => e.demo);
    } else
      periods.push({
        start: date,
        end: date,
        reasons,
        eventIds: active.map((e) => e.id),
        demo: active.some((e) => e.demo),
      });
  }
  return periods;
}
export function upcomingHighEvents(
  events: Event[],
  data: Dataset,
  today = businessToday(),
) {
  // Exactly 30 calendar dates, including today; ongoing events are included.
  const end = shiftDate(today, 29);
  return events
    .filter(
      (e) => overlaps(e, today, end) && assessDemand(e, data).level === "HIGH",
    )
    .sort((a, b) => (a.startDate ?? "").localeCompare(b.startDate ?? ""));
}

export function districtMetrics(events: Event[], data: Dataset) {
  return data.districts.map((district) => {
    const records = events.filter((e) => e.districtId === district.id);
    const venues = data.venues.filter((v) => v.districtId === district.id);
    const hotels = data.hotels.filter((h) => h.districtId === district.id);
    const locatedEvents = records.filter((e) =>
      venues.some((v) => v.id === e.venueId),
    );
    const busiest = venues
      .map((v) => ({
        name: v.name,
        count: locatedEvents.filter((e) => e.venueId === v.id).length,
      }))
      .sort((a, b) => b.count - a.count)[0];
    return {
      id: district.id,
      name: district.name,
      events: records.length,
      categories:
        Object.entries(categories)
          .filter(([key]) => records.some((e) => e.category === key))
          .map(
            ([key, value]) =>
              `${value.label} ${records.filter((e) => e.category === key).length}`,
          )
          .join(" / ") || "暂无活动",
      venues: venues.length,
      concentration: busiest?.count
        ? `${busiest.name} · ${busiest.count}/${locatedEvents.length} 条已关联场馆活动`
        : "无可用活动场馆关系",
      hotels: hotels.length,
      configuredHotels: hotels.filter((h) => verifiedCoords(h.coordinates))
        .length,
      demo:
        district.demo ||
        records.some((e) => e.demo) ||
        venues.some((v) => v.districtDemo) ||
        hotels.some((h) => h.districtDemo),
    };
  });
}
