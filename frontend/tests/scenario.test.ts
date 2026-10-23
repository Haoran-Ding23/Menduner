import { describe, expect, it } from "vitest";
import { computeScenarios, formatMoney, validateScenario } from "../src/services/scenario";

/**
 * 这组测试对应 2026-10-24 审核报告 F01 / F02。
 *
 * 审核给出的验收例写成断言：
 *   1000 位不重复访客、住宿比例 20%、每人住 1 晚、每间 2 人、房价 500 元
 *   → 市场 100 间夜、住宿支出 50000 元；
 *     本店份额 10% → 10 间夜、5000 元；20% → 20 间夜、10000 元，且市场总额不变。
 */

const auditExample = {
  visitors: 1000,
  stayShare: 0.2,
  avgNights: 1,
  guestsPerRoom: 2,
  marketRate: 500,
  hotelShare: 0.1,
  spendPerVisitor: 200,
};

const mid = (input: Parameters<typeof computeScenarios>[0]) =>
  computeScenarios(input).scenarios.find((scenario) => scenario.key === "mid")!;

describe("F01 市场与分配的关系", () => {
  it("审核验收例：市场 100 间夜 / 50000 元，本店 10 间夜 / 5000 元", () => {
    const scenario = mid(auditExample);
    expect(scenario.marketRoomNights).toBe(100);
    expect(scenario.marketLodgingSpend).toBe(50000);
    expect(scenario.hotelRoomNights).toBe(10);
    expect(scenario.hotelRevenue).toBe(5000);
  });

  it("本店份额改成 20% 只影响本店，市场规模不变", () => {
    const ten = mid(auditExample);
    const twenty = mid({ ...auditExample, hotelShare: 0.2 });
    expect(twenty.marketRoomNights).toBe(100);
    expect(twenty.marketLodgingSpend).toBe(50000);
    expect(twenty.hotelRoomNights).toBe(20);
    expect(twenty.hotelRevenue).toBe(10000);
    expect(ten.marketLodgingSpend).toBe(twenty.marketLodgingSpend);
  });

  it("平均住宿晚数直接放大市场间夜", () => {
    const twoNights = mid({ ...auditExample, avgNights: 2 });
    expect(twoNights.marketRoomNights).toBe(200);
    expect(twoNights.marketLodgingSpend).toBe(100000);
  });

  it("本店房价与市场房价分开计算收入", () => {
    const scenario = mid({ ...auditExample, hotelRate: 800 });
    // 间夜不变，收入按本店房价
    expect(scenario.hotelRoomNights).toBe(10);
    expect(scenario.hotelRevenue).toBe(8000);
    expect(scenario.marketLodgingSpend).toBe(50000);
  });

  it("用的是不重复访客而不是累计人次：人数不因住宿晚数被重复计入", () => {
    const one = mid({ ...auditExample, avgNights: 1 });
    const three = mid({ ...auditExample, avgNights: 3 });
    // 市场住宿支出随住宿晚数线性增长，但访客数本身不变
    expect(three.marketLodgingSpend).toBe(one.marketLodgingSpend * 3);
    expect(three.visitors).toBe(one.visitors);
  });

  it("声明总消费含住宿时，住宿支出大于总消费会被标为不一致而不是静默截断", () => {
    const result = computeScenarios({ ...auditExample, spendPerVisitor: 10, spendIncludesLodging: true });
    expect(result.ok).toBe(true);
    expect(result.consistent).toBe(false);
    expect(result.issues.some((issue) => issue.field === "spendIncludesLodging")).toBe(true);
    // 金额保留原值，不被裁剪
    expect(result.scenarios[1].marketLodgingSpend).toBe(50000);
  });

  it("未声明含住宿时不做包含关系校验", () => {
    const result = computeScenarios({ ...auditExample, spendPerVisitor: 10 });
    expect(result.consistent).toBe(true);
  });

  it("低中高是参数情景，不是置信区间", () => {
    const result = computeScenarios(auditExample);
    expect(result.scenarios.map((item) => item.factor)).toEqual([0.6, 1, 1.4]);
    expect(result.formula.join()).toContain("不是置信区间");
  });
});

describe("F02 输入校验", () => {
  it("住宿比例超过 1 直接拒绝计算", () => {
    const result = computeScenarios({ ...auditExample, stayShare: 1.2 });
    expect(result.ok).toBe(false);
    expect(result.scenarios).toEqual([]);
    expect(result.issues[0].field).toBe("stayShare");
  });

  it("本店份额超过 1 直接拒绝计算", () => {
    const result = computeScenarios({ ...auditExample, hotelShare: 1.5 });
    expect(result.ok).toBe(false);
  });

  it("比例恰好 0 与 1 都合法", () => {
    expect(computeScenarios({ ...auditExample, stayShare: 0 }).ok).toBe(true);
    expect(computeScenarios({ ...auditExample, hotelShare: 1 }).ok).toBe(true);
  });

  it("负数被拒绝", () => {
    const result = computeScenarios({ ...auditExample, visitors: -1 });
    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.field === "visitors")).toBe(true);
  });

  it("每间入住人数为 0 被拒绝（避免除零）", () => {
    const result = computeScenarios({ ...auditExample, guestsPerRoom: 0 });
    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.message.includes("除零"))).toBe(true);
  });

  it("空值不会被当成 0", () => {
    const result = computeScenarios({ ...auditExample, avgNights: null });
    expect(result.ok).toBe(false);
    expect(result.scenarios).toEqual([]);
  });

  it("Infinity 视为无效", () => {
    const result = computeScenarios({ ...auditExample, visitors: Number.POSITIVE_INFINITY });
    expect(result.ok).toBe(false);
  });

  it("一次列出所有缺失参数", () => {
    const issues = validateScenario({
      visitors: null,
      stayShare: null,
      avgNights: null,
      guestsPerRoom: null,
      marketRate: null,
      hotelShare: null,
      spendPerVisitor: null,
    });
    expect(issues.filter((issue) => issue.level === "error")).toHaveLength(7);
  });
});

describe("formatMoney", () => {
  it("超过一万按万元保留一位小数", () => {
    expect(formatMoney(50000)).toBe("5.0 万元");
  });

  it("不足一万按元", () => {
    expect(formatMoney(8600)).toBe("8600 元");
  });

  it("非法值显示破折号", () => {
    expect(formatMoney(Number.NaN)).toBe("—");
  });
});
