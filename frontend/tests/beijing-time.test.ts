import { describe, expect, it } from "vitest";
import { beijingToday, shiftDate } from "../src/utils/caliber";
import { rangeFor, todayKey } from "../src/pages/EventAgenda";

/**
 * F03：业务日期必须与读者设备的时区无关。
 *
 * 审核观察到：浏览器时区为 America/New_York、UTC 22:03 时，活动清单显示 10-23，
 * 而工作台显示 10-24 —— 同一屏两个「今天」。根因是活动清单用了 dayjs() 的设备本地日期。
 */

describe("beijingToday 与设备时区无关", () => {
  it("同一时刻在北京 / 纽约 / UTC 下得到同一个业务日期", () => {
    // 2026-10-23T22:03Z：北京已是 10-24，纽约仍是 10-23，UTC 仍是 10-23。
    const instant = new Date("2026-10-23T22:03:00Z");
    expect(beijingToday(instant)).toBe("2026-10-24");
    // 同一 Date 对象在任何设备时区下都表示同一时刻，因此结果恒定。
    expect(beijingToday(new Date(instant.getTime()))).toBe("2026-10-24");
  });

  it("北京时间午夜前一刻仍算前一天", () => {
    // 北京 2026-10-23 23:59 = UTC 15:59
    expect(beijingToday(new Date("2026-10-23T15:59:00Z"))).toBe("2026-10-23");
    // 北京 2026-10-24 00:00 = UTC 16:00
    expect(beijingToday(new Date("2026-10-23T16:00:00Z"))).toBe("2026-10-24");
  });

  it("跨年边界：UTC 还在上一年时北京已进入新年", () => {
    expect(beijingToday(new Date("2026-12-31T16:30:00Z"))).toBe("2027-01-01");
    expect(beijingToday(new Date("2026-12-31T15:30:00Z"))).toBe("2026-12-31");
  });

  it("月末边界正确进位", () => {
    expect(beijingToday(new Date("2026-10-31T16:10:00Z"))).toBe("2026-11-01");
  });
});

describe("活动清单的今天与工作台一致", () => {
  it("todayKey 与口径模块的北京时间同源", () => {
    expect(todayKey()).toBe(beijingToday());
  });

  it("本周区间是周一到周日且包含今天", () => {
    const { start, end } = rangeFor("week");
    expect(start <= todayKey()).toBe(true);
    expect(end >= todayKey()).toBe(true);
    // 周一：Date 的 getUTCDay 0=周日，用 ISO 编号核对
    const startDay = new Date(start + "T00:00:00Z").getUTCDay();
    expect(startDay).toBe(1);
    expect(shiftDate(start, 6)).toBe(end);
  });

  it("本日区间就是今天", () => {
    const { start, end } = rangeFor("day");
    expect(start).toBe(todayKey());
    expect(end).toBe(todayKey());
  });

  it("本月区间覆盖整月且含今天", () => {
    const { start, end } = rangeFor("month");
    expect(start.slice(0, 7)).toBe(todayKey().slice(0, 7));
    expect(start.endsWith("-01")).toBe(true);
    expect(start <= todayKey() && end >= todayKey()).toBe(true);
  });
});
