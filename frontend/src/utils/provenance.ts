/**
 * 数据批次与口径版本（F12）。
 *
 * 为什么需要：页面上每个数字都依赖「数据是哪天抓的、按什么口径算的」。没有这两个信息，
 * 用户无法判断一个 19 或 436 是三小时前的还是三天前的，也无法在口径变更后解释差异。
 *
 * 三条硬约束（GPT Round 5 的验收标准）：
 *   1. 更新时间、批次、口径版本必须来自真实后端字段，不能在前端编造；
 *   2. 页面显示与导出文件的元数据一致；字段缺失时显示「未知」，不猜；
 *   3. 时间按北京时间展示，且旧批次/过期数据要有提示。
 */

export interface ProvenanceInput {
  /** 后端返回的更新时间（ISO 字符串，可能缺失）。 */
  updatedAt?: string | null;
  /** 北京时间的「今天」，用于判断是否过期。 */
  today: string;
  /** 超过多少天算旧数据。 */
  staleDays?: number;
  /** 后端 /status 返回的口径版本；前端不维护副本。 */
  caliberVersion?: string | null;
}

export interface Provenance {
  /** 北京时间展示串（YYYY-MM-DD HH:mm），缺失为「未知」。 */
  updatedLabel: string;
  /** 批次标识：由更新时间派生；缺失为「未知」。 */
  batchId: string;
  /** 口径版本：来自后端 /status，缺失为「未知」。 */
  caliberVersion: string;
  /** 数据是否过期（无更新时间时视为未知，不算过期）。 */
  stale: boolean;
  /** 面向用户的说明。 */
  note: string;
}

const BEIJING = "Asia/Shanghai";

/** 把任意 ISO 时间渲染成北京时间；无法解析时返回「未知」，绝不回落到本地时区。 */
export function beijingTimestamp(value?: string | null): string {
  if (!value) return "未知";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "未知";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BEIJING,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(parsed));
  const take = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${take("year")}-${take("month")}-${take("day")} ${take("hour")}:${take("minute")}`;
}

/** 批次标识：取更新时间的 UTC 日期+时分，缺失返回「未知」。 */
export function batchOf(updatedAt?: string | null): string {
  if (!updatedAt) return "未知";
  const parsed = Date.parse(updatedAt);
  if (Number.isNaN(parsed)) return "未知";
  return new Date(parsed).toISOString().slice(0, 16).replace(/[-:T]/g, "").slice(0, 12);
}

/** 距今天数；无法计算时返回 null（未知，不当作过期）。 */
export function daysSince(updatedAt: string | null | undefined, today: string): number | null {
  if (!updatedAt) return null;
  const stamp = Date.parse(updatedAt);
  if (Number.isNaN(stamp)) return null;
  // 用 UTC 日期比较，避免设备时区把一天算成两天
  const updatedDay = new Date(stamp).toISOString().slice(0, 10);
  const diff = Date.parse(today + "T00:00:00Z") - Date.parse(updatedDay + "T00:00:00Z");
  return Math.round(diff / 86400000);
}

export function provenanceOf(input: ProvenanceInput): Provenance {
  const staleDays = input.staleDays ?? 3;
  const age = daysSince(input.updatedAt, input.today);
  const stale = age !== null && age > staleDays;
  const note = stale
    ? `数据已 ${age} 天未更新，页面数字可能已过期，请先确认采集是否正常`
    : age === null
      ? "数据更新时间未知，无法判断新鲜度"
      : "";
  return {
    updatedLabel: beijingTimestamp(input.updatedAt),
    batchId: batchOf(input.updatedAt),
    caliberVersion: input.caliberVersion?.trim() || "未知",
    stale,
    note,
  };
}
