import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Tag, Alert, Switch, Space } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { filterEvents, eventCoordinates, categories, venueHotspots } from "../../utils/data";
import { assessDemand, businessToday } from "../../services/intelligence";
import Filters from "../../components/Filters";
import EventMap from "../../components/Map";
import EventCard from "../../components/EventCard";
import VenueHotspots from "../../components/VenueHotspots";
import RegionNav, { DEFAULT_REGION } from "../../components/RegionNav";
import CaliberBar from "../../components/CaliberBar";
import { distinctByCanonical } from "../../utils/dedupe";
import { monthRange } from "../../utils/data";
import type { TimeWindow } from "../../utils/caliber";
import { SITE_SHORT } from "../../config";
export default function CityEventMap() {
  const { dataset, allEvents, filters, update } = usePlatform();
  // Hotels are drawn on request rather than always. The map is about where the demand is;
  // the hotel layer answers the follow-up question, and leaving it on by default buries the
  // event markers under a cluster of H pins in the same few districts.
  const [showHotels, setShowHotels] = useState(true);

  // The map opens on 太仓: a hotel plans its own county first and the whole city second. An
  // absent ?district= therefore means 太仓 rather than "everything", and 全市 is an explicit
  // choice carried as district=all. Keeping both in one parameter means the region buttons,
  // the dropdown and the URL can never disagree about where the reader is.
  //
  // The default only applies when 太仓 is actually present in the data. A build or an import
  // without it - a fresh dataset, a test fixture, a partial snapshot - would otherwise open on
  // an empty map with no way to tell that the region simply is not loaded.
  const hasDefaultRegion = dataset.districts.some((d) => d.id === DEFAULT_REGION);
  const region = filters.district || (hasDefaultRegion ? DEFAULT_REGION : "all");
  const activeDistrict = region === "all" ? "" : region;
  const regionName =
    region === "all"
      ? "苏州全市"
      : dataset.districts.find((d) => d.id === region)?.name ?? "太仓市";
  // The heading names what is actually on screen - month and place - instead of a fixed
  // "…活动地图". 太仓市 → 太仓, because the heading is read as a phrase ("10月太仓活动"),
  // while the region chips keep the full administrative name. The whole-city view is 苏州, not
  // 苏州全, so the suffix strip is skipped when no district is chosen.
  const shortRegion = region === "all" ? "苏州" : regionName.replace(/(市|区|县)$/, "");
  const heading = `${filters.month}月${shortRegion}活动`;

  // The browser tab names the same thing the page does; a generic title for every view makes a
  // pinned tab or a history entry impossible to tell apart.
  useEffect(() => {
    document.title = `${heading} · ${SITE_SHORT}`;
  }, [heading]);

  const events = useMemo(
    () =>
      filterEvents(dataset.events, { ...filters, district: activeDistrict }),
    [
      dataset.events,
      filters.year,
      filters.month,
      activeDistrict,
      filters.category,
      filters.includeDemo,
    ],
  );
  // 地图按月浏览，所以把当月表达成一个统一的时间窗口，交给同一套口径计算。
  const mapWindow: TimeWindow = useMemo(() => {
    const [start, end] = monthRange(filters.year, filters.month);
    return {
      kind: "custom",
      start,
      end,
      label: `${filters.year} 年 ${filters.month} 月（${start} 至 ${end}）`,
    };
  }, [filters.year, filters.month]);

  // 热点与统计按去重身份算：同一活动被两个来源收录不该算成两场。
  const identities = useMemo(() => distinctByCanonical(events), [events]);
  const mapped = identities.filter((e) => eventCoordinates(e, dataset));

  // Historical events are archived by default so the map answers "what is coming", but a hotel
  // comparing this year against last needs them; the button states how many are being withheld
  // instead of leaving the reader to discover the archive switch elsewhere.
  const today = businessToday();
  const historyCount = useMemo(() => {
    // Counted from the unfiltered set: the working dataset has already dropped archived rows, so
    // counting there would report only the handful ended in the last few days.
    const scope = allEvents.filter(
      (e) =>
        (filters.includeDemo || !e.demo) &&
        (!activeDistrict || e.districtId === activeDistrict) &&
        (!filters.category || e.category === filters.category),
    );
    return scope.filter((e) => (e.endDate ?? e.startDate ?? "") < today).length;
  }, [allEvents, filters.includeDemo, filters.category, activeDistrict, today]);
  // Demand is clustered by VENUE: a hotel acts on "this theatre has 8 events", not on an
  // inferred business district.
  const clusters = useMemo(
    () => venueHotspots(identities, dataset.venues),
    [identities, dataset.venues],
  );
  const hotspots = clusters.filter((row) => row.isHotspot);
  // What the hotel layer would draw, so the control can say how much it is showing.
  const hotelCount = useMemo(() => {
    const ids = new Set<string>();
    for (const event of identities) {
      for (const { hotel } of assessDemand(event, dataset).nearbyHotels) {
        ids.add(hotel.id);
      }
    }
    return ids.size;
  }, [identities, dataset]);
  // Years that actually hold events for this region, newest first: the history of a Taicang
  // hotel spans 2021-2026, and reaching it through a month grid alone is a lot of clicking.
  const years = useMemo(() => {
    const scope = allEvents.filter(
      (e) => (!activeDistrict || e.districtId === activeDistrict),
    );
    return [...new Set(scope.map((e) => (e.startDate ?? "").slice(0, 4)).filter(Boolean))]
      .sort()
      .reverse();
  }, [allEvents, activeDistrict]);

  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">空间情报</div>
        <h1>{heading}</h1>
        <p>城市活动空间情报 · 连接活动、场馆与周边酒店资源</p>
      </div>
      <Filters regions={false} />
      <RegionNav />
      <CaliberBar window={mapWindow} events={events} />
      {historyCount > 0 && (
        <div className="history-bar">
          <span className="muted">
            {filters.includePast
              ? `已显示历史活动，共 ${historyCount} 条已结束`
              : `另有 ${historyCount} 条已结束的历史活动未显示`}
          </span>
          <Button
            size="small"
            type={filters.includePast ? "default" : "primary"}
            onClick={() => update({ past: filters.includePast ? null : 1 })}
          >
            {filters.includePast ? "只看未结束" : `查看历史活动（${historyCount} 条）`}
          </Button>
          <Space size={4} wrap>
            <span className="muted" style={{ fontSize: 12 }}>
              跳到年份
            </span>
            {years.map((year) => (
              <Button
                key={year}
                size="small"
                type={String(filters.year) === year ? "primary" : "default"}
                onClick={() => update({ year, past: 1 })}
              >
                {year}
              </Button>
            ))}
          </Space>
        </div>
      )}
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
    </>
  );
}
