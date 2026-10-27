import type { Dataset, Event, Hotel } from "../types";
import { categoryWeights } from "./intelligence";
import { dates, distanceKm, eventCoordinates, eventStatus, verifiedCoords } from "../utils/data";

/**
 * 可解释的推荐排序。
 *
 * 排序规则集中在这个文件里，因为「为什么这条排第一」必须是能回答的问题：如果权重散落在各个
 * 页面，同一条活动在不同页面排名不同，也没人能解释差别。这里每条规则都返回**分数 + 理由 + 未知**，
 * 界面把三者一起显示，缺数据时写"未知"而不是假装有值。
 *
 * 三条原则：
 *   1. 距离、业务相关性、数据可信度**分开算分也分开显示** —— 把它们合成一个黑箱分数，用户就
 *      无法判断"离得近但数据不可靠"和"离得远但证据齐全"哪个更值得看；
 *   2. 没有数据的维度记为 unknown，不给分，也不补默认值（不编造规模、客源）；
 *   3. 权重全部是具名常量，改权重不需要动逻辑。
 */

/** 评分维度。界面按维度分组展示，避免把不同性质的分数混在一起比较。 */
export type Dimension = "relevance" | "distance" | "credibility" | "timing";

export const DIMENSION_LABELS: Record<Dimension, string> = {
  relevance: "业务相关性",
  distance: "距离",
  credibility: "数据可信度",
  timing: "时间紧迫度",
};

/** 权重：相关性 > 可信度 > 距离 > 时间。全部具名，便于解释与调整。 */
export const WEIGHTS: Record<Dimension, number> = {
  relevance: 3,
  credibility: 2,
  distance: 2,
  timing: 1,
};

/** 距离衰减：0 km 得满分，超过这个半径得 0 分。 */
export const DISTANCE_FADE_KM = 15;

export interface RankedEvent {
  event: Event;
  score: number;
  /** 按维度分开的得分，界面可以逐项显示。 */
  byDimension: Record<Dimension, number | null>;
  /** 主要理由，最多三条，按权重大小排序。 */
  reasons: string[];
  /** 缺失的信息，界面必须显示，不能省略。 */
  unknown: string[];
}

export interface RankContext {
  hotel: Hotel;
  dataset: Dataset;
  /** 参考日期（北京时间），用于判断"还有几天开始"。 */
  today: string;
}

const CATEGORY_TEXT: Record<string, string> = {
  culture: "文化艺术类客群",
  business: "商务客群",
  sports: "赛事/活动客群",
  religion: "民俗节庆客群",
  other: "泛客群",
};

/**
 * 相关性：类别权重 × 场馆是否在酒店同区的加成。
 * 客群匹配本身是**规则推断**，不是采集到的事实，所以理由里明确写"推断"。
 */
function relevanceScore(event: Event, hotel: Hotel): { score: number | null; reason?: string; unknown?: string } {
  const weight = categoryWeights[event.category];
  if (weight === undefined) {
    return { score: null, unknown: "还不知道活动类别，暂时判断不了客群" };
  }
  const base = Math.min(1, weight / 2);
  const sameDistrict = !!event.districtId && event.districtId === hotel.districtId;
  const score = Math.min(1, base + (sameDistrict ? 0.2 : 0));
  const text = CATEGORY_TEXT[event.category] ?? "泛客群";
  return {
    score,
    reason: sameDistrict
      ? `与本店同区，且属于${text}（规则推断，非采集事实）`
      : `属于${text}（规则推断，非采集事实）`,
  };
}

function distanceScore(event: Event, context: RankContext): { score: number | null; reason?: string; unknown?: string; km?: number } {
  const point = eventCoordinates(event, context.dataset);
  if (!point || !verifiedCoords(context.hotel.coordinates)) {
    return { score: null, unknown: "场馆位置还没确认，暂时算不了距离" };
  }
  const km = distanceKm(context.hotel.coordinates, point);
  if (km === null) return { score: null, unknown: "距离计算失败" };
  const score = Math.max(0, 1 - km / DISTANCE_FADE_KM);
  return { score, km, reason: `距本店 ${km.toFixed(1)} km` };
}

/** 可信度：只数"有来源支撑的字段"，不参考活动热度。 */
function credibilityScore(event: Event, dataset: Dataset): { score: number; reason: string; unknown?: string } {
  const checks = [
    { ok: !!dates(event), label: "日期" },
    { ok: !!event.venueId, label: "场馆" },
    { ok: !!event.districtId, label: "地区" },
    {
      ok: eventStatus((dataset.evidence ?? []).filter((item) => item.entityId === event.id)) === "Verified",
      label: "来源核验",
    },
  ];
  const ok = checks.filter((check) => check.ok).length;
  const missing = checks.filter((check) => !check.ok).map((check) => check.label);
  return {
    score: ok / checks.length,
    reason: `关键信息有 ${ok} 项可查证（${checks.filter((c) => c.ok).map((c) => c.label).join("、")}）`,
    unknown: missing.length ? `还没确认：${missing.join("、")}` : undefined,
  };
}

/** 紧迫度：越近开始越值得现在处理；已进行中的活动给中等分。 */
function timingScore(event: Event, today: string): { score: number | null; reason?: string; unknown?: string } {
  const span = dates(event);
  if (!span) return { score: null, unknown: "日期未核验，无法判断时间紧迫度" };
  const [start, end] = span;
  if (end < today) return { score: 0, reason: "已结束" };
  if (start <= today) return { score: 0.5, reason: "进行中" };
  const days = Math.round((Date.parse(start) - Date.parse(today)) / 86400000);
  const score = Math.max(0, 1 - days / 14);
  return { score, reason: `${days} 天后开始` };
}

export function rankEvent(event: Event, context: RankContext): RankedEvent {
  const relevance = relevanceScore(event, context.hotel);
  const distance = distanceScore(event, context);
  const credibility = credibilityScore(event, context.dataset);
  const timing = timingScore(event, context.today);

  const byDimension: Record<Dimension, number | null> = {
    relevance: relevance.score,
    distance: distance.score,
    credibility: credibility.score,
    timing: timing.score,
  };

  const score = (Object.keys(byDimension) as Dimension[]).reduce((total, key) => {
    const value = byDimension[key];
    return total + (value === null ? 0 : value * WEIGHTS[key]);
  }, 0);

  const reasons = [
    { weight: WEIGHTS.relevance, text: relevance.reason },
    { weight: WEIGHTS.distance, text: distance.reason },
    { weight: WEIGHTS.credibility, text: credibility.reason },
    { weight: WEIGHTS.timing, text: timing.reason },
  ]
    .filter((item) => !!item.text)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3)
    .map((item) => item.text as string);

  const unknown = [relevance.unknown, distance.unknown, credibility.unknown, timing.unknown]
    .filter((text): text is string => !!text);

  return { event, score, byDimension, reasons, unknown };
}

/** 语法糖：按分数降序，同分按名称保证结果稳定。 */
export function rankEvents(events: Event[], context: RankContext): RankedEvent[] {
  return events
    .map((event) => rankEvent(event, context))
    .sort((a, b) => b.score - a.score || a.event.name.localeCompare(b.event.name));
}
