import { describe, expect, it } from "vitest";
import { normalizeEvent } from "../src/services/adapter";
import { canonicalIdOf, distinctByCanonical } from "../src/utils/dedupe";
import type { Event } from "../src/types";

/**
 * F04：接口返回的 canonicalId 必须一路传到前端，否则所有「按身份统计」的逻辑都会退化成
 * 「按记录数统计」。
 *
 * 线上实际发生过这个错：适配器只在场馆映射里带了 canonicalId，事件映射漏了，于是同一场
 * 文津图书展的两条来源记录在工作台各占一行（审核报告 F04 的复现现象）。
 */

const raw = (overrides: Record<string, unknown> = {}) => ({
  id: "evt-a",
  name: "书海观澜,文津拾贝——第二十一届文津图书展",
  category: "culture",
  startDate: "2026-09-16",
  endDate: "2026-10-31",
  canonicalId: "evt-a",
  ...overrides,
});

describe("normalizeEvent 保留去重身份", () => {
  it("camelCase 与 snake_case 两种写法都能读到", () => {
    expect(normalizeEvent(raw(), 0).canonicalId).toBe("evt-a");
    expect(normalizeEvent(raw({ canonicalId: undefined, canonical_id: "evt-a" }), 0).canonicalId).toBe(
      "evt-a",
    );
  });

  it("没有该字段时为 undefined，由 canonicalIdOf 回落到自身 id", () => {
    const event = normalizeEvent(raw({ canonicalId: undefined }), 0);
    expect(event.canonicalId).toBeUndefined();
    expect(canonicalIdOf(event)).toBe(event.id);
  });
});

describe("distinctByCanonical 合并同一身份", () => {
  const make = (id: string, canonicalId?: string, name = "活动"): Event =>
    ({ id, canonicalId, name, category: "culture", startDate: "2026-09-16", endDate: "2026-10-31" }) as Event;

  it("两条来源记录只保留规范记录", () => {
    const records = [make("evt-a"), make("evt-b", "evt-a", "场馆:活动")];
    const kept = distinctByCanonical(records);
    expect(kept).toHaveLength(1);
    expect(kept[0].id).toBe("evt-a");
  });

  it("规范记录排在后面时仍然保留规范记录", () => {
    const records = [make("evt-b", "evt-a", "场馆:活动"), make("evt-a")];
    expect(distinctByCanonical(records)[0].id).toBe("evt-a");
  });

  it("不同身份不会合并", () => {
    expect(distinctByCanonical([make("evt-a"), make("evt-c")])).toHaveLength(2);
  });

  it("同一身份三条记录只留一条", () => {
    const records = [make("evt-a"), make("evt-b", "evt-a"), make("evt-c", "evt-a")];
    expect(distinctByCanonical(records)).toHaveLength(1);
  });
});
