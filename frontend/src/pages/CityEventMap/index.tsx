import { useMemo } from "react";
import { Empty, Tag, Alert } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { filterEvents, eventCoordinates, categories } from "../../utils/data";
import Filters from "../../components/Filters";
import EventMap from "../../components/Map";
import EventCard from "../../components/EventCard";
export default function CityEventMap() {
  const { dataset, filters } = usePlatform();
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
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">SPATIAL INTELLIGENCE</div>
        <h1>Menduner City Event Map</h1>
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
          <small>商圈分组</small>
          <strong>
            {new Set(events.map((e) => e.districtId).filter(Boolean)).size}
            <span>个</span>
          </strong>
        </div>
        <div>
          <small>当前数据性质</small>
          <strong className="stat-text">
            {events.some((e) => e.demo) ? "包含 DEMO" : "实际导入"}
          </strong>
        </div>
      </div>
      <div className="map-layout">
        <section className="panel map-panel">
          <div className="panel-heading">
            <h3>空间分布</h3>

            <Tag color="cyan">金鸡湖 / 独墅湖</Tag>
          </div>
          <EventMap events={events} demandLayer />
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
      <Alert
        className="gap-top"
        type="info"
        showIcon
        message={`当前 ${events.filter((e) => e.demo).length} 条 DEMO 活动；商圈仅为演示分组，未绘制边界。${events.length - mapped.length} 条缺少核验坐标的活动仅保留在列表。`}
      />
    </>
  );
}
