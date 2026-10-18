/**
 * The customer-facing plans: what each tier unlocks, what it costs, and what is still coming.
 *
 * This is the commercial surface of the product, not an internal planning document. The one rule
 * that matters: public city data (activities, sources, evidence, quality) stays free — the paid
 * tiers sell the WORKFLOW around it (hotel-centric filtering, area comparison, multi-hotel
 * management, later the weekly report and change alerts), because locking public data would
 * destroy the reason anyone trusts the product in the first place.
 *
 * Entitlements are a prototype: there is no customer account or payment integration yet, so the
 * current plan is a local demo switch (see hooks/useEntitlements.tsx). The plans page says so
 * explicitly instead of pretending a purchase happened.
 */
export type PlanId = "free" | "pro" | "enterprise";

export const PLAN_ORDER: PlanId[] = ["free", "pro", "enterprise"];
export const PLAN_RANK: Record<PlanId, number> = { free: 0, pro: 1, enterprise: 2 };
export const PLAN_LABELS: Record<PlanId, string> = {
  free: "免费版",
  pro: "专业版",
  enterprise: "企业版",
};

export interface PlanCard {
  id: PlanId;
  name: string;
  tagline: string;
  price: string;
  priceNote: string;
  highlights: string[];
  recommended?: boolean;
}

export const PLANS: PlanCard[] = [
  {
    id: "free",
    name: "免费版",
    tagline: "先了解这座城市",
    price: "¥0",
    priceNote: "公开数据不收费",
    highlights: [
      "公开活动地图、日历、活动清单",
      "场馆活动清单与知识图谱",
      "每条活动的来源链接与字段证据",
      "数据质量与来源覆盖说明",
    ],
  },
  {
    id: "pro",
    name: "专业版",
    tagline: "盯住一家酒店，把情报变成每周工作",
    price: "¥980",
    priceNote: "每酒店 / 月 · 试点四期免费",
    recommended: true,
    highlights: [
      "酒店活动情报：按酒店位置与日期筛选周边活动",
      "商圈洞察：区域活动与酒店资源对比",
      "周报导出（PDF + Excel，即将上线）",
      "关注与变化提醒（即将上线）",
    ],
  },
  {
    id: "enterprise",
    name: "企业版",
    tagline: "管理多家酒店，团队一起用",
    price: "¥780",
    priceNote: "每酒店 / 月（多店）· 试点四期免费",
    highlights: [
      "专业版全部能力",
      "多酒店组合对比",
      "团队与成员权限（即将上线）",
      "企业私有经营数据接入（后续）",
    ],
  },
];

/** Minimum plan that unlocks a feature. `free` means public. */
export type FeatureId =
  | "public_events"
  | "evidence"
  | "graph"
  | "hotel_intel"
  | "insights"
  | "multi_hotel"
  | "weekly_report"
  | "alerts"
  | "team"
  | "private_data"
  | "api";

export interface FeatureRow {
  id: FeatureId;
  label: string;
  minimum: PlanId;
  /** "live" exists in the product today; "soon" is on the roadmap; "later" is out of scope now. */
  status: "已上线" | "即将上线" | "后续";
  note?: string;
}

export const FEATURES: FeatureRow[] = [
  { id: "public_events", label: "公开活动地图 / 日历 / 活动清单", minimum: "free", status: "已上线" },
  { id: "evidence", label: "来源链接 / 字段证据 / 数据质量", minimum: "free", status: "已上线" },
  { id: "graph", label: "知识图谱（活动 → 场馆 → 商圈 → 酒店 → 客群）", minimum: "free", status: "已上线" },
  {
    id: "hotel_intel",
    label: "酒店活动情报（单店周边筛选）",
    minimum: "pro",
    status: "已上线",
    note: "付费工作流的起点",
  },
  { id: "insights", label: "商圈洞察（区域对比）", minimum: "pro", status: "已上线" },
  {
    id: "multi_hotel",
    label: "多酒店组合对比",
    minimum: "enterprise",
    status: "已上线",
    note: "企业版按酒店数计费",
  },
  {
    id: "weekly_report",
    label: "周报导出（PDF + Excel）",
    minimum: "pro",
    status: "即将上线",
    note: "试点期手工交付",
  },
  {
    id: "alerts",
    label: "关注与变化提醒",
    minimum: "pro",
    status: "即将上线",
    note: "依赖变化日志",
  },
  { id: "team", label: "团队与成员权限", minimum: "enterprise", status: "即将上线" },
  {
    id: "private_data",
    label: "企业私有经营数据接入",
    minimum: "enterprise",
    status: "后续",
    note: "需要租户隔离",
  },
  { id: "api", label: "约定范围 API", minimum: "enterprise", status: "后续" },
];

export function featureById(id: FeatureId): FeatureRow {
  const row = FEATURES.find((item) => item.id === id);
  if (!row) throw new Error(`Unknown feature: ${id}`);
  return row;
}

/** True when `current` reaches `required`; free is the floor. */
export function planAtLeast(current: PlanId, required: PlanId): boolean {
  return PLAN_RANK[current] >= PLAN_RANK[required];
}

/** Features a plan unlocks, for the plan cards. */
export function unlockedFeatures(plan: PlanId): FeatureRow[] {
  return FEATURES.filter((row) => planAtLeast(plan, row.minimum));
}

export const PLAN_STORAGE_KEY = "menduner.plan";

export function readStoredPlan(): PlanId {
  try {
    const stored = window.localStorage.getItem(PLAN_STORAGE_KEY);
    if (stored === "pro" || stored === "enterprise") return stored;
  } catch {
    /* storage unavailable (private mode): the free plan is the floor */
  }
  return "free";
}

export function storePlan(plan: PlanId): void {
  try {
    if (plan === "free") window.localStorage.removeItem(PLAN_STORAGE_KEY);
    else window.localStorage.setItem(PLAN_STORAGE_KEY, plan);
  } catch {
    /* storage unavailable: the switch only lasts this session */
  }
}
