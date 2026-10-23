import { useMemo, useState } from "react";
import { Empty, Input, Select, Space, Table, Tag, Tooltip } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import type { Hotel } from "../../types";

/**
 * 找酒店：按星级、地区、名称浏览酒店库。
 *
 * 星级是**来源标注**，不是推断。高德的分类串里写了「五星级宾馆」的，这里才显示五星级，并把
 * 原始分类串放在提示里；只有品牌没有星级的（例如洲际），显示「未标注」——把品牌当星级写是
 * 编造，而使用者拿这条去定价或对照时不该被一个猜测误导。
 *
 * 本页不含价格与房态：这两样没有可追溯的公开来源。
 */

type StarFilter = "all" | "5" | "4" | "3" | "economy" | "unstated";

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
  const { dataset } = usePlatform();
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

  const rows = useMemo(() => {
    const needle = keyword.trim();
    return dataset.hotels
      .filter((hotel) => matchesStar(hotel, star))
      .filter((hotel) => district === "all" || hotel.districtId === district)
      .filter((hotel) => !needle || hotel.name.includes(needle) || (hotel.address ?? "").includes(needle))
      .sort((a, b) => starRank(b) - starRank(a) || a.name.localeCompare(b.name, "zh-CN"));
  }, [dataset.hotels, star, district, keyword]);

  const counts = useMemo(() => {
    const result: Record<string, number> = {
      "5": 0, "4": 0, "3": 0, economy: 0, unstated: 0,
    };
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

  return (
    <>
      <div className="page-heading">
        <h1>找酒店</h1>
      </div>

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
          星级取自来源标注（高德分类串）。来源没有标注星级的酒店显示「未标注」，不按品牌推断；
          本页不含价格与房态。
        </p>

        <Table<Hotel>
          className="gap-top"
          rowKey="id"
          size="small"
          dataSource={rows}
          pagination={rows.length > 12 ? { pageSize: 12 } : false}
          locale={{ emptyText: <Empty description="没有符合条件的酒店" /> }}
          columns={[
            { title: "酒店", dataIndex: "name" },
            {
              title: "星级",
              width: 150,
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
            {
              title: "档位",
              width: 90,
              render: (_, hotel) => hotel.tierLabel ?? "—",
            },
            { title: "地区", width: 130, render: (_, hotel) => districtLabel(hotel, districtNames) },
            { title: "地址", dataIndex: "address", render: (v) => v ?? "—" },
            {
              title: "坐标",
              width: 90,
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
