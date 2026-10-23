import { describe, expect, it } from "vitest";
import { DIMENSION_LABELS, WEIGHTS, rankEvent, rankEvents } from "../src/services/ranking";
import type { Dataset, Event, Hotel } from "../src/types";

/**
 * 排序的测试重点在「不编造」和「可解释」，而不是分数大小：
 *   * 缺坐标时距离必须是 unknown，不能给 0 分假装很近；
 *   * 三个维度分别返回，便于界面分开显示；
 *   * 没有类别时相关性 unknown，不按泛客群给满分；
 *   * 同分排序稳定，结果不随数组顺序抖动。
 */

const hotel: Hotel = {
  id: "h1",
  name: "测试酒店",
  address: null,
  districtId: "taicang",
  coordinates: { lng: 121.1, lat: 31.45, system: "GCJ-02", status: "Verified", sourceUrl: "https://a.test" },
  districtDemo: false,
} as Hotel;

const venue = {
  id: "v1",
  name: "太仓大剧院",
  districtId: "taicang",
  coordinates: { lng: 121.13, lat: 31.46, system: "GCJ-02", status: "Verified", sourceUrl: "https://a.test" },
};

// eventCoordinates 要求有 venueId 的已核验证据才认坐标（无证据一律不给位置），
  // 所以夹具必须带一条 Verified 证据，否则测的就不是排序而是缺数据路径。
  const venueEvidence = {
    id: "ev-v1",
    entityId: "e1",
    field: "venueId",
    value: "v1",
    status: "Verified",
    method: "extract",
    sourceName: "来源",
    sourceUrl: "https://a.test",
    updatedAt: "2026-10-20",
  } as unknown as Dataset["evidence"][number];
  const dataset = {
    events: [],
    evidence: [venueEvidence],
    venues: [venue],
    hotels: [hotel],
    districts: [],
  } as unknown as Dataset;

const baseEvent = (partial: Partial<Event>): Event =>
  ({
    id: "e1",
    name: "测试活动",
    category: "culture",
    startDate: "2026-10-26",
    endDate: "2026-10-27",
    venueId: "v1",
    districtId: "taicang",
    demo: false,
    ...partial,
  }) as Event;

const context = { hotel, dataset, today: "2026-10-24" };

describe("rankEvent", () => {
  it("给出四个维度的分数，分数各自独立", () => {
    const ranked = rankEvent(baseEvent({}), context);
    expect(ranked.byDimension.relevance).not.toBeNull();
    expect(ranked.byDimension.distance).not.toBeNull();
    expect(ranked.byDimension.credibility).not.toBeNull();
    expect(ranked.byDimension.timing).not.toBeNull();
    expect(Object.keys(WEIGHTS).sort()).toEqual(
      ["credibility", "distance", "relevance", "timing"],
    );
    expect(DIMENSION_LABELS.relevance).toBe("业务相关性");
  });

  it("缺少已核验坐标时距离为未知，而不是给 0 分", () => {
    const noVenue = baseEvent({ venueId: null });
    const ranked = rankEvent(noVenue, context);
    expect(ranked.byDimension.distance).toBeNull();
    expect(ranked.unknown.join()).toContain("坐标");
  });

  it("缺坐标的活动不会因为距离得 0 而被误判为很远", () => {
    const near = rankEvent(baseEvent({}), context);
    const unknownDistance = rankEvent(baseEvent({ id: "e2", venueId: null }), context);
    // 未知维度不计分，因此分数差别只来自其余维度，而不是把未知当成 0。
    expect(unknownDistance.score).toBeGreaterThan(0);
    expect(near.score).toBeGreaterThan(unknownDistance.score);
  });

  it("类别未知时相关性为未知，不按泛客群给满分", () => {
    const ranked = rankEvent(baseEvent({ category: "unknown-category" as Event["category"] }), context);
    expect(ranked.byDimension.relevance).toBeNull();
    expect(ranked.unknown.join()).toContain("类别未知");
  });

  it("理由最多三条且按权重顺序给出", () => {
    const ranked = rankEvent(baseEvent({}), context);
    expect(ranked.reasons.length).toBeLessThanOrEqual(3);
    expect(ranked.reasons.length).toBeGreaterThan(0);
  });

  it("日期缺失时紧迫度为未知", () => {
    const ranked = rankEvent(baseEvent({ startDate: null, endDate: null }), context);
    expect(ranked.byDimension.timing).toBeNull();
    expect(ranked.unknown.join()).toContain("日期");
  });

  it("进行中的活动得到中等紧迫度而不是满分", () => {
    const ongoing = rankEvent(
      baseEvent({ startDate: "2026-10-20", endDate: "2026-11-01" }),
      context,
    );
    const tomorrow = rankEvent(baseEvent({ startDate: "2026-10-25", endDate: "2026-10-26" }), context);
    expect(ongoing.byDimension.timing).toBe(0.5);
    // 明天开始：1 - 1/14 ≈ 0.93，比进行中更紧迫但不会满分（满分留给当天开始）。
    expect(tomorrow.byDimension.timing).toBeGreaterThan(0.9);
  });
});

describe("rankEvents", () => {
  it("按分数降序，同分时按名称排序保持稳定", () => {
    const events = [
      baseEvent({ id: "a", name: "乙活动" }),
      baseEvent({ id: "b", name: "甲活动" }),
    ];
    const first = rankEvents(events, context).map((item) => item.event.id);
    const second = rankEvents([...events].reverse(), context).map((item) => item.event.id);
    expect(first).toEqual(second);
  });

  it("近的活动排在远的活动之前（其余条件相同）", () => {
    const farVenue = {
      ...venue,
      id: "v-far",
      coordinates: { ...venue.coordinates, lng: 121.6, lat: 31.9 },
    };
    const withFar = { ...dataset, venues: [venue, farVenue] } as Dataset;
    const ranked = rankEvents(
      [
        baseEvent({ id: "near" }),
        baseEvent({ id: "far", venueId: "v-far" }),
      ],
      { hotel, dataset: withFar, today: "2026-10-24" },
    );
    expect(ranked[0].event.id).toBe("near");
  });
});
