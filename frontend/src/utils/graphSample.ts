import type { Dataset, Event } from "../types";

/**
 * 图谱默认样例的选择（F06）。
 *
 * 规则必须可复核，不能"凭印象挑一个好看的例子"：
 *   * 只从真实数据里选，不硬编码任何关系；
 *   * 按「关系完整度」打分：场馆（且有坐标）> 地区 > 来源数 > 证据字段数；
 *   * 同分按 id 排序，保证每次打开看到同一个样例（可复现）；
 *   * 返回选择理由，界面上可以写明"为什么是这一条"。
 *
 * 明确不做：不因为活动持续多日就推断"访客多日住宿"，那属于客流/经济推断，不是图上的事实。
 */

export interface GraphSample {
  /** 选中的活动 id；没有可用数据时为 null。 */
  eventId: string | null;
  /** 选择理由（给人看的）。 */
  reasons: string[];
  /** 评分明细，便于复核。 */
  score: { venue: number; district: number; sources: number; evidence: number; total: number };
  /** 候选数量，说明是从多少条里选的。 */
  candidates: number;
}

const scoreOf = (event: Event, dataset: Dataset) => {
  const venue = dataset.venues.find((v) => v.id === event.venueId);
  const hasVenue = venue ? 1 : 0;
  const hasCoords = venue?.coordinates?.lng != null ? 1 : 0;
  const hasDistrict = event.districtId ? 1 : 0;
  const sources = dataset.events.filter(
    (other) => (other.canonicalId || other.id) === (event.canonicalId || event.id),
  ).length;
  const evidence = dataset.evidence.filter((item) => item.entityId === event.id).length;
  const total = (hasVenue + hasCoords) * 3 + hasDistrict * 2 + sources + Math.min(evidence, 5) * 0.2;
  return {
    venue: hasVenue + hasCoords,
    district: hasDistrict,
    sources,
    evidence,
    total: Number(total.toFixed(2)),
  };
};

export function selectGraphSample(dataset: Dataset): GraphSample {
  // 整个数据集都是演示数据时（测试夹具）不排除 DEMO，否则样例恒为空；真实数据集里则排除。
  const allDemo = dataset.events.length > 0 && dataset.events.every((event) => event.demo);
  const events = allDemo ? dataset.events : dataset.events.filter((event) => !event.demo);
  if (events.length === 0) {
    return {
      eventId: null,
      reasons: ["没有可用的真实活动，图谱为空"],
      score: { venue: 0, district: 0, sources: 0, evidence: 0, total: 0 },
      candidates: 0,
    };
  }

  const ranked = events
    .map((event) => ({ event, score: scoreOf(event, dataset) }))
    .sort((a, b) => b.score.total - a.score.total || a.event.id.localeCompare(b.event.id));

  const best = ranked[0];
  const venue = dataset.venues.find((v) => v.id === best.event.venueId);
  const reasons = [
    best.score.venue > 0 ? `场馆已关联（${venue?.name ?? "名称缺失"}）` : "未关联场馆",
    best.score.district > 0 ? "地区已归属" : "地区待补充",
    best.score.sources > 1 ? `${best.score.sources} 个来源记录指向同一活动` : "单一来源",
    best.score.evidence > 0 ? `${best.score.evidence} 条字段证据` : "暂无字段证据",
  ];

  return { eventId: best.event.id, reasons, score: best.score, candidates: events.length };
}

/**
 * 场所类型语义（F06 要求机场、航站楼、接驳站分开）。
 *
 * 只有数据里明确写了类型才认；本地库目前没有这类场所，因此返回「待补充」而不是编一个类型。
 */
export function placeKind(placeType: string | null | undefined): {
  kind: "airport" | "terminal" | "shuttle" | "unknown";
  label: string;
} {
  if (!placeType) return { kind: "unknown", label: "类型待补充" };
  const text = placeType.toLowerCase();
  if (text.includes("航站楼") || text.includes("terminal")) return { kind: "terminal", label: "航站楼" };
  // 接驳站要排在机场前面：「机场接驳站」是接驳设施，不是机场本身。
  if (text.includes("接驳") || text.includes("班车") || text.includes("shuttle")) {
    return { kind: "shuttle", label: "接驳站" };
  }
  if (text.includes("机场") || text.includes("airport")) return { kind: "airport", label: "机场" };
  return { kind: "unknown", label: "类型待补充" };
}

/** 多日展览只说明供给持续；不得据此推断住宿、客流或经济贡献。 */
export function multiDayCaveat(startDate: string | null, endDate: string | null): string | null {
  if (!startDate || !endDate) return null;
  const days = (Date.parse(endDate) - Date.parse(startDate)) / 86400000;
  if (Number.isNaN(days) || days < 1) return null;
  return `活动持续 ${Math.round(days) + 1} 天：这只说明供给持续，不构成访客多日住宿、客流或经济贡献的证据`;
}
