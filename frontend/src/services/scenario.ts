/**
 * 经济贡献情景：把「一场活动带来多少钱」拆成可核对的三段。
 *
 * ## 2026-10-24 审核修正（F01）
 *
 * 上一版把「市场住宿支出」算成 `本店间夜 ÷ 本店份额 × 房价`，于是**市场规模会随某一家酒店
 * 的份额变化**：份额从 10% 改到 20%，市场住宿支出从 50 万掉到 25 万，而本店收入不变。这是
 * 因果方向错误 —— 份额描述的是分配，不该影响市场规模。
 *
 * 现在的关系是单向的：
 *
 *   市场总间夜   = 不重复访客 × 住宿比例 × 平均住宿晚数 ÷ 每间入住人数
 *   市场住宿支出 = 市场总间夜 × 市场平均房价
 *   本店间夜     = 市场总间夜 × 本店份额
 *   本店住宿收入 = 本店间夜 × 本店平均房价
 *
 * 市场那两项只由需求侧参数决定；改动本店份额只影响本店那两项。
 *
 * ## 另一个修正：人次 ≠ 人数
 *
 * 上一版把「到场人次」直接乘以住宿比例。一个人逛两天是该算 1 个不重复访客而不是 2 人次，
 * 否则住宿需求会被重复计入。现在输入明确是**不重复访客人数**，累计人次不再参与住宿计算。
 *
 * ## 城市净新增不在这里算
 *
 * 商圈消费里包含本地居民原本就会花的钱，活动只是改变了消费的时间与地点；净新增还要扣替代
 * 效应与挤出效应。用活动总消费冒充净收益是最常见的错误，所以这里明确说明「未计算」。
 */

export type ParamSource = "source" | "user" | "assumption";

export const SOURCE_LABELS: Record<ParamSource, string> = {
  source: "来源数据",
  user: "用户输入",
  assumption: "假设",
};

export interface ScenarioInput {
  /** 不重复访客人数（不是累计人次）。 */
  visitors: number | null;
  /** 其中需要在本地住宿的比例，0-1。 */
  stayShare: number | null;
  /** 住宿者平均住宿晚数，必须 > 0。 */
  avgNights: number | null;
  /** 平均每间入住人数，必须 > 0。 */
  guestsPerRoom: number | null;
  /** 市场（商圈）平均房价，元/间夜。 */
  marketRate: number | null;
  /** 本店在周边住宿中的份额，0-1。 */
  hotelShare: number | null;
  /** 本店平均房价；留空表示与本店所在市场同价。 */
  hotelRate?: number | null;
  /** 人均商圈消费，元/人。 */
  spendPerVisitor: number | null;
  /** 商圈消费是否已包含住宿支出。 */
  spendIncludesLodging?: boolean;
}

export interface ScenarioRange {
  key: "low" | "mid" | "high";
  label: string;
  /** 该情景对访客人数的倍数；这是参数情景，不是置信区间。 */
  factor: number;
  visitors: number;
  marketRoomNights: number;
  marketLodgingSpend: number;
  hotelRoomNights: number;
  hotelRevenue: number;
  districtSpend: number;
}

export type IssueLevel = "error" | "warn";

export interface ValidationIssue {
  field: string;
  label: string;
  level: IssueLevel;
  message: string;
}

export interface ScenarioResult {
  ok: boolean;
  issues: ValidationIssue[];
  scenarios: ScenarioRange[];
  formula: string[];
  note: string;
  /** 跨字段一致性检查通过与否（例如住宿支出不能大于包含它的总消费）。 */
  consistent: boolean;
}

const REQUIRED: { key: keyof ScenarioInput; label: string }[] = [
  { key: "visitors", label: "不重复访客人数" },
  { key: "stayShare", label: "住宿比例" },
  { key: "avgNights", label: "平均住宿晚数" },
  { key: "guestsPerRoom", label: "平均每间入住人数" },
  { key: "marketRate", label: "市场平均房价" },
  { key: "hotelShare", label: "本店份额" },
  { key: "spendPerVisitor", label: "人均商圈消费" },
];

const RATIO_FIELDS: { key: keyof ScenarioInput; label: string }[] = [
  { key: "stayShare", label: "住宿比例" },
  { key: "hotelShare", label: "本店份额" },
];

const NON_NEGATIVE: { key: keyof ScenarioInput; label: string }[] = [
  { key: "visitors", label: "不重复访客人数" },
  { key: "marketRate", label: "市场平均房价" },
  { key: "spendPerVisitor", label: "人均商圈消费" },
  { key: "hotelRate", label: "本店平均房价" },
];

const POSITIVE: { key: keyof ScenarioInput; label: string }[] = [
  { key: "avgNights", label: "平均住宿晚数" },
  { key: "guestsPerRoom", label: "平均每间入住人数" },
];

const FACTORS: { key: ScenarioRange["key"]; label: string; factor: number }[] = [
  { key: "low", label: "低情景", factor: 0.6 },
  { key: "mid", label: "中情景", factor: 1 },
  { key: "high", label: "高情景", factor: 1.4 },
];

function isMissing(value: unknown): boolean {
  return value === null || value === undefined || typeof value !== "number" || !Number.isFinite(value);
}

export function validateScenario(input: ScenarioInput): ValidationIssue[] {
  const issues: ValidationIssue[] = [];

  for (const field of REQUIRED) {
    if (isMissing(input[field.key])) {
      issues.push({
        field: field.key,
        label: field.label,
        level: "error",
        message: `缺少${field.label}，无法计算`,
      });
    }
  }

  for (const field of RATIO_FIELDS) {
    const value = input[field.key];
    if (!isMissing(value) && ((value as number) < 0 || (value as number) > 1)) {
      issues.push({
        field: field.key,
        label: field.label,
        level: "error",
        message: `${field.label}必须在 0 到 1 之间（当前 ${value}）`,
      });
    }
  }

  for (const field of NON_NEGATIVE) {
    const value = input[field.key];
    if (!isMissing(value) && (value as number) < 0) {
      issues.push({
        field: field.key,
        label: field.label,
        level: "error",
        message: `${field.label}不能为负数`,
      });
    }
  }

  for (const field of POSITIVE) {
    const value = input[field.key];
    if (!isMissing(value) && (value as number) <= 0) {
      issues.push({
        field: field.key,
        label: field.label,
        level: "error",
        message: `${field.label}必须大于 0（否则会产生除零）`,
      });
    }
  }

  return issues;
}

export function computeScenarios(input: ScenarioInput): ScenarioResult {
  const formula = [
    "市场总间夜 = 不重复访客人数 × 住宿比例 × 平均住宿晚数 ÷ 平均每间入住人数",
    "市场住宿支出 = 市场总间夜 × 市场平均房价",
    "本店间夜 = 市场总间夜 × 本店份额",
    "本店住宿收入 = 本店间夜 × 本店平均房价（未填本店房价时按市场房价计）",
    "商圈整体消费 = 不重复访客人数 × 人均商圈消费（若勾选「已包含住宿」，住宿支出不再重复相加）",
    "低 / 中 / 高情景按中情景访客人数的 60% / 100% / 140% 展开（参数情景，不是置信区间）",
  ];

  const note =
    "以上是情景估算，不是观测结果，也不是净新增收益：商圈消费里包含本地居民原本就会发生的支出，" +
    "活动只是改变了消费的时间与地点；净新增还需扣除替代效应与挤出效应，本系统不提供该数字。";

  const issues = validateScenario(input);
  if (issues.some((issue) => issue.level === "error")) {
    return { ok: false, issues, scenarios: [], formula, note, consistent: true };
  }

  const visitors = input.visitors as number;
  const stayShare = input.stayShare as number;
  const avgNights = input.avgNights as number;
  const guestsPerRoom = input.guestsPerRoom as number;
  const marketRate = input.marketRate as number;
  const hotelShare = input.hotelShare as number;
  const hotelRate = isMissing(input.hotelRate) ? marketRate : (input.hotelRate as number);
  const spend = input.spendPerVisitor as number;
  const includesLodging = input.spendIncludesLodging ?? false;

  const scenarios = FACTORS.map(({ key, label, factor }) => {
    const scenarioVisitors = Math.round(visitors * factor);
    // 市场间夜只由需求侧参数决定，本店份额不参与 —— 这是 F01 修正的核心。
    const marketRoomNights = (scenarioVisitors * stayShare * avgNights) / guestsPerRoom;
    const marketLodgingSpend = marketRoomNights * marketRate;
    const hotelRoomNights = marketRoomNights * hotelShare;
    return {
      key,
      label,
      factor,
      visitors: scenarioVisitors,
      marketRoomNights: Math.round(marketRoomNights),
      marketLodgingSpend: Math.round(marketLodgingSpend),
      hotelRoomNights: Math.round(hotelRoomNights),
      hotelRevenue: Math.round(hotelRoomNights * hotelRate),
      districtSpend: Math.round(scenarioVisitors * spend),
    };
  });

  // 跨字段一致性：若声明「总消费已包含住宿」，住宿支出不应大于总消费。不一致时保留数字
  // 并标出来，让用户看到矛盾，而不是把金额悄悄截断成合理值。
  const inconsistent = includesLodging
    ? scenarios.filter((scenario) => scenario.marketLodgingSpend > scenario.districtSpend)
    : [];
  if (inconsistent.length > 0) {
    issues.push({
      field: "spendIncludesLodging",
      label: "总消费与住宿支出",
      level: "warn",
      message:
        "住宿支出大于「已包含住宿」的商圈总消费，参数之间矛盾，请核对人均消费或房价与住宿比例",
    });
  }

  return {
    ok: true,
    issues,
    scenarios,
    formula,
    note,
    consistent: inconsistent.length === 0,
  };
}

/** 金额展示：不足一万按元，超过按万元并保留一位小数，避免出现看似精确的长数字。 */
export function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(1)} 万元`;
  return `${Math.round(value)} 元`;
}
