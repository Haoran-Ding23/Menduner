import { describe, expect, it } from "vitest";
import {
  MAX_NEARBY_NODES,
  angleInSector,
  placeNearby,
  polarFromTop,
  radiusForDistance,
  sectorRange,
} from "../src/utils/graphLayout";

/**
 * 图谱「太阳发散」布局的规则测试（GPT Round 35 规格）。
 * 这些断言证明的是"规则本身对"，不依赖浏览器渲染。
 */
describe("graph radial layout (GPT Round 35 spec)", () => {
  it("五个扇区从正上方顺时针排布，且两侧各留 6°", () => {
    expect(sectorRange("Hotel")).toEqual([330, 390]);      // 324+6, 36+360-6
    expect(sectorRange("Restaurant")).toEqual([42, 102]);  // 36+6, 108-6
    expect(sectorRange("Transport")).toEqual([114, 174]);
    expect(sectorRange("Shopping")).toEqual([186, 246]);
    expect(sectorRange("Other")).toEqual([258, 318]);
  });

  it("未知类别归入「其他」，不会被猜成酒店或餐饮", () => {
    expect(sectorRange("Airport")).toEqual(sectorRange("Other"));
  });

  it("酒店扇区在正上方附近（θ 接近 0/360），交通在正下方附近", () => {
    const hotelMid = (sectorRange("Hotel")[0] + sectorRange("Hotel")[1]) / 2 % 360;
    expect(hotelMid < 30 || hotelMid > 330).toBe(true);
    const transportMid = (sectorRange("Transport")[0] + sectorRange("Transport")[1]) / 2;
    expect(transportMid).toBeGreaterThan(120);
    expect(transportMid).toBeLessThan(170);
  });

  it("距离分三环，环内半径单调递增，超过 3000m 不画", () => {
    const near = radiusForDistance(100)!;
    const nearEdge = radiusForDistance(500)!;
    const mid = radiusForDistance(800)!;
    const outer = radiusForDistance(2000)!;
    expect(near).toBeGreaterThanOrEqual(230);
    expect(nearEdge).toBeLessThanOrEqual(330);
    expect(mid).toBeGreaterThan(nearEdge);          // 跨环必须更远
    expect(outer).toBeGreaterThan(mid);
    expect(radiusForDistance(3001)).toBeNull();
    expect(radiusForDistance(null)).toBeNull();
    expect(radiusForDistance(undefined)).toBeNull();
  });

  it("极坐标从正上方顺时针：0° 在正上方，90° 在正右方", () => {
    const top = polarFromTop(0, 100);
    expect(Math.abs(top.x)).toBeLessThan(1e-9);
    expect(Math.round(top.y)).toBe(-100);
    const right = polarFromTop(90, 100);
    expect(Math.round(right.x)).toBe(100);
    expect(Math.abs(right.y)).toBeLessThan(1e-9);
  });

  it("同一扇区内角度按数量均匀分布，且落在扇区内", () => {
    const [from, to] = sectorRange("Restaurant");
    const angles = [0, 1, 2].map((i) => angleInSector("Restaurant", i, 3));
    angles.forEach((angle) => {
      expect(angle).toBeGreaterThanOrEqual(from);
      expect(angle).toBeLessThanOrEqual(to);
    });
    expect(angles[0]).toBeLessThan(angles[1]);
    expect(angles[1]).toBeLessThan(angles[2]);
  });

  it("同一输入永远得到同一位置（可复现，不随机）", () => {
    const items = [
      { id: "h2", kind: "Hotel", meters: 900 },
      { id: "h1", kind: "Hotel", meters: 300 },
      { id: "r1", kind: "Restaurant", meters: 400 },
      { id: "t1", kind: "Transport", meters: 1200 },
      { id: "x1", kind: "Unknown", meters: 200 },
    ];
    const first = placeNearby(items);
    const second = placeNearby([...items].reverse());
    expect(JSON.stringify(first)).toEqual(JSON.stringify(second));
  });

  it("没有坐标/超范围的不进环，超过 30 个的折叠并报数量", () => {
    const many = Array.from({ length: MAX_NEARBY_NODES + 5 }, (_, index) => ({
      id: "h" + index,
      kind: "Hotel",
      meters: 100 + index * 10,
    }));
    const withBad = [...many, { id: "no-coord", kind: "Hotel", meters: null }, { id: "too-far", kind: "Hotel", meters: 9000 }];
    const result = placeNearby(withBad);
    expect(result.placed).toHaveLength(MAX_NEARBY_NODES);
    expect(result.hiddenCount).toBe(5);
    expect(result.placed.some((item) => item.id === "no-coord")).toBe(false);
    expect(result.placed.some((item) => item.id === "too-far")).toBe(false);
  });

  it("酒店落在酒店扇区、餐饮落在餐饮扇区（不会互换）", () => {
    const { placed } = placeNearby([
      { id: "h1", kind: "Hotel", meters: 300 },
      { id: "r1", kind: "Restaurant", meters: 300 },
      { id: "t1", kind: "Transport", meters: 300 },
    ]);
    const hotel = placed.find((item) => item.id === "h1")!;
    const restaurant = placed.find((item) => item.id === "r1")!;
    const transport = placed.find((item) => item.id === "t1")!;
    expect(hotel.theta < 40 || hotel.theta > 320).toBe(true);
    expect(restaurant.theta).toBeGreaterThan(40);
    expect(restaurant.theta).toBeLessThan(110);
    expect(transport.theta).toBeGreaterThan(110);
    expect(transport.theta).toBeLessThan(180);
  });
});
