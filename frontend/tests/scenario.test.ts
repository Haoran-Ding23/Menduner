import { describe, expect, it } from "vitest";
import { computeScenarios, formatMoney } from "../src/services/scenario";

/**
 * 情景估算的测试关注两件事：
 *   * 缺关键参数时必须**不出金额**（这是"不输出貌似精确数字"的硬约束）；
 *   * 三个情景与计算过程可复核 —— 给定参数，结果要能用手算对上。
 */

const complete = {
  attendance: 5000,
  spendPerVisitor: 200,
  stayShare: 0.4,
  roomRate: 500,
  hotelShare: 0.2,
};

describe("computeScenarios", () => {
  it("缺少任一关键参数时不给出金额，只列出缺少什么", () => {
    const result = computeScenarios({ ...complete, attendance: null });
    expect(result.ok).toBe(false);
    expect(result.missing).toContain("预计到场人次");
    expect(result.scenarios).toEqual([]);
  });

  it("缺住宿相关参数时同样拒绝估算", () => {
    const result = computeScenarios({ ...complete, stayShare: null, roomRate: null });
    expect(result.ok).toBe(false);
    expect(result.missing).toEqual(["需住宿比例", "平均房价"]);
  });

  it("三个情景按 60% / 100% / 140% 展开", () => {
    const result = computeScenarios(complete);
    expect(result.ok).toBe(true);
    expect(result.scenarios.map((s) => s.factor)).toEqual([0.6, 1, 1.4]);
    expect(result.scenarios.map((s) => s.attendance)).toEqual([3000, 5000, 7000]);
  });

  it("中情景的金额可以手算复核", () => {
    const mid = computeScenarios(complete).scenarios.find((s) => s.key === "mid")!;
    // 5000 人次 × 40% 需住宿 = 2000 人；每间 2 人 → 1000 间夜
    expect(mid.roomNights).toBe(1000);
    // 本店份额 20% → 周边住宿总额 = 1000 / 0.2 × 500 = 2,500,000 元
    expect(mid.lodgingSpend).toBe(2_500_000);
    // 本店住宿收入 = 总额 × 20% = 500,000 元
    expect(mid.hotelRevenue).toBe(500_000);
    // 商圈整体消费 = 5000 × 200 = 1,000,000 元
    expect(mid.districtSpend).toBe(1_000_000);
  });

  it("明确声明是情景估算而非净新增收益", () => {
    const result = computeScenarios(complete);
    expect(result.note).toContain("不是观测结果");
    expect(result.note).toContain("净新增");
    expect(result.formula.length).toBeGreaterThanOrEqual(4);
  });

  it("本店份额为 0 时不反推周边总额，避免除零产生无穷大", () => {
    const result = computeScenarios({ ...complete, hotelShare: 0 });
    const mid = result.scenarios.find((s) => s.key === "mid")!;
    expect(mid.lodgingSpend).toBe(0);
    expect(mid.hotelRevenue).toBe(0);
  });
});

describe("formatMoney", () => {
  it("超过一万按万元并保留一位小数", () => {
    expect(formatMoney(2_500_000)).toBe("250.0 万元");
  });

  it("不足一万按元展示，不出现小数", () => {
    expect(formatMoney(8600)).toBe("8600 元");
  });

  it("非法值显示破折号而不是 NaN", () => {
    expect(formatMoney(Number.NaN)).toBe("—");
  });
});
