import type {
  Dataset,
  Event,
  Evidence,
  Category,
  Place,
  Status,
  Coordinates,
  District,
  HotelStar,
} from "../types";
import { categories, validDate, safeUrl, effectiveStatus } from "../utils/data";
const text = (v: unknown): string | null =>
  typeof v === "string" && v.trim() ? v.trim() : null;
const status = (v: unknown): Status =>
  ["Verified", "Unverified", "Missing", "Conflicting", "Needs Review"].includes(
    String(v),
  )
    ? (v as Status)
    : "Unverified";
const first = (r: Record<string, unknown>, ...keys: string[]) =>
  keys.map((k) => r[k]).find((v) => v !== undefined && v !== null);
export function normalizeEvent(
  raw: Record<string, unknown>,
  index: number,
): Event {
  const start = first(raw, "startDate", "start_date", "Start Date", "开始日期");
  const end = first(raw, "endDate", "end_date", "End Date", "结束日期");
  const cat = String(
    first(raw, "category", "event_type", "Event Type", "活动类型") ?? "others",
  );
  const aliases: Record<string, Category> = {
    "Business/Economic": "business",
    "Cultural/Entertainment": "culture",
    "Education/Academic": "education",
    "Government/Public Administration": "government",
    Sports: "sports",
    "Religious/Folk Customs": "folk",
    Others: "others",
  };
  const attendance = first(raw, "attendance", "Attendance", "参与人数");
  return {
    id: text(first(raw, "id", "event_id", "Event ID")) ?? `import-${index + 1}`,
    // 去重身份：后端在 /api/dataset 里给出 canonicalId（同一活动的多条来源记录指向同一条规范
    // 记录）。这里必须原样带过来 —— 少了这一个字段，前面所有按身份统计的逻辑都会退化成
    // 「按记录数统计」，同一场活动就会在两个地方出现两次。
    canonicalId:
      text(first(raw, "canonicalId", "canonical_id")) ?? undefined,
    name:
      text(first(raw, "name", "event_name", "Event Name", "活动名称")) ??
      "未命名活动",
    category:
      cat in categories ? (cat as Category) : (aliases[cat] ?? "others"),
    startDate: validDate(start) ? start : null,
    endDate: validDate(end) ? end : null,
    venueId: text(first(raw, "venueId", "venue_id")),
    // The API snapshot names this column `district`; the import path and this type use
    // `districtId`. Accepting both is what lets the region navigation filter by 太仓 at all.
    districtId: text(first(raw, "districtId", "district_id", "district")),
    organizer: text(first(raw, "organizer", "Organizer", "主办方")),
    attendance:
      typeof attendance === "number" &&
      Number.isFinite(attendance) &&
      attendance >= 0
        ? attendance
        : null,
    sponsor: text(first(raw, "sponsor", "Sponsor")),
    demo: raw.demo === true,
    raw,
  };
}
const TIERS = new Set(["high", "mid", "comfort"]);

/** Portfolio tier, accepted only when the source stated a grade we recognise. */
function tier(value: unknown): "high" | "mid" | "comfort" | undefined {
  const raw = text(value);
  return raw && TIERS.has(raw) ? (raw as "high" | "mid" | "comfort") : undefined;
}

function coordinate(x: unknown): Coordinates | null {
  if (!x || typeof x !== "object") return null;
  const c = x as Record<string, unknown>;
  // No coercion, no coordinate-system guessing. Unsupported systems stay off map.
  if (
    c.system !== "GCJ-02" ||
    typeof c.lng !== "number" ||
    typeof c.lat !== "number" ||
    !Number.isFinite(c.lng) ||
    !Number.isFinite(c.lat) ||
    Math.abs(c.lng) > 180 ||
    Math.abs(c.lat) > 90
  )
    return null;
  return {
    lng: c.lng,
    lat: c.lat,
    system: "GCJ-02",
    status:
      status(c.status) === "Verified" && !safeUrl(c.sourceUrl)
        ? "Needs Review"
        : status(c.status),
    sourceUrl: safeUrl(c.sourceUrl),
  };
}
export function normalizeDataset(input: unknown): Dataset {
  const r = Array.isArray(input) ? { events: input } : input;
  if (!r || typeof r !== "object" || !Array.isArray((r as Dataset).events))
    throw new Error("JSON 必须是活动数组或包含 events 的数据集。");
  const data = r as Record<string, unknown>;
  const rows = data.events as unknown[];
  if (rows.some((x) => !x || typeof x !== "object" || Array.isArray(x)))
    throw new Error("活动记录必须是对象。");
  const events = rows.map((x, i) =>
    normalizeEvent(x as Record<string, unknown>, i),
  );
  const array = (key: string): Record<string, unknown>[] => {
    const v = data[key];
    if (v === undefined) return [];
    if (
      !Array.isArray(v) ||
      v.some((x) => !x || typeof x !== "object" || Array.isArray(x))
    )
      throw new Error(`${key} 必须是对象数组`);
    return v;
  };
  const venues = array("venues").map((v) => ({
    id: text(v.id) ?? "",
    canonicalId: text(v.canonicalId) ?? undefined,
    name: text(v.name) ?? "未命名场馆",
    address: text(v.address),
    districtId: text(v.districtId),
    districtDemo: v.districtDemo !== false,
    coordinates: coordinate(v.coordinates),
  }));
  const STAR_STATUSES = new Set(["Verified", "Unstated"]);

/** Star grade as recorded by the backend; anything malformed is dropped rather than shown. */
function starRecord(value: unknown): HotelStar | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  const label = text(raw.label);
  const status = text(raw.status);
  if (!label || !status || !STAR_STATUSES.has(status)) return undefined;
  return {
    level: typeof raw.level === "number" ? raw.level : null,
    label,
    claimedStar: raw.claimedStar === true,
    status: status as HotelStar["status"],
    category: text(raw.category),
    source: text(raw.source) ?? "高德分类标注",
    sourceUrl: text(raw.sourceUrl),
    evidence: text(raw.evidence),
    rule: text(raw.rule) ?? undefined,
  };
}

const hotels = array("hotels").map((v) => ({
    id: text(v.id) ?? "",
    name: text(v.name) ?? "未命名酒店",
    address: text(v.address),
    districtId: text(v.districtId),
    districtDemo: v.districtDemo !== false,
    coordinates: coordinate(v.coordinates),
    tier: tier(v.tier),
    tierLabel: text(v.tierLabel),
    tierSource: text(v.tierSource),
    tierEvidence: text(v.tierEvidence),
    star: starRecord(v.star),
  }));
  const districts = array("districts").map((d) => {
    // Administrative divisions carry a kind (市辖区 / 代管县级市); older rows carry a
    // business-area kind from an earlier geocoding model. Dropping the field made every region
    // look identical, so the map could not offer 太仓 and 姑苏区 as places to go to.
    const rawKind = text(d.kind);
    const kind =
      rawKind === "city" || rawKind === "district" || rawKind === "county_city" ||
      rawKind === "business_area" || rawKind === "subdistrict"
        ? (rawKind as District["kind"])
        : undefined;
    return {
      id: text(d.id) ?? "",
      name: text(d.name) ?? "未命名商圈",
      demo: d.demo !== false,
      description: text(d.description) ?? "归属需独立核验",
      kind,
      parentId: text(d.parentId),
      level: typeof d.level === "number" ? d.level : undefined,
    };
  });
  // A place is only a place when the source said which category it belongs to; an unknown kind
  // is dropped rather than drawn as a vague dot on the graph.
  const places = array("places")
    .map((p) => {
      const kind = text(p.kind);
      if (kind !== "restaurant" && kind !== "transport") return null;
      return {
        id: text(p.id) ?? "",
        kind: kind as Place["kind"],
        subtype: text(p.subtype) ?? "",
        name: text(p.name) ?? "未命名地点",
        address: text(p.address),
        city: text(p.city),
        district: text(p.district),
        coordinates: coordinate(p.coordinates),
        declaredType: text(p.declaredType),
        sampledNearVenueId: text(p.sampledNearVenueId),
        sampledRadiusM:
          typeof p.sampledRadiusM === "number" ? p.sampledRadiusM : null,
        distanceToVenueKm:
          typeof p.distanceToVenueKm === "number" ? p.distanceToVenueKm : null,
      };
    })
    .filter((p): p is Place => p !== null);
  const stamp =
    typeof data.updatedAt === "string" && !isNaN(Date.parse(data.updatedAt))
      ? data.updatedAt
      : new Date().toISOString();
  const evidence: Evidence[] = array("evidence").map((e, i) => ({
    id: text(e.id) ?? `evidence-${i}`,
    entityId: text(e.entityId) ?? "",
    field: text(e.field) ?? "unknown",
    value: e.value ?? null,
    status: status(e.status),
    method: text(e.method) ?? "unverified_internal_reference",
    sourceName: text(e.sourceName),
    sourceUrl: safeUrl(e.sourceUrl),
    updatedAt: text(e.updatedAt) ?? stamp,
    note: text(e.note) ?? undefined,
    sourceRole: ["official_organizer", "government", "venue", "other"].includes(
      String(e.sourceRole),
    )
      ? (e.sourceRole as Evidence["sourceRole"])
      : undefined,
    confidence:
      typeof e.confidence === "number" &&
      Number.isFinite(e.confidence) &&
      e.confidence >= 0 &&
      e.confidence <= 1
        ? e.confidence
        : undefined,
    confidenceMethod: text(e.confidenceMethod) ?? undefined,
    origin: text(e.origin) ?? undefined,
    decidedBy: text(e.decidedBy) ?? undefined,
    decidedReason: text(e.decidedReason) ?? undefined,
    decidedAt: text(e.decidedAt) ?? undefined,
  }));
  evidence.forEach((e) => (e.status = effectiveStatus(e)));
  for (const [label, list] of Object.entries({
    events,
    venues,
    hotels,
    districts,
    places,
    evidence,
  })) {
    const ids = list.map((x) => x.id);
    if (ids.some((x) => !x) || new Set(ids).size !== ids.length)
      throw new Error(`${label} 的 ID 缺失或重复。`);
  }
  for (const event of events)
    for (const field of [
      "name",
      "category",
      "startDate",
      "endDate",
      "venueId",
      "districtId",
      "organizer",
      "attendance",
      "sponsor",
    ] as const) {
      if (!evidence.some((e) => e.entityId === event.id && e.field === field))
        evidence.push({
          id: `auto:${event.id}:${field}`,
          entityId: event.id,
          field,
          value: event[field],
          status: event[field] === null ? "Missing" : "Unverified",
          method: "unverified_internal_reference",
          sourceName: null,
          sourceUrl: null,
          updatedAt: stamp,
          note: "导入值尚未独立核验。",
        });
    }
  return {
    events,
    venues,
    hotels,
    districts,
    places,
    evidence,
    updatedAt: stamp,
  };
}
