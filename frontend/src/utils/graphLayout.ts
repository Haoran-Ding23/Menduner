/**
 * 图谱「太阳发散」布局（GPT Round 35 规格）。
 *
 * 抽成纯函数，便于用单元测试证明规则本身正确，而不是靠截图肉眼判断：
 *  - 5 个扇区各 72°，从正上方顺时针：酒店/餐饮/交通/购物/其他，两侧各留 6°；
 *  - 距离分环：0–500m / 500–1500m / 1500–3000m，环内按距离线性映射半径；
 *  - 角度 θi = θmin + (i + 0.5) / n × (θmax − θmin)，保证同一输入永远得到同一位置；
 *  - 坐标 x = cx + r·sinθ，y = cy − r·cosθ（θ 从正上方顺时针）。
 */

export type Sector = [number, number];

export const SECTOR_MARGIN = 6;

/** 类别 → 扇区角度（度，从正上方顺时针）。未知类别归入「其他」，绝不猜。 */
export const SECTORS: Record<string, Sector> = {
  Hotel: [324, 36],
  Restaurant: [36, 108],
  Transport: [108, 180],
  Shopping: [180, 252],
  Other: [252, 324],
};

export const MAX_NEARBY_NODES = 30;
export const MAX_DISTANCE_METERS = 3000;

/** 距离环：上限（米）与对应的半径区间（像素）。 */
export const RINGS: { max: number; from: number; to: number }[] = [
  { max: 500, from: 230, to: 330 },
  { max: 1500, from: 350, to: 480 },
  { max: 3000, from: 500, to: 640 },
];

export function sectorOf(kind: string): Sector {
  return SECTORS[kind] ?? SECTORS.Other;
}

/** 把扇区换算成可能跨 0° 的连续区间（例如 324→396）。 */
export function sectorRange(kind: string): [number, number] {
  const [rawFrom, rawTo] = sectorOf(kind);
  const from = rawFrom + SECTOR_MARGIN;
  const to = (rawTo <= rawFrom ? rawTo + 360 : rawTo) - SECTOR_MARGIN;
  return [from, to];
}

/**
 * 距离 → 半径。超出 3000m 返回 null（超过最外环不画，避免把远处设施塞进图里）。
 */
export function radiusForDistance(meters: number | null | undefined): number | null {
  if (meters === null || meters === undefined || Number.isNaN(meters)) return null;
  if (meters < 0 || meters > MAX_DISTANCE_METERS) return null;
  let lowerBound = 0;
  for (const ring of RINGS) {
    if (meters <= ring.max) {
      const span = ring.max - lowerBound;
      const ratio = span <= 0 ? 0 : (meters - lowerBound) / span;
      return ring.from + (ring.to - ring.from) * Math.min(1, Math.max(0, ratio));
    }
    lowerBound = ring.max;
  }
  return RINGS[RINGS.length - 1].to;
}

/** 扇区内第 index 个（共 total 个）节点的角度。 */
export function angleInSector(kind: string, index: number, total: number): number {
  const [from, to] = sectorRange(kind);
  const span = to - from;
  if (total <= 0) return ((from + to) / 2) % 360;
  return (from + ((index + 0.5) / total) * span) % 360;
}

/** 极坐标 → 画布坐标（θ 从正上方顺时针）。 */
export function polarFromTop(thetaDeg: number, radius: number): { x: number; y: number } {
  const rad = (thetaDeg * Math.PI) / 180;
  return { x: Math.sin(rad) * radius, y: -Math.cos(rad) * radius };
}

/** 一个周边设施的布局结果。 */
export interface PlacedNode {
  id: string;
  kind: string;
  meters: number;
  theta: number;
  radius: number;
  x: number;
  y: number;
}

/**
 * 给一批周边设施算位置：
 *  - 按「类别 → 扇区」，同扇区内按「距离升序、稳定 id 升序」；
 *  - 超过 maxNodes 的截断（返回 hiddenCount 供界面显示"更多 N 个"）；
 *  - 没有距离或超过 3000m 的一律不画。
 */
export function placeNearby(
  items: { id: string; kind: string; meters: number | null | undefined }[],
  options: { maxNodes?: number } = {},
): { placed: PlacedNode[]; hiddenCount: number } {
  const maxNodes = options.maxNodes ?? MAX_NEARBY_NODES;
  const usable = items
    .filter((item) => typeof item.meters === "number" && radiusForDistance(item.meters) !== null)
    .sort((a, b) => (a.meters! - b.meters!) || a.id.localeCompare(b.id));

  const kept = usable.slice(0, maxNodes);
  const hiddenCount = Math.max(0, usable.length - kept.length);

  const groups = new Map<string, typeof kept>();
  kept.forEach((item) => {
    const kind = SECTORS[item.kind] ? item.kind : "Other";
    const bucket = groups.get(kind) ?? [];
    bucket.push(item);
    groups.set(kind, bucket);
  });

  const placed: PlacedNode[] = [];
  groups.forEach((bucket, kind) => {
    bucket
      .slice()
      .sort((a, b) => (a.meters! - b.meters!) || a.id.localeCompare(b.id))
      .forEach((item, index) => {
        const theta = angleInSector(kind, index, bucket.length);
        const radius = radiusForDistance(item.meters)!;
        const { x, y } = polarFromTop(theta, radius);
        placed.push({ id: item.id, kind, meters: item.meters!, theta, radius, x, y });
      });
  });
  return { placed, hiddenCount };
}
