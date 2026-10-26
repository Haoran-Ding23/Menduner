import { describe, expect, it } from "vitest";
import {
  batchOf,
  beijingTimestamp,
  daysSince,
  provenanceOf,
} from "../src/utils/provenance";

/**
 * F12 验收（GPT Round 5）：①元数据来自真实字段；②缺失显示「未知」不猜；③北京时间明确、
 * 旧批次有提示。这里逐条覆盖，重点在「缺失时不编造」。
 */

describe("北京时间展示", () => {
  it("UTC 时间转成北京时间（跨零点）", () => {
    // UTC 2026-10-25T22:30Z = 北京 2026-10-26 06:30
    expect(beijingTimestamp("2026-10-25T22:30:00Z")).toBe("2026-10-26 06:30");
  });

  it("缺失或非法值显示「未知」，不回落到本地时区", () => {
    expect(beijingTimestamp(null)).toBe("未知");
    expect(beijingTimestamp(undefined)).toBe("未知");
    expect(beijingTimestamp("not-a-date")).toBe("未知");
  });
});

describe("批次标识", () => {
  it("由更新时间派生，格式稳定", () => {
    expect(batchOf("2026-10-26T06:20:00Z")).toBe("20261026" + "0620");
  });

  it("缺失时为「未知」", () => {
    expect(batchOf(null)).toBe("未知");
  });
});

describe("新鲜度", () => {
  it("计算距今天数（按 UTC 日期比较）", () => {
    expect(daysSince("2026-10-24T20:00:00Z", "2026-10-26")).toBe(2);
  });

  it("无法计算时返回 null，而不是 0", () => {
    expect(daysSince(null, "2026-10-26")).toBeNull();
    expect(daysSince("bad", "2026-10-26")).toBeNull();
  });

  it("超过阈值标记过期并给出提示", () => {
    const stale = provenanceOf({ updatedAt: "2026-10-20T00:00:00Z", today: "2026-10-26" });
    expect(stale.stale).toBe(true);
    expect(stale.note).toContain("天未更新");
  });

  it("新鲜数据不提示过期", () => {
    const fresh = provenanceOf({ updatedAt: "2026-10-26T01:00:00Z", today: "2026-10-26" });
    expect(fresh.stale).toBe(false);
    expect(fresh.note).toBe("");
  });

  it("更新时间未知时不误判为过期", () => {
    const unknown = provenanceOf({ updatedAt: null, today: "2026-10-26" });
    expect(unknown.stale).toBe(false);
    expect(unknown.updatedLabel).toBe("未知");
    expect(unknown.batchId).toBe("未知");
    expect(unknown.note).toContain("未知");
  });

  it("口径版本来自后端，缺失显示「未知」", () => {
    expect(provenanceOf({ today: "2026-10-26" }).caliberVersion).toBe("未知");
    expect(
      provenanceOf({ today: "2026-10-26", caliberVersion: "2026.10-caliber1-geo1-dedupe1" })
        .caliberVersion,
    ).toBe("2026.10-caliber1-geo1-dedupe1");
  });
});
