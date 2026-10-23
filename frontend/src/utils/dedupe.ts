import type { Event } from "../types";

/**
 * 按「去重后的活动身份」统计。
 *
 * 后端把同一活动在不同来源下的多条记录用 canonical_id 归到一起（backend/dedupe.py），接口里每条
 * 记录都带 canonicalId。前端如果继续数记录条数，就会把「同一活动被两个来源收录」当成两场活动 ——
 * 地图热点、附近活动、商圈统计、周报会一起偏高。
 *
 * 这个模块是唯一入口：所有面向用户的计数都先过 distinctByCanonical。
 */

export function canonicalIdOf(event: Event): string {
  return event.canonicalId || event.id;
}

/**
 * 同一身份只保留一条代表记录。
 *
 * 优先保留「规范记录」（id === canonicalId），因为后端挑它时已经按「有场馆 > 日期更完整 > id」
 * 排过序；找不到规范记录时保留第一条，保证结果稳定而不是随数组顺序抖动。
 */
export function distinctByCanonical(events: Event[]): Event[] {
  const chosen = new Map<string, Event>();
  for (const event of events) {
    const key = canonicalIdOf(event);
    const current = chosen.get(key);
    if (!current) {
      chosen.set(key, event);
      continue;
    }
    const eventIsCanonical = event.id === key;
    const currentIsCanonical = current.id === key;
    if (eventIsCanonical && !currentIsCanonical) {
      chosen.set(key, event);
    }
  }
  return [...chosen.values()];
}

/** 该身份在原始记录里出现了几次（用于界面标注「另有 N 个来源」）。 */
export function sourceCount(events: Event[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const event of events) {
    const key = canonicalIdOf(event);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}
