import { useEffect, useMemo, useState } from "react";
import CaliberBar from "../../components/CaliberBar";
import type { TimeWindow } from "../../utils/caliber";
import {
  Button,
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
import { distinctByCanonical } from "../../utils/dedupe";
import { useEntitlements } from "../../hooks/useEntitlements";
import {
  distanceKm,
  overlaps,
  verifiedCoords,
  monthRange,
  eventCoordinates,
} from "../../utils/data";
import EventMap from "../../components/Map";
import EventCard from "../../components/EventCard";

/** Tier colours, shared by the picker and the selected-hotel card. */
const TIER_COLORS: Record<string, string> = {
  high: "gold",
  mid: "blue",
  comfort: "green",
};
const TIER_ORDER = ["high", "mid", "comfort"] as const;
export const TierLabel: Record<string, string> = {
  high: "高端",
  mid: "中端",
  comfort: "舒适",
};

/** Hotels grouped by portfolio tier, so the whole set is readable at a glance. */
function tierOptions(
  hotels: {
    id: string;
    name: string;
    tier?: "high" | "mid" | "comfort";
    tierLabel?: string | null;
  }[],
) {
  const groups = TIER_ORDER.map((tier) => ({
    label: TierLabel[tier],
    options: hotels
      .filter((h) => h.tier === tier)
      .map((h) => ({ label: h.name, value: h.id })),
  })).filter((g) => g.options.length);
  const untiered = hotels
    .filter((h) => !h.tier)
    .map((h) => ({ label: h.name, value: h.id }));
  if (untiered.length) groups.push({ label: "其他", options: untiered });
  return groups;
}

export default function HotelIntelligence() {
  const { dataset, filters, params, update } = usePlatform();
  // 专业版盯一家酒店,企业版管理多家:套餐决定这里能选几家(演示版套餐在本机切换)。
  const { plan } = useEntitlements();
  const singleHotel = plan === "pro";
  const [portfolio, setPortfolio] = useState<string[] | null>(null);
  const owned = dataset.hotels.filter(
    (h) => portfolio === null || portfolio.includes(h.id),
  );
  const hotelId = params.get("hotel") ?? owned[0]?.id;
  const [radius, setRadius] = useState(10);
  const [custom, setCustom] = useState<[string, string] | null>(null);
  const range = custom ?? monthRange(filters.year, filters.month);
  // 专业版:当前酒店下拉列出全部酒店,选中即把"组合"收敛为它;企业版沿用多选组合。
  const selectable = singleHotel ? dataset.hotels : owned;
  const hotel = selectable.find((h) => h.id === hotelId) ?? selectable[0];
  useEffect(() => {
    if (singleHotel && hotel) setPortfolio([hotel.id]);
  }, [singleHotel, hotel]);
  const monthWindow: TimeWindow = useMemo(() => {
    const [start, end] = monthRange(filters.year, filters.month);
    return { kind: "custom", start, end, label: filters.year + " 年 " + filters.month + " 月（" + start + " 至 " + end + "）" };
  }, [filters.year, filters.month]);
  const monthEvents = useMemo(
    () => dataset.events.filter((e) => {
      const start = e.startDate;
      if (!start) return false;
      const end = e.endDate ?? start;
      return start <= monthWindow.end && end >= monthWindow.start;
    }),
    [dataset.events, monthWindow],
  );

  const dated = dataset.events.filter(
    (e) =>
      (filters.includeDemo || !e.demo) &&
      (!filters.category || e.category === filters.category) &&
      (!filters.district || e.districtId === filters.district) &&
      overlaps(e, ...range),
  );
  const matches = useMemo(
    () =>
      distinctByCanonical(dated)
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
        <div className="eyebrow">酒店情报</div>
        <h1>酒店活动情报</h1>
        <p>按酒店位置与日期查看附近活动和核验来源</p>
            </div>

      <CaliberBar window={monthWindow} events={monthEvents} />

      <section className="panel hotel-toolbar">
        {/* One labelled control per row keeps the toolbar readable; a multi-select that
            renders every hotel as a tag pushed the rest of the controls off the line. */}
        <div className="field-grid">
          <label>
            <small>酒店组合</small>
            {singleHotel ? (
              <div className="muted" style={{ paddingTop: 6 }}>
                专业版聚焦一家酒店;多店组合对比属于企业版(可在「套餐与升级」解锁)。
              </div>
            ) : (
              <Select
                aria-label="酒店组合"
                mode="multiple"
                maxTagCount="responsive"
                style={{ width: "100%" }}
                value={portfolio ?? dataset.hotels.map((h) => h.id)}
                options={tierOptions(dataset.hotels)}
                onChange={setPortfolio}
              />
            )}
          </label>
          <label>
            <small>当前酒店</small>
            <Select
              aria-label="酒店"
              style={{ width: "100%" }}
              value={hotel?.id}
              options={selectable.map((h) => ({
                label: h.tierLabel ? `${h.tierLabel} · ${h.name}` : h.name,
                value: h.id,
              }))}
              onChange={(hotel) => update({ hotel })}
            />
          </label>
          <label>
            <small>日期范围</small>
            <DatePicker.RangePicker
              style={{ width: "100%" }}
              value={[dayjs(range[0]), dayjs(range[1])]}
              onChange={(v) =>
                setCustom(
                  v?.[0] && v[1]
                    ? [v[0].format("YYYY-MM-DD"), v[1].format("YYYY-MM-DD")]
                    : null,
                )
              }
            />
          </label>
          <label>
            <small>需求半径 ≤ {radius} km</small>
            <Slider
              min={1}
              max={30}
              value={radius}
              onChange={setRadius}
              tooltip={{ formatter: (v) => `${v} km` }}
            />
          </label>
        </div>
        <Space wrap size={8} className="gap-top">
          {!singleHotel && (
            <>
              <Button
                size="small"
                onClick={() => setPortfolio(dataset.hotels.map((h) => h.id))}
              >
                全选 {dataset.hotels.length} 家
              </Button>
              <Button size="small" onClick={() => setPortfolio([])}>
                清空
              </Button>
              {(["high", "mid", "comfort"] as const).map((tier) => {
                const ids = dataset.hotels.filter((h) => h.tier === tier).map((h) => h.id);
                if (!ids.length) return null;
                return (
                  <Button
                    key={tier}
                    size="small"
                    onClick={() =>
                      setPortfolio((prev) => {
                        const current = prev ?? dataset.hotels.map((h) => h.id);
                        const all = ids.every((id) => current.includes(id));
                        return all
                          ? current.filter((id) => !ids.includes(id))
                          : [...new Set([...current, ...ids])];
                      })
                    }
                  >
                    只选{TierLabel[tier]}（{ids.length}）
                  </Button>
                );
              })}
            </>
          )}
          <small className="muted">
            {singleHotel
              ? `专业版 · 当前 1 家酒店 · 共 ${dataset.hotels.length} 家可选`
              : `已选 ${hotel ? owned.length : 0} 家 · 共 ${dataset.hotels.length} 家`}
          </small>
        </Space>
      </section>
      <div className="hotel-layout">
        <section className="panel hotel-info">
          <div className="eyebrow">当前酒店</div>
          <h2>{hotel?.name ?? "未配置酒店"}</h2>
          <Space wrap>
            {hotel?.tierLabel && (
              <Tag color={TIER_COLORS[hotel.tier ?? "mid"]}>{hotel.tierLabel}</Tag>
            )}
            <Tag color={verifiedCoords(hotel?.coordinates) ? "green" : "orange"}>
              {verifiedCoords(hotel?.coordinates) ? "坐标已核验" : "坐标待核验"}
            </Tag>
          </Space>
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
                key: "tier",
                label: "档位依据",
                children: hotel?.tierSource ? (
                  <>
                    {hotel.tierSource}
                    {hotel.tierEvidence && (
                      <small className="block muted">{hotel.tierEvidence}</small>
                    )}
                  </>
                ) : (
                  "—"
                ),
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
              高德地点来源 ↗
            </a>
          )}
          <div className="metric-note">
            <strong>{unknown.length}</strong>
            <p>条活动因地点未核实，未计入距离范围</p>
          </div>
        </section>
        <section className="panel hotel-map">
          <EventMap
            events={matches.map((m) => m.event)}
            hotel={hotel}
            radiusKm={radius}
          />
        </section>
        <section className="panel event-list">
          <div className="panel-heading">
            <h3>附近活动</h3>
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
      
    </>
  );
}
