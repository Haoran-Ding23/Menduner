"""修复 api.ts 里被 shell 破坏的模板字符串：改成不含反引号的字符串拼接。"""
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "frontend" / "src" / "services" / "api.ts"
text = target.read_text(encoding="utf-8")

marker = "// ---- 商圈（business area）聚合"
index = text.find(marker)
if index == -1:
    raise SystemExit("  未找到商圈接口标记")
text = text[:index].rstrip() + "\n"

block = '''
// ---- 商圈（business area）聚合：数据来自后端 /market/*，前端不做距离计算 ----
export interface MarketCoverage {
  radiusMeters: number;
  areaCount: number;
  areaWithCenter: number;
  areaVerified: number;
  areaLowQuality: number;
  venuesTotal: number;
  venuesWithVerifiedCoords: number;
  eventsTotal: number;
  eventsNearby: number;
  eventsAmbiguous: number;
  eventsUnmatched: number;
  note: string;
}

export interface MarketAreaRow {
  id: string;
  name: string;
  parentName: string | null;
  quality: string;
  centerSource: string | null;
  radiusMeters: number;
  nearbyEvents: number;
  ambiguousEvents: number;
  parentDistrictEvents: number;
}

export interface MarketAreaProfile {
  area: {
    id: string;
    name: string;
    parentName: string | null;
    quality: string;
    radiusMeters: number;
    center: {
      lng: number;
      lat: number;
      system: string | null;
      source: string | null;
      matchedName: string | null;
      adname: string | null;
      matchLevel: string | null;
      matchedAt: string | null;
    };
  };
  window: { start: string | null; end: string | null };
  nearbyEvents: {
    identity: string;
    name: string;
    category: string;
    startDate: string;
    endDate: string | null;
    distanceMeters: number;
  }[];
  ambiguousEvents: {
    identity: string;
    name: string;
    category: string;
    startDate: string;
    endDate: string | null;
    distanceMeters: number;
  }[];
  coverage: {
    method: string;
    matched: number;
    matchedAll: number;
    ambiguous: number;
    ambiguousAll: number;
    parentDistrictEvents: number;
    unmatchedInParent: number;
    venuesWithVerifiedCoords: number;
    venuesTotal: number;
  };
  categories: [string, number][];
  months: [string, number][];
  hotels: { name: string; distanceMeters: number; starLabel: string | null }[];
  caveat: string;
}

function marketQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? "?" + text : "";
}

export async function loadMarketCoverage(radius?: number): Promise<MarketCoverage> {
  const response = await fetch("/api/market/coverage" + marketQuery({ radius }));
  if (!response.ok) throw new Error("商圈覆盖数据加载失败");
  return response.json();
}

export async function loadMarketAreas(radius?: number): Promise<MarketAreaRow[]> {
  const response = await fetch("/api/market/areas" + marketQuery({ radius }));
  if (!response.ok) throw new Error("商圈列表加载失败");
  const payload = await response.json();
  return (payload.areas ?? []) as MarketAreaRow[];
}

export async function loadMarketAreaProfile(
  id: string,
  params: { radius?: number; start?: string; end?: string } = {},
): Promise<MarketAreaProfile> {
  const response = await fetch(
    "/api/market/area/" + encodeURIComponent(id) + marketQuery(params),
  );
  if (!response.ok) throw new Error("商圈画像加载失败");
  return response.json();
}
'''

target.write_text(text + block, encoding="utf-8")
print("  api.ts 已修复（无模板字符串）")
