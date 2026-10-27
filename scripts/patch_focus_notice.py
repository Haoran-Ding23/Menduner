"""地图页：当活动无法定位时，明确告诉用户原因（GPT Round 28 验收第 3 条）。

根因：eventCoordinates() 在两种情况下返回 null ——
  1) 场馆坐标缺失或未核验；
  2) 该活动的 venueId 证据处于 Conflicting / Needs Review（视为场馆关联未确认）。
这是**正确的保守行为**，但如果页面什么都不说，用户只会觉得"地图坏了"。
所以这里补一条明确提示，并在有原始坐标（未核验）时给出坐标数值与高德链接。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "CityEventMap" / "index.tsx"
s = page.read_text(encoding="utf-8")

if "定位提示" not in s:
    s = s.replace(
        'import EventCard from "../../components/EventCard";',
        'import EventCard from "../../components/EventCard";\n'
        'import { eventCoordinates } from "../../utils/data";',
        1,
    )

    anchor = "  // 从工作台等页面跳进来时带 ?event=<id>，直接打开该活动详情并定位，"
    block = '''  // 定位提示：活动无法在地图上定位时，说清原因，不假装它在那儿
  const focusNotice = useMemo(() => {
    const id = filters.detail ?? filters.event;
    if (!id) return null;
    const target = dataset.events.find((item) => item.id === id);
    if (!target) return null;
    if (eventCoordinates(target, dataset)) return null;
    const venue = dataset.venues.find((item) => item.id === target.venueId);
    const raw = venue?.coordinates;
    if (raw && raw.lng != null) {
      return {
        text: "该活动的场馆关联或坐标尚未核验，暂不在地图上定位（不用行政区中心代替场馆位置）",
        coords: `${raw.lng}, ${raw.lat}`,
        link: `https://uri.amap.com/marker?position=${raw.lng},${raw.lat}`,
      };
    }
    return {
      text: "该活动没有可用的场馆坐标，暂不在地图上定位",
      coords: null,
      link: null,
    };
  }, [dataset, filters.detail, filters.event]);

''' + anchor
    s = s.replace(anchor, block, 1)

    # 把提示渲染在地图之上
    map_usage = "      <EventMap events={events} demandLayer={showHotels} />"
    notice = '''      {focusNotice && (
        <div className="map-focus-notice">
          <span>{focusNotice.text}</span>
          {focusNotice.coords && (
            <a href={focusNotice.link ?? "#"} target="_blank" rel="noreferrer">
              原始坐标 {focusNotice.coords}（在高德查看）
            </a>
          )}
        </div>
      )}
''' + map_usage
    if map_usage in s:
        s = s.replace(map_usage, notice, 1)

    page.write_text(s, encoding="utf-8")

print("  已加定位提示:", "map-focus-notice" in page.read_text(encoding="utf-8"))
