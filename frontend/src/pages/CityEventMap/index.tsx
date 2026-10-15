import { useMemo, useState } from "react";
import { Empty, Tag, Alert, Switch, Space } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { filterEvents, eventCoordinates, categories, venueHotspots } from "../../utils/data";
import { assessDemand } from "../../services/intelligence";
import Filters from "../../components/Filters";
import EventMap from "../../components/Map";
import EventCard from "../../components/EventCard";
import VenueHotspots from "../../components/VenueHotspots";
export default function CityEventMap() {
  const { dataset, filters } = usePlatform();
  // Hotels are drawn on request rather than always. The map is about where the demand is;
  // the hotel layer answers the follow-up question, and leaving it on by default buries the
  // event markers under a cluster of H pins in the same few districts.
  const [showHotels, setShowHotels] = useState(true);
  const events = useMemo(
    () => filterEvents(dataset.events, filters),
    [
      dataset.events,
      filters.year,
      filters.month,
      filters.district,
      filters.category,
      filters.includeDemo,
    ],
  );
  const mapped = events.filter((e) => eventCoordinates(e, dataset));
  // Demand is clustered by VENUE: a hotel acts on "this theatre has 8 events", not on an
  // inferred business district.
  const clusters = useMemo(
    () => venueHotspots(events, dataset.venues),
    [events, dataset.venues],
  );
  const hotspots = clusters.filter((row) => row.isHotspot);
  // What the hotel layer would draw, so the control can say how much it is showing.
  const hotelCount = useMemo(() => {
    const ids = new Set<string>();
    for (const event of events) {
      for (const { hotel } of assessDemand(event, dataset).nearbyHotels) {
        ids.add(hotel.id);
      }
    }
    return ids.size;
  }, [events, dataset]);
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">空间情报</div>
        <h1>苏州城市活动地图</h1>
        <p>城市活动空间情报 · 连接活动、场馆与周边酒店资源</p>
      </div>
      <Filters />
      <div className="stats-strip">
        <div>
          <small>当前筛选活动</small>
          <strong>
            {events.length}
            <span>条</span>
          </strong>
        </div>
        <div>
          <small>可定位活动</small>
          <strong>
            {mapped.length}
            <span>条</span>
          </strong>
        </div>
        <div>
          <small>涉及场馆</small>
          <strong>
            {clusters.length}
            <span>个</span>
          </strong>
        </div>
        <div>
          <small>热点场馆（≥3 场）</small>
          <strong>
            {hotspots.length}
            <span>个</span>
          </strong>
        </div>
      </div>
      <div className="map-layout">
        <section className="panel map-panel">
          <div className="panel-heading">
            <h3>空间分布</h3>
            <Space wrap>
              <Switch
                aria-label="显示酒店"
                checked={showHotels}
                onChange={setShowHotels}
              />
              <span>显示酒店（{hotelCount} 家）</span>
              <Tag color="cyan">金鸡湖 / 独墅湖</Tag>
            </Space>
          </div>
          <EventMap events={events} demandLayer={showHotels} />
          <div className="legend">
            {Object.values(categories).map((c) => (
              <span key={c.label}>
                <i style={{ background: c.color }} />
                {c.label}
              </span>
            ))}
          </div>
        </section>
        <section className="panel event-list">
          <div className="panel-heading">
            <h3>活动列表</h3>
            <Tag>{events.length}</Tag>
          </div>
          <div className="list-scroll">
            {events.length ? (
              events.map((e) => <EventCard key={e.id} event={e} />)
            ) : (
              <Empty description="所选月份或筛选下暂无活动" />
            )}
          </div>
        </section>
      </div>
      <VenueHotspots />
      <Alert
        className="gap-top"
        type="info"
        showIcon
        message={`当前 ${events.filter((e) => e.demo).length} 条 DEMO 活动。${events.length - mapped.length} 条缺少核验坐标的活动仅保留在列表。上图标记按活动类别着色，图例见地图下方。`}
      />
    </>
  );
}
