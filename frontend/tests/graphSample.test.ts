import { describe, expect, it } from "vitest";
import { multiDayCaveat, placeKind, selectGraphSample } from "../src/utils/graphSample";
import type { Dataset, Event } from "../src/types";

/**
 * F06 验收（GPT Round 8）：
 *  ① 默认样例必须来自真实数据、关系完整，选择规则可复核，不能硬编码不存在的关系；
 *  ② 机场/航站楼/接驳站类型必须有证据才认，缺证据显示待补充；
 *  ③ 多日展览不得推断住宿/客流/经济贡献。
 */

const event = (over: Partial<Event> & { id: string }): Event =>
  ({
    name: over.name ?? over.id,
    category: "culture",
    startDate: "2026-11-01",
    endDate: "2026-11-02",
    venueId: null,
    districtId: null,
    demo: false,
    ...over,
  }) as Event;

const venue = (id: string, withCoords: boolean) => ({
  id,
  name: `场馆-${id}`,
  districtId: null,
  districtDemo: false,
  coordinates: withCoords
    ? { lng: 121.1, lat: 31.4, system: "GCJ-02", status: "Verified", sourceUrl: "https://a.test" }
    : null,
});

const makeDataset = (events: Event[], venues: unknown[], evidence: unknown[] = []) =>
  ({ events, venues, evidence, hotels: [], districts: [] }) as unknown as Dataset;

describe("默认样例选择", () => {
  it("优先选关系最完整的真实活动", () => {
    const dataset = makeDataset(
      [
        event({ id: "poor" }),
        event({ id: "rich", venueId: "v1", districtId: "d1" }),
      ],
      [venue("v1", true)],
    );
    const sample = selectGraphSample(dataset);
    expect(sample.eventId).toBe("rich");
    expect(sample.reasons.join()).toContain("场馆已关联");
    expect(sample.candidates).toBe(2);
  });

  it("同分时按 id 排序，结果可复现", () => {
    const dataset = makeDataset(
      [event({ id: "b", venueId: "v1", districtId: "d1" }), event({ id: "a", venueId: "v1", districtId: "d1" })],
      [venue("v1", true)],
    );
    expect(selectGraphSample(dataset).eventId).toBe("a");
  });

  it("排除演示数据，不拿 DEMO 当样例", () => {
    const dataset = makeDataset([event({ id: "demo", demo: true, venueId: "v1" })], [venue("v1", true)]);
    const sample = selectGraphSample(dataset);
    expect(sample.eventId).toBeNull();
    expect(sample.reasons[0]).toContain("没有可用的真实活动");
  });

  it("没有场馆时如实说明，而不是编一个", () => {
    const sample = selectGraphSample(makeDataset([event({ id: "x" })], []));
    expect(sample.eventId).toBe("x");
    expect(sample.reasons.join()).toContain("未关联场馆");
    expect(sample.reasons.join()).toContain("地区待补充");
  });

  it("跨来源记录计入关系完整度", () => {
    const dataset = makeDataset(
      [
        event({ id: "canon", venueId: "v1", districtId: "d1" }),
        event({ id: "dup", venueId: "v1", districtId: "d1", canonicalId: "canon" }),
      ],
      [venue("v1", true)],
    );
    expect(selectGraphSample(dataset).reasons.join()).toContain("个来源记录");
  });
});

describe("场所类型（机场 / 航站楼 / 接驳站）", () => {
  it("有证据才认类型", () => {
    expect(placeKind("机场").kind).toBe("airport");
    expect(placeKind("T2航站楼").kind).toBe("terminal");
    expect(placeKind("机场接驳站").kind).toBe("shuttle");
  });

  it("缺类型显示待补充，不猜测", () => {
    expect(placeKind(null)).toEqual({ kind: "unknown", label: "类型待补充" });
    expect(placeKind("other").label).toBe("类型待补充");
  });
});

describe("多日展览口径", () => {
  it("说明供给持续，同时明确不构成住宿或经济推断", () => {
    const caveat = multiDayCaveat("2026-09-16", "2026-10-31");
    expect(caveat).toContain("持续");
    expect(caveat).toContain("不构成");
    expect(caveat).toContain("住宿");
  });

  it("单日活动不给提示", () => {
    expect(multiDayCaveat("2026-11-01", "2026-11-01")).toBeNull();
  });
});
