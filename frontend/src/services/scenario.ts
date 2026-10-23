/**
 * 经济贡献情景：把「一场活动带来多少钱」拆成可核对的三段，而不是给一个金额。
 *
 * 为什么不做成预算器：
 *   1. 观众人数、人均消费这些参数我们**没有采集到**，用户自己填也只代表假设，所以每个参数都
 *      必须标出来源（来源数据 / 用户输入 / 假设），否则屏幕上会凭空出现一个看似权威的数字；
 *   2. 三段是不同主体的钱：商圈整体消费、住宿支出、本店经营结果。混成一个总数会让酒店误以为
 *      流量全部是自己的；
 *   3. 缺关键参数时**不出金额**，只提示补什么 —— 这比给一个「大概 120 万」诚实得多。
 *
 * 城市净新增收益不在这里计算：它要扣掉原有消费被替代的部分、本地居民原本也会花的钱、以及
 * 挤出效应。用活动总消费冒充净收益是最常见的错误，所以这里明确说明「未计算」。
 */

export type ParamSource = "source" | "user" | "assumption";

export const SOURCE_LABELS: Record<ParamSource, string> = {
  source: "来源数据",
  user: "用户输入",
  assumption: "假设",
};

export interface ScenarioInput {
  /** 活动期间预计到场人次（**没有来源数据时为空**）。 */
  attendance: number | null;
  /** 人均商圈消费（元/人次）。 */
  spendPerVisitor: number | null;
  /** 到场人次中需要在本地住宿的比例（0-1）。 */
  stayShare: number | null;
  /** 平均房价（元/间夜）。 */
  roomRate: number | null;
  /** 本店在周边住宿中的份额（0-1）。 */
  hotelShare: number | null;
  /** 每间夜入住人数，默认 2 是常见假设。 */
  guestsPerRoom?: number | null;
}

export interface ScenarioRange {
  key: "low" | "mid" | "high";
  label: string;
  /** 该情景使用的人次倍数，展示计算过程时要写出来。 */
  factor: number;
  attendance: number;
  /** 商圈整体消费（元），含非住宿消费。 */
  districtSpend: number;
  /** 住宿支出总额（元），属于商圈消费的一部分。 */
  lodgingSpend: number;
  /** 本店可分摊的住宿收入（元）。 */
  hotelRevenue: number;
  /** 本店可分摊的间夜数。 */
  roomNights: number;
}

export interface ScenarioResult {
  ok: boolean;
  /** 缺失的关键参数名，界面据此提示补充。 */
  missing: string[];
  scenarios: ScenarioRange[];
  /** 计算过程，逐行展示给用户核对。 */
  formula: string[];
  /** 明确声明这一块不是净新增。 */
  note: string;
}

const REQUIRED: { key: keyof ScenarioInput; label: string }[] = [
  { key: "attendance", label: "预计到场人次" },
  { key: "spendPerVisitor", label: "人均商圈消费" },
  { key: "stayShare", label: "需住宿比例" },
  { key: "roomRate", label: "平均房价" },
  { key: "hotelShare", label: "本店份额" },
];

const FACTORS: { key: ScenarioRange["key"]; label: string; factor: number }[] = [
  { key: "low", label: "低情景", factor: 0.6 },
  { key: "mid", label: "中情景", factor: 1 },
  { key: "high", label: "高情景", factor: 1.4 },
];

export function computeScenarios(input: ScenarioInput): ScenarioResult {
  const missing = REQUIRED.filter((item) => {
    const value = input[item.key];
    return value === null || value === undefined || !Number.isFinite(value as number);
  }).map((item) => item.label);

  const formula = [
    "本店间夜 = 到场人次 × 需住宿比例 ÷ 每间夜人数",
    "住宿支出 = 本店间夜 ÷ 本店份额 × 平均房价（即周边住宿总额）",
    "本店住宿收入 = 周边住宿总额 × 本店份额",
    "商圈整体消费 = 到场人次 × 人均商圈消费（住宿支出包含在其中，不额外相加）",
    "低 / 中 / 高情景分别按中情景人数的 60% / 100% / 140% 计算",
  ];

  const note =
    "以上是**情景估算**，不是观测结果，也不是净新增收益：商圈消费里包含本地居民原本就会发生的支出，" +
    "活动只是改变了时间和地点；净新增还要扣除替代效应与挤出效应，本系统不提供该数字。";

  if (missing.length > 0) {
    return { ok: false, missing, scenarios: [], formula, note };
  }

  const guestsPerRoom = input.guestsPerRoom && input.guestsPerRoom > 0 ? input.guestsPerRoom : 2;
  const attendance = input.attendance as number;
  const spend = input.spendPerVisitor as number;
  const stayShare = input.stayShare as number;
  const roomRate = input.roomRate as number;
  const hotelShare = input.hotelShare as number;

  const scenarios = FACTORS.map(({ key, label, factor }) => {
    const visitors = Math.round(attendance * factor);
    const stayingVisitors = visitors * stayShare;
    const roomNights = Math.round(stayingVisitors / guestsPerRoom);
    // 本店份额用于把周边住宿总额拆回本店；份额为 0 时总额无法反推，此时只报本店为 0。
    const lodgingSpend = hotelShare > 0 ? (roomNights / hotelShare) * roomRate : 0;
    return {
      key,
      label,
      factor,
      attendance: visitors,
      districtSpend: Math.round(visitors * spend),
      lodgingSpend: Math.round(lodgingSpend),
      hotelRevenue: Math.round(lodgingSpend * hotelShare),
      roomNights,
    };
  });

  return { ok: true, missing: [], scenarios, formula, note };
}

/** 金额展示：不足一万按元，超过按万元并保留一位小数，避免出现看似精确的长数字。 */
export function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(1)} 万元`;
  return `${Math.round(value)} 元`;
}
