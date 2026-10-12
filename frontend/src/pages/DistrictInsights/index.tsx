import OpportunityAnalysis from "../../components/OpportunityAnalysis";
import { useState } from "react";
import { Table, Button, Tag, Alert } from "antd";
import { usePlatform } from "../../hooks/usePlatform";
import { categories, monthRange, overlaps } from "../../utils/data";
import Filters from "../../components/Filters";
import Chart from "../../components/Charts";
import type { Event } from "../../types";
export default function DistrictInsights() {
  const { dataset, filters, update, go, openEvent } = usePlatform();
  const [venueId, setVenueId] = useState("");
  const annual = dataset.events.filter(
    (e) =>
      (filters.includeDemo || !e.demo) &&
      (!filters.district || e.districtId === filters.district) &&
      (!filters.category || e.category === filters.category) &&
      overlaps(e, `${filters.year}-01-01`, `${filters.year}-12-31`),
  );
  const current = annual.filter(
    (e) =>
      overlaps(e, ...monthRange(filters.year, filters.month)) &&
      (!venueId || e.venueId === venueId),
  );
  const districtCounts = dataset.districts.map((d) => ({
    name: d.name,
    value: annual.filter((e) => e.districtId === d.id).length,
  }));
  const monthly = Array.from(
    { length: 12 },
    (_, i) =>
      annual.filter((e) => overlaps(e, ...monthRange(filters.year, i + 1)))
        .length,
  );
  const cat = Object.entries(categories).map(([k, c]) => ({
    name: c.label,
    value: annual.filter((e) => e.category === k).length,
    itemStyle: { color: c.color },
  }));
  const venue = dataset.venues.map((v) => ({
    name: v.name,
    value: annual.filter((e) => e.venueId === v.id).length,
  }));
  const bar = (
    data: {
      name: string;
      value: number;
    }[],
  ) => ({
    tooltip: {},
    grid: { left: 45, right: 20, bottom: 65, top: 25 },
    xAxis: {
      type: "category" as const,
      data: data.map((d) => d.name),
      axisLabel: { interval: 0, rotate: 15 },
    },
    yAxis: { type: "value" as const, minInterval: 1 },
    series: [
      {
        type: "bar" as const,
        data: data.map((d) => d.value),
        itemStyle: { color: "#1677ff", borderRadius: [5, 5, 0, 0] },
        barMaxWidth: 45,
      },
    ],
  });
  return (
    <>
      <div className="page-heading">
        <div className="eyebrow">DISTRICT ACTIVITY</div>
        <h1>
          District Insights <span>商圈洞察</span>
        </h1>
        <p>Urban Intelligence · 比较商圈活动与城市资源分布</p>
      </div>
      <Filters />
      <OpportunityAnalysis
        events={dataset.events.filter(
          (e) =>
            (filters.includeDemo || !e.demo) &&
            (!filters.category || e.category === filters.category) &&
            overlaps(e, ...monthRange(filters.year, filters.month)),
        )}
      />
      <div className="stats-strip">
        <div>
          <small>全年匹配活动（去重）</small>
          <strong>{annual.length}</strong>
        </div>
        <div>
          <small>本月匹配活动</small>
          <strong>{current.length}</strong>
        </div>
        <div>
          <small>年度 DEMO 记录</small>
          <strong>{annual.filter((e) => e.demo).length}</strong>
        </div>
        <div>
          <small>统计区间</small>
          <strong className="stat-text">{filters.year}.01 — 12</strong>
        </div>
      </div>
      <div className="charts-grid">
        <section className="panel">
          <div className="panel-heading">
            <h3>商圈活动数量 · 全年</h3>
            <Button size="small" onClick={() => go("/map")}>
              查看地图 ↗
            </Button>
          </div>
          <Chart
            option={bar(districtCounts)}
            onClick={(name) =>
              update({
                district:
                  dataset.districts.find((d) => d.name === name)?.id ?? "",
              })
            }
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h3>月度活动趋势</h3>
            <Tag>跨月活动逐月计入</Tag>
          </div>
          <Chart
            option={{
              tooltip: { trigger: "axis" },
              grid: { left: 45, right: 20, bottom: 35, top: 25 },
              xAxis: {
                type: "category",
                data: monthly.map((_, i) => `${i + 1}月`),
              },
              yAxis: { type: "value", minInterval: 1 },
              series: [
                {
                  type: "line",
                  data: monthly,
                  smooth: true,
                  areaStyle: { color: "#e8f3ff" },
                  lineStyle: { color: "#1677ff" },
                  itemStyle: { color: "#1677ff" },
                },
              ],
            }}
            onClick={(name) => update({ month: parseInt(name) })}
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h3>活动类别分布 · 全年</h3>
          </div>
          <Chart
            option={{
              tooltip: {},
              legend: { bottom: 0, textStyle: { fontSize: 11 } },
              series: [
                {
                  type: "pie",
                  radius: ["38%", "63%"],
                  center: ["50%", "43%"],
                  data: cat.filter((x) => x.value),
                  label: { show: false },
                },
              ],
            }}
            onClick={(name) =>
              update({
                category:
                  Object.entries(categories).find(
                    ([, c]) => c.label === name,
                  )?.[0] ?? "",
              })
            }
          />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h3>场馆活动数量 · 全年</h3>
            {venueId && (
              <Button size="small" onClick={() => setVenueId("")}>
                清除场馆筛选
              </Button>
            )}
          </div>
          <Chart
            option={bar(venue)}
            onClick={(name) =>
              setVenueId(dataset.venues.find((v) => v.name === name)?.id ?? "")
            }
          />
        </section>
      </div>
      <Alert
        className="gap-top gap-bottom"
        type="info"
        message={`样本 ${annual.length} 条；全年记录按 ID 去重。跨月活动在每个覆盖月份计数，月度总和可大于年度总数。商圈为 DEMO 分组，无收入贡献估算。`}
      />
      <section className="panel">
        <div className="panel-heading">
          <h3>筛选活动 · {filters.month}月</h3>
        </div>
        <Table<Event>
          rowKey="id"
          dataSource={current}
          pagination={{ pageSize: 5 }}
          columns={[
            {
              title: "活动",
              dataIndex: "name",
              render: (_, e) => (
                <Button type="link" onClick={() => openEvent(e.id)}>
                  {e.name}
                  {e.demo ? " · DEMO" : ""}
                </Button>
              ),
            },
            { title: "开始", dataIndex: "startDate" },
            { title: "结束", dataIndex: "endDate" },
            {
              title: "类别",
              dataIndex: "category",
              render: (c: keyof typeof categories) => categories[c].label,
            },
          ]}
        />
      </section>
    </>
  );
}
