"""12 轮第 6 轮（地图）：加「查看商圈」开关——默认关，打开只出点，点中心才出范围圆与摘要。

GPT Round 32 第 6 轮要求与验收：53 个中心可选；仅选中中心有范围圆；关闭后完全消失。

实现：
1. EventMap 增加 areas / selectedArea / onAreaSelect 三个 prop：
   打开时画中心点（官方蓝实心、参考青空心），选中项画 800 米半透明圆；
2. 地图页新增「查看商圈」开关（默认 false）与选中摘要行；
3. 关闭时整层移除（不残留 marker / circle）。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---------- 1) Map 组件 ----------
mp = root / "frontend" / "src" / "components" / "Map" / "index.tsx"
m = mp.read_text(encoding="utf-8")

if "areasLayer" not in m:
    m = m.replace("""  hotel,
  demandLayer = false,
  radiusKm,
}: {""",
"""  hotel,
  demandLayer = false,
  radiusKm,
  areasLayer,
  selectedArea,
  onAreaSelect,
}: {""", 1)
    m = m.replace("""  /** Draw the reviewed demand radius around the selected hotel, in kilometres. */
  radiusKm?: number;""",
"""  /** Draw the reviewed demand radius around the selected hotel, in kilometres. */
  radiusKm?: number;
  /** 商圈图层：只有用户主动打开时才传值（渐进式披露）。 */
  areasLayer?: { id: string; name: string; status: string; lng: number; lat: number; radiusMeters: number }[];
  selectedArea?: string | null;
  onAreaSelect?: (id: string) => void;""", 1)

    # 在 demandLayer 绘制之后追加商圈图层绘制
    anchor = """    if (demandLayer) {"""
    area_code = """    if (areasLayer && areasLayer.length) {
      areasLayer.forEach((area) => {
        const active = area.id === selectedArea;
        const el = document.createElement("button");
        el.className = "map-marker area-marker" + (active ? " active" : "");
        el.setAttribute("aria-label", area.name);
        el.style.width = active ? "18px" : "12px";
        el.style.height = active ? "18px" : "12px";
        el.style.borderRadius = "50%";
        el.style.boxSizing = "border-box";
        el.style.cursor = "pointer";
        el.style.background = area.status === "official" ? "#2563EB" : "#fff";
        el.style.border = "2px solid " + (area.status === "official" ? "#2563EB" : "#0F766E");
        if (active) el.style.boxShadow = "0 0 0 6px rgba(37,99,235,0.18)";
        el.addEventListener("click", () => onAreaSelect?.(area.id));
        markers.push(
          new A.Marker({
            position: [area.lng, area.lat],
            content: el,
            anchor: "center",
            title: area.name + (area.status === "official" ? "" : "（参考地点）"),
            zIndex: active ? 180 : 90,
          }),
        );
        if (active) {
          markers.push(
            new A.Circle({
              center: [area.lng, area.lat],
              radius: area.radiusMeters,
              strokeColor: "#2563EB",
              strokeOpacity: 0.6,
              strokeWeight: 1,
              fillColor: "#2563EB",
              fillOpacity: 0.08,
            }),
          );
        }
      });
    }
    if (demandLayer) {"""
    if anchor in m:
        m = m.replace(anchor, area_code, 1)

    # 依赖数组补上新 prop
    m = m.replace("    demandLayer,", "    demandLayer,\n    areasLayer,\n    selectedArea,", 1)
    mp.write_text(m, encoding="utf-8")

print("  Map 商圈图层:", "areasLayer" in mp.read_text(encoding="utf-8"))

# ---------- 2) 地图页 ----------
pg = root / "frontend" / "src" / "pages" / "CityEventMap" / "index.tsx"
s = pg.read_text(encoding="utf-8")

if "showAreas" not in s:
    s = s.replace("  const [showHotels, setShowHotels] = useState(false);",
"""  const [showHotels, setShowHotels] = useState(false);
  // 商圈图层：默认关闭，用户主动打开才出现（渐进式披露）
  const [showAreas, setShowAreas] = useState(false);
  const [selectedAreaId, setSelectedAreaId] = useState<string | null>(null);
  const [areaRows, setAreaRows] = useState<
    { id: string; name: string; status: string; centerLng: number; centerLat: number; radiusMeters: number; nearbyEvents: number }[]
  >([]);""", 1)

    s = s.replace('import { filterEvents, eventCoordinates, categories, venueHotspots } from "../../utils/data";',
                  'import { filterEvents, eventCoordinates, categories, venueHotspots } from "../../utils/data";\nimport { loadMarketAreas } from "../../services/api";', 1)

    # 懒加载商圈数据（只有打开开关时才请求）
    s = s.replace("  const selectedEventId = detail ?? selected ?? null;",
"""  const selectedEventId = detail ?? selected ?? null;

  useEffect(() => {
    if (!showAreas || areaRows.length) return;
    loadMarketAreas()
      .then((result) => setAreaRows(result.areas))
      .catch(() => setAreaRows([]));
  }, [showAreas, areaRows.length]);""", 1)

    # 开关 + 选中摘要
    s = s.replace('''              <Switch
                aria-label="查看附近酒店"''',
'''              <Switch
                aria-label="查看商圈"
                checked={showAreas}
                onChange={(value) => {
                  setShowAreas(value);
                  if (!value) setSelectedAreaId(null);
                }}
              />
              <span>{showAreas ? "已显示商圈参考点" : "查看商圈"}</span>
              <Switch
                aria-label="查看附近酒店"''', 1)

    # 传给 EventMap
    s = s.replace('<EventMap events={events} demandLayer={showHotels} />',
'''<EventMap
        events={events}
        demandLayer={showHotels}
        areasLayer={
          showAreas
            ? areaRows.map((area) => ({
                id: area.id,
                name: area.name,
                status: area.status,
                lng: area.centerLng,
                lat: area.centerLat,
                radiusMeters: area.radiusMeters,
              }))
            : undefined
        }
        selectedArea={selectedAreaId}
        onAreaSelect={(id) => setSelectedAreaId((current) => (current === id ? null : id))}
      />''', 1)

    # 选中摘要行（在提示条之后）
    s = s.replace('''      <EventMap
        events={events}''',
'''      {showAreas && selectedAreaId && (
        <div className="area-summary">
          {(() => {
            const area = areaRows.find((item) => item.id === selectedAreaId);
            if (!area) return null;
            return (
              <>
                <strong>{area.name}</strong>
                <span className="muted">
                  {area.status === "official" ? "官方商圈" : "参考地点（非官方商圈）"} · 半径 {area.radiusMeters} 米 ·
                  该范围内已收录活动 {area.nearbyEvents} 场 · 圆是估算范围，不是正式边界
                </span>
              </>
            );
          })()}
        </div>
      )}
      <EventMap
        events={events}''', 1)

    pg.write_text(s, encoding="utf-8")

print("  地图页开关:", "showAreas" in pg.read_text(encoding="utf-8"))
