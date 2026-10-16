import type {
  Dataset,
  Event,
  FiredRule,
  GraphEdge,
  GraphNode,
  Place,
  Venue,
} from "../types";
import { effectiveStatus, relatedEvents } from "../utils/data";
import { nearbyHotels } from "./intelligence";

/**
 * The knowledge graph is GENERATED, not authored.
 *
 * Nothing below names an event, a venue or a place. Every node and every edge comes from a rule
 * that reads the selected event's own fields, its venue's coordinate, and the records around it —
 * so the same code draws a graph for the 345th event as for the first, and a newly crawled event
 * appears in the graph the moment it lands, with no edit here.
 *
 * Three families of rule, each labelled on the edge so a reader can tell what stands behind it:
 *
 *   SOURCED    the relation is the source record itself: the event's venue reference, the venue's
 *              district, the AMap place a restaurant or a station came from. Drawn solid.
 *   PROXIMITY  the relation is a distance computed from verified coordinates (NEAR). Drawn solid,
 *              because the coordinate is a record; the distance is arithmetic.
 *   HYPOTHESIS rule-derived, not sourced: audience segments from the event's category, duration
 *              and recorded attendance. Drawn dashed and marked 规则假设 — it asserts a segment,
 *              never evidence, and the panel lists which rule fired and why.
 */

/** Proximity reach and how many of each thing is worth drawing. */
export const PLACE_RULES = [
  {
    id: "near_restaurant",
    kind: "Restaurant" as const,
    placeKind: "restaurant" as const,
    label: "餐饮",
    reachKm: 1.5,
    limit: 5,
    detail: "场馆 1.5 km 内的高德餐饮 POI,按直线距离取最近的 5 家",
  },
] as const;

/**
 * Public transport does not share one radius: a bus stop you can see from the door and an airport
 * 25 km away are both "access", at different scales. Reach per subtype mirrors the sampling radius
 * in scripts/enrich_places.py.
 */
export const TRANSIT_REACH_KM: Record<string, number> = {
  地铁站: 2.5,
  轻轨站: 2.5,
  公交车站: 1,
  火车站: 12,
  长途汽车站: 12,
  机场: 30,
};
export const TRANSIT_LIMIT: Record<string, number> = {
  地铁站: 3,
  轻轨站: 2,
  公交车站: 3,
  火车站: 2,
  长途汽车站: 2,
  机场: 1,
};
export const TRANSIT_RULE = {
  id: "near_transit",
  kind: "Transport" as const,
  label: "交通",
  detail: "按分类型半径取最近的地铁/公交/火车站/长途站/机场,半径见 TRANSIT_REACH_KM",
};

export interface AudienceRule {
  id: string;
  segment: string;
  detail: string;
  applies: (event: Event) => boolean;
  /** What the event has to look like for this to fire, for the rule panel. */
  basis: string;
}

const spanDays = (event: Event): number => {
  if (!event.startDate) return 0;
  const start = Date.parse(`${event.startDate}T00:00:00Z`);
  const end = Date.parse(`${event.endDate ?? event.startDate}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end)) return 0;
  return Math.max(1, Math.round((end - start) / 86_400_000) + 1);
};

/**
 * Audience segments, one per event category plus two structural rules.
 *
 * The category rules are exclusive by construction (every event has exactly one category), so a
 * reader always sees the segment the event's own classification implies. The other two are
 * additive and only fire on a field that is actually present: a multi-day run is a different
 * hotel-demand shape from a single evening, and a recorded attendance figure over 5,000 is a
 * crowd rather than a claim. No rule fires on a missing value.
 */
export const AUDIENCE_RULES: AudienceRule[] = [
  {
    id: "audience_business",
    segment: "商务差旅客群",
    detail: "会展、经贸类活动的到场者以商务差旅为主",
    basis: "category = business",
    applies: (e) => e.category === "business",
  },
  {
    id: "audience_culture",
    segment: "文化消费客群",
    detail: "演出、展览类活动的到场者是本地文化消费人群",
    basis: "category = culture",
    applies: (e) => e.category === "culture",
  },
  {
    id: "audience_sports",
    segment: "体育观赛客群",
    detail: "赛事类活动以观赛人群为主,跨城到场比例高",
    basis: "category = sports",
    applies: (e) => e.category === "sports",
  },
  {
    id: "audience_education",
    segment: "教育家庭客群",
    detail: "教育类活动多为家庭或学生群体到场",
    basis: "category = education",
    applies: (e) => e.category === "education",
  },
  {
    id: "audience_folk",
    segment: "民俗节庆客群",
    detail: "民俗节庆活动的到场者以本地及周边游客为主",
    basis: "category = folk",
    applies: (e) => e.category === "folk",
  },
  {
    id: "audience_government",
    segment: "公共事务客群",
    detail: "政府及公共事务活动的到场者以公务人员为主",
    basis: "category = government",
    applies: (e) => e.category === "government",
  },
  {
    id: "audience_others",
    segment: "综合消费客群",
    detail: "类别未归类时给出综合消费客群,不细分",
    basis: "category = others(或未归类)",
    applies: () => true,
  },
  {
    id: "audience_multi_day",
    segment: "多日住宿需求",
    detail: "展期/会期跨 2 天以上,需要连续住宿,不只是当晚",
    basis: "startDate → endDate 跨度 ≥ 2 天",
    applies: (e) => spanDays(e) >= 2,
  },
  {
    id: "audience_large_scale",
    segment: "大规模聚集",
    detail: "已记录的出席人数超过 5,000,属于大规模聚集场景",
    basis: "attendance ≥ 5000",
    applies: (e) => typeof e.attendance === "number" && e.attendance >= 5000,
  },
];

/**
 * Which hotel tiers a segment is likely to look at — a hypothesis, not a finding.
 *
 * It exists because the graph must connect 客群 to something or the node floats: a demand signal
 * with no supply attached answers nothing. Drawn dashed, labelled 规则假设, and switchable off.
 */
export const TIER_HYPOTHESES: Record<string, Array<"high" | "mid" | "comfort">> = {
  商务差旅客群: ["high", "mid"],
  文化消费客群: ["mid", "comfort"],
  体育观赛客群: ["mid", "comfort"],
  教育家庭客群: ["comfort", "mid"],
  民俗节庆客群: ["comfort", "mid"],
  公共事务客群: ["high", "mid"],
  综合消费客群: ["high", "mid", "comfort"],
  多日住宿需求: ["mid", "comfort"],
  大规模聚集: ["high", "mid", "comfort"],
};
export const TIER_RULE = {
  id: "audience_hotel_tier",
  label: "客群-酒店层级假设",
  detail: "按客群给出的可能偏好层级,连接图中已有的酒店;虚线,属规则假设而非证据",
};

export interface GraphOptions {
  related?: boolean;
  places?: boolean;
  audience?: boolean;
}

export interface BuiltGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  fired: FiredRule[];
}

const segmentId = (segment: string) =>
  `audience-${Array.from(segment)
    .map((ch) => ch.codePointAt(0)?.toString(16))
    .join("")}`;

export function buildKnowledgeGraph(
  event: Event | undefined,
  dataset: Dataset,
  options: GraphOptions = {},
): BuiltGraph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const fired: FiredRule[] = [];
  if (!event) return { nodes, edges, fired };

  const add = (node: GraphNode) => {
    if (!nodes.some((n) => n.id === node.id)) nodes.push(node);
  };
  const supported = (entityId: string, field: string, value: unknown) =>
    !dataset.evidence.some(
      (e) =>
        e.entityId === entityId &&
        e.field === field &&
        ["Conflicting", "Needs Review"].includes(effectiveStatus(e)),
    ) &&
    dataset.evidence.some(
      (e) =>
        e.entityId === entityId &&
        e.field === field &&
        e.value === value &&
        effectiveStatus(e) === "Verified",
    );
  const distanceKm = (a: Venue | Place, b: Venue | Place): number | null => {
    if (!a.coordinates || !b.coordinates) return null;
    const toRad = (d: number) => (d * Math.PI) / 180;
    const dLat = toRad(b.coordinates.lat - a.coordinates.lat);
    const dLng = toRad(b.coordinates.lng - a.coordinates.lng);
    const h =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(a.coordinates.lat)) *
        Math.cos(toRad(b.coordinates.lat)) *
        Math.sin(dLng / 2) ** 2;
    return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
  };

  add({
    id: event.id,
    label: event.name,
    kind: "Event",
    demo: event.demo,
    entityId: event.id,
    rule: "event_root",
    reason: "被选中的活动本身",
  });

  const venue = dataset.venues.find((v) => v.id === event.venueId);
  const venueInGraph =
    venue && (event.demo || supported(event.id, "venueId", event.venueId));
  if (venue && venueInGraph) {
    add({
      id: venue.id,
      label: venue.name,
      kind: "Venue",
      demo: false,
      entityId: venue.id,
      sourceUrl: venue.coordinates?.sourceUrl ?? null,
      rule: "held_at",
      reason: "活动引用该场馆,且该引用已核验",
    });
    edges.push({
      id: "held-" + event.id,
      source: event.id,
      target: venue.id,
      label: "HELD_AT",
      demo: event.demo,
      rule: "held_at",
      reason: "来源给出的场馆引用",
    });

    const district = dataset.districts.find((d) => d.id === venue.districtId);
    if (
      district &&
      (venue.districtDemo || supported(venue.id, "districtId", venue.districtId))
    ) {
      add({
        id: district.id,
        label: district.name,
        kind: "District",
        demo: district.demo,
        entityId: district.id,
        rule: "located_in",
        reason: "场馆归属的商圈,来自高德反查",
      });
      edges.push({
        id: "located-" + venue.id,
        source: venue.id,
        target: district.id,
        label: "LOCATED_IN",
        demo: venue.districtDemo,
        rule: "located_in",
        reason: "场馆 → 商圈归属",
      });
      dataset.hotels
        .filter(
          (h) =>
            h.districtId === district.id &&
            (h.districtDemo || supported(h.id, "districtId", h.districtId)),
        )
        .forEach((h) => {
          add({
            id: h.id,
            label: h.name,
            kind: "Hotel",
            demo: false,
            entityId: h.id,
            sourceUrl: h.coordinates?.sourceUrl ?? null,
            rule: "located_in",
            reason: "酒店 → 商圈归属",
          });
          edges.push({
            id: "hotel-" + h.id,
            source: h.id,
            target: district.id,
            label: "LOCATED_IN",
            demo: h.districtDemo,
            rule: "located_in",
            reason: "酒店 → 商圈归属",
          });
        });
    }

    // Coordinate-derived proximity: the coordinate is a record, the distance is arithmetic.
    let nearbyCount = 0;
    nearbyHotels(event, dataset).forEach(({ hotel, distance }) => {
      add({
        id: hotel.id,
        label: hotel.name,
        kind: "Hotel",
        demo: false,
        entityId: hotel.id,
        sourceUrl: hotel.coordinates?.sourceUrl ?? null,
        rule: "near_hotel",
        reason: `与场馆直线距离 ${distance.toFixed(2)} km`,
      });
      edges.push({
        id: `near-${venue.id}-${hotel.id}`,
        source: venue.id,
        target: hotel.id,
        label: `NEAR · ${distance.toFixed(2)} km`,
        demo: false,
        rule: "near_hotel",
        reason: "由双方核验坐标计算的直线距离(10 km 内)",
      });
      nearbyCount += 1;
    });
    if (nearbyCount) {
      fired.push({
        id: "near_hotel",
        label: "周边酒店",
        detail: "场馆 10 km 内、由核验坐标计算直线距离的酒店",
        relations: nearbyCount,
        analytical: false,
      });
    }

    if (options.places && venue.coordinates) {
      // 餐饮
      for (const rule of PLACE_RULES) {
        const rows = dataset.places
          .filter((p) => p.kind === rule.placeKind && p.coordinates)
          .map((p) => ({ place: p, km: distanceKm(venue, p) }))
          .filter((r): r is { place: Place; km: number } => r.km !== null && r.km <= rule.reachKm)
          .sort((a, b) => a.km - b.km)
          .slice(0, rule.limit);
        rows.forEach(({ place, km }) => {
          add({
            id: place.id,
            label: place.name,
            kind: rule.kind,
            demo: false,
            entityId: place.id,
            sourceUrl: place.coordinates?.sourceUrl ?? null,
            rule: rule.id,
            reason: `${place.subtype} · 距场馆 ${km.toFixed(2)} km(高德 POI)`,
          });
          edges.push({
            id: `place-${venue.id}-${place.id}`,
            source: venue.id,
            target: place.id,
            label: `${rule.label} · ${km.toFixed(2)} km`,
            demo: false,
            rule: rule.id,
            reason: `${place.subtype};由双方坐标计算,采样半径 ${place.sampledRadiusM ?? "—"} m`,
          });
        });
        if (rows.length) {
          fired.push({
            id: rule.id,
            label: `周边${rule.label}`,
            detail: rule.detail,
            relations: rows.length,
            analytical: false,
          });
        }
      }
      // 交通, per subtype reach
      const bySubtype = new Map<string, Array<{ place: Place; km: number }>>();
      dataset.places
        .filter((p) => p.kind === "transport" && p.coordinates)
        .forEach((place) => {
          const km = distanceKm(venue, place);
          if (km === null) return;
          const reach = TRANSIT_REACH_KM[place.subtype];
          if (reach === undefined || km > reach) return;
          const rows = bySubtype.get(place.subtype) ?? [];
          rows.push({ place, km });
          bySubtype.set(place.subtype, rows);
        });
      let transitCount = 0;
      bySubtype.forEach((rows, subtype) => {
        rows
          .sort((a, b) => a.km - b.km)
          .slice(0, TRANSIT_LIMIT[subtype] ?? 2)
          .forEach(({ place, km }) => {
            add({
              id: place.id,
              label: place.name,
              kind: "Transport",
              demo: false,
              entityId: place.id,
              sourceUrl: place.coordinates?.sourceUrl ?? null,
              rule: TRANSIT_RULE.id,
              reason: `${subtype} · 距场馆 ${km.toFixed(2)} km(高德 POI)`,
            });
            edges.push({
              id: `place-${venue.id}-${place.id}`,
              source: venue.id,
              target: place.id,
              label: `${subtype} · ${km.toFixed(2)} km`,
              demo: false,
              rule: TRANSIT_RULE.id,
              reason: `采样半径见 enrich_places.py;${subtype} 的绘制半径 ${TRANSIT_REACH_KM[subtype]} km`,
            });
            transitCount += 1;
          });
      });
      if (transitCount) {
        fired.push({
          id: TRANSIT_RULE.id,
          label: "周边交通",
          detail: TRANSIT_RULE.detail,
          relations: transitCount,
          analytical: false,
        });
      }
    }
  }

  // Rule-derived audience segments. Additive, and only from fields the event actually carries.
  if (options.audience) {
    const segments: Array<{ rule: AudienceRule; segment: string }> = [];
    AUDIENCE_RULES.forEach((rule) => {
      if (!rule.applies(event)) return;
      if (rule.id === "audience_others" && segments.length) return;
      segments.push({ rule, segment: rule.segment });
    });
    const tiers: Array<"high" | "mid" | "comfort"> = [];
    segments.forEach(({ rule, segment }) => {
      const id = segmentId(segment);
      add({
        id,
        label: segment,
        kind: "Audience",
        analytical: true,
        demo: false,
        entityId: id,
        rule: rule.id,
        reason: `${rule.detail}(${rule.basis})`,
      });
      edges.push({
        id: `audience-${event.id}-${id}`,
        source: event.id,
        target: id,
        label: "TARGETS · 规则",
        demo: false,
        analytical: true,
        rule: rule.id,
        reason: rule.basis,
      });
      (TIER_HYPOTHESES[segment] ?? []).forEach((t) => {
        if (!tiers.includes(t)) tiers.push(t);
      });
      fired.push({
        id: rule.id,
        label: `客群 · ${segment}`,
        detail: `${rule.detail}(触发条件:{${rule.basis}})`,
        relations: 1,
        analytical: true,
      });
    });
    // The hypothesis edges only attach to hotels the graph already shows for THIS event.
    const hotelsInGraph = nodes.filter((n) => n.kind === "Hotel");
    let tierEdges = 0;
    hotelsInGraph.forEach((hotel) => {
      const row = dataset.hotels.find((h) => h.id === hotel.id);
      if (!row?.tier || !tiers.includes(row.tier)) return;
      segments.forEach(({ segment }) => {
        if (!(TIER_HYPOTHESES[segment] ?? []).includes(row.tier!)) return;
        edges.push({
          id: `tier-${segmentId(segment)}-${hotel.id}`,
          source: segmentId(segment),
          target: hotel.id,
          label: "可能偏好 · 规则假设",
          demo: false,
          analytical: true,
          rule: TIER_RULE.id,
          reason: `${segment} 的可能层级包含「${row.tierLabel ?? row.tier}」`,
        });
        tierEdges += 1;
      });
    });
    if (tierEdges) {
      fired.push({
        id: TIER_RULE.id,
        label: TIER_RULE.label,
        detail: TIER_RULE.detail,
        relations: tierEdges,
        analytical: true,
      });
    }
  }

  // Related events, drawn only on request (analytic: computed from the shared venue reference).
  if (options.related && venue && nodes.some((n) => n.id === venue.id)) {
    const related = relatedEvents(event, dataset);
    related.forEach(({ event: other, kind, overlapDays }) => {
      add({
        id: other.id,
        label: other.name,
        kind: "Event",
        demo: other.demo,
        entityId: other.id,
        rule: "related_event",
        reason:
          kind === "SAME_VENUE_OVERLAPPING"
            ? `与本次活动的展期重叠 ${overlapDays} 天`
            : "与本次活动共用同一场馆",
      });
      edges.push({
        id: `related-${event.id}-${other.id}`,
        source: event.id,
        target: other.id,
        label:
          kind === "SAME_VENUE_OVERLAPPING"
            ? `同期 · 同场馆 ${overlapDays} 天`
            : "同场馆",
        demo: false,
        analytical: true,
        rule: "related_event",
        reason: "由场馆引用计算,不是来源声明",
      });
    });
    if (related.length) {
      fired.push({
        id: "related_event",
        label: "关联活动",
        detail: "同场馆(同期优先)的其他活动,由场馆引用计算",
        relations: related.length,
        analytical: true,
      });
    }
  }

  return { nodes, edges, fired };
}
