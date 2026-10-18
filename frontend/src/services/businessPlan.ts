import type { Dataset, Event, Hotel } from "../types";
import { businessToday, shiftDate } from "./intelligence";
import { distanceKm, verifiedCoords } from "../utils/data";

/**
 * The internal business plan: pricing assumptions, costs, the pilot pipeline and milestone
 * status. The values below are DEFAULTS — explicitly labelled assumptions, not measured facts.
 * The panel is admin-only (the API enforces it); pricing and customer names must never reach a
 * customer account.
 *
 * Everything measured lives in `summarizeEvidence`, which reads the live dataset rather than
 * repeating numbers from a document, so the panel cannot show yesterday's market size as today's.
 */
export type HypothesisStatus = "待验证" | "进行中" | "已验证" | "已推翻";
export type PipelineStage =
  | "未接触"
  | "已联系"
  | "已同意试点"
  | "试点中"
  | "试点结束"
  | "已付费"
  | "已拒绝";
export type MilestoneStatus = "未开始" | "进行中" | "完成" | "暂缓";

export interface Hypothesis {
  id: string;
  text: string;
  how: string;
  status: HypothesisStatus;
  note: string;
}

export interface PipelineRow {
  id: string;
  /** Exact hotel name in the dataset when it is one, so the evidence column can match it. */
  hotel: string;
  source: string;
  stage: PipelineStage;
  /** Weekly reports delivered so far, 0–4 for the pilot. */
  issues: number;
  contact: string;
  nextAction: string;
  nextDate: string;
  note: string;
}

export interface Milestone {
  id: string;
  title: string;
  status: MilestoneStatus;
  note: string;
}

export interface BusinessPlan {
  pricing: {
    proMonthly: number;
    enterpriseMonthly: number;
    trialIssues: number;
  };
  costs: {
    server: number;
    data: number;
    operations: number;
  };
  scenarios: {
    /** How many hotels pay in the scenario. The pilot has zero so far. */
    paidHotels: number;
    /** Share of paying hotels on the enterprise price (0–1). */
    enterpriseShare: number;
    /** Assumed share of pilot hotels that convert to paid (0–1). */
    trialConversion: number;
  };
  hypotheses: Hypothesis[];
  pipeline: PipelineRow[];
  milestones: Milestone[];
}

export const HYPOTHESIS_STATUSES: HypothesisStatus[] = ["待验证", "进行中", "已验证", "已推翻"];
export const PIPELINE_STAGES: PipelineStage[] = [
  "未接触",
  "已联系",
  "已同意试点",
  "试点中",
  "试点结束",
  "已付费",
  "已拒绝",
];
export const MILESTONE_STATUSES: MilestoneStatus[] = ["未开始", "进行中", "完成", "暂缓"];

/**
 * The starting plan. Every number is an assumption to be replaced by evidence, and the panel
 * shows it as such; the hypotheses list is what the pilot exists to test.
 */
export const DEFAULT_PLAN: BusinessPlan = {
  pricing: { proMonthly: 980, enterpriseMonthly: 780, trialIssues: 4 },
  costs: { server: 300, data: 200, operations: 6000 },
  scenarios: { paidHotels: 5, enterpriseShare: 0.2, trialConversion: 0.4 },
  hypotheses: [
    {
      id: "h1",
      text: "酒店愿意为「提前发现周边活动 + 节省整理时间」付费",
      how: "四期试点后的真实报价反应 + 是否继续使用",
      status: "待验证",
      note: "当前无试点酒店,尚未开始",
    },
    {
      id: "h2",
      text: "编辑周报的时间可以从 2–3 小时/周压到 20 分钟",
      how: "试点前问一次、四期后再问一次",
      status: "待验证",
      note: "",
    },
    {
      id: "h3",
      text: "「变化提醒」是续费理由,不只是锦上添花",
      how: "第 2–4 期周报中变化条目的使用情况与追问",
      status: "待验证",
      note: "需要先做出变化日志(P1b)",
    },
    {
      id: "h4",
      text: "按酒店/月收费(不按坐席)符合采购习惯",
      how: "四期结束后的报价沟通",
      status: "待验证",
      note: "",
    },
    {
      id: "h5",
      text: "公开来源 + 可追溯证据是差异化,而不是「又一个活动聚合」",
      how: "对比对方现有的信息渠道,看其是否使用来源链接",
      status: "进行中",
      note: "线上数据 100% 带来源链接,字段证据可逐条查看",
    },
    {
      id: "h6",
      text: "企业多店管理 + 私有经营数据接入有独立需求",
      how: "先验证单店价值,再谈企业",
      status: "待验证",
      note: "本轮不接入私有数据(租户隔离未建)",
    },
  ],
  pipeline: [
    {
      id: "pl1",
      hotel: "苏州洲际酒店",
      source: "候选(数据集中);样例周报已出",
      stage: "未接触",
      issues: 1,
      contact: "",
      nextAction: "通过销售/收益负责人介绍邀请函",
      nextDate: "",
      note: "样例酒店,非真实试点",
    },
    {
      id: "pl2",
      hotel: "濠韵楼商务酒店",
      source: "候选(观前街,商务类多日活动最多)",
      stage: "未接触",
      issues: 0,
      contact: "",
      nextAction: "",
      nextDate: "",
      note: "",
    },
    {
      id: "pl3",
      hotel: "长城大厦(广济路)",
      source: "候选(石路/博物馆群)",
      stage: "未接触",
      issues: 0,
      contact: "",
      nextAction: "",
      nextDate: "",
      note: "",
    },
    {
      id: "pl4",
      hotel: "苏州吴宫泛太平洋酒店大堂",
      source: "候选(盘门景区旁)",
      stage: "未接触",
      issues: 0,
      contact: "",
      nextAction: "",
      nextDate: "",
      note: "数据集里是场馆级记录,谈前先确认真实物业",
    },
    {
      id: "pl5",
      hotel: "如意酒店(石路广济南路地铁站)",
      source: "候选(交通枢纽旁)",
      stage: "未接触",
      issues: 0,
      contact: "",
      nextAction: "",
      nextDate: "",
      note: "",
    },
  ],
  milestones: [
    { id: "P0", title: "独立身份 + 角色 + 页面拆分", status: "完成", note: "liuge=审核员,menduner=管理员" },
    { id: "P1a", title: "四期试点周报(手工,PDF+Excel)", status: "未开始", note: "等试点酒店;第 1 期按 2026-10-19 周" },
    { id: "P1b", title: "变化日志 + 关注清单 + 周报导出", status: "未开始", note: "变化日志是续费理由,应最先做" },
    { id: "P2", title: "用户表 / 套餐开关 / 用量记录", status: "未开始", note: "" },
    { id: "P3", title: "租户隔离 + 企业私有数据 + API", status: "暂缓", note: "企业版前提,本轮不做" },
  ],
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Merge a saved document over the defaults, so a new planning field appears without a migration. */
export function mergePlan(saved: unknown): BusinessPlan {
  if (!isObject(saved)) return structuredClone(DEFAULT_PLAN);
  const merged = structuredClone(DEFAULT_PLAN);
  for (const key of Object.keys(merged) as (keyof BusinessPlan)[]) {
    const value = saved[key];
    if (Array.isArray(value)) {
      // Arrays are owned by the document: an emptied pipeline must stay empty.
      (merged as unknown as Record<string, unknown>)[key] = value;
    } else if (isObject(value)) {
      Object.assign(merged[key] as object, value);
    }
  }
  return merged;
}

export interface PlanState {
  document: BusinessPlan | null;
  updatedAt: string | null;
  updatedBy: string | null;
}

export async function loadPlan(): Promise<PlanState> {
  const response = await fetch("/api/plan", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`读取商业规划失败 (${response.status})`);
  }
  const body = await response.json();
  return {
    document: isObject(body?.document) ? mergePlan(body.document) : null,
    updatedAt: typeof body?.updatedAt === "string" ? body.updatedAt : null,
    updatedBy: typeof body?.updatedBy === "string" ? body.updatedBy : null,
  };
}

export async function savePlan(document: BusinessPlan): Promise<PlanState> {
  const response = await fetch("/api/plan", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document }),
  });
  if (!response.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await response.json()).slice(0, 200);
    } catch {
      detail = "";
    }
    throw new Error(`保存失败 (${response.status})${detail ? `: ${detail}` : ""}`);
  }
  const body = await response.json();
  return {
    document: isObject(body?.document) ? mergePlan(body.document) : null,
    updatedAt: typeof body?.updatedAt === "string" ? body.updatedAt : null,
    updatedBy: typeof body?.updatedBy === "string" ? body.updatedBy : null,
  };
}

// --- derived numbers -------------------------------------------------------------------
// All of them are arithmetic on the assumptions above, shown next to the assumptions so the
// reader can see which input moved a number. Nothing here is a forecast of the market.

export function monthlyCost(plan: BusinessPlan): number {
  return plan.costs.server + plan.costs.data + plan.costs.operations;
}

/** Average price per paying hotel given the enterprise share. */
export function blendedPrice(plan: BusinessPlan): number {
  const share = Math.min(1, Math.max(0, plan.scenarios.enterpriseShare));
  return plan.pricing.proMonthly * (1 - share) + plan.pricing.enterpriseMonthly * share;
}

/** How many paying hotels cover the monthly cost at the blended price. */
export function breakEvenHotels(plan: BusinessPlan): number {
  const price = blendedPrice(plan);
  if (price <= 0) return Infinity;
  return Math.ceil(monthlyCost(plan) / price);
}

/** Scenario revenue: the chosen number of paying hotels, annualised. */
export function annualRevenue(plan: BusinessPlan): number {
  return blendedPrice(plan) * plan.scenarios.paidHotels * 12;
}

/** Scenario profit per year after the fixed monthly cost. */
export function annualMargin(plan: BusinessPlan): number {
  return annualRevenue(plan) - monthlyCost(plan) * 12;
}

/** Pilot candidates × assumed conversion, rounded up: who the pilot could turn into payers. */
export function projectedPayers(plan: BusinessPlan): number {
  const conversion = Math.min(1, Math.max(0, plan.scenarios.trialConversion));
  return Math.ceil(plan.pipeline.length * conversion);
}

export interface PipelineStats {
  total: number;
  contacted: number;
  inPilot: number;
  paid: number;
  rejected: number;
}

export function pipelineStats(plan: BusinessPlan): PipelineStats {
  const count = (stages: PipelineStage[]) =>
    plan.pipeline.filter((row) => stages.includes(row.stage)).length;
  return {
    total: plan.pipeline.length,
    contacted: count(["已联系", "已同意试点", "试点中", "试点结束"]),
    inPilot: count(["试点中"]),
    paid: count(["已付费"]),
    rejected: count(["已拒绝"]),
  };
}

// --- what the market evidence actually says ---------------------------------------------

export interface HotelEvidence {
  hotel: string;
  matched: boolean;
  distanceWindow: string;
  /** Events starting in the next 30 days, within 3 km, 2+ days, not pure culture. */
  businessMultiDay30d: number | null;
  /** Same window but culture events, shown separately rather than folded in. */
  cultureMultiDay30d: number | null;
  note: string;
}

export interface MarketEvidence {
  revision: number;
  updatedAt: string;
  events: number;
  hotels: number;
  venues: number;
  evidenceRows: number;
  verifiedFields: number;
  needsReviewFields: number;
  sources: number;
  places: number;
  startsIn30d: number;
  running30d: number;
  hotelsWithEvents: number;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const parseDay = (value: string | null | undefined): Date | null => {
  if (!value) return null;
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

function venueCoordinates(event: Event, dataset: Dataset) {
  const venue = dataset.venues.find((row) => row.id === event.venueId);
  const coordinates = venue?.coordinates;
  return coordinates && verifiedCoords(coordinates) ? coordinates : null;
}

/**
 * The live numbers that support (or undercut) the paid story. Same window semantics as the
 * weekly report: "starts inside the window" and "already running" are counted separately, and
 * the distance is the straight line over GCJ-02 coordinates.
 */
export function summarizeEvidence(
  dataset: Dataset,
  options: { revision?: number; sources?: number; today?: string } = {},
): MarketEvidence {
  const today = options.today ?? businessToday();
  const windowEnd = shiftDate(today, 29);
  const start = parseDay(today);
  const end = parseDay(windowEnd);
  let startsIn30d = 0;
  let running30d = 0;
  const venuesHoldingEvents = new Set<string>();
  for (const event of dataset.events) {
    if (event.demo) continue;
    const eventStart = parseDay(event.startDate);
    const eventEnd = parseDay(event.endDate ?? event.startDate);
    if (!eventStart || !start || !end) continue;
    if (start.getTime() <= eventStart.getTime() && eventStart.getTime() <= end.getTime()) {
      startsIn30d += 1;
    } else if (
      eventStart.getTime() < start.getTime() &&
      eventEnd &&
      eventEnd.getTime() >= start.getTime()
    ) {
      running30d += 1;
    }
    if (event.venueId) venuesHoldingEvents.add(event.venueId);
  }
  const needsReview = dataset.evidence.filter(
    (row) => row.status === "Needs Review" || row.status === "Conflicting",
  ).length;
  const verified = dataset.evidence.filter((row) => row.status === "Verified").length;
  const hotelsWithEvents = dataset.hotels.filter((hotel) => {
    if (!hotel.coordinates || !verifiedCoords(hotel.coordinates)) return false;
    return dataset.events.some((event) => {
      const point = venueCoordinates(event, dataset);
      if (!point) return false;
      const distance = distanceKm(hotel.coordinates as never, point);
      return distance !== null && distance <= 5;
    });
  }).length;
  return {
    revision: options.revision ?? 0,
    updatedAt: dataset.updatedAt,
    events: dataset.events.length,
    hotels: dataset.hotels.length,
    venues: venuesHoldingEvents.size,
    evidenceRows: dataset.evidence.length,
    verifiedFields: verified,
    needsReviewFields: needsReview,
    sources: options.sources ?? 0,
    places: dataset.places.length,
    startsIn30d,
    running30d,
    hotelsWithEvents,
  };
}

/** Per-pipeline-hotel evidence: what the sales conversation would actually be about. */
export function hotelEvidence(
  dataset: Dataset,
  hotelName: string,
  today = businessToday(),
): HotelEvidence {
  const hotel = dataset.hotels.find((row: Hotel) => row.name === hotelName);
  const hotelCoords =
    hotel?.coordinates && verifiedCoords(hotel.coordinates) ? hotel.coordinates : null;
  const base: HotelEvidence = {
    hotel: hotelName,
    matched: Boolean(hotel && hotelCoords),
    distanceWindow: "未来 30 天 · 3 km · 2 天以上",
    businessMultiDay30d: null,
    cultureMultiDay30d: null,
    note: "",
  };
  if (!hotel || !hotelCoords) {
    return { ...base, note: "数据集中没有该酒店的已核验坐标" };
  }
  const windowEnd = shiftDate(today, 29);
  const start = parseDay(today);
  const end = parseDay(windowEnd);
  let business = 0;
  let culture = 0;
  for (const event of dataset.events) {
    if (event.demo) continue;
    const eventStart = parseDay(event.startDate);
    const eventEnd = parseDay(event.endDate ?? event.startDate);
    if (!eventStart || !eventEnd || !start || !end) continue;
    const startsInside =
      start.getTime() <= eventStart.getTime() && eventStart.getTime() <= end.getTime();
    const running =
      eventStart.getTime() < start.getTime() && eventEnd.getTime() >= start.getTime();
    if (!startsInside && !running) continue;
    const days = Math.round((eventEnd.getTime() - eventStart.getTime()) / DAY_MS) + 1;
    if (days < 2) continue;
    const point = venueCoordinates(event, dataset);
    if (!point) continue;
    const distance = distanceKm(hotelCoords as never, point);
    if (distance === null || distance > 3) continue;
    if (event.category === "culture") culture += 1;
    else business += 1;
  }
  return { ...base, businessMultiDay30d: business, cultureMultiDay30d: culture };
}
