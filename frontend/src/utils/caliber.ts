import { dates, overlaps } from "./data";
import type { Event } from "../types";

/**
 * 时间与统计口径的唯一来源。
 *
 * 这个模块存在的原因是同一个问题在不同的页面上被回答得不一致：地图按「月份」过滤，酒店页按
 * 「需求半径内本月」，活动清单按「本周 / 本月」，而它们的「数量」有时是活动数、有时是活动覆盖
 * 的天数。用户看到同一批筛选条件下的两个不同数字，无法判断哪个可信。
 *
 * 这里定义三件事，所有页面都必须从这里取：
 *   1. 时间窗口（未来 7 天 / 未来 30 天 / 自定义），全部以北京时间计算；
 *   2. 活动状态（即将开始 / 进行中 / 已结束），按窗口起点而不是按「今天」比较，
 *      这样看历史窗口时"已结束"才是相对于该窗口的；
 *   3. 统计口径：活动数（去重后的活动条数）与覆盖天数（活动在窗口内实际占用的日历天），
 *      两个数字含义不同，界面必须分别标注，不能混用。
 */

export type WindowKind = "next7" | "next30" | "custom";

export interface TimeWindow {
  kind: WindowKind;
  /** 含端点的北京时间日期，YYYY-MM-DD */
  start: string;
  end: string;
  label: string;
}

export type EventPhase = "upcoming" | "ongoing" | "ended";

export const WINDOW_OPTIONS: { value: WindowKind; label: string }[] = [
  { value: "next7", label: "未来 7 天" },
  { value: "next30", label: "未来 30 天" },
  { value: "custom", label: "自定义" },
];

/** 北京时间（Asia/Shanghai）的今天。服务器在 UTC，用 Intl 而不是本地时区。 */
export function beijingToday(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  return ["year", "month", "day"]
    .map((type) => parts.find((part) => part.type === type)!.value)
    .join("-");
}

export function shiftDate(date: string, deltaDays: number): string {
  const base = Date.parse(date + "T00:00:00Z");
  return new Date(base + deltaDays * 86400000).toISOString().slice(0, 10);
}

export function isValidDateString(value: string | null | undefined): value is string {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value + "T00:00:00Z"));
}

/**
 * 从 URL 参数解析时间窗口。
 *
 * 默认是「未来 30 天」而不是自然月：一个酒店问的是"接下来值得关注的活动"，月份边界会把
 * 10 月 31 日和 11 月 1 日切开，人为制造一个没人关心的断层。
 */
export function windowFromParams(
  params: URLSearchParams,
  today: string = beijingToday(),
): TimeWindow {
  const kindParam = params.get("window");
  const from = params.get("from");
  const to = params.get("to");

  if (isValidDateString(from) && isValidDateString(to) && from <= to) {
    return { kind: "custom", start: from, end: to, label: `${from} 至 ${to}` };
  }
  if (kindParam === "next7") {
    return {
      kind: "next7",
      start: today,
      end: shiftDate(today, 6),
      label: `未来 7 天（${today} 至 ${shiftDate(today, 6)}）`,
    };
  }
  return {
    kind: "next30",
    start: today,
    end: shiftDate(today, 29),
    label: `未来 30 天（${today} 至 ${shiftDate(today, 29)}）`,
  };
}

/** 事件在给定窗口中的状态。已结束是相对于窗口起点判断的，而不是相对于今天。 */
export function phaseOf(event: Event, window: TimeWindow): EventPhase {
  const range = dates(event);
  if (!range) return "ended";
  const [start, end] = range;
  if (end < window.start) return "ended";
  if (start > window.end) return "ended";
  if (start < window.start && end >= window.start) return "ongoing";
  return "upcoming";
}

/**
 * 相对「今天」的活动状态：这是酒店客户真正关心的口径（这场活动现在还在不在办）。
 *
 * 与 phaseOf(event, window) 的区别：后者是相对统计窗口起点判断，
 * 用在一整个月的报表里；但页头/地图上的"进行中"若用它，
 * 10 月 2 日就结束的活动会被算成"进行中"，与实际不符。
 */
export function phaseToday(event: Event, today: string = new Date().toISOString().slice(0, 10)): EventPhase {
  const range = dates(event);
  if (!range) return "ended";
  const [start, end] = range;
  if (end < today) return "ended";
  if (start > today) return "upcoming";
  return "ongoing";
}

export const PHASE_LABELS: Record<EventPhase, string> = {
  upcoming: "即将开始",
  ongoing: "进行中",
  ended: "已结束",
};

export interface CaliberScope {
  district?: string;
  category?: string;
  includeDemo: boolean;
}

/** 一个筛选范围内的活动（不做时间过滤），各页面共用同一份选择逻辑。 */
export function scopeEvents(events: Event[], scope: CaliberScope): Event[] {
  return events.filter(
    (event) =>
      (scope.includeDemo || !event.demo) &&
      (!scope.district || event.districtId === scope.district) &&
      (!scope.category || event.category === scope.category),
  );
}

/** 窗口内的活动：与窗口有交集即算，进行中的活动不会被切开丢掉。 */
export function eventsInWindow(events: Event[], scope: CaliberScope, window: TimeWindow): Event[] {
  return scopeEvents(events, scope).filter((event) => overlaps(event, window.start, window.end));
}

export interface CaliberCounts {
  /** 去重后仍在窗口内的活动条数。 */
  activities: number;
  /** 这些活动在窗口内实际占用的日历天数（同一活动跨多天只按天累计一次）。 */
  coveredDays: number;
  /** 窗口内的活动按状态拆分。 */
  phases: Record<EventPhase, number>;
  /** 因缺少已核验坐标而无法上图的活动数。 */
  withoutCoordinates: number;
}

/**
 * 统计口径。活动数和覆盖天数是两个不同的量，所以分开返回，界面必须分别标注；
 * 把它们合并成一个「活动数」正是之前各页面对不上的原因。
 */
export function caliberCounts(
  window: TimeWindow,
  windowEvents: Event[],
  hasCoordinates: (event: Event) => boolean,
): CaliberCounts {
  const daySet = new Set<string>();
  const phases: Record<EventPhase, number> = { upcoming: 0, ongoing: 0, ended: 0 };
  let withoutCoordinates = 0;

  for (const event of windowEvents) {
    const range = dates(event);
    if (range) {
      const [start, end] = range;
      // Clamp to the window: an exhibition running all year must not inflate "covered days" with
      // days that are outside the period the user asked about.
      const from = Math.max(Date.parse(start + "T00:00:00Z"), Date.parse(window.start + "T00:00:00Z"));
      const to = Math.min(Date.parse(end + "T00:00:00Z"), Date.parse(window.end + "T00:00:00Z"));
      for (let time = from; time <= to; time += 86400000) {
        daySet.add(new Date(time).toISOString().slice(0, 10));
      }
    }
    phases[phaseOf(event, window)] += 1;
    if (!hasCoordinates(event)) withoutCoordinates += 1;
  }

  return {
    activities: windowEvents.length,
    coveredDays: daySet.size,
    phases,
    withoutCoordinates,
  };
}
