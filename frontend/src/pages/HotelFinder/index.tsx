import { useMemo, useState } from "react";
import { Empty, Input, Select, Space, Table, Tag, Tooltip } from "antd";
import { useNavigate } from "react-router-dom";
import { usePlatform } from "../../hooks/usePlatform";
import { distanceKm, eventCoordinates, monthRange, overlaps, verifiedCoords } from "../../utils/data";
import type { Hotel } from "../../types";

/**
 * 找酒店：按星级、地区、名称浏览酒店库，并看到每家周边的活动与场馆。
 *
 * 星级是**来源标注**，不是推断。高德分类串写了「五星级宾馆」的才显示五星级，并把原文放进提示；
 * 只有品牌没有星级的（例如洲际）显示「未标注」。把品牌当星级写等于编造，而拿这条去对照自己
 * 挂牌酒店的经理会被恰好这个数字误导。
 *
 * 「附近活动 / 附近场馆」按 10 km 直线距离统计，与地图上画的需求半径一致，且限定在当前选中的
 * 月份，因此数字会随月份变化，而不是一个说不清口径的总数。没有已核验坐标的酒店不做估算。
 *
 * 本页不含价格与房态：这两样没有可追溯的公开来源。
 */

type StarFilter = "all" | "5" | "4" | "3" | "economy" | "unstated";

const RADIUS_KM = 10;
const STAR_ORDER: Record<string, number> = { "5星级": 5, "4星级": 4, "3星级": 3, 经济型: 0 };

function starRank(hotel: Hotel): number {
  const star = hotel.star;
  if (!star) return -2;
  if (star.level !== null) return star.level;
  return STAR_ORDER[star.label] ?? -1;
}

function matchesStar(hotel: Hotel, filter: StarFilter): boolean {
  if (filter === "all") return true;
  const star = hotel.star;
  const known = Boolean(star?.claimedStar) && star?.level != null;
  if (filter === "unstated") return !known;
  if (filter === "economy") return star?.label === "经济型";
  if (!known) return false;
  return String(star!.level) === filter;
}

function districtLabel(hotel: Hotel, names: Map<string, string>): string {
  const id = hotel.districtId;
  if (!id) return "—";
  return names.get(id) ?? id.replace(/^district-/, "");
}

export default function HotelFinder() {
  const { dataset, filters } = usePlatform();
  const navigate = useNavigate();
  const [star, setStar] = useState<StarFilter>("all");
  const [district, setDistrict] = useState<string>("all");
  const [keyword, setKeyword] = useState("");

  const districtNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of dataset.districts) map.set(d.id, d.name);
    return map;
  }, [dataset.districts]);

  const districts = useMemo(() => {
    const seen = new Map<string, string>();
    for (const hotel of dataset.hotels) {
      if (!hotel.districtId) continue;
      seen.set(hotel.districtId, districtLabel(hotel, districtNames));
    }
    return [...seen.entries()]
      .map(([id, name]) => ({ value: id, label: name }))
      .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
  }, [dataset.hotels, districtNames]);

  // The counts are recomputed when the month changes, so the column means "in this month".
  const nearCounts = useMemo(() => {
    const range = monthRange(filters.year, filters.month);
    const dated = dataset.events.filter(
      (event) => (filters.includeDemo || !event.demo) && overlaps(event, ...range),
    );
    const eventPoints = dated
      .map((event) => eventCoordinates(event, dataset))
      .filter((point): point is NonNullable<typeof point> => Boolean(point));
    const venuePoints = dataset.venues
      .filter((venue) => verifiedCoords(venue.coordinates))
      .map((venue) => venue.coordinates!);

    const result = new Map<string, { events: number; venues: number }>();
    for (const hotel of dataset.hotels) {
      if (!verifiedCoords(hotel.coordinates)) continue;
      const events = eventPoints.filter((point) => {
        const distance = distanceKm(hotel.coordinates!, point);
        return distance !== null && distance <= RADIUS_KM;
      }).length;
      const venues = venuePoints.filter((point) => {
        const distance = distanceKm(hotel.coordinates!, point);
        return distance !== null && distance <= RADIUS_KM;
      }).length;
      result.set(hotel.id, { events, venues });
    }
    return result;
  }, [dataset, filters.year, filters.month, filters.includeDemo]);

  const rows = useMemo(() => {
    const needle = keyword.trim();
    return dataset.hotels
      .filter((hotel) => matchesStar(hotel, star))
      .filter((hotel) => district === "all" || hotel.districtId === district)
      .filter(
        (hotel) => !needle || hotel.name.includes(needle) || (hotel.address ?? "").includes(needle),
      )
      .sort((a, b) => starRank(b) - starRank(a) || a.name.localeCompare(b.name, "zh-CN"));
  }, [dataset.hotels, star, district, keyword]);

  const counts = useMemo(() => {
    const result: Record<string, number> = { "5": 0, "4": 0, "3": 0, economy: 0, unstated: 0 };
    for (const hotel of dataset.hotels) {
      for (const key of ["5", "4", "3", "economy", "unstated"] as StarFilter[]) {
        if (matchesStar(hotel, key)) result[key] += 1;
      }
    }
    return result;
  }, [dataset.hotels]);

  const options = [
    { value: "all", label: `全部星级（${dataset.hotels.length}）` },
    { value: "5", label: `五星级（${counts["5"]}）` },
    { value: "4", label: `四星级（${counts["4"]}）` },
    { value: "3", label: `三星级（${counts["3"]}）` },
    { value: "economy", label: `经济型（${counts.economy}）` },
    { value: "unstated", label: `未标注星级（${counts.unstated}）` },
  ];

  const bars = [
    { key: "5" as StarFilter, label: "五星级", color: "#B45309" },
    { key: "4" as StarFilter, label: "四星级", color: "#B7791F" },
    { key: "3" as StarFilter, label: "三星级", color: "#0F766E" },
    { key: "economy" as StarFilter, label: "经济型", color: "#64748B" },
    { key: "unstated" as StarFilter, label: "未标注", color: "#CBD5E1" },
  ];
  const maxBar = Math.max(1, ...bars.map((bar) => counts[bar.key] ?? 0));

  const openHotel = (hotel: Hotel) => {
    const params = new URLSearchParams({
      year: String(filters.year),
      month: String(filters.month),
      hotel: hotel.id,
    });
    navigate(`/hotels?${params.toString()}`);
  };

  return (
    <>
      <div className="page-heading">
        <h1>找酒店</h1>
      </div>

      <section className="panel gap-bottom">
        <div className="panel-heading">
          <h3 style={{ margin: 0 }}>星级分布</h3>
          <small className="muted">点一根柱子即可只看该星级</small>
        </div>
        <div className="star-chart">
          {bars.map((bar) => {
            const count = counts[bar.key] ?? 0;
            const active = star === bar.key;
            return (
              <button
                key={bar.key}
                type="button"
                className={"star-bar" + (active ? " active" : "")}
                onClick={() => setStar(active ? "all" : bar.key)}
                title={`只看${bar.label}`}
              >
                <span className="star-bar-count">{count}</span>
                <span
                  className="star-bar-fill"
                  style={{
                    height: `${Math.max(6, (count / maxBar) * 100)}%`,
                    background: bar.color,
                  }}
                />
                <span className="star-bar-label">{bar.label}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <Space wrap size={12}>
          <Select
            aria-label="星级"
            style={{ width: 190 }}
            value={star}
            options={options}
            onChange={(value) => setStar(value as StarFilter)}
          />
          <Select
            aria-label="地区"
            style={{ width: 170 }}
            value={district}
            options={[{ value: "all", label: "全部地区" }, ...districts]}
            onChange={setDistrict}
          />
          <Input
            aria-label="搜索酒店名称或地址"
            allowClear
            placeholder="搜索名称或地址"
            style={{ width: 240 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <span className="muted">共 {rows.length} 家</span>
        </Space>
        {/* Stated here rather than in a page subtitle: it explains why a well-known hotel can
            legitimately show 未标注, which is the one thing on this page that looks like a gap. */}
        <p className="muted" style={{ margin: "10px 0 0", fontSize: 12.5 }}>
          星级取自来源标注（高德分类串）。来源没有标注星级的酒店显示「未标注」，不按品牌推断。
          附近活动与场馆按 {RADIUS_KM} km 直线距离统计，限定在 {filters.year} 年 {filters.month} 月。
          本页不含价格与房态。点任意一行可查看该酒店周边的活动。
        </p>

        <Table<Hotel>
          className="gap-top"
          rowKey="id"
          size="small"
          dataSource={rows}
          pagination={rows.length > 12 ? { pageSize: 12 } : false}
          locale={{ emptyText: <Empty description="没有符合条件的酒店" /> }}
          onRow={(hotel) => ({
            onClick: () => openHotel(hotel),
            style: { cursor: "pointer" },
          })}
          columns={[
            { title: "酒店", dataIndex: "name" },
            {
              title: "星级",
              width: 120,
              render: (_, hotel) => {
                const starRecord = hotel.star;
                if (!starRecord) return <span className="muted">未标注</span>;
                const verified = starRecord.claimedStar && starRecord.level !== null;
                return (
                  <Tooltip
                    title={
                      <span>
                        {starRecord.source}
                        {starRecord.category ? `：${starRecord.category}` : ""}
                        <br />
                        {verified ? "来源明确标注星级" : "来源未标注星级，不推断"}
                      </span>
                    }
                  >
                    <span style={{ color: verified ? "#B45309" : "#94A3B8" }}>
                      {starRecord.label}
                    </span>
                  </Tooltip>
                );
              },
            },
            { title: "档位", width: 80, render: (_, hotel) => hotel.tierLabel ?? "—" },
            { title: "地区", width: 120, render: (_, hotel) => districtLabel(hotel, districtNames) },
            {
              title: `附近活动`,
              width: 100,
              align: "right",
              render: (_, hotel) => {
                const near = nearCounts.get(hotel.id);
                return near ? <strong>{near.events}</strong> : <span className="muted">—</span>;
              },
            },
            {
              title: `附近场馆`,
              width: 100,
              align: "right",
              render: (_, hotel) => {
                const near = nearCounts.get(hotel.id);
                return near ? <strong>{near.venues}</strong> : <span className="muted">—</span>;
              },
            },
            { title: "地址", dataIndex: "address", render: (v) => v ?? "—" },
            {
              title: "坐标",
              width: 84,
              render: (_, hotel) =>
                hotel.coordinates ? (
                  hotel.coordinates.status === "Verified" ? (
                    <Tag color="green">已核验</Tag>
                  ) : (
                    <Tag>待核验</Tag>
                  )
                ) : (
                  <span className="muted">—</span>
                ),
            },
          ]}
        />
      </section>
    </>
  );
}
