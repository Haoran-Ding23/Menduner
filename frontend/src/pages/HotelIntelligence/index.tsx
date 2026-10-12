import { useMemo, useState } from "react";
import {
  Select,
  DatePicker,
  Slider,
  Descriptions,
  Tag,
  Empty,
  Alert,
  Space,
} from "antd";
import dayjs from "dayjs";
import { usePlatform } from "../../hooks/usePlatform";
import {
  distanceKm,
  overlaps,
  verifiedCoords,
  monthRange,
  eventCoordinates,
} from "../../utils/data";
import EventMap from "../../components/Map";
import EventCard from "../../components/EventCard";
export default function HotelIntelligence() {
  const { dataset, filters, params, update } = usePlatform();
  const [portfolio, setPortfolio] = useState<string[] | null>(null);
  const owned = dataset.hotels.filter(
    (h) => portfolio === null || portfolio.includes(h.id),
  );
  const hotelId = params.get("hotel") ?? owned[0]?.id;
  const [radius, setRadius] = useState(10);
  const [custom, setCustom] = useState<[string, string] | null>(null);
  const range = custom ?? monthRange(filters.year, filters.month);
  const hotel = owned.find((h) => h.id === hotelId) ?? owned[0];
  const dated = dataset.events.filter(
    (e) =>
      (filters.includeDemo || !e.demo) &&
      (!filters.category || e.category === filters.category) &&
      (!filters.district || e.districtId === filters.district) &&
      overlaps(e, ...range),
  );
  const matches = useMemo(
    () =>
      dated
        .flatMap((event) => {
          const coordinates = eventCoordinates(event, dataset);
          if (!coordinates || !verifiedCoords(hotel?.coordinates)) return [];
          const distance = distanceKm(hotel.coordinates, coordinates);
          return distance !== null && distance <= radius
            ? [{ event, distance }]
            : [];
        })
        .sort(
          (a, b) =>
            (a.event.startDate ?? "").localeCompare(b.event.startDate ?? "") ||
            a.distance - b.distance,
        ),
    [dataset.venues, dated, hotel, radius],
  );
  const unknown = dated.filter((e) => !eventCoordinates(e, dataset));
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">HOSPITALITY INTELLIGENCE</div>
        <h1>
          Hotel Event Intelligence <span>酒店活动情报</span>
        </h1>
        <p>External Demand Signals · 按酒店位置与日期查看附近活动和核验来源</p>
      </div>
      <section className="panel hotel-toolbar">
        <Space wrap>
          <span>My Hotels · 酒店组合</span>
          <Select
            aria-label="酒店组合"
            mode="multiple"
            style={{ minWidth: 240, maxWidth: 440 }}
            value={portfolio ?? dataset.hotels.map((h) => h.id)}
            options={dataset.hotels.map((h) => ({
              label: h.name,
              value: h.id,
            }))}
            onChange={setPortfolio}
          />
          <Select
            aria-label="酒店"
            style={{ width: 275 }}
            value={hotel?.id}
            options={owned.map((h) => ({ label: h.name, value: h.id }))}
            onChange={(hotel) => update({ hotel })}
          />
          <DatePicker.RangePicker
            value={[dayjs(range[0]), dayjs(range[1])]}
            onChange={(v) =>
              setCustom(
                v?.[0] && v[1]
                  ? [v[0].format("YYYY-MM-DD"), v[1].format("YYYY-MM-DD")]
                  : null,
              )
            }
          />
          <span>距离 ≤ {radius} km</span>
          <Slider
            min={1}
            max={30}
            value={radius}
            onChange={setRadius}
            style={{ width: 180 }}
          />
        </Space>
      </section>
      <Alert
        className="gap-top gap-bottom"
        type="info"
        showIcon
        message="邻近 ≠ 酒店需求或经济贡献。距离为 GCJ-02 坐标上的近似直线距离，不是道路距离。DEMO 活动不代表真实市场情报。"
      />
      <div className="hotel-layout">
        <section className="panel hotel-info">
          <div className="eyebrow">SELECTED HOTEL</div>
          <h2>{hotel?.name ?? "未配置酒店"}</h2>
          <Tag color={verifiedCoords(hotel?.coordinates) ? "green" : "orange"}>
            {verifiedCoords(hotel?.coordinates) ? "坐标已核验" : "坐标待核验"}
          </Tag>
          <Descriptions
            className="gap-top"
            column={1}
            items={[
              {
                key: "address",
                label: "地址",
                children: hotel?.address ?? "—",
              },
              {
                key: "district",
                label: "商圈",
                children:
                  (dataset.districts.find((d) => d.id === hotel?.districtId)
                    ?.name ?? "—") + (hotel?.districtDemo ? "（DEMO）" : ""),
              },
              {
                key: "count",
                label: "符合条件",
                children: `${matches.length} 条活动`,
              },
            ]}
          />
          {hotel?.coordinates?.sourceUrl && (
            <a
              href={hotel.coordinates.sourceUrl}
              target="_blank"
              rel="noreferrer"
            >
              高德 POI 来源 ↗
            </a>
          )}
          <div className="metric-note">
            <strong>{unknown.length}</strong>
            <p>条日期匹配活动缺少核验坐标，未进入距离筛选</p>
          </div>
        </section>
        <section className="panel hotel-map">
          <EventMap events={matches.map((m) => m.event)} hotel={hotel} />
        </section>
        <section className="panel event-list">
          <div className="panel-heading">
            <h3>Nearby Events · 附近活动</h3>
            <Tag>{matches.length}</Tag>
          </div>
          <div className="list-scroll">
            {matches.length ? (
              matches.map((m) => (
                <EventCard
                  key={m.event.id}
                  event={m.event}
                  distance={m.distance}
                />
              ))
            ) : (
              <Empty
                description={
                  verifiedCoords(hotel?.coordinates)
                    ? "日期或距离范围内暂无可定位活动"
                    : "酒店坐标未核验，无法计算距离"
                }
              />
            )}
          </div>
        </section>
      </div>
      <section className="panel gap-top">
        <div className="panel-heading">
          <h3>Why Menduner complements RMS</h3>
        </div>
        <div className="comparison-grid">
          <article>
            <strong>Traditional RMS · 既有经营数据</strong>
            <p>
              以历史及当前预订、房价和库存信息为核心输入；部分 RMS
              也可接入外部信号。
            </p>
          </article>
          <article>
            <strong>Menduner · 可追溯城市活动信号</strong>
            <p>
              提供可追溯城市活动情报与外部需求信号，供酒店管理者结合现有 RMS
              和业务经验使用。
            </p>
          </article>
        </div>
      </section>
    </>
  );
}
